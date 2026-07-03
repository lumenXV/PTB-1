"""Stability checks for QMR.CO research runs and dataset loading."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

from ptb1.historian import PriceBar, load_price_history
from ptb1.live_paper import LivePaperConfig, LivePaperSession
from ptb1.market_data import (
    CSVProvider,
    HTTPMarketProvider,
    MarketDataRepository,
    MarketDataRequest,
    MarketDataResult,
    MarketDataStatus,
    ProviderManager,
)
from ptb1.operations import OperationsStatus, Watchlist, render_market_intelligence, render_menu, render_status
from ptb1.paper import PaperSession
from ptb1.researcher import Signal
from ptb1.risk_manager import RiskManager
from ptb1.security import AuditLogger, ConfigValidator, PrivacyFilter, SecretManager, SecureStorage
from ptb1.strategies import BuyAndHoldStrategy, RsiStrategy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


class HistorianValidationTests(unittest.TestCase):
    """Verify that Historian rejects malformed historical datasets clearly."""

    def test_empty_csv_rejected(self) -> None:
        """An empty CSV file should not be accepted as price history."""
        with self.assertRaisesRegex(ValueError, "No CSV header"):
            load_price_history(FIXTURES / "empty.csv")

    def test_header_only_csv_rejected(self) -> None:
        """A CSV with headers but no rows should not run as a dataset."""
        with self.assertRaisesRegex(ValueError, "No historical rows"):
            load_price_history(FIXTURES / "header_only.csv")

    def test_missing_required_column_rejected(self) -> None:
        """A CSV missing required columns should name the missing column."""
        with self.assertRaisesRegex(ValueError, "close"):
            load_price_history(FIXTURES / "missing_close.csv")

    def test_bad_numeric_value_rejected(self) -> None:
        """A non-numeric price or volume should be rejected."""
        with self.assertRaisesRegex(ValueError, "Invalid numeric value"):
            load_price_history(FIXTURES / "bad_number.csv")

    def test_bad_date_rejected(self) -> None:
        """An invalid date should be rejected."""
        with self.assertRaisesRegex(ValueError, "Invalid date"):
            load_price_history(FIXTURES / "bad_date.csv")


class SecuritySkeletonTests(unittest.TestCase):
    """Verify QMR.CO security and trust primitives are safe by default."""

    def test_privacy_filter_redacts_sensitive_values(self) -> None:
        """Sensitive text values should be redacted from output."""
        output = PrivacyFilter().redact(
            "email=user@example.com api_key=abc123 token=secret-token Bearer abc.def"
        )

        self.assertNotIn("user@example.com", output)
        self.assertNotIn("abc123", output)
        self.assertNotIn("secret-token", output)
        self.assertIn("<redacted-email>", output)

    def test_privacy_filter_redacts_raw_ips(self) -> None:
        """Raw IP addresses should not appear in safe output."""
        output = PrivacyFilter().redact("provider request from 192.168.1.10")

        self.assertNotIn("192.168.1.10", output)
        self.assertIn("<redacted-ip>", output)

    def test_secret_manager_never_prints_secret_values(self) -> None:
        """SecretManager diagnostics should expose presence only."""
        manager = SecretManager(env={"QMR_TOKEN": "super-secret-value"})

        self.assertEqual(manager.require(["QMR_TOKEN"])["QMR_TOKEN"], "super-secret-value")
        self.assertEqual(manager.redacted_environment(["QMR_TOKEN"]), {"QMR_TOKEN": "<set>"})

        with self.assertRaisesRegex(ValueError, "MISSING_TOKEN"):
            manager.require(["MISSING_TOKEN"])

    def test_secure_storage_does_not_store_plaintext_and_round_trips(self) -> None:
        """Protected storage should not contain plaintext and should reveal explicitly."""
        storage = SecureStorage()
        secret_data = "watchlist=AMD,NVDA email=user@example.com"

        protected = storage.protect(secret_data)

        self.assertNotIn(secret_data, protected)
        self.assertNotIn("user@example.com", protected)
        self.assertEqual(storage.reveal(protected), secret_data)

    def test_audit_logger_redacts_sensitive_values(self) -> None:
        """Audit logs should be safe to view and share."""
        logger = AuditLogger()

        logger.record(
            "provider request",
            "provider failed for user@example.com from 10.0.0.1",
            {"api_key": "abc123", "symbol": "AMD", "account_id": "acct-1"},
        )

        entry = logger.entries()[0]
        serialized = f"{entry.event_type} {entry.message} {entry.details}"
        self.assertNotIn("user@example.com", serialized)
        self.assertNotIn("10.0.0.1", serialized)
        self.assertNotIn("abc123", serialized)
        self.assertNotIn("acct-1", serialized)
        self.assertIn("AMD", serialized)

    def test_config_validator_rejects_unsafe_config(self) -> None:
        """Unsafe config should fail closed."""
        validator = ConfigValidator(secret_manager=SecretManager(env={}))

        with self.assertRaisesRegex(ValueError, "live trading"):
            validator.validate({"live_trading_enabled": True})
        with self.assertRaisesRegex(ValueError, "broker secrets"):
            validator.validate({"broker_api_key": "abc123"})
        with self.assertRaisesRegex(ValueError, "privacy_logging"):
            validator.validate({"privacy_logging": "raw"})

    def test_config_validator_accepts_safe_defaults(self) -> None:
        """Empty config should resolve to safe defaults."""
        validated = ConfigValidator(secret_manager=SecretManager(env={})).validate({})

        self.assertEqual(validated.privacy_logging, "redacted")
        self.assertEqual(validated.storage_mode, "protected")
        self.assertFalse(validated.live_trading_enabled)


class MarketDataProviderTests(unittest.TestCase):
    """Verify the internal market data provider abstraction."""

    def test_csv_provider_returns_historian_price_bars(self) -> None:
        """CSVProvider should delegate to Historian and return the same bars."""
        path = PROJECT_ROOT / "datasets" / "sample_prices.csv"

        self.assertEqual(CSVProvider().load(path), load_price_history(path))

    def test_csv_provider_uses_historian_validation(self) -> None:
        """CSVProvider should surface Historian validation errors."""
        with self.assertRaisesRegex(ValueError, "Invalid numeric value"):
            CSVProvider().load(FIXTURES / "bad_number.csv")

    def test_http_provider_converts_response_to_price_bars(self) -> None:
        """HTTPMarketProvider should hide provider data and return PriceBars."""
        provider = HTTPMarketProvider(fetcher=lambda request: _fake_market_response())

        bars = provider.load(MarketDataRequest(symbol="PTB", period="5d", interval="1d"))

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].symbol, "PTB")
        self.assertEqual(bars[0].date.isoformat(), "2024-01-01")
        self.assertEqual(bars[0].close, 101.0)
        self.assertEqual(bars[1].volume, 1100)

    def test_http_provider_rejects_empty_response(self) -> None:
        """HTTPMarketProvider should reject empty provider results."""
        provider = HTTPMarketProvider(fetcher=lambda request: {"chart": {"result": [], "error": None}})

        with self.assertRaisesRegex(ValueError, "Malformed market data response"):
            provider.load(MarketDataRequest(symbol="PTB", period="5d", interval="1d"))

    def test_http_provider_rejects_missing_ohlcv_fields(self) -> None:
        """HTTPMarketProvider should reject responses missing OHLCV fields."""
        response = _fake_market_response()
        del response["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        provider = HTTPMarketProvider(fetcher=lambda request: response)

        with self.assertRaisesRegex(ValueError, "Missing OHLCV"):
            provider.load(MarketDataRequest(symbol="PTB", period="5d", interval="1d"))

    def test_http_provider_reports_invalid_symbol(self) -> None:
        """HTTPMarketProvider should reject provider invalid-symbol responses."""
        provider = HTTPMarketProvider(
            fetcher=lambda request: {"chart": {"result": None, "error": {"description": "Not Found"}}}
        )

        with self.assertRaisesRegex(ValueError, "Invalid market data symbol"):
            provider.load(MarketDataRequest(symbol="BAD", period="5d", interval="1d"))

    def test_http_provider_reports_network_failure(self) -> None:
        """HTTPMarketProvider should normalize network failures."""
        def failing_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise OSError("network unavailable")

        provider = HTTPMarketProvider(fetcher=failing_fetcher)

        with self.assertRaisesRegex(ValueError, "Network failure"):
            provider.load(MarketDataRequest(symbol="PTB", period="5d", interval="1d"))

    def test_http_provider_reports_timeout(self) -> None:
        """HTTPMarketProvider should normalize timeouts."""
        def timeout_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise TimeoutError

        provider = HTTPMarketProvider(fetcher=timeout_fetcher)

        with self.assertRaisesRegex(ValueError, "Timed out"):
            provider.load(MarketDataRequest(symbol="PTB", period="5d", interval="1d"))

    def test_http_provider_reports_rate_limit(self) -> None:
        """HTTPMarketProvider should normalize HTTP 429 rate limits."""
        def rate_limited_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise HTTPError("https://example.test", 429, "Too Many Requests", {}, None)

        provider = HTTPMarketProvider(fetcher=rate_limited_fetcher)

        with self.assertRaisesRegex(ValueError, "Rate limited"):
            provider.load(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

    def test_provider_check_success(self) -> None:
        """Provider check should return OK and last price for valid provider data."""
        provider = HTTPMarketProvider(fetcher=lambda request: _fake_market_response())

        result = provider.check(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.OK)
        self.assertEqual(result.symbol, "AMD")
        self.assertEqual(result.last_price, 102.0)
        self.assertEqual(result.reason, "Fresh provider data received.")

    def test_provider_check_rate_limited(self) -> None:
        """Provider check should report rate limits without raising."""
        def rate_limited_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise HTTPError("https://example.test", 429, "Too Many Requests", {"Retry-After": "60"}, None)

        result = HTTPMarketProvider(fetcher=rate_limited_fetcher).check(
            MarketDataRequest(symbol="AMD", period="5d", interval="1d")
        )

        self.assertEqual(result.status, MarketDataStatus.RATE_LIMITED)
        self.assertEqual(result.http_status, 429)
        self.assertEqual(result.retry_after, "60")
        self.assertIn("rate limited", result.reason)

    def test_provider_check_network_error(self) -> None:
        """Provider check should report network errors without raising."""
        def failing_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise OSError("network unavailable")

        result = HTTPMarketProvider(fetcher=failing_fetcher).check(
            MarketDataRequest(symbol="AMD", period="5d", interval="1d")
        )

        self.assertEqual(result.status, MarketDataStatus.ERROR)
        self.assertIsNone(result.http_status)
        self.assertIn("Network failure", result.reason)


class ProviderManagerTests(unittest.TestCase):
    """Verify market data cache, cooldown, and provider status handling."""

    def test_fresh_cache_avoids_provider_call(self) -> None:
        """Fresh cached data should be reused without another provider call."""
        now = _Clock(datetime(2024, 1, 1, 12, 0, 0))
        provider = _CountingProvider(_fake_price_bars())
        manager = ProviderManager(
            provider=provider,
            repository=MarketDataRepository(freshness_seconds=60, now=now),
        )

        first = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))
        second = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(first.status, MarketDataStatus.OK)
        self.assertEqual(second.status, MarketDataStatus.OK)
        self.assertEqual(provider.calls, 1)

    def test_stale_cache_triggers_provider_call(self) -> None:
        """Stale cached data should trigger a provider refresh."""
        now = _Clock(datetime(2024, 1, 1, 12, 0, 0))
        provider = _CountingProvider(_fake_price_bars())
        manager = ProviderManager(
            provider=provider,
            repository=MarketDataRepository(freshness_seconds=60, now=now),
        )

        manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))
        now.advance(61)
        result = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.OK)
        self.assertEqual(provider.calls, 2)

    def test_rate_limit_sets_cooldown(self) -> None:
        """Rate limits should return RATE_LIMITED and set a retry time."""
        now = _Clock(datetime(2024, 1, 1, 12, 0, 0))
        manager = ProviderManager(
            provider=_RateLimitProvider(),
            repository=MarketDataRepository(now=now),
            cooldown_seconds=60,
        )

        result = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.RATE_LIMITED)
        self.assertEqual(result.next_retry_time, datetime(2024, 1, 1, 12, 1, 0))

    def test_cooldown_prevents_provider_call(self) -> None:
        """A cooling-down symbol should not call the provider again."""
        now = _Clock(datetime(2024, 1, 1, 12, 0, 0))
        provider = _RateLimitProvider()
        manager = ProviderManager(
            provider=provider,
            repository=MarketDataRepository(now=now),
            cooldown_seconds=60,
        )

        manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))
        manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(provider.calls, 1)

    def test_cooldown_expiry_allows_retry(self) -> None:
        """After cooldown expires, the provider may be called again."""
        now = _Clock(datetime(2024, 1, 1, 12, 0, 0))
        provider = _RateLimitThenSuccessProvider(_fake_price_bars())
        manager = ProviderManager(
            provider=provider,
            repository=MarketDataRepository(now=now),
            cooldown_seconds=60,
        )

        first = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))
        now.advance(61)
        second = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(first.status, MarketDataStatus.RATE_LIMITED)
        self.assertEqual(second.status, MarketDataStatus.OK)
        self.assertEqual(provider.calls, 2)


class CliStabilityTests(unittest.TestCase):
    """Verify that repeated CLI research runs remain stable."""

    def test_default_command_launches_operations_center(self) -> None:
        """The default command should print Operations Center and exit cleanly."""
        result = self._run_ptb1(stdin="6\n")

        self.assertEqual(result.returncode, 0)
        self.assertIn("QMR.CO", result.stdout)
        self.assertIn("Version v0.6", result.stdout)
        self.assertIn("Menu", result.stdout)
        self.assertIn("Market Intelligence", result.stdout)
        self.assertIn("Exiting QMR.CO.", result.stdout)

    def test_operations_center_keeps_watchlist_for_session(self) -> None:
        """A symbol added in Market Intelligence should appear on the main status screen."""
        result = self._run_ptb1(stdin="5\n1\nAMD\n4\n6\n")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Watching\n---------------------------------------\nAMD: Waiting for refresh.", result.stdout)
        self.assertIn("Exiting QMR.CO.", result.stdout)

    def test_repeated_single_dataset_runs_are_identical(self) -> None:
        """The same dataset should produce the same report on repeated runs."""
        first_run = self._run_ptb1("--data", "datasets/sample_prices.csv")
        second_run = self._run_ptb1("--data", "datasets/sample_prices.csv")

        self.assertEqual(first_run.returncode, 0)
        self.assertEqual(second_run.returncode, 0)
        self.assertEqual(first_run.stdout, second_run.stdout)
        self.assertIn("Overall Winner: RSI", first_run.stdout)

    def test_all_datasets_run_successfully(self) -> None:
        """All demo datasets should run together without crashing."""
        result = self._run_ptb1("--all-datasets")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Datasets loaded: 3", result.stdout)
        self.assertIn("Overall Cross-Dataset Winner:", result.stdout)

    def test_cli_displays_bad_dataset_errors_without_traceback(self) -> None:
        """The CLI should display validation errors instead of Python tracebacks."""
        result = self._run_ptb1("--data", "tests/fixtures/missing_close.csv")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Error: Missing required column", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_paper_mode_runs_one_strategy(self) -> None:
        """Paper mode should run one strategy without changing research mode."""
        result = self._run_ptb1("--paper", "--strategy", "RSI", "--data", "datasets/sample_prices.csv")

        self.assertEqual(result.returncode, 0)
        self.assertIn("QMR.CO Paper Trading Engine", result.stdout)
        self.assertIn("Strategy: RSI", result.stdout)
        self.assertIn("Mode: Paper trading with fake money only", result.stdout)

    def test_paper_mode_rejects_missing_strategy(self) -> None:
        """Paper mode should require an explicit strategy."""
        result = self._run_ptb1("--paper", "--data", "datasets/sample_prices.csv")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Paper mode requires --strategy", result.stdout)

    def _run_ptb1(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run QMR.CO as a user would from the command line."""
        return subprocess.run(
            [sys.executable, "-m", "ptb1", *args],
            cwd=PROJECT_ROOT,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )


