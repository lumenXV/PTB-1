"""Stability checks for QMR.CO research runs and dataset loading."""

from __future__ import annotations

import subprocess
import sys
import unittest
import json
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

from ptb1.assets import Asset, AssetType, create_crypto_asset, create_etf_asset, create_stock_asset
from ptb1.cli import build_parser
from ptb1.dashboard import (
    DashboardApplication,
    DashboardSession,
    DashboardState,
    _render_card,
    _render_empty_state,
    _render_status_pill,
    _render_table,
    build_dashboard_state,
    create_dashboard_handler,
    render_dashboard_html,
)
from ptb1.historian import PriceBar, load_price_history
from ptb1.live_paper import LivePaperConfig, LivePaperSession
from ptb1.market_data import (
    CSVProvider,
    HTTPMarketProvider,
    MarketDataRepository,
    MarketDataRequest,
    MarketDataResult,
    MarketDataStatus,
    MarketQuote,
    ProviderManager,
    StooqProvider,
)
from ptb1.operations import OperationsStatus, Watchlist, render_market_intelligence, render_menu, render_status
from ptb1.paper import PaperSession
from ptb1.researcher import Signal
from ptb1.risk_manager import RiskManager
from ptb1.security import AuditLogger, ConfigValidator, PrivacyFilter, SecretManager, SecureStorage
from ptb1.strategy_result import ResearchContext, StrategyResult, format_strategy_result
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


