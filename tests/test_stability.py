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
    _market_status_indicator,
    _render_card,
    _render_empty_state,
    _render_status_pill,
    _render_table,
    build_dashboard_state,
    create_dashboard_handler,
    render_about_html,
    render_dashboard_html,
    render_landing_html,
    render_learning_html,
    render_membership_html,
    render_platform_html,
    render_public_route,
    render_sign_in_html,
)
from ptb1.engine import EngineFacade, EnginePaperSessionConfig
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
from ptb1.paper_session import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_SCANNER_UNIVERSE,
    MIN_SCAN_INTERVAL_SECONDS,
    PaperSessionConfig,
    PaperSessionController,
    normalize_symbol_universe,
)
from ptb1.researcher import Signal
from ptb1.risk_manager import RiskManager
from ptb1.security import AuditLogger, ConfigValidator, PrivacyFilter, SecretManager, SecureStorage
from ptb1.snapshots import (
    DashboardPaperSnapshot,
    EventSnapshot,
    ScannerSnapshot,
    ScannerSymbolSnapshot,
    SessionSnapshot,
    snapshot_to_dict,
)
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


class PaperScannerSnapshotTests(unittest.TestCase):
    """Verify immutable paper scanner transport snapshots."""

    def test_snapshot_serialization_preserves_none_and_tuples(self) -> None:
        """Snapshots should serialize safely without fabricating unavailable values."""
        generated_at = datetime(2024, 1, 1, 12, 0, 0)
        snapshot = DashboardPaperSnapshot(
            schema_version="1",
            session=SessionSnapshot(None, False, None, None, None, None, None, None, None, None, None, None, None, None, None, None, "No active session."),
            scanner=ScannerSnapshot(False, "IDLE", (), None, None, None, 0, 0, 0, 0, 0, 0, "Idle.", generated_at),
            positions=(),
            orders=(),
            completed_trades=(),
            recent_events=(EventSnapshot(1, generated_at, "USER_ACTION", "Viewed token=abc123", None, {"email": "user@example.com"}),),
            generated_at=generated_at,
        )

        payload = snapshot_to_dict(snapshot)

        self.assertEqual(payload["schema_version"], "1")
        self.assertIsNone(payload["session"]["session_id"])
        self.assertEqual(payload["positions"], [])
        self.assertEqual(payload["generated_at"], "2024-01-01T12:00:00")
        self.assertNotIn("abc123", json.dumps(payload))
        self.assertNotIn("user@example.com", json.dumps(payload))

    def test_snapshot_rejects_mutable_lists_and_raw_exceptions(self) -> None:
        """Unsupported internals should fail safely during serialization."""
        with self.assertRaisesRegex(ValueError, "tuples"):
            snapshot_to_dict({"bad": ["mutable"]})
        with self.assertRaisesRegex(ValueError, "Raw exceptions"):
            snapshot_to_dict({"bad": ValueError("secret")})