class PaperSessionTests(unittest.TestCase):
    """Verify fake-money paper sessions stay separate and deterministic."""

    def test_buy_and_hold_paper_session_tracks_open_position(self) -> None:
        """Buy and Hold should open one fake long position and keep it open."""
        prices = load_price_history(PROJECT_ROOT / "datasets" / "sample_prices.csv")
        result = PaperSession(starting_cash=10_000.0, risk_manager=RiskManager()).run(
            prices=prices,
            strategy=BuyAndHoldStrategy(),
            dataset_name="sample_prices",
        )

        self.assertEqual(result.account.cash, 0.0)
        self.assertEqual(result.account.portfolio_value, 13_000.0)
        self.assertEqual(len(result.account.positions), 1)
        self.assertEqual(len(result.account.order_log), 1)
        self.assertEqual(len(result.account.trade_log), 0)

    def test_rsi_paper_session_records_completed_trades(self) -> None:
        """RSI should create completed fake paper trades on the sample dataset."""
        prices = load_price_history(PROJECT_ROOT / "datasets" / "sample_prices.csv")
        result = PaperSession(starting_cash=10_000.0, risk_manager=RiskManager()).run(
            prices=prices,
            strategy=RsiStrategy(),
            dataset_name="sample_prices",
        )

        self.assertEqual(result.account.cash, 13_748.0)
        self.assertEqual(result.account.portfolio_value, 13_748.0)
        self.assertEqual(len(result.account.positions), 0)
        self.assertEqual(len(result.account.trade_log), 2)
        self.assertGreater(len(result.account.order_log), len(result.account.trade_log))


