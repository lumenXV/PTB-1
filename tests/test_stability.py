"""Stability checks for QMR.CO research runs and dataset loading."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from ptb1.historian import PriceBar, load_price_history
from ptb1.live_paper import LivePaperConfig, LivePaperSession
from ptb1.market_data import CSVProvider, HTTPMarketProvider, MarketDataRequest
from ptb1.operations import OperationsStatus, Watchlist, render_market_intelligence, render_menu, render_status
from ptb1.paper import PaperSession
from ptb1.researcher import Signal
from ptb1.risk_manager import RiskManager
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
        result = LivePaperSession(_FakeLiveProvider(_fake_price_bars()), RiskManager()).run(
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
        result = LivePaperSession(_FakeLiveProvider(_fake_price_bars()), RiskManager()).run(
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
        result = LivePaperSession(_FakeLiveProvider(_fake_price_bars()), RiskManager()).run(
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
        result = LivePaperSession(_FailingLiveProvider(), RiskManager()).run(
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
        self.assertIn("Provider failure", result.decisions[0].order_result)

    def test_live_paper_rate_limit_pauses_without_trade(self) -> None:
        """Live paper should pause and place no fake order when provider rate limits."""
        result = LivePaperSession(_RateLimitedLiveProvider(), RiskManager()).run(
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
        self.assertIn("Rate limited", result.decisions[0].order_result)

    def test_live_paper_short_history_holds_with_current_strategy(self) -> None:
        """Live paper should hold when the selected strategy has too little history."""
        result = LivePaperSession(_FakeLiveProvider(_fake_price_bars(count=2)), RiskManager()).run(
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
        provider = HTTPMarketProvider(fetcher=lambda request: _fake_market_response())

        entries = watchlist.refresh(provider)

        self.assertEqual(entries[0].quote.symbol, "PTB")
        self.assertEqual(entries[0].quote.last_price, 102.0)
        self.assertEqual(entries[0].quote.daily_change, 1.0)

    def test_watchlist_refresh_handles_invalid_symbol(self) -> None:
        """Watchlist refresh should keep invalid symbols display-only."""
        watchlist = Watchlist()
        watchlist.add_symbol("BAD")
        provider = HTTPMarketProvider(
            fetcher=lambda request: {"chart": {"result": None, "error": {"description": "Not Found"}}}
        )

        entries = watchlist.refresh(provider)

        self.assertIsNone(entries[0].quote)
        self.assertIn("Invalid market data symbol", entries[0].error)

    def test_watchlist_refresh_handles_provider_failure(self) -> None:
        """Watchlist refresh should display provider failures without raising."""
        def failing_fetcher(request: MarketDataRequest) -> dict[str, object]:
            raise OSError("network unavailable")

        watchlist = Watchlist()
        watchlist.add_symbol("PTB")
        entries = watchlist.refresh(HTTPMarketProvider(fetcher=failing_fetcher))

        self.assertIsNone(entries[0].quote)
        self.assertIn("Network failure", entries[0].error)


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


class _FakeLiveProvider:
    """Fake provider for deterministic live paper tests."""

    def __init__(self, bars: list[PriceBar]) -> None:
        """Create the provider with fixed bars."""
        self.bars = bars

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Return fixed bars for the requested symbol."""
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


class _FailingLiveProvider:
    """Fake provider that simulates market data failure."""

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Raise a provider error."""
        raise ValueError("Network failure loading market data for AMD.")


class _RateLimitedLiveProvider:
    """Fake provider that simulates a provider rate limit."""

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Raise a provider rate-limit error."""
        raise ValueError("Rate limited loading market data for AMD.")


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