class UnifiedResearchFoundationTests(unittest.TestCase):
    """Verify additive multi-asset research primitives."""

    def test_asset_type_includes_current_and_future_categories(self) -> None:
        """AssetType should support current assets and future placeholders."""
        self.assertEqual(AssetType.STOCK.value, "stock")
        self.assertEqual(AssetType.ETF.value, "etf")
        self.assertEqual(AssetType.CRYPTO.value, "crypto")
        self.assertEqual(AssetType.INDEX.value, "index")
        self.assertEqual(AssetType.FOREX.value, "forex")
        self.assertEqual(AssetType.COMMODITY.value, "commodity")
        self.assertEqual(AssetType.UNKNOWN.value, "unknown")

    def test_stock_asset_creation(self) -> None:
        """Stock assets should normalize symbols without enabling special behavior."""
        asset = create_stock_asset("amd", "Advanced Micro Devices")

        self.assertEqual(asset.symbol, "AMD")
        self.assertEqual(asset.display_name, "Advanced Micro Devices")
        self.assertEqual(asset.asset_type, AssetType.STOCK)
        self.assertEqual(asset.currency, "USD")
        self.assertFalse(asset.research_only)

    def test_etf_asset_creation(self) -> None:
        """ETF assets should share the same research representation."""
        asset = create_etf_asset("voo", "Vanguard S&P 500 ETF")

        self.assertEqual(asset.symbol, "VOO")
        self.assertEqual(asset.asset_type, AssetType.ETF)
        self.assertEqual(asset.provider_symbol, "VOO")

    def test_crypto_asset_creation_is_research_only(self) -> None:
        """Crypto assets should be representable without enabling trading behavior."""
        asset = create_crypto_asset("btc-usd", "Bitcoin")

        self.assertEqual(asset.symbol, "BTC-USD")
        self.assertEqual(asset.asset_type, AssetType.CRYPTO)
        self.assertTrue(asset.research_only)
        self.assertEqual(asset.exchange, "research-only")

    def test_asset_rejects_empty_fields_and_invalid_type(self) -> None:
        """Assets should fail fast when required metadata is missing."""
        with self.assertRaisesRegex(ValueError, "Asset symbol"):
            Asset("", "Missing Symbol", AssetType.STOCK, "USD", "US", "BAD")
        with self.assertRaisesRegex(ValueError, "Asset type"):
            Asset("AMD", "Advanced Micro Devices", "stock", "USD", "US", "AMD")  # type: ignore[arg-type]

    def test_research_context_creation(self) -> None:
        """ResearchContext should describe a future strategy evaluation input."""
        asset = create_stock_asset("AMD", "Advanced Micro Devices")
        context = ResearchContext(
            asset=asset,
            provider="csv",
            dataset="sample_prices",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timeframe="1d",
        )

        self.assertEqual(context.asset, asset)
        self.assertEqual(context.provider, "csv")
        self.assertEqual(context.timeframe, "1d")

    def test_strategy_result_accepts_explainability_fields(self) -> None:
        """StrategyResult should capture explainable strategy decisions."""
        result = StrategyResult(
            signal=Signal.HOLD,
            reason="RSI is within the neutral range. No entry or exit criteria were met.",
            strategy_name="RSI",
            strategy_version="v1",
            confidence=0.64,
            indicators={"RSI": 54.3, "Buy threshold": 30, "Sell threshold": 70},
            warnings=(),
            metadata={"latency_ms": 12, "provider": "csv"},
            asset_type=AssetType.STOCK,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )

        self.assertEqual(result.signal, Signal.HOLD)
        self.assertEqual(result.confidence, 0.64)
        self.assertEqual(result.metadata["latency_ms"], 12)

    def test_strategy_result_rejects_short_reason(self) -> None:
        """StrategyResult reasons should uphold QMR.CO's explainability standard."""
        with self.assertRaisesRegex(ValueError, "reason must be descriptive"):
            StrategyResult(signal=Signal.HOLD, reason="Hold.")

    def test_strategy_result_rejects_invalid_confidence(self) -> None:
        """Confidence should remain optional but bounded when present."""
        with self.assertRaisesRegex(ValueError, "confidence"):
            StrategyResult(
                signal=Signal.BUY,
                reason="The strategy has enough context to explain this buy signal.",
                confidence=1.5,
            )

    def test_format_strategy_result_plain_console_text(self) -> None:
        """StrategyResult formatting should remain plain console text."""
        result = StrategyResult(
            signal=Signal.HOLD,
            reason="RSI is within the neutral range. No entry or exit criteria were met.",
            strategy_name="RSI",
            strategy_version="v1",
            confidence=0.64,
            indicators={"RSI": 54.3, "Buy threshold": 30, "Sell threshold": 70},
            warnings=("Research-only asset.",),
            asset_type=AssetType.STOCK,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )

        output = format_strategy_result(result)

        self.assertIn("Strategy: RSI", output)
        self.assertIn("Strategy Version: v1", output)
        self.assertIn("Signal: HOLD", output)
        self.assertIn("Confidence: 0.64", output)
        self.assertIn("- RSI: 54.3", output)
        self.assertIn("Reason: RSI is within the neutral range", output)
        self.assertIn("- Research-only asset.", output)
        self.assertIn("Asset Type: stock", output)