class LivePaperSessionTests(unittest.TestCase):
    """Verify fake-money live paper sessions stay bounded and deterministic."""

    def test_live_paper_limited_loop_can_buy(self) -> None:
        """Live paper should place a fake buy when strategy and risk allow it."""
        output: list[str] = []
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.OK)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.BUY),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=output.append,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 1)
        self.assertEqual(result.account.order_log[0].status, "FILLED")
        self.assertIn("PAPER TRADE ONLY", "\n".join(output))

    def test_live_paper_can_sell_open_position(self) -> None:
        """Live paper should sell an existing fake position when strategy and risk allow it."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.OK)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_SequenceSignalStrategy([Signal.BUY, Signal.SELL]),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=2,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.trade_log), 1)
        self.assertEqual(len(result.account.positions), 0)
        self.assertEqual(result.account.order_log[-1].side, "SELL")

    def test_live_paper_hold_places_no_order(self) -> None:
        """Live paper should not place fake orders for HOLD signals."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.OK)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.HOLD),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].signal, Signal.HOLD)

    def test_live_paper_provider_failure_does_not_trade(self) -> None:
        """Live paper should skip trading when provider data fails."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.ERROR)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.BUY),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].risk_decision, "PAUSED")
        self.assertIn("ERROR", result.decisions[0].order_result)

    def test_live_paper_rate_limit_pauses_without_trade(self) -> None:
        """Live paper should pause and place no fake order when provider rate limits."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.RATE_LIMITED)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.BUY),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].risk_decision, "PAUSED")
        self.assertIn("RATE_LIMITED", result.decisions[0].order_result)

    def test_live_paper_missing_data_pauses_without_trade(self) -> None:
        """Live paper should pause and place no fake order when data is missing."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.MISSING)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.BUY),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].risk_decision, "PAUSED")
        self.assertIn("MISSING", result.decisions[0].order_result)

    def test_live_paper_stale_data_pauses_without_trade(self) -> None:
        """Live paper should pause and place no fake order when cached data is stale."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.STALE)), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=_FixedSignalStrategy(Signal.BUY),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].risk_decision, "PAUSED")
        self.assertIn("STALE", result.decisions[0].order_result)

    def test_live_paper_short_history_holds_with_current_strategy(self) -> None:
        """Live paper should hold when the selected strategy has too little history."""
        result = LivePaperSession(_ResultLiveProvider(_market_result(MarketDataStatus.OK, bars=_fake_price_bars(count=2))), RiskManager()).run(
            LivePaperConfig(
                symbols=["AMD"],
                strategy=RsiStrategy(),
                starting_cash=10_000.0,
                interval_seconds=0,
                max_iterations=1,
            ),
            emit=lambda text: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(len(result.account.order_log), 0)
        self.assertEqual(result.decisions[0].signal, Signal.HOLD)


class OperationsCenterTests(unittest.TestCase):
    """Verify Operations Center display rendering."""

    def test_render_status_contains_platform_summary(self) -> None:
        """Operations status should include platform and verification facts."""
        output = render_status(
            OperationsStatus(
                version="v0.6",
                stable_branch="stable/v0.6",
                runtime_seconds=0,
                strategy_count=4,
                dataset_count=3,
                market_provider_status="Connected",
                market_status="OPEN",
                last_update="12:00:00",
                mode="Idle",
            )
        )

        self.assertIn("Research Engine", output)
        self.assertIn("Paper Trading", output)
        self.assertIn("Market Intelligence", output)
        self.assertIn("Watching", output)
        self.assertIn("Runtime", output)

    def test_render_menu_contains_expected_options(self) -> None:
        """Operations menu should expose the expected launch options."""
        output = render_menu()

        self.assertIn("1. Research", output)
        self.assertIn("2. Paper Trading", output)
        self.assertIn("3. Learning Mode", output)
        self.assertIn("4. System Status", output)
        self.assertIn("5. Market Intelligence", output)
        self.assertIn("6. Exit", output)

    def test_empty_watchlist_display(self) -> None:
        """Market Intelligence should display an empty watchlist clearly."""
        output = render_market_intelligence(Watchlist(), "Connected")

        self.assertIn("No symbols selected.", output)

    def test_watchlist_add_and_remove_symbol(self) -> None:
        """Watchlist should add and remove normalized symbols."""
        watchlist = Watchlist()

        watchlist.add_symbol("ptb")
        self.assertEqual([entry.symbol for entry in watchlist.entries()], ["PTB"])
        self.assertTrue(watchlist.remove_symbol("PTB"))
        self.assertEqual(watchlist.entries(), [])

    def test_watchlist_refresh_updates_quote(self) -> None:
        """Watchlist refresh should update watched prices on demand."""
        watchlist = Watchlist()
        watchlist.add_symbol("PTB")
        provider = ProviderManager(provider=HTTPMarketProvider(fetcher=lambda request: _fake_market_response()))

        entries = watchlist.refresh(provider)

        self.assertEqual(entries[0].result.quote.symbol, "PTB")
        self.assertEqual(entries[0].result.quote.last_price, 102.0)
        self.assertEqual(entries[0].result.quote.daily_change, 1.0)

    def test_watchlist_refresh_handles_invalid_symbol(self) -> None:
        """Watchlist refresh should keep invalid symbols display-only."""
        watchlist = Watchlist()
        watchlist.add_symbol("BAD")
        provider = ProviderManager(
            provider=HTTPMarketProvider(
                fetcher=lambda request: {"chart": {"result": None, "error": {"description": "Not Found"}}}
            )
        )

        entries = watchlist.refresh(provider)

        self.assertIsNone(entries[0].result.quote)
        self.assertEqual(entries[0].result.status, MarketDataStatus.ERROR)
        self.assertIn("Invalid market data symbol", entries[0].result.message)

    def test_watchlist_refresh_handles_provider_failure(self) -> None:
        """Watchlist refresh should display provider failures without raising."""
        def failing_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise OSError("network unavailable")

        watchlist = Watchlist()
        watchlist.add_symbol("PTB")
        entries = watchlist.refresh(ProviderManager(provider=HTTPMarketProvider(fetcher=failing_fetcher)))

        self.assertIsNone(entries[0].result.quote)
        self.assertIn("Network failure", entries[0].result.message)

    def test_watchlist_displays_cached_status(self) -> None:
        """Watchlist should display repository-backed status values."""
        watchlist = Watchlist()
        watchlist.add_symbol("AMD")
        provider = ProviderManager(provider=_RateLimitProvider())

        watchlist.refresh(provider)
        output = render_market_intelligence(watchlist, provider.connection_status())

        self.assertIn("AMD: RATE_LIMITED", output)
        self.assertIn("last update Never", output)


def _fake_market_response() -> dict[str, object]:
    """Return a small chart-style fake provider response."""
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [1704067200, 1704153600],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0],
                                "high": [102.0, 103.0],
                                "low": [99.0, 100.0],
                                "close": [101.0, 102.0],
                                "volume": [1000, 1100],
                            }
                        ]
                    },
                }
            ],
        }
    }