class PaperSessionControllerTests(unittest.TestCase):
    """Verify the EngineFacade and PaperSessionController vertical slice."""

    def test_default_universe_and_interval_are_conservative(self) -> None:
        """Scanner defaults should remain bounded and deterministic."""
        self.assertEqual(DEFAULT_SCANNER_UNIVERSE[0], "SPY")
        self.assertEqual(DEFAULT_SCANNER_UNIVERSE[-1], "CAT")
        self.assertEqual(len(DEFAULT_SCANNER_UNIVERSE), 20)
        self.assertEqual(MIN_SCAN_INTERVAL_SECONDS, 300)
        self.assertEqual(DEFAULT_SCAN_INTERVAL_SECONDS, 900)

    def test_symbol_universe_normalizes_deduplicates_and_rejects_bad_values(self) -> None:
        """Symbol universes should validate before scanner use."""
        self.assertEqual(normalize_symbol_universe((" amd ", "AMD", "spy")), ("AMD", "SPY"))
        with self.assertRaisesRegex(ValueError, "Invalid scanner symbol"):
            normalize_symbol_universe(("41WED",))
        with self.assertRaisesRegex(ValueError, "empty"):
            normalize_symbol_universe(())
        with self.assertRaisesRegex(ValueError, "40"):
            normalize_symbol_universe(tuple(f"A{chr(65 + (i // 26))}{chr(65 + (i % 26))}" for i in range(41)))

    def test_controller_singleton_duplicate_start_stop_and_restart(self) -> None:
        """Only one fake session should run at a time, with safe restart after stop."""
        controller = PaperSessionController(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)), start_worker=False)
        config = PaperSessionConfig(symbols=("AMD",), strategy_name="Fixed Signal", strategies=()) if False else PaperSessionConfig(symbols=("AMD",), strategy_name="RSI")

        first = controller.start(config)
        duplicate = controller.start(config)
        stopped = controller.stop()
        second = controller.start(config)

        self.assertTrue(first.started)
        self.assertFalse(duplicate.started)
        self.assertEqual(duplicate.status_code, 409)
        self.assertFalse(stopped.session.active)
        self.assertTrue(second.started)
        controller.shutdown()

    def test_controller_run_scan_hold_creates_no_order(self) -> None:
        """HOLD signals should not create fake paper orders."""
        controller = PaperSessionController(
            provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)),
            strategies=(_FixedSignalStrategy(Signal.HOLD),),
            start_worker=False,
        )
        controller.start(PaperSessionConfig(symbols=("AMD",), strategy_name="Fixed Signal"))
        controller.run_scan_once()
        snapshot = controller.snapshot()

        self.assertEqual(snapshot.scanner.hold_count, 1)
        self.assertEqual(snapshot.orders, ())
        controller.shutdown()

    def test_controller_approved_buy_routes_through_fake_paper_account(self) -> None:
        """Approved BUY actions should create fake-money paper account orders."""
        controller = PaperSessionController(
            provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)),
            strategies=(_FixedSignalStrategy(Signal.BUY),),
            start_worker=False,
        )
        controller.start(PaperSessionConfig(symbols=("AMD",), strategy_name="Fixed Signal"))
        controller.run_scan_once()
        snapshot = controller.snapshot()

        self.assertEqual(len(snapshot.orders), 1)
        self.assertEqual(snapshot.orders[0].status, "FILLED")
        self.assertTrue(snapshot.orders[0].fake_money)
        self.assertEqual(len(snapshot.positions), 1)
        controller.shutdown()

    def test_controller_provider_failure_stale_and_strategy_error_create_no_order(self) -> None:
        """Unsafe data or strategy failures should fail closed."""
        for status in (MarketDataStatus.ERROR, MarketDataStatus.STALE, MarketDataStatus.MISSING):
            controller = PaperSessionController(
                provider_manager=_ResultLiveProvider(_market_result(status)),
                strategies=(_FixedSignalStrategy(Signal.BUY),),
                start_worker=False,
            )
            controller.start(PaperSessionConfig(symbols=("AMD",), strategy_name="Fixed Signal"))
            controller.run_scan_once()
            self.assertEqual(controller.snapshot().orders, ())
            controller.shutdown()

        controller = PaperSessionController(
            provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)),
            strategies=(_FailingStrategy(),),
            start_worker=False,
        )
        controller.start(PaperSessionConfig(symbols=("AMD",), strategy_name="Failing Strategy"))
        controller.run_scan_once()
        self.assertEqual(controller.snapshot().orders, ())
        self.assertEqual(controller.snapshot().scanner.error_count, 1)
        controller.shutdown()

    def test_events_are_ordered_filterable_and_include_user_action(self) -> None:
        """The in-memory event stream should be ordered and filterable."""
        controller = PaperSessionController(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)), start_worker=False)
        controller.start(PaperSessionConfig(symbols=("AMD",), strategy_name="RSI"))
        controller.stop()

        events = controller.events()
        filtered = controller.events(after_sequence=events[0].sequence)

        self.assertEqual([event.sequence for event in events], sorted(event.sequence for event in events))
        self.assertTrue(any(event.event_type == "USER_ACTION" for event in events))
        self.assertTrue(all(event.sequence > events[0].sequence for event in filtered))

    def test_engine_facade_exposes_snapshots_and_rejects_bad_start(self) -> None:
        """Dashboard-facing calls should go through EngineFacade only."""
        facade = EngineFacade(
            provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)),
            paper_controller=PaperSessionController(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)), start_worker=False),
        )
        bad_status, bad_payload = facade.start_paper_session({"scan_interval_seconds": 1, "symbols": ["AMD"]})
        good_status, good_payload = facade.start_paper_session({"scan_interval_seconds": 300, "symbols": ["AMD"], "strategy_name": "RSI"})

        self.assertEqual(bad_status, 400)
        self.assertIn("error", bad_payload)
        self.assertEqual(good_status, 201)
        self.assertEqual(good_payload["schema_version"], "1")
        self.assertTrue(facade.get_paper_snapshot().session.active)
        facade.shutdown()


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

    def test_dashboard_html_contains_reference_style_landmarks(self) -> None:
        """Dashboard should render the premium research-console visual landmarks."""
        output = render_dashboard_html(build_dashboard_state())

        self.assertIn("Paper Research Account", output)
        self.assertIn("Start researching", output)
        self.assertIn("Market Posture", output)
        self.assertIn("Daily Market Brief", output)
        self.assertIn("Market Pulse", output)
        self.assertIn("Names in focus", output)
        self.assertIn("Strategy Agreement", output)

    def test_landing_html_ctas_target_application_routes(self) -> None:
        """The public landing page should route CTAs into the local application."""
        output = render_landing_html()

        self.assertIn('href="/app"', output)
        self.assertIn('href="/app/research"', output)
        self.assertIn('href="/app/paper"', output)
        self.assertIn("Start Researching", output)
        self.assertIn("Open Dashboard", output)
        self.assertIn("Explore Research", output)
        self.assertIn("Paper Trading", output)
        self.assertNotIn('href="#"', output)

    def test_about_page_has_company_mission_and_unique_content(self) -> None:
        """The About page should explain the company without duplicating Platform."""
        about = render_about_html()
        platform = render_platform_html()

        self.assertIn("Mission", about)
        self.assertIn("Founder", about)
        self.assertIn("Jeffery M.", about)
        self.assertIn("small team with big dreams", about)
        self.assertIn("research platform", about)
        self.assertIn("not a broker", about)
        self.assertNotEqual(about, platform)
        self.assertNotIn('href="#"', about)

    def test_platform_page_focuses_on_product_workflow(self) -> None:
        """The Platform page should describe QMR.CO workflow sections."""
        output = render_platform_html()

        for section in (
            "Market Research",
            "Research Cards",
            "Strategy Analysis",
            "Portfolio Intelligence",
            "Risk Analysis",
            "Paper Trading",
            "Explainable Intelligence",
            "Reports",
        ):
            self.assertIn(section, output)
        self.assertNotIn('href="#"', output)

    def test_market_status_indicator_uses_matching_color_and_label(self) -> None:
        """Market status labels should not show a closed market with an open marker."""
        self.assertEqual(_market_status_indicator("OPEN"), ("open", "Market Open"))
        self.assertEqual(_market_status_indicator("CLOSED"), ("closed", "Market Closed"))
        self.assertEqual(_market_status_indicator("unexpected"), ("unknown", "Status Unknown"))

        closed_state = DashboardState(
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
        unknown_state = DashboardState(
            version="v0.7.3",
            provider_manager_status="Connected",
            primary_provider="stooq",
            fallback_provider="http",
            market_status="UNKNOWN",
            last_update="12:00:00",
            watchlist_lines=("No symbols selected.",),
            paper_summary=None,
            live_paper_summary=None,
        )

        self.assertIn('class="market-dot closed">Market Closed</div>', render_dashboard_html(closed_state))
        self.assertIn('class="market-dot unknown">Status Unknown</div>', render_dashboard_html(unknown_state))

    def test_sign_in_page_is_explicitly_coming_soon_without_form(self) -> None:
        """The sign-in route should not imply an auth system exists."""
        output = render_sign_in_html()

        self.assertIn("Sign In is coming soon.", output)
        self.assertIn("accounts are not available", output)
        self.assertNotIn("<form", output)
        self.assertNotIn("<input", output)
        self.assertNotIn('type="password"', output)
        self.assertNotIn('href="#"', output)

    def test_learning_pages_contain_level_specific_education(self) -> None:
        """Learning pages should provide real route content for each level."""
        beginner = render_learning_html("beginner")
        intermediate = render_learning_html("intermediate")
        advanced = render_learning_html("advanced")
        dashboard = render_dashboard_html(build_dashboard_state())

        self.assertIn("Beginner Learning", beginner)
        self.assertIn("what a stock or ETF represents", beginner)
        self.assertIn("Intermediate Learning", intermediate)
        self.assertIn("strategy comparison", intermediate)
        self.assertIn("Advanced Learning", advanced)
        self.assertIn("drawdown, Sharpe ratio", advanced)
        self.assertIn('href="/learn/beginner"', dashboard)
        self.assertIn('href="/learn/intermediate"', dashboard)
        self.assertIn('href="/learn/advanced"', dashboard)

    def test_membership_page_shows_pricing_without_payments(self) -> None:
        """Membership should show planned tiers without checkout behavior."""
        output = render_membership_html()

        self.assertIn("$0/month", output)
        self.assertIn("$35.99/month", output)
        self.assertIn("$49.99/month", output)
        self.assertIn("Planned standard price: $69.99/month", output)
        self.assertIn("Feature comparison", output)
        self.assertIn("Coming Soon", output)
        self.assertIn("Explore Free", output)
        self.assertIn("No tier enables live trading", output)
        self.assertNotIn("checkout", output.lower())
        self.assertNotIn('href="#"', output)

    def test_risk_page_uses_meaningful_empty_state_without_fake_metrics(self) -> None:
        """Risk page content should be useful without inventing portfolio numbers."""
        output = render_dashboard_html(build_dashboard_state())
        start = output.index('id="section-security"')
        end = output.index('id="section-settings"')
        risk_section = output[start:end]

        for section in (
            "Risk Analysis",
            "Portfolio Risk Score",
            "Volatility",
            "Maximum Drawdown",
            "Concentration Risk",
            "Sector Exposure",
            "Asset Correlation",
            "Diversification",
            "Data Freshness",
            "Methodology Explanation",
        ):
            self.assertIn(section, risk_section)
        self.assertIn("will appear after a portfolio or paper-trading session contains enough data", risk_section)
        self.assertIn("does not guarantee future performance", risk_section)
        self.assertNotIn("68%", risk_section)
        self.assertNotIn("$", risk_section)

    def test_public_route_renderer_handles_new_pages_without_dead_links(self) -> None:
        """Public page renderer should support every company, education, and pricing route."""
        for route in (
            "/platform",
            "/about",
            "/membership",
            "/pricing",
            "/sign-in",
            "/learn/beginner",
            "/learn/intermediate",
            "/learn/advanced",
        ):
            with self.subTest(route=route):
                output = render_public_route(route)
                self.assertIn("QMR.CO", output)
                self.assertNotIn('href="#"', output)

    def test_dashboard_sidebar_targets_are_real_application_routes(self) -> None:
        """Sidebar controls should have route targets instead of dead placeholders."""
        output = render_dashboard_html(build_dashboard_state())

        self.assertIn('data-route="/app"', output)
        self.assertIn('data-route="/app/research"', output)
        self.assertIn('data-route="/app/market"', output)
        self.assertIn('data-route="/app/strategies"', output)
        self.assertIn('data-route="/app/portfolio"', output)
        self.assertIn('data-route="/app/paper"', output)
        self.assertIn('data-route="/app/risk"', output)
        self.assertIn('data-route="/app/reports"', output)
        self.assertNotIn('href="#"', output)

    def test_symbol_search_markup_and_safe_error_state_exist(self) -> None:
        """Symbol search should be a functional form with safe malformed-symbol handling."""
        output = render_dashboard_html(build_dashboard_state())

        self.assertIn('id="symbol-search"', output)
        self.assertIn('id="symbol-search-input"', output)
        self.assertIn("Enter a valid stock or ETF symbol.", output)
        self.assertIn("/api/markets?symbols=", output)

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

    def test_dashboard_paper_routes_return_safe_snapshots(self) -> None:
        """Paper session API routes should expose safe facade-backed snapshots."""
        controller = PaperSessionController(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)), start_worker=False)
        app = DashboardApplication(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)))
        app.engine = EngineFacade(provider_manager=_ResultLiveProvider(_market_result(MarketDataStatus.OK)), paper_controller=controller)

        start_status, start_payload = app.handle_api_post(
            "/api/paper/start",
            {"starting_cash": 10000, "strategy_name": "RSI", "scan_interval_seconds": 300, "symbols": ["AMD"]},
        )
        session_status, session_payload = app.handle_api_get("/api/paper/session", {})
        scanner_status, scanner_payload = app.handle_api_get("/api/paper/scanner", {})
        events_status, events_payload = app.handle_api_get("/api/paper/events", {"after": ["0"]})
        stop_status, stop_payload = app.handle_api_post("/api/paper/stop", {})

        self.assertEqual(start_status, 201)
        self.assertEqual(session_status, 200)
        self.assertEqual(scanner_status, 200)
        self.assertEqual(events_status, 200)
        self.assertEqual(stop_status, 200)
        self.assertTrue(start_payload["session"]["active"])
        self.assertEqual(session_payload["schema_version"], "1")
        self.assertIn("scanner", scanner_payload)
        self.assertTrue(events_payload["events"])
        self.assertFalse(stop_payload["session"]["active"])
        json.dumps(session_payload)

    def test_dashboard_rejects_malformed_json_without_raw_exception(self) -> None:
        """Malformed dashboard JSON should return a safe 400 response."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())
        server = ThreadingHTTPServer(("localhost", 0), create_dashboard_handler(app))
        try:
            import threading
            from urllib.request import Request

            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.server_address[1]
            request = Request(
                f"http://localhost:{port}/api/paper/start",
                data=b"{bad json",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=2)
            body = raised.exception.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(raised.exception.code, 400)
        self.assertIn("Malformed JSON", body)
        self.assertNotIn("Traceback", body)

    def test_dashboard_handler_serves_landing_and_app_routes(self) -> None:
        """The local server should serve public and app routes without blank views."""
        app = DashboardApplication(provider_manager=_FakeDashboardProvider())
        server = ThreadingHTTPServer(("localhost", 0), create_dashboard_handler(app))
        try:
            import threading

            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.server_address[1]
            bodies = {
                route: urlopen(f"http://localhost:{port}{route}", timeout=2).read().decode("utf-8")
                for route in (
                    "/",
                    "/platform",
                    "/about",
                    "/membership",
                    "/pricing",
                    "/sign-in",
                    "/learn/beginner",
                    "/learn/intermediate",
                    "/learn/advanced",
                    "/app",
                    "/app/research",
                    "/app/market",
                    "/app/strategies",
                    "/app/portfolio",
                    "/app/paper",
                    "/app/risk",
                    "/app/reports",
                )
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertIn("Markets are complicated", bodies["/"])
        for route in (
            "/platform",
            "/about",
            "/membership",
            "/pricing",
            "/sign-in",
            "/learn/beginner",
            "/learn/intermediate",
            "/learn/advanced",
            "/app",
            "/app/research",
            "/app/market",
            "/app/strategies",
            "/app/portfolio",
            "/app/paper",
            "/app/risk",
            "/app/reports",
        ):
            self.assertIn("QMR.CO", bodies[route])
            self.assertNotIn('href="#"', bodies[route])
        for route in ("/app", "/app/research", "/app/market", "/app/strategies", "/app/portfolio", "/app/paper", "/app/risk", "/app/reports"):
            self.assertIn("Paper Research Account", bodies[route])

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


class _FailingStrategy:
    """Small strategy that fails safely in controller tests."""

    name = "Failing Strategy"

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Raise a controlled strategy failure."""
        raise ValueError("raw strategy failure should not escape")


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
        self.calls: list[str] = []

    def connection_status(self) -> str:
        """Return fake provider readiness."""
        return "Connected"

    def primary_provider_name(self) -> str:
        """Return fake primary provider name."""
        return "fake"

    def fallback_provider_names(self) -> str:
        """Return fake fallback provider names."""
        return "none"

    def get_market_data(self, request: MarketDataRequest) -> MarketDataResult:
        """Return a fixed managed result for live paper."""
        self.calls.append(request.symbol.upper())
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