class DashboardShellTests(unittest.TestCase):
    """Verify the local read-only dashboard shell renders safely."""

    def test_dashboard_state_uses_safe_defaults(self) -> None:
        """Dashboard state should not require active paper or live-paper sessions."""
        state = build_dashboard_state()

        self.assertEqual(state.version, "v0.7.3")
        self.assertEqual(state.provider_manager_status, "Connected")
        self.assertEqual(state.primary_provider, "stooq")
        self.assertEqual(state.fallback_provider, "http")
        self.assertEqual(state.watchlist_lines, ("No symbols selected.",))
        self.assertIsNone(state.paper_summary)
        self.assertIsNone(state.live_paper_summary)

    def test_render_dashboard_html_contains_required_messages(self) -> None:
        """Dashboard HTML should clearly communicate local read-only paper mode."""
        state = DashboardState(
            version="v0.7.3",
            provider_manager_status="Connected",
            primary_provider="stooq",
            fallback_provider="http",
            market_status="CLOSED",
            last_update="12:00:00",
            watchlist_lines=("No symbols selected.",),
            paper_summary=None,
            live_paper_summary=None,
        )

        output = render_dashboard_html(state)

        self.assertIn("QMR.CO", output)
        self.assertIn("PAPER TRADE ONLY", output)
        self.assertIn("Provider Manager", output)
        self.assertIn("No real trading", output)
        self.assertIn("No active paper session.", output)
        self.assertIn("No active live paper session.", output)
        self.assertIn("Local Mode", output)
        self.assertIn("READ ONLY", output)
        self.assertIn("data-section=\"dashboard\"", output)
        self.assertIn("data-section=\"markets\"", output)
        self.assertIn("data-section=\"watchlist\"", output)
        self.assertIn("data-section=\"paper-trading\"", output)

    def test_dashboard_html_has_no_trade_controls(self) -> None:
        """The dashboard should not render trading action controls."""
        output = render_dashboard_html(build_dashboard_state())

        self.assertNotIn(">Buy<", output)
        self.assertNotIn(">Sell<", output)
        self.assertNotIn("Start Trading", output)
        self.assertNotIn("Connect Broker", output)

    def test_dashboard_html_contains_visual_system_tokens(self) -> None:
        """Dashboard HTML should include the centralized Milestone 8.2 visual tokens."""
        output = render_dashboard_html(build_dashboard_state())

        self.assertIn('data-qmr-design-tokens="8.2"', output)
        self.assertIn("--qmr-space-md", output)
        self.assertIn("--qmr-radius-card", output)
        self.assertIn("--qmr-blue", output)
        self.assertIn("@media (max-width: 920px)", output)

    def test_dashboard_render_helpers_produce_component_markup(self) -> None:
        """Reusable visual helpers should render consistent dashboard components."""
        card = _render_card("Status", "<p>Ready</p>", "wide")
        empty_state = _render_empty_state("No data", "Nothing has loaded yet.", "empty-id")
        status_pill = _render_status_pill("Mode", "READ ONLY", "mode-pill")
        table = _render_table(("Name", "Value"), (("Provider", "Connected"),))

        self.assertIn('class="card wide"', card)
        self.assertIn("<h2>Status</h2>", card)
        self.assertIn('class="empty-state" id="empty-id"', empty_state)
        self.assertIn("No data", empty_state)
        self.assertIn('class="status-pill ok" id="mode-pill"', status_pill)
        self.assertIn("READ ONLY", status_pill)
        self.assertIn("<table>", table)
        self.assertIn("<th>Name</th>", table)
        self.assertIn("<td>Connected</td>", table)

    def test_cli_parser_accepts_dashboard_flag(self) -> None:
        """The dashboard flag should parse without starting the server."""
        args = build_parser().parse_args(["--dashboard"])

        self.assertTrue(args.dashboard)

    def test_status_api_returns_safe_json_payload(self) -> None:
        """Status API should expose read-only platform facts only."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())

        status, payload = app.handle_api_get("/api/status", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["paper_trade_only"])
        self.assertFalse(payload["real_trading_enabled"])
        self.assertEqual(payload["primary_provider"], "fake")
        json.dumps(payload)

    def test_markets_api_uses_provider_manager(self) -> None:
        """Markets API should request data through the injected provider manager."""
        provider = _FakeDashboardProvider()
        app = DashboardApplication(provider_manager=provider)

        status, payload = app.handle_api_get("/api/markets", {"symbols": ["AMD"]})

        self.assertEqual(status, 200)
        self.assertEqual(provider.calls, ["AMD"])
        self.assertEqual(payload["symbols"][0]["symbol"], "AMD")
        self.assertEqual(payload["symbols"][0]["status"], "OK")
        self.assertFalse(payload["trade_execution"])
        json.dumps(payload)

    def test_watchlist_add_remove_and_refresh_are_dashboard_local(self) -> None:
        """Watchlist mutation should stay inside the dashboard session."""
        provider = _FakeDashboardProvider()
        session = DashboardSession()
        app = DashboardApplication(provider_manager=provider, session=session)

        added = app.add_watchlist_symbol("AMD")
        watchlist = app.watchlist()
        removed = app.remove_watchlist_symbol("AMD")
        refreshed = app.refresh_watchlist()

        self.assertTrue(added["added"])
        self.assertEqual(watchlist["watchlist"][0]["symbol"], "AMD")
        self.assertTrue(removed["removed"])
        self.assertEqual(refreshed["watchlist"], [])
        self.assertEqual(session.watchlist, {})

    def test_watchlist_rejects_invalid_symbol_without_provider_call(self) -> None:
        """Invalid symbols should not be stored or sent to providers."""
        provider = _FakeDashboardProvider()
        app = DashboardApplication(provider_manager=provider)

        status, payload = app.handle_api_post("/api/watchlist/add", {"symbol": "41WED"})

        self.assertEqual(status, 400)
        self.assertIn("Invalid symbol", payload["error"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(app.session.watchlist, {})

    def test_api_routes_return_json_serializable_payloads(self) -> None:
        """Every dashboard API route should return valid JSON data."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())

        routes = [
            app.handle_api_get("/api/status", {}),
            app.handle_api_get("/api/markets", {"symbols": ["AMD,AAPL"]}),
            app.handle_api_get("/api/watchlist", {}),
            app.handle_api_get("/api/strategies", {}),
            app.handle_api_get("/api/research", {}),
            app.handle_api_get("/api/paper", {}),
            app.handle_api_get("/api/security", {}),
            app.handle_api_post("/api/watchlist/add", {"symbol": "AMD"}),
            app.handle_api_post("/api/watchlist/refresh", {}),
            app.handle_api_post("/api/watchlist/remove", {"symbol": "AMD"}),
        ]

        for status, payload in routes:
            self.assertEqual(status, 200)
            json.dumps(payload)

    def test_paper_api_returns_inactive_default_state(self) -> None:
        """Paper API should not imply a running account exists."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())

        status, payload = app.handle_api_get("/api/paper", {})

        self.assertEqual(status, 200)
        self.assertFalse(payload["active"])
        self.assertIn("No active paper session", payload["message"])
        self.assertIn("No active account", payload["default_cash_note"])

    def test_security_api_contains_no_sensitive_values(self) -> None:
        """Security API should not expose secrets or sensitive sample values."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())

        status, payload = app.handle_api_get("/api/security", {})
        serialized = json.dumps(payload)

        self.assertEqual(status, 200)
        self.assertNotIn("abc123", serialized)
        self.assertNotIn("user@example.com", serialized)
        self.assertNotIn("192.168.1.10", serialized)
        self.assertFalse(payload["secrets_exposed"])
        self.assertFalse(payload["tokens_exposed"])

    def test_dashboard_handler_serves_status_json_without_hanging(self) -> None:
        """A bounded local server should serve JSON and shut down cleanly."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())
        server = ThreadingHTTPServer(("localhost", 0), create_dashboard_handler(app))
        try:
            import threading

            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.server_address[1]
            body = urlopen(f"http://localhost:{port}/api/status", timeout=2).read().decode("utf-8")
            payload = json.loads(body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(payload["primary_provider"], "fake")


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

    def test_stooq_provider_converts_csv_response(self) -> None:
        """StooqProvider should convert no-key CSV data into PriceBars."""
        provider = StooqProvider(fetcher=lambda request: _fake_stooq_csv())

        bars = provider.load(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1].symbol, "AMD")
        self.assertEqual(bars[-1].close, 102.0)

    def test_stooq_provider_rejects_malformed_response(self) -> None:
        """StooqProvider should reject malformed CSV data."""
        provider = StooqProvider(fetcher=lambda request: "No data")

        with self.assertRaisesRegex(ValueError, "Stooq unavailable or malformed response"):
            provider.load(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

    def test_provider_manager_falls_back_to_legacy_provider(self) -> None:
        """ProviderManager should use legacy provider if Stooq fails."""
        manager = ProviderManager(
            providers=[
                StooqProvider(fetcher=lambda request: "No data"),
                HTTPMarketProvider(fetcher=lambda request: _fake_market_response()),
            ]
        )

        result = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.OK)
        self.assertEqual(result.provider_name, "http")
        self.assertEqual(result.attempted_providers, ("stooq", "http"))

    def test_provider_manager_fails_safely_when_all_providers_fail(self) -> None:
        """ProviderManager should pause safely when all providers fail."""
        manager = ProviderManager(
            providers=[
                StooqProvider(fetcher=lambda request: "No data"),
                HTTPMarketProvider(fetcher=lambda request: {"chart": {"result": [], "error": None}}),
            ]
        )

        result = manager.get_market_data(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.ERROR)
        self.assertIsNone(result.provider_name)
        self.assertEqual(result.attempted_providers, ("stooq", "http"))

    def test_provider_check_reports_provider_used(self) -> None:
        """ProviderManager check should report the provider that succeeded."""
        manager = ProviderManager(
            providers=[
                StooqProvider(fetcher=lambda request: _fake_stooq_csv()),
                HTTPMarketProvider(fetcher=lambda request: _fake_market_response()),
            ]
        )

        result = manager.check(MarketDataRequest(symbol="AMD", period="5d", interval="1d"))

        self.assertEqual(result.status, MarketDataStatus.OK)
        self.assertEqual(result.provider_used, "stooq")
        self.assertIn("stooq: OK", result.attempted_providers[0])


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
        self.assertIn("Version v0.7.3", result.stdout)
        self.assertIn("Menu", result.stdout)
        self.assertIn("Market Intelligence", result.stdout)
        self.assertIn("Exiting QMR.CO.", result.stdout)

    def test_operations_center_keeps_watchlist_for_session(self) -> None:
        """A symbol added in Market Intelligence should appear on the main status screen."""
        watchlist = Watchlist()
        provider = ProviderManager(provider=HTTPMarketProvider(fetcher=lambda request: _fake_market_response()))

        watchlist.add_validated_symbol("AMD", provider)
        output = render_status(
            OperationsStatus(
                version="v0.7.3",
                stable_branch="stable/v0.7.3",
                runtime_seconds=0,
                strategy_count=4,
                dataset_count=3,
                provider_manager_status="Connected",
                primary_provider="http",
                fallback_provider="None",
                market_status="OPEN",
                last_update="12:00:00",
                mode="Idle",
            ),
            watchlist,
        )

        self.assertIn("Watching\n---------------------------------------\nAMD: $102.00", output)

    def test_operations_center_rejects_invalid_menu_input_cleanly(self) -> None:
        """Random menu input should not crash the Operations Center."""
        result = self._run_ptb1(stdin="hello\n6\n")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Invalid selection. Enter 1, 2, 3, 4, 5, or 6.", result.stdout)
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
                version="v0.7.3",
                stable_branch="stable/v0.7.3",
                runtime_seconds=0,
                strategy_count=4,
                dataset_count=3,
                provider_manager_status="Connected",
                primary_provider="stooq",
                fallback_provider="http",
                market_status="OPEN",
                last_update="12:00:00",
                mode="Idle",
            )
        )

        self.assertIn("Research Engine", output)
        self.assertIn("Paper Trading", output)
        self.assertIn("Market Intelligence", output)
        self.assertIn("Provider Manager", output)
        self.assertIn("Primary", output)
        self.assertIn("Fallback", output)
        self.assertIn("Version v0.7.3", output)
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
        output = render_market_intelligence(Watchlist(), "Connected", "stooq", "http")

        self.assertIn("No symbols selected.", output)
        self.assertIn("Provider Manager", output)
        self.assertIn("Primary", output)
        self.assertIn("Fallback", output)

    def test_watchlist_add_and_remove_symbol(self) -> None:
        """Watchlist should add and remove normalized symbols."""
        watchlist = Watchlist()

        watchlist.add_symbol("ptb")
        self.assertEqual([entry.symbol for entry in watchlist.entries()], ["PTB"])
        self.assertTrue(watchlist.remove_symbol("PTB"))
        self.assertEqual(watchlist.entries(), [])

    def test_watchlist_rejects_invalid_symbol_format(self) -> None:
        """Clearly invalid symbols should not be added before provider validation."""
        watchlist = Watchlist()

        with self.assertRaisesRegex(ValueError, "Invalid symbol"):
            watchlist.add_symbol("41WED")
        with self.assertRaisesRegex(ValueError, "Invalid symbol"):
            watchlist.add_symbol("AAAAAAASL")

        self.assertEqual(watchlist.entries(), [])

    def test_watchlist_add_validated_symbol_auto_fetches(self) -> None:
        """Adding a valid symbol should fetch and store provider status immediately."""
        watchlist = Watchlist()
        provider = ProviderManager(provider=HTTPMarketProvider(fetcher=lambda request: _fake_market_response()))

        result = watchlist.add_validated_symbol("AMD", provider)

        self.assertEqual(result.status, MarketDataStatus.OK)
        self.assertEqual([entry.symbol for entry in watchlist.entries()], ["AMD"])
        self.assertEqual(watchlist.entries()[0].result.quote.last_price, 102.0)

    def test_watchlist_rejects_provider_invalid_symbol(self) -> None:
        """Provider-confirmed invalid symbols should not remain in the watchlist."""
        watchlist = Watchlist()
        provider = ProviderManager(
            provider=HTTPMarketProvider(
                fetcher=lambda request: {"chart": {"result": None, "error": {"description": "Not Found"}}}
            )
        )

        with self.assertRaisesRegex(ValueError, "Invalid symbol"):
            watchlist.add_validated_symbol("BAD", provider)

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
        output = render_market_intelligence(
            watchlist,
            provider.connection_status(),
            provider.primary_provider_name(),
            provider.fallback_provider_names(),
        )

        self.assertIn("AMD: RATE_LIMITED", output)
        self.assertIn("last update Never", output)


class _FakeDashboardProvider:
    """Small provider manager test double for dashboard tests."""

    def __init__(self) -> None:
        """Create the fake provider with call tracking."""
        self.calls: list[str] = []

    def connection_status(self) -> str:
        """Return fake provider readiness."""
        return "Connected"

    def primary_provider_name(self) -> str:
        """Return the fake primary provider name."""
        return "fake"

    def fallback_provider_names(self) -> str:
        """Return fake fallback provider names."""
        return "none"

    def get_market_data(self, request: MarketDataRequest) -> MarketDataResult:
        """Return a deterministic market data result."""
        symbol = request.symbol.upper()
        self.calls.append(symbol)
        if symbol == "BAD":
            return MarketDataResult(
                symbol=symbol,
                status=MarketDataStatus.ERROR,
                bars=[],
                quote=None,
                message="Invalid market data symbol.",
                provider_status="ERROR",
                cache_status="MISSING",
                last_successful_update=None,
                provider_name=None,
                attempted_providers=("fake",),
            )
        return MarketDataResult(
            symbol=symbol,
            status=MarketDataStatus.OK,
            bars=[],
            quote=MarketQuote(
                symbol=symbol,
                last_price=102.0,
                daily_change=1.0,
                daily_percent_change=0.99,
                last_updated="12:00:00",
            ),
            message="Fresh fake market data.",
            provider_status="OK: fake",
            cache_status="FRESH",
            last_successful_update=datetime(2024, 1, 1, 12, 0, 0),
            provider_name="fake",
            attempted_providers=("fake",),
        )


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


def _fake_stooq_csv() -> str:
    """Return a small Stooq-style CSV response."""
    return "\n".join(
        [
            "Date,Open,High,Low,Close,Volume",
            "2024-01-01,100.0,102.0,99.0,101.0,1000",
            "2024-01-02,101.0,103.0,100.0,102.0,1100",
        ]
    )


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