class _FixedSignalStrategy:
    """Small test strategy that always emits one signal."""

    name = "Fixed Signal"

    def __init__(self, signal: Signal) -> None:
        """Create a fixed-signal test strategy."""
        self.signal = signal

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Return the configured test signal."""
        return self.signal


class _SequenceSignalStrategy:
    """Small test strategy that emits signals in order."""

    name = "Sequence Signal"

    def __init__(self, signals: list[Signal]) -> None:
        """Create a sequence-signal test strategy."""
        self.signals = signals
        self.index = 0

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Return the next configured test signal."""
        signal = self.signals[min(self.index, len(self.signals) - 1)]
        self.index += 1
        return signal


class _Clock:
    """Controllable clock for market repository tests."""

    def __init__(self, value: datetime) -> None:
        """Create a clock at a fixed datetime."""
        self.value = value

    def __call__(self) -> datetime:
        """Return the current test time."""
        return self.value

    def advance(self, seconds: int) -> None:
        """Advance the test clock."""
        self.value += timedelta(seconds=seconds)


class _CountingProvider:
    """Fake provider that counts calls and returns fixed bars."""

    def __init__(self, bars: list[PriceBar]) -> None:
        """Create the provider with fixed bars."""
        self.bars = bars
        self.calls = 0

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Return fixed bars for the requested symbol."""
        self.calls += 1
        return [
            PriceBar(
                symbol=request.symbol,
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in self.bars
        ]

    def connection_status(self) -> str:
        """Return fake provider readiness."""
        return "Connected"


class _RateLimitProvider:
    """Fake provider that always rate limits."""

    def __init__(self) -> None:
        """Create a counting rate-limit provider."""
        self.calls = 0

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Raise a provider rate-limit error."""
        self.calls += 1
        raise ValueError(f"Rate limited loading market data for {request.symbol}.")

    def connection_status(self) -> str:
        """Return fake provider readiness."""
        return "Connected"


class _RateLimitThenSuccessProvider:
    """Fake provider that rate limits once, then succeeds."""

    def __init__(self, bars: list[PriceBar]) -> None:
        """Create a provider with one rate limit before success."""
        self.bars = bars
        self.calls = 0

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Rate limit first, then return fixed bars."""
        self.calls += 1
        if self.calls == 1:
            raise ValueError(f"Rate limited loading market data for {request.symbol}.")
        return [
            PriceBar(
                symbol=request.symbol,
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in self.bars
        ]

    def connection_status(self) -> str:
        """Return fake provider readiness."""
        return "Connected"


class _ResultLiveProvider:
    """Fake managed provider for live paper tests."""

    def __init__(self, result: MarketDataResult) -> None:
        """Create the provider with a fixed managed result."""
        self.result = result

    def get_market_data(self, request: MarketDataRequest) -> MarketDataResult:
        """Return a fixed managed result for live paper."""
        return self.result


def _market_result(status: MarketDataStatus, bars: list[PriceBar] | None = None) -> MarketDataResult:
    """Build a managed market result for tests."""
    result_bars = _fake_price_bars() if bars is None and status is MarketDataStatus.OK else bars or []
    quote = None
    if result_bars:
        latest = result_bars[-1]
        previous = result_bars[-2] if len(result_bars) > 1 else latest
        change = latest.close - previous.close
        quote = _TestQuote(latest.symbol, latest.close, change, (change / previous.close) * 100 if previous.close else 0.0)
    return MarketDataResult(
        symbol="AMD",
        status=status,
        bars=result_bars,
        quote=quote,
        message=f"{status.value} test market data.",
        provider_status=status.value,
        cache_status="FRESH" if status is MarketDataStatus.OK else status.value,
        last_successful_update=datetime(2024, 1, 1, 12, 0, 0) if result_bars else None,
    )


class _TestQuote:
    """Small quote object matching MarketQuote fields for tests."""

    def __init__(self, symbol: str, last_price: float, daily_change: float, daily_percent_change: float) -> None:
        """Create a test quote."""
        self.symbol = symbol
        self.last_price = last_price
        self.daily_change = daily_change
        self.daily_percent_change = daily_percent_change
        self.last_updated = "12:00:00"


def _fake_price_bars(count: int = 20) -> list[PriceBar]:
    """Build simple fake price bars for live paper tests."""
    return [
        PriceBar(
            symbol="AMD",
            date=date(2024, 1, index + 1),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=1000 + index,
        )
        for index in range(count)
    ]
