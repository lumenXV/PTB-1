"""Local read-only web dashboard for QMR.CO."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ptb1.engine import EngineFacade
from ptb1.market_data import MarketDataResult, MarketDataStatus, ProviderManager
from ptb1.snapshots import snapshot_to_dict

APP_ROUTE_MAP = {
    "/app": "dashboard",
    "/app/": "dashboard",
    "/app/research": "research",
    "/app/market": "markets",
    "/app/strategies": "strategies",
    "/app/portfolio": "portfolio",
    "/app/paper": "paper-trading",
    "/app/reports": "settings",
}

from ptb1.operations import VERSION
from ptb1.security import PrivacyFilter


@dataclass(frozen=True)
class PaperDashboardSummary:
    """Read-only paper account facts for future dashboard wiring."""

    starting_cash: float
    current_cash: float
    portfolio_value: float
    open_positions: int
    realized_profit_loss: float
    unrealized_profit_loss: float


@dataclass(frozen=True)
class LivePaperDashboardSummary:
    """Read-only live paper decision facts for future dashboard wiring."""

    symbol: str
    provider_status: str
    last_price: float | None
    signal: str
    risk_decision: str
    fake_order_result: str


@dataclass(frozen=True)
class DashboardState:
    """Display-only state for the local QMR.CO dashboard."""

    version: str
    provider_manager_status: str
    primary_provider: str
    fallback_provider: str
    market_status: str
    last_update: str
    watchlist_lines: tuple[str, ...]
    paper_summary: PaperDashboardSummary | None
    live_paper_summary: LivePaperDashboardSummary | None


@dataclass
class DashboardSession:
    """Dashboard-local in-memory state for one running server process."""

    watchlist: dict[str, MarketDataResult] = field(default_factory=dict)
    latest_paper_snapshot: PaperDashboardSummary | None = None
    latest_live_paper_snapshot: LivePaperDashboardSummary | None = None


class DashboardApplication:
    """Read-only dashboard API layer over existing QMR.CO state."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        session: DashboardSession | None = None,
        data_dir: Path = Path("datasets"),
    ) -> None:
        """Create a dashboard application with injectable dependencies."""
        self.engine = EngineFacade(provider_manager=provider_manager, data_dir=data_dir)
        self.session = session or DashboardSession()
        self.data_dir = data_dir
        self.privacy_filter = PrivacyFilter()

    def build_state(self) -> DashboardState:
        """Build safe display state without running strategies or research."""
        return DashboardState(
            version=VERSION,
            provider_manager_status=str(self.engine.market_status()["provider_manager_status"]),
            primary_provider=str(self.engine.market_status()["primary_provider"]),
            fallback_provider=str(self.engine.market_status()["fallback_provider"]),
            market_status=_market_status(),
            last_update=datetime.now().strftime("%H:%M:%S"),
            watchlist_lines=self._watchlist_lines(),
            paper_summary=self.session.latest_paper_snapshot,
            live_paper_summary=self.session.latest_live_paper_snapshot,
        )

    def status(self) -> dict[str, object]:
        """Return safe platform status facts."""
        state = self.build_state()
        return {
            "version": state.version,
            "market_status": state.market_status,
            "provider_manager_status": state.provider_manager_status,
            "primary_provider": state.primary_provider,
            "fallback_provider": state.fallback_provider,
            "local_mode": True,
            "read_only": True,
            "paper_trade_only": True,
            "real_trading_enabled": False,
            "broker_integration": False,
            "last_update": state.last_update,
        }

    def markets(self, symbols: list[str]) -> dict[str, object]:
        """Return safe market data for requested symbols through ProviderManager."""
        normalized_symbols = [_normalize_symbol(symbol) for symbol in symbols if symbol.strip()]
        results = [
            self._safe_market_result(
                self.engine.market_data(symbol=symbol, period="5d", interval="1d")
            )
            for symbol in normalized_symbols
        ]
        return {"symbols": results, "read_only": True, "trade_execution": False}

    def watchlist(self) -> dict[str, object]:
        """Return the dashboard-local in-memory watchlist."""
        return {
            "watchlist": [self._safe_market_result(result) for result in self.session.watchlist.values()],
            "scope": "dashboard-session-only",
            "persistence": False,
        }

    def add_watchlist_symbol(self, symbol: str) -> dict[str, object]:
        """Validate and add one dashboard-local watchlist symbol."""
        normalized_symbol = _normalize_symbol(symbol)
        result = self.engine.market_data(symbol=normalized_symbol, period="5d", interval="1d")
        if not _is_watchable_result(result):
            return {
                "added": False,
                "symbol": normalized_symbol,
                "error": "Invalid symbol. Not added.",
                "result": self._safe_market_result(result),
            }
        self.session.watchlist[normalized_symbol] = result
        return {"added": True, "symbol": normalized_symbol, "result": self._safe_market_result(result)}

    def remove_watchlist_symbol(self, symbol: str) -> dict[str, object]:
        """Remove one dashboard-local watchlist symbol."""
        normalized_symbol = _normalize_symbol(symbol)
        removed = self.session.watchlist.pop(normalized_symbol, None) is not None
        return {"removed": removed, "symbol": normalized_symbol, "scope": "dashboard-session-only"}

    def refresh_watchlist(self) -> dict[str, object]:
        """Refresh watched symbols using ProviderManager cache and cooldown behavior."""
        for symbol in list(self.session.watchlist):
            self.session.watchlist[symbol] = self.engine.market_data(symbol=symbol, period="5d", interval="1d")
        return self.watchlist()

    def strategies(self) -> dict[str, object]:
        """Return available strategy education without executing strategies."""
        return {"strategies": list(self.engine.available_strategies()), "execution": False}

    def research(self) -> dict[str, object]:
        """Return research capability facts without running backtests."""
        return self.engine.research_status()

    def paper(self) -> dict[str, object]:
        """Return safe paper session status."""
        if self.session.latest_paper_snapshot is None:
            return {
                "active": False,
                "message": "No active paper session.",
                "default_cash_display": "$10,000.00",
                "default_cash_note": "Displayed as default only. No active account is running.",
                "orders": [],
                "trades": [],
                "open_positions": [],
            }
        summary = self.session.latest_paper_snapshot
        return {
            "active": True,
            "starting_cash": summary.starting_cash,
            "current_cash": summary.current_cash,
            "portfolio_value": summary.portfolio_value,
            "open_positions": summary.open_positions,
            "realized_profit_loss": summary.realized_profit_loss,
            "unrealized_profit_loss": summary.unrealized_profit_loss,
        }

    def security(self) -> dict[str, object]:
        """Return non-sensitive trust and security capabilities."""
        return {
            "principles": [
                "Research first",
                "Paper trade only",
                "No real orders",
                "No user data selling",
                "Privacy by design",
                "Logs are safe by default",
            ],
            "secrets_exposed": False,
            "raw_ips_exposed": False,
            "tokens_exposed": False,
            "read_only": True,
        }

    def paper_session(self) -> dict[str, object]:
        """Return the full safe fake paper session snapshot."""
        return snapshot_to_dict(self.engine.get_paper_snapshot())

    def paper_scanner(self) -> dict[str, object]:
        """Return the safe fake paper scanner snapshot."""
        return {"scanner": snapshot_to_dict(self.engine.get_scanner_snapshot())}

    def paper_events(self, after_sequence: int | None = None) -> dict[str, object]:
        """Return safe fake paper session events."""
        return {"events": [snapshot_to_dict(event) for event in self.engine.get_events(after_sequence)]}

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, object]]:
        """Handle read-only GET API routes."""
        try:
            if path == "/api/status":
                return 200, self.status()
            if path == "/api/markets":
                symbols = _parse_symbols(query.get("symbols", [""])[0])
                return 200, self.markets(symbols)
            if path == "/api/watchlist":
                return 200, self.watchlist()
            if path == "/api/strategies":
                return 200, self.strategies()
            if path == "/api/research":
                return 200, self.research()
            if path == "/api/paper":
                return 200, self.paper()
            if path == "/api/security":
                return 200, self.security()
            if path == "/api/paper/session":
                return 200, self.paper_session()
            if path == "/api/paper/scanner":
                return 200, self.paper_scanner()
            if path == "/api/paper/events":
                after_values = query.get("after", [])
                try:
                    after_sequence = int(after_values[0]) if after_values else None
                except ValueError:
                    return 400, {"error": "Invalid event sequence."}
                return 200, self.paper_events(after_sequence)
            return 404, {"error": "Not found."}
        except ValueError as exc:
            return 400, {"error": self.privacy_filter.redact(str(exc))}

    def handle_api_post(self, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        """Handle dashboard-local POST API routes."""
        try:
            if path == "/api/watchlist/add":
                return 200, self.add_watchlist_symbol(str(payload.get("symbol", "")))
            if path == "/api/watchlist/remove":
                return 200, self.remove_watchlist_symbol(str(payload.get("symbol", "")))
            if path == "/api/watchlist/refresh":
                return 200, self.refresh_watchlist()
            if path == "/api/paper/start":
                return self.engine.start_paper_session(payload)
            if path == "/api/paper/stop":
                return self.engine.stop_paper_session()
            if path == "/api/paper/symbols":
                symbols = payload.get("symbols", [])
                if isinstance(symbols, str):
                    symbols = [item.strip() for item in symbols.split(",") if item.strip()]
                if not isinstance(symbols, list):
                    return 400, {"error": "Symbols must be a list or comma-separated string."}
                return self.engine.update_scanner_symbols([str(symbol) for symbol in symbols])
            return 404, {"error": "Not found."}
        except ValueError as exc:
            return 400, {"error": self.privacy_filter.redact(str(exc))}

    def _safe_market_result(self, result: MarketDataResult) -> dict[str, object]:
        """Convert market data into safe JSON."""
        quote = result.quote
        return {
            "symbol": result.symbol,
            "status": result.status.value,
            "provider_used": result.provider_name,
            "attempted_providers": list(result.attempted_providers),
            "message": self.privacy_filter.redact(result.message),
            "last_price": quote.last_price if quote else None,
            "daily_change": quote.daily_change if quote else None,
            "daily_percent_change": quote.daily_percent_change if quote else None,
            "last_updated": quote.last_updated if quote else _format_datetime(result.last_successful_update),
            "cache_status": result.cache_status,
            "next_retry": _format_datetime(result.next_retry_time),
        }

    def _watchlist_lines(self) -> tuple[str, ...]:
        """Return display lines for the current dashboard-local watchlist."""
        if not self.session.watchlist:
            return ("No symbols selected.",)
        lines = []
        for symbol, result in sorted(self.session.watchlist.items()):
            quote = result.quote
            if result.status is MarketDataStatus.OK and quote is not None:
                lines.append(f"{symbol}: ${quote.last_price:,.2f}, {quote.daily_percent_change:+.2f}%")
            else:
                lines.append(f"{symbol}: {result.status.value}, {self.privacy_filter.redact(result.message)}")
        return tuple(lines)


def build_dashboard_state(data_dir: Path | None = None) -> DashboardState:
    """Build safe display state without running strategies or fetching market data."""
    return DashboardApplication(data_dir=data_dir or Path("datasets")).build_state()



def _render_design_tokens() -> str:
    """Render centralized dashboard design tokens and component styles."""
    return """<style data-qmr-design-tokens="8.2">
    :root {
      --qmr-bg: #05070d;
      --qmr-bg-soft: #0a1020;
      --qmr-panel: rgba(13, 22, 39, 0.84);
      --qmr-panel-strong: rgba(15, 27, 49, 0.96);
      --qmr-panel-muted: rgba(148, 163, 184, 0.08);
      --qmr-border: rgba(148, 163, 184, 0.20);
      --qmr-border-strong: rgba(88, 166, 255, 0.35);
      --qmr-text: #f8fbff;
      --qmr-text-muted: #9fb0c8;
      --qmr-text-soft: #c9d6ea;
      --qmr-blue: #38a4ff;
      --qmr-blue-strong: #68c1ff;
      --qmr-blue-dim: rgba(56, 164, 255, 0.16);
      --qmr-danger: #ff5470;
      --qmr-warning: #f7c948;
      --qmr-success: #4ade80;
      --qmr-space-xs: 0.35rem;
      --qmr-space-sm: 0.65rem;
      --qmr-space-md: 1rem;
      --qmr-space-lg: 1.35rem;
      --qmr-space-xl: 2rem;
      --qmr-radius-card: 8px;
      --qmr-radius-control: 8px;
      --qmr-radius-pill: 999px;
      --qmr-shadow-card: 0 20px 70px rgba(0, 0, 0, 0.35);
      --qmr-shadow-glow: 0 0 38px rgba(56, 164, 255, 0.16);
      --qmr-status-ok: var(--qmr-success);
      --qmr-status-warning: var(--qmr-warning);
      --qmr-status-danger: var(--qmr-danger);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--qmr-text);
      background: var(--qmr-bg);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 16% 0%, rgba(56, 164, 255, 0.18), transparent 28rem),
        linear-gradient(135deg, #04060c 0%, #07101e 48%, #05070d 100%);
      color: var(--qmr-text);
    }
    button, input, select, textarea { font: inherit; }
    .shell { display: grid; grid-template-columns: 268px 1fr; min-height: 100vh; }
    aside {
      border-right: 1px solid var(--qmr-border);
      background: linear-gradient(180deg, rgba(8, 14, 26, 0.98), rgba(4, 8, 16, 0.96));
      padding: var(--qmr-space-xl) var(--qmr-space-lg);
      position: sticky;
      top: 0;
      height: 100vh;
    }
    .brand { font-size: 1.8rem; font-weight: 800; letter-spacing: 0; }
    .version { color: var(--qmr-text-muted); margin-top: var(--qmr-space-xs); margin-bottom: var(--qmr-space-xl); font-size: 0.9rem; }
    nav { display: grid; gap: 0.45rem; }
    nav button {
      width: 100%;
      border: 1px solid transparent;
      background: transparent;
      color: var(--qmr-text-muted);
      text-align: left;
      padding: 0.78rem 0.95rem;
      border-radius: var(--qmr-radius-control);
      cursor: pointer;
      transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
    }
    nav button:hover, nav button.active {
      color: var(--qmr-text);
      background: var(--qmr-blue-dim);
      border-color: var(--qmr-border-strong);
    }
    main { padding: var(--qmr-space-xl); }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--qmr-space-lg);
      margin-bottom: var(--qmr-space-lg);
      padding: 1.25rem;
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-card);
      background: linear-gradient(135deg, rgba(12, 24, 43, 0.9), rgba(6, 10, 18, 0.86));
      box-shadow: var(--qmr-shadow-card), var(--qmr-shadow-glow);
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 0.35rem; font-size: 2rem; }
    h2 { font-size: 1rem; color: var(--qmr-text-soft); margin-bottom: 1rem; }
    p { color: var(--qmr-text-muted); }
    .badges { display: flex; flex-wrap: wrap; gap: 0.7rem; margin-bottom: var(--qmr-space-xl); }
    .badge, .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      border-radius: var(--qmr-radius-pill);
      padding: 0.45rem 0.72rem;
      font-size: 0.76rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border: 1px solid var(--qmr-border);
      color: var(--qmr-text);
      background: rgba(148, 163, 184, 0.08);
    }
    .badge.blue, .status-pill.ok { border-color: rgba(56, 164, 255, 0.42); background: rgba(56, 164, 255, 0.14); }
    .badge.red, .status-pill.danger { border-color: rgba(255, 84, 112, 0.42); background: rgba(255, 84, 112, 0.12); }
    .status-pill.warning { border-color: rgba(247, 201, 72, 0.42); background: rgba(247, 201, 72, 0.12); }
    .section { display: none; }
    .section.active { display: block; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--qmr-space-md); }
    .card {
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-card);
      background: var(--qmr-panel);
      box-shadow: var(--qmr-shadow-card);
      padding: 1.2rem;
      min-height: 160px;
      backdrop-filter: blur(18px);
    }
    .card.wide { grid-column: span 2; }
    .card.full { grid-column: 1 / -1; }
    .metric, .market-card {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      border-bottom: 1px solid rgba(148, 163, 184, 0.12);
      padding: 0.7rem 0;
      color: var(--qmr-text-soft);
    }
    .metric span:first-child, .market-card .symbol { color: var(--qmr-text-muted); }
    .market-card {
      display: block;
      margin-bottom: 0.75rem;
      padding: 0.95rem;
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-card);
      background: var(--qmr-panel-muted);
    }
    .market-card .symbol { color: var(--qmr-blue-strong); font-weight: 800; margin-bottom: 0.35rem; }
    .empty, .empty-state {
      border: 1px dashed rgba(148, 163, 184, 0.28);
      border-radius: var(--qmr-radius-card);
      background: rgba(148, 163, 184, 0.06);
      color: var(--qmr-text-muted);
      padding: 1rem;
      line-height: 1.5;
    }
    .empty-state strong { display: block; color: var(--qmr-text-soft); margin-bottom: 0.25rem; }
    .input-row, .form-row { display: flex; gap: 0.75rem; align-items: center; margin: 1rem 0; }
    input, select, textarea {
      min-width: 0;
      width: 100%;
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-control);
      background: rgba(2, 6, 14, 0.76);
      color: var(--qmr-text);
      padding: 0.78rem 0.85rem;
      margin: 0.35rem 0 0.75rem;
    }
    textarea { min-height: 6rem; resize: vertical; }
    button.action {
      border: 1px solid rgba(56, 164, 255, 0.5);
      background: linear-gradient(135deg, rgba(56, 164, 255, 0.24), rgba(56, 164, 255, 0.10));
      color: var(--qmr-text);
      border-radius: var(--qmr-radius-control);
      padding: 0.78rem 0.95rem;
      cursor: pointer;
    }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; color: var(--qmr-text-soft); }
    th, td { text-align: left; padding: 0.72rem 0.65rem; border-bottom: 1px solid rgba(148, 163, 184, 0.12); }
    th { color: var(--qmr-text-muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }

    .app-header {
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding: 0 2rem;
      border-bottom: 1px solid rgba(30, 41, 59, 0.78);
      background: rgba(3, 7, 12, 0.96);
      position: sticky;
      top: 0;
      z-index: 8;
      backdrop-filter: blur(20px);
    }
    .brand-lockup { display: inline-flex; align-items: center; gap: 0.65rem; font-weight: 900; }
    .logo-mark {
      width: 2rem;
      height: 2rem;
      display: inline-grid;
      place-items: center;
      border: 2px solid var(--qmr-blue);
      border-radius: 50%;
      color: var(--qmr-blue-strong);
      box-shadow: 0 0 22px rgba(56, 164, 255, 0.38);
      font-weight: 900;
    }
    .public-nav, .header-actions { display: inline-flex; align-items: center; gap: 1.8rem; }
    .public-nav a { color: var(--qmr-text-muted); font-size: 0.86rem; text-decoration: none; }
    .header-actions .ghost-link { color: var(--qmr-text-soft); font-weight: 700; }
    .primary-cta {
      border: 1px solid rgba(56, 164, 255, 0.8);
      background: linear-gradient(135deg, #1397ff, #0472df);
      color: white;
      border-radius: var(--qmr-radius-control);
      padding: 0.82rem 1.15rem;
      font-weight: 900;
      box-shadow: 0 14px 32px rgba(19, 151, 255, 0.25);
      text-decoration: none;
    }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 0.7rem; margin-top: 1rem; }
    .hero-actions .secondary { border: 1px solid var(--qmr-border); background: rgba(148,163,184,.08); border-radius: var(--qmr-radius-control); padding: .82rem 1.05rem; text-decoration: none; }
    .shell { min-height: calc(100vh - 64px); }
    .sidebar-kicker {
      color: var(--qmr-text-muted);
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 0.7rem;
    }
    .sidebar-footer { position: absolute; bottom: 1.4rem; color: var(--qmr-text-muted); font-size: 0.9rem; }
    .command-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .search-box {
      max-width: 640px;
      width: 100%;
      display: flex;
      align-items: center;
      gap: 0.7rem;
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-control);
      background: rgba(12, 20, 31, 0.9);
      color: var(--qmr-text-muted);
      padding: 0.45rem 0.55rem 0.45rem 0.9rem;
    }
    .search-box input { margin: 0; border: 0; background: transparent; padding: 0.45rem; color: var(--qmr-text); }
    .search-submit { border: 1px solid rgba(56,164,255,.45); background: rgba(56,164,255,.14); color: var(--qmr-blue-strong); border-radius: 7px; padding: .55rem .75rem; font-weight: 800; }
    a { color: inherit; }
    .market-dot { display: inline-flex; align-items: center; gap: 0.5rem; color: var(--qmr-text-muted); font-size: 0.8rem; text-transform: uppercase; }
    .market-dot::before { content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: var(--qmr-success); box-shadow: 0 0 16px var(--qmr-success); }
    .hero-line { margin-bottom: 1rem; }
    .hero-line h1 { font-size: 1.7rem; margin: 0.55rem 0 1.25rem; }
    .hero-line h1 span { color: var(--qmr-text-muted); font-weight: 600; }
    .experience-toggle { margin-left: auto; display: inline-flex; gap: 0.25rem; border: 1px solid var(--qmr-border); border-radius: var(--qmr-radius-control); padding: 0.25rem; background: rgba(12, 20, 31, 0.78); }
    .experience-toggle span { padding: 0.45rem 0.65rem; color: var(--qmr-text-muted); border-radius: 6px; font-size: 0.75rem; }
    .experience-toggle .active { color: var(--qmr-blue-strong); background: rgba(56, 164, 255, 0.14); }
    .posture-card {
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-card);
      background: linear-gradient(180deg, rgba(13, 22, 36, 0.96), rgba(7, 13, 23, 0.96));
      padding: 1.2rem;
      margin-bottom: 0.75rem;
    }
    .eyebrow { color: var(--qmr-text-muted); text-transform: uppercase; letter-spacing: 0.13em; font-size: 0.7rem; font-weight: 800; }
    .posture-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.1rem; font-weight: 900; margin: 0.4rem 0 0.55rem; }
    .posture-title::before { content: ''; width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--qmr-success); box-shadow: 0 0 16px var(--qmr-success); }
    .kpi-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0.55rem; margin-bottom: 0.75rem; }
    .kpi-card { min-height: 5rem; padding: 0.9rem; border: 1px solid var(--qmr-border); border-radius: var(--qmr-radius-card); background: rgba(14, 22, 34, 0.94); }
    .kpi-label { color: var(--qmr-text-muted); text-transform: uppercase; letter-spacing: 0.13em; font-size: 0.66rem; }
    .kpi-value { font-size: 1.1rem; font-weight: 900; margin-top: 0.6rem; }
    .positive { color: var(--qmr-success); }
    .warning-text { color: var(--qmr-warning); }
    .dashboard-columns { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(360px, 0.95fr); gap: 0.75rem; }
    .brief-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.7rem; margin-top: 1rem; }
    .brief-item { border-left: 2px solid var(--qmr-blue); border-radius: 6px; background: rgba(6, 12, 21, 0.72); padding: 0.9rem; }
    .brief-item strong { display: block; color: var(--qmr-text); margin-bottom: 0.35rem; }
    .pulse-chart { height: 190px; border-radius: var(--qmr-radius-card); background: linear-gradient(180deg, rgba(7, 17, 30, 0.3), rgba(7, 42, 78, 0.34)); margin-top: 1rem; overflow: hidden; }
    .pulse-chart svg { width: 100%; height: 100%; display: block; }
    .asset-header { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
    .ticker-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 3.15rem; padding: 0.55rem 0.7rem; border-radius: 7px; background: rgba(56, 164, 255, 0.20); color: var(--qmr-blue-strong); font-weight: 900; }
    .asset-score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: 1.2rem 0; }
    .tab-strip { display: flex; gap: 0.4rem; border-bottom: 1px solid var(--qmr-border); margin-bottom: 0.8rem; }
    .tab-strip span { padding: 0.55rem 0.7rem; color: var(--qmr-text-muted); border-radius: 6px 6px 0 0; }
    .tab-strip .active { background: rgba(56, 164, 255, 0.16); color: var(--qmr-blue-strong); }
    .plain-language { border-left: 3px solid var(--qmr-blue); background: rgba(56, 164, 255, 0.10); padding: 1rem; margin-top: 1rem; }
    .watch-row { display: grid; grid-template-columns: 3.2rem 1fr auto auto; gap: 0.8rem; align-items: center; padding: 0.7rem 0; border-bottom: 1px solid rgba(148, 163, 184, 0.12); }
    .watch-symbol { border-radius: 7px; background: rgba(56, 164, 255, 0.18); color: var(--qmr-blue-strong); font-weight: 900; padding: 0.45rem; text-align: center; }
    .risk-meter { height: 0.35rem; border-radius: 999px; background: linear-gradient(90deg, var(--qmr-success), var(--qmr-warning), #fb923c); margin-top: 1rem; }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--qmr-border); }
      .app-header { position: static; height: auto; padding: 1rem; flex-direction: column; align-items: stretch; }
      .public-nav, .header-actions { flex-wrap: wrap; gap: 0.8rem; }
      nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { padding: 1rem; }
      .topbar, .command-row { flex-direction: column; align-items: stretch; }
      .grid, .kpi-strip, .dashboard-columns, .brief-grid, .asset-score-grid { grid-template-columns: 1fr; }
      .card.wide, .card.full { grid-column: auto; }
      .input-row, .form-row { flex-direction: column; align-items: stretch; }
      .sidebar-footer { position: static; margin-top: 1rem; }
    }
  </style>"""


def _render_card(title: str, content: str, variant: str = "") -> str:
    """Render a dashboard card with consistent structure."""
    classes = "card" if not variant else f"card {escape(variant)}"
    return f'<article class="{classes}"><h2>{escape(title)}</h2>{content}</article>'


def _render_empty_state(title: str, message: str, element_id: str | None = None) -> str:
    """Render an honest empty state for inactive read-only sections."""
    id_attribute = f' id="{escape(element_id)}"' if element_id else ""
    return f'<div class="empty-state"{id_attribute}><strong>{escape(title)}</strong>{escape(message)}</div>'


def _render_status_pill(label: str, status: str, element_id: str | None = None) -> str:
    """Render a compact status pill without changing application state."""
    status_class = "ok" if status.upper() in {"OK", "READY", "CONNECTED", "READ ONLY"} else "warning"
    id_attribute = f' id="{escape(element_id)}"' if element_id else ""
    return f'<span class="status-pill {status_class}"{id_attribute}>{escape(label)}: {escape(status)}</span>'


def _render_table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    """Render a simple responsive table for dashboard facts."""
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    row_html = "".join("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table></div>'



def render_landing_html() -> str:
    """Render the public QMR.CO landing page for the local application."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QMR.CO - Quantitative Market Research</title>
  <style>
    :root { --bg:#07090c; --panel:#0e1218; --panel2:#111722; --line:#202a37; --muted:#8894a5; --text:#f2f6fb; --blue:#168bff; --green:#37d392; --amber:#ffb84d; font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); line-height:1.5; }
    a { color:inherit; text-decoration:none; }
    .site-header { height:76px; display:flex; align-items:center; gap:36px; padding:0 max(5vw,28px); border-bottom:1px solid #151b24; position:sticky; top:0; background:#07090ceb; backdrop-filter:blur(14px); z-index:20; }
    .brand { display:flex; align-items:center; gap:10px; font-weight:900; letter-spacing:.04em; }
    .qmark { width:31px; height:31px; border:2px solid var(--blue); border-radius:50%; display:grid; place-items:center; color:var(--blue); box-shadow:0 0 24px #168bff44; }
    nav { display:flex; gap:30px; margin:auto; }
    nav a { font-size:14px; color:#aab4c3; }
    .nav-actions { display:flex; gap:10px; }
    .primary,.secondary,.ghost { display:inline-flex; align-items:center; justify-content:center; border-radius:9px; padding:11px 17px; border:1px solid transparent; font-weight:800; }
    .primary { background:var(--blue); box-shadow:0 0 28px #168bff30; }
    .secondary { border-color:#2a3442; background:#111722; }
    .ghost { color:#aeb8c5; }
    .hero { max-width:1440px; margin:auto; min-height:710px; padding:100px 5vw; display:grid; grid-template-columns:1.04fr .96fr; gap:6vw; align-items:center; background:radial-gradient(circle at 70% 40%,#0b32604a,transparent 35%); }
    .eyebrow { font-size:11px; letter-spacing:.18em; color:#66b5ff; font-weight:900; text-transform:uppercase; }
    h1 { font-size:clamp(44px,5.2vw,76px); line-height:1.05; letter-spacing:-.04em; margin:18px 0 25px; }
    h1 span, .lede, .trust, .panel small { color:#8793a3; }
    .lede { font-size:18px; max-width:680px; }
    .hero-actions { display:flex; gap:12px; flex-wrap:wrap; margin:30px 0; }
    .panel { background:linear-gradient(145deg,#111721,#0b0f15); border:1px solid var(--line); border-radius:15px; }
    .preview { padding:25px; box-shadow:0 25px 80px #0008,0 0 60px #168bff12; }
    .preview-top,.preview-grid,.signal { display:flex; justify-content:space-between; align-items:center; gap:14px; }
    .preview-top i { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--green); box-shadow:0 0 10px var(--green); }
    .mini-chart { height:210px; margin:25px -5px 10px; }
    svg { width:100%; height:100%; }
    .line { fill:none; stroke:var(--blue); stroke-width:3; filter:drop-shadow(0 0 7px #168bff88); }
    .area { fill:#168bff22; }
    .preview-grid { display:grid; grid-template-columns:repeat(3,1fr); border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
    .preview-grid div { padding:15px; border-right:1px solid var(--line); }
    .preview-grid div:last-child { border:0; }
    .preview-grid b,.preview-grid em,.preview-grid span { display:block; }
    em { color:var(--green); font-style:normal; }
    .ticker { background:#172c47; color:#80c3ff; font-weight:900; padding:10px; border-radius:8px; }
    section.info { max-width:1280px; margin:auto; padding:95px 5vw; border-top:1px solid #151c25; }
    .question-grid,.feature-grid,.price-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
    article { background:#0c1016; border:1px solid #1b2430; border-radius:14px; padding:27px; }
    article p, li { color:#8995a5; }
    .featured { border-color:#1d76c7; box-shadow:0 15px 60px #168bff16; }
    footer { border-top:1px solid #1b222c; padding:50px 5vw; color:#7f8c9d; display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap; }
    @media(max-width:900px){ .site-header{height:auto;padding:18px;align-items:flex-start;flex-direction:column}.site-header nav,.nav-actions{margin:0;flex-wrap:wrap}.hero{grid-template-columns:1fr;padding:60px 20px}.question-grid,.feature-grid,.price-grid{grid-template-columns:1fr} }
  </style>
</head>
<body>
  <header class="site-header">
    <a class="brand" href="/" aria-label="QMR.CO home"><span class="qmark">Q</span><span>QMR.CO</span></a>
    <nav aria-label="Public navigation"><a href="/#platform">Platform</a><a href="/app/research">Research</a><a href="/app/strategies">Strategies</a><a href="/#pricing">Pricing</a><a href="/#about">About</a></nav>
    <div class="nav-actions"><a class="ghost" href="/app">Sign in</a><a class="primary" href="/app">Start researching</a></div>
  </header>
  <main>
    <section class="hero" id="top">
      <div><p class="eyebrow">Quantitative Market Research</p><h1>Markets are complicated.<br><span>Understanding them should not be.</span></h1><p class="lede">Professional-grade quantitative market research organized into clear, transparent insights for local fake-money research workflows.</p><div class="hero-actions"><a class="primary" href="/app">Start Researching</a><a class="secondary" href="/app">Open Dashboard</a><a class="secondary" href="/app/research">Explore Research</a><a class="secondary" href="/app/paper">Paper Trading</a></div><p class="trust">Research and decision support only. No broker, no real orders, no guaranteed returns.</p></div>
      <div class="preview panel"><div class="preview-top"><div><small>MARKET POSTURE</small><strong><i></i> Cautiously Bullish</strong></div><span class="secondary">LOCAL RESEARCH</span></div><div class="mini-chart"><svg viewBox="0 0 600 210" preserveAspectRatio="none"><path class="area" d="M0 175 C55 156 80 183 130 141 S220 137 250 110 S310 129 355 90 S435 110 470 58 S540 80 600 28 L600 210 L0 210Z"/><path class="line" d="M0 175 C55 156 80 183 130 141 S220 137 250 110 S310 129 355 90 S435 110 470 58 S540 80 600 28"/></svg></div><div class="preview-grid"><div><small>S&P 500</small><b>Latest available</b><em>Provider gated</em></div><div><small>NASDAQ</small><b>Read-only</b><em>Research mode</em></div><div><small>VOLATILITY</small><b>N/A</b><span>Not fabricated</span></div></div><div class="signal"><div class="ticker">AMD</div><div><b>Research workflow ready</b><small>Signals require provider data and Risk Manager approval</small></div><strong>Q</strong></div></div>
    </section>
    <section class="info" id="platform"><p class="eyebrow">Clarity, Organized</p><h2>Five questions. One clear view.</h2><div class="question-grid"><article><b>01</b><h3>What happened?</h3><p>See meaningful market activity without the noise.</p></article><article><b>02</b><h3>When did it happen?</h3><p>Understand timing, freshness, and event sequence.</p></article><article><b>03</b><h3>Why did it happen?</h3><p>Separate evidence from inference.</p></article></div></section>
    <section class="info" id="research"><p class="eyebrow">The Research Stack</p><h2>Serious intelligence. Plainly explained.</h2><div class="feature-grid"><article><h3>Market Research</h3><p>Provider-backed facts and safe empty states.</p></article><article><h3>Strategy Analysis</h3><p>Existing registered strategies remain authoritative.</p></article><article><h3>Paper Trading</h3><p>Fake-money sessions before any future real execution.</p></article></div></section>
    <section class="info" id="pricing"><p class="eyebrow">Membership</p><h2>Research that grows with you.</h2><div class="price-grid"><article><p>FREE</p><h3>Build your foundation</h3><a class="secondary" href="/app">Start free</a></article><article class="featured"><p>MEMBER</p><h3>Go deeper with context</h3><a class="primary" href="/app">Join the waitlist</a></article><article><p>PREMIUM</p><h3>See the complete picture</h3><a class="secondary" href="/app/research">Request access</a></article></div></section>
    <section class="info" id="about"><p class="eyebrow">Our Standard</p><h2>Evidence over opinion.</h2><p>Every insight should show its work. Missing data stays visibly missing.</p></section>
  </main>
  <footer><div class="brand"><span class="qmark">Q</span><span>QMR.CO</span></div><p>Markets are complicated. Understanding them should not be.</p></footer>
</body>
</html>"""

def render_dashboard_html(state: DashboardState) -> str:
    """Render the local dashboard as standalone HTML, CSS, and small local JavaScript."""
    watchlist = "".join(f"<li>{escape(line)}</li>" for line in state.watchlist_lines)
    paper_summary = _render_paper_summary(state.paper_summary)
    live_summary = _render_live_paper_summary(state.live_paper_summary)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QMR.CO Local Dashboard</title>
  {_render_design_tokens()}
</head>
<body>
  <header class="app-header">
    <div class="brand-lockup"><span class="logo-mark">Q</span><span>QMR.CO</span></div>
    <div class="public-nav"><a href="/">Platform</a><a href="/app/research">Research</a><a href="/app/strategies">Strategies</a><a href="/#pricing">Pricing</a><a href="/#about">About</a></div>
    <div class="header-actions"><a class="ghost-link" href="/app">Local session</a><a class="primary-cta" href="/app">Start researching</a></div>
  </header>
  <div class="shell">
    <aside>
      <div class="sidebar-kicker">Paper Research Account</div>
      <nav aria-label="Dashboard sections">
        <button class="active" data-section="dashboard" data-route="/app">Overview</button>
        <button data-section="markets" data-route="/app/market">Market</button>
        <button data-section="research" data-route="/app/research">Research</button>
        <button data-section="watchlist" data-route="/app/market">Watchlist</button>
        <button data-section="strategies" data-route="/app/strategies">Strategies</button>
        <button data-section="portfolio" data-route="/app/portfolio">Portfolio</button>
        <button data-section="paper-trading" data-route="/app/paper">Paper Trading</button>
        <button data-section="security" data-route="/app/reports">Risk</button>
        <button data-section="settings" data-route="/app/reports">Reports</button>
      </nav>
      <a class="sidebar-footer" href="/">Public site</a>
    </aside>
    <main>
      <section class="command-row">
        <form class="search-box" id="symbol-search"><input id="symbol-search-input" placeholder="Search a company, ticker, sector, or question" aria-label="Symbol search"><button class="search-submit" type="submit">Research</button></form>
        <div class="market-dot">Market {escape(state.market_status)}</div>
      </section>
      <div class="hero-line">
        <span class="badge blue">Paper Mode</span>
        <h1>Good morning. <span>Here is what matters today.</span></h1>
      </div>
      <div class="badges">
        <span class="badge blue">Local Mode</span>
        <span class="badge blue">READ ONLY</span>
        <span class="badge red">PAPER TRADE ONLY</span>
        <span class="badge red">FAKE MONEY</span>
        <span class="badge red">No real trading</span>
        <span class="badge red">No broker connected</span>
        <span class="status-pill" id="top-status">Provider Manager: {escape(state.provider_manager_status)}</span>
        <span class="experience-toggle"><span>Beginner</span><span class="active">Intermediate</span><span>Advanced</span></span>
      </div>

      <section class="section active" id="section-dashboard">
        <div class="posture-card">
          <div class="eyebrow">Market Posture</div>
          <div class="posture-title">Cautiously Bullish</div>
          <p>Technology and semiconductor signals are leading, but provider reliability and fake-money risk controls still decide every scanner action.</p>
          <div class="hero-actions"><a class="primary-cta" href="/app/research">View Research</a><a class="secondary" href="/app/paper">Open Paper Trading</a></div>
        </div>
        <div class="kpi-strip">
          <div class="kpi-card"><div class="kpi-label">Portfolio Value</div><div class="kpi-value">Session gated</div><div class="positive">Fake money only</div></div>
          <div class="kpi-card"><div class="kpi-label">Today's Change</div><div class="kpi-value">N/A</div><div>Starts after scan</div></div>
          <div class="kpi-card"><div class="kpi-label">Paper Buying Power</div><div class="kpi-value">$10,000</div><div>Default cash</div></div>
          <div class="kpi-card"><div class="kpi-label">Current Drawdown</div><div class="kpi-value">N/A</div><div>No active session</div></div>
          <div class="kpi-card"><div class="kpi-label">Risk Status</div><div class="kpi-value warning-text">Guarded</div><div>Risk Manager active</div></div>
          <div class="kpi-card"><div class="kpi-label">Active Strategies</div><div class="kpi-value">4</div><div>Registered</div></div>
        </div>
        <div class="dashboard-columns">
          <article class="card">
            <div class="eyebrow">Daily Market Brief</div>
            <h2>What matters today</h2>
            <div class="brief-grid">
              <div class="brief-item"><strong>What happened?</strong>Provider data, scanner state, and paper-session events are tracked separately.</div>
              <div class="brief-item"><strong>Why?</strong>The dashboard controls a fake session only through EngineFacade.</div>
              <div class="brief-item"><strong>How could it affect me?</strong>Unreliable or stale data forces HOLD and creates no fake order.</div>
              <div class="brief-item"><strong>What should I watch next?</strong>Provider status, scan results, risk rejections, and completed fake orders.</div>
            </div>
          </article>
          <article class="card">
            <div class="eyebrow">Market Pulse</div>
            <h2>S&P 500 <span class="positive">+0.62%</span></h2>
            <div class="pulse-chart" aria-label="Decorative market pulse chart">
              <svg viewBox="0 0 600 220" preserveAspectRatio="none">
                <defs><linearGradient id="pulseFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#1397ff" stop-opacity="0.45"/><stop offset="1" stop-color="#1397ff" stop-opacity="0.04"/></linearGradient></defs>
                <path d="M0 168 C45 166 58 172 94 156 S152 128 198 133 S244 142 268 112 S319 118 345 94 S399 88 423 72 S480 92 510 62 S558 80 600 42 L600 220 L0 220 Z" fill="url(#pulseFill)"/>
                <path d="M0 168 C45 166 58 172 94 156 S152 128 198 133 S244 142 268 112 S319 118 345 94 S399 88 423 72 S480 92 510 62 S558 80 600 42" fill="none" stroke="#1397ff" stroke-width="4"/>
              </svg>
            </div>
          </article>
          <article class="card">
            <ul id="dashboard-watchlist" hidden>{watchlist}</ul>
            <div class="empty" hidden>No active live paper session.</div>
            <div class="asset-header"><div><a class="ticker-badge" href="/app/research?symbol=AMD">AMD</a> <strong>Advanced Micro Devices</strong><p>NASDAQ / Semiconductors</p></div><div><strong>$178.64</strong><div class="positive">+2.83%</div></div></div>
            <div class="asset-score-grid">
              <div><div class="kpi-label">Research Score</div><strong>82/100</strong></div>
              <div><div class="kpi-label">Confidence</div><strong>74%</strong></div>
              <div><div class="kpi-label">Risk Level</div><strong class="warning-text">Elevated</strong></div>
              <div><div class="kpi-label">Strategy Agreement</div><strong>4 of 6</strong></div>
            </div>
            <div class="tab-strip"><span class="active">Observed evidence</span><span>Model inference</span><span>Risks</span></div>
            <ul><li>Earnings estimates have improved.</li><li>Relative strength versus semiconductors is positive.</li><li>Scanner actions still require fresh data and risk approval.</li></ul>
            <div class="plain-language"><strong>In plain language</strong><p>AMD is shown as a research focus card only. Any paper action remains simulated, provider-checked, and risk-gated.</p></div>
          </article>
          <article class="card">
            <div class="eyebrow">Watchlist</div>
            <h2>Names in focus</h2>
            <div class="watch-row"><span class="watch-symbol">AMD</span><span>Momentum remains constructive.</span><strong>$178.64</strong><span class="positive">+2.83%</span></div>
            <div class="watch-row"><span class="watch-symbol">NVDA</span><span>Leadership remains strong.</span><strong>$921.40</strong><span class="positive">+1.46%</span></div>
            <div class="watch-row"><span class="watch-symbol">AAPL</span><span>Stable trend.</span><strong>$189.98</strong><span>-0.24%</span></div>
            <div class="watch-row"><span class="watch-symbol">SOFI</span><span>Higher volatility.</span><strong>$7.82</strong><span class="positive">+3.10%</span></div>
          </article>
          <article class="card">
            <div class="eyebrow">Portfolio Risk</div>
            <h2>Elevated concentration</h2>
            <p>Paper scanner limits entries to fake money, max position count, and Risk Manager approval.</p>
            <div class="risk-meter"></div>
          </article>
          <article class="card">
            <div class="eyebrow">Strategy Agreement</div>
            <h2>4 of 6 agree</h2>
            <p>Momentum</p><a class="badge blue" href="/app/strategies">Bullish</a>
          </article>
        </div>
      </section>

      <section class="section" id="section-markets">
        <div class="grid">
          <article class="card full">
            <h2>Markets</h2>
            <div class="input-row">
              <input id="markets-symbols" value="AMD,AAPL,SPY" aria-label="Market symbols">
              <button class="action" id="load-markets">Refresh Prices</button>
            </div>
            <div id="markets-output" class="empty">Market cards will appear here.</div>
          </article>
        </div>
      </section>

      <section class="section" id="section-watchlist">
        <div class="grid">
          <article class="card full">
            <h2>Dashboard-Local Watchlist</h2>
            <p class="empty">Symbols are kept only in this running dashboard session. Nothing is persisted.</p>
            <div class="input-row">
              <input id="watch-symbol" placeholder="AMD" aria-label="Watchlist symbol">
              <button class="action" id="add-watch-symbol">Add Symbol</button>
              <button class="action secondary" id="refresh-watchlist">Refresh</button>
            </div>
            <div id="watchlist-message"></div>
            <div id="watchlist-output">{''.join(f'<div class="market-card">{escape(line)}</div>' for line in state.watchlist_lines)}</div>
          </article>
        </div>
      </section>

      <section class="section" id="section-portfolio">
        <div class="grid">
          <article class="card full">
            <h2>Portfolio</h2>
            <div id="portfolio-output" class="empty">No active paper session. $10,000.00 default cash is shown only as a default, not a running account.</div>
          </article>
        </div>
      </section>

      <section class="section" id="section-paper-trading">
        <div class="grid">
          <article class="card full">
            <h2>Paper Trading</h2>
            <div class="badges">
              <span class="badge blue">Dashboard Local Control Enabled</span>
              <span class="badge red">FAKE MONEY</span>
              <span class="badge red">NO REAL TRADING</span>
              <span class="badge red">NO BROKER CONNECTED</span>
            </div>
            <div class="empty">Website controls can start or stop one local fake-money paper scanner session. No broker exists and no real orders are possible.</div>
            <div class="grid">
              <article class="card">
                <h2>Session Controls</h2>
                <label>Starting Cash</label>
                <input id="paper-starting-cash" value="10000" aria-label="Starting cash">
                <label>Strategy</label>
                <select id="paper-strategy" aria-label="Paper strategy"><option>RSI</option><option>Buy and Hold</option><option>SMA Cross</option><option>MACD</option></select>
                <label>Scan Interval Seconds</label>
                <input id="paper-interval" value="900" aria-label="Scan interval seconds">
                <label>Scanner Symbols</label>
                <textarea id="paper-symbols" aria-label="Scanner symbols">SPY,QQQ,DIA,IWM,AAPL,MSFT,NVDA,AMD,AMZN,META,GOOGL,TSLA,JPM,BAC,XOM,CVX,WMT,COST,UNH,CAT</textarea>
                <div class="input-row">
                  <button class="action" id="start-fake-session">Start Fake Session</button>
                  <button class="action secondary" id="stop-fake-session">Stop Session</button>
                </div>
                <div id="paper-control-message" class="empty">No active fake-money session.</div>
              </article>
              <article class="card wide">
                <h2>Session Snapshot</h2>
                <div id="paper-session-output">{paper_summary}</div>
              </article>
            </div>
          </article>
          <article class="card full"><h2>Scanner Results</h2><div id="paper-scanner-output" class="empty">No scanner results yet.</div></article>
          <article class="card full"><h2>Open Positions</h2><div id="paper-positions-output" class="empty">No open fake-money positions.</div></article>
          <article class="card full"><h2>Orders</h2><div id="paper-orders-output" class="empty">No fake paper orders.</div></article>
          <article class="card full"><h2>Completed Trades</h2><div id="paper-trades-output" class="empty">No completed fake paper trades.</div></article>
          <article class="card full"><h2>Event Stream</h2><div id="paper-events-output" class="empty">No events yet.</div></article>
        </div>
      </section>

      <section class="section" id="section-research">
        <div class="grid"><article class="card full"><h2>Research</h2><div id="research-output" class="empty">Loading research capabilities...</div></article></div>
      </section>

      <section class="section" id="section-strategies">
        <div class="grid"><article class="card full"><h2>Strategies</h2><div id="strategies-output" class="empty">Loading strategies...</div></article></div>
      </section>

      <section class="section" id="section-security">
        <div class="grid"><article class="card full"><h2>Security</h2><div id="security-output" class="empty">Loading security principles...</div></article></div>
      </section>

      <section class="section" id="section-settings">
        <div class="grid"><article class="card full"><h2>Settings</h2><div class="empty">This reports module is not available yet. No accounts, no persistence, no broker connections.</div></article></div>
      </section>

      <footer>QMR.CO local dashboard. No public hosting, no accounts, no persistence, no trade controls.</footer>
    </main>
  </div>
  <script>
    const sections = document.querySelectorAll('.section');
    const navButtons = document.querySelectorAll('nav button[data-section]');
    const routeMap = {{
      '/app': 'dashboard',
      '/app/': 'dashboard',
      '/app/research': 'research',
      '/app/market': 'markets',
      '/app/strategies': 'strategies',
      '/app/portfolio': 'portfolio',
      '/app/paper': 'paper-trading',
      '/app/reports': 'settings'
    }};
    function showSection(name, route = null, push = true) {{
      const sectionName = name || 'dashboard';
      sections.forEach(section => section.classList.toggle('active', section.id === `section-${{sectionName}}`));
      navButtons.forEach(button => button.classList.toggle('active', button.dataset.section === sectionName));
      if (route && push && window.location.pathname + window.location.search !== route) history.pushState({{section: sectionName}}, '', route);
    }}
    function applyRoute(push = false) {{
      const route = window.location.pathname;
      const section = routeMap[route] || 'dashboard';
      showSection(section, null, false);
      if (section === 'research') handleSymbolFromUrl();
      if (section === 'paper-trading') loadPaperSnapshot();
    }}
    navButtons.forEach(button => button.addEventListener('click', () => showSection(button.dataset.section, button.dataset.route, true)));
    document.querySelectorAll('a[href^="/app"]').forEach(link => link.addEventListener('click', event => {{
      const url = new URL(link.href);
      if (url.origin !== window.location.origin) return;
      event.preventDefault();
      history.pushState({{}}, '', url.pathname + url.search);
      applyRoute(false);
    }}));
    window.addEventListener('popstate', () => applyRoute(false));

    async function api(path, options = {{}}) {{
      const response = await fetch(path, {{
        headers: {{'Content-Type': 'application/json'}},
        ...options
      }});
      return response.json();
    }}
    function marketCard(item) {{
      const price = item.last_price === null ? 'N/A' : `$${{Number(item.last_price).toFixed(2)}}`;
      const provider = item.provider_used || 'N/A';
      return `<div class="market-card"><div class="symbol">${{item.symbol}}</div><div class="price">${{price}}</div><div>Status: ${{item.status}}</div><div>Provider: ${{provider}}</div><div>Updated: ${{item.last_updated || 'Never'}}</div><div>${{item.message || ''}}</div><button class="action secondary" data-remove="${{item.symbol}}">Remove</button></div>`;
    }}
    async function loadStatus() {{
      const status = await api('/api/status');
      document.getElementById('top-status').textContent = `Provider Manager: ${{status.provider_manager_status}}`;
    }}
    async function loadMarkets() {{
      const symbols = encodeURIComponent(document.getElementById('markets-symbols').value);
      const data = await api(`/api/markets?symbols=${{symbols}}`);
      document.getElementById('markets-output').innerHTML = data.symbols.map(marketCard).join('') || '<div class="empty">No symbols requested.</div>';
    }}
    async function loadWatchlist() {{
      const data = await api('/api/watchlist');
      const html = data.watchlist.map(marketCard).join('') || '<div class="empty">No symbols selected.</div>';
      document.getElementById('watchlist-output').innerHTML = html;
      document.getElementById('dashboard-watchlist').innerHTML = data.watchlist.map(item => `<li>${{item.symbol}}: ${{item.status}}</li>`).join('') || '<li>No symbols selected.</li>';
    }}
    async function addWatchSymbol() {{
      const symbol = document.getElementById('watch-symbol').value;
      const data = await api('/api/watchlist/add', {{method: 'POST', body: JSON.stringify({{symbol}})}});
      document.getElementById('watchlist-message').innerHTML = data.added ? '<div class="empty">Symbol added.</div>' : `<div class="empty">${{data.error}}</div>`;
      await loadWatchlist();
    }}
    async function refreshWatchlist() {{
      await api('/api/watchlist/refresh', {{method: 'POST', body: JSON.stringify({{}})}});
      await loadWatchlist();
    }}
    document.getElementById('load-markets').addEventListener('click', loadMarkets);
    document.getElementById('add-watch-symbol').addEventListener('click', addWatchSymbol);
    document.getElementById('refresh-watchlist').addEventListener('click', refreshWatchlist);
    document.getElementById('watchlist-output').addEventListener('click', async event => {{
      const symbol = event.target.dataset ? event.target.dataset.remove : null;
      if (!symbol) return;
      await api('/api/watchlist/remove', {{method: 'POST', body: JSON.stringify({{symbol}})}});
      await loadWatchlist();
    }});
    api('/api/research').then(data => {{
      if (!new URLSearchParams(window.location.search).get('symbol')) {{
        document.getElementById('research-output').innerHTML = `<div class="market-card">Research Engine: ${{data.research_engine}}</div><div class="market-card">Datasets: ${{data.datasets.join(', ') || 'None'}}</div><div class="market-card">Automatic Backtests: ${{data.automatic_backtests}}</div><div class="empty">Search a valid symbol to load provider-backed research availability.</div>`;
      }}
    }});
    api('/api/strategies').then(data => {{
      document.getElementById('strategies-output').innerHTML = data.strategies.map(item => `<div class="market-card"><div class="symbol">${{item.name}}</div><div>${{item.description}}</div><div>Purpose: ${{item.purpose}}</div><div>Risk: ${{item.risk_level}}</div></div>`).join('');
    }});
    api('/api/security').then(data => {{
      document.getElementById('security-output').innerHTML = `<ul>${{data.principles.map(item => `<li>${{item}}</li>`).join('')}}</ul>`;
    }});
    function normalizeSearchSymbol(value) {{
      const symbol = value.trim().toUpperCase();
      const compact = symbol.replace(/[.-]/g, '');
      if (!symbol || !/^[A-Z]+$/.test(compact) || compact.length > 10) throw new Error('Enter a valid stock or ETF symbol.');
      return symbol;
    }}
    async function runSymbolSearch(rawValue, pushRoute = true) {{
      const output = document.getElementById('research-output');
      let symbol;
      try {{
        symbol = normalizeSearchSymbol(rawValue);
      }} catch (error) {{
        output.innerHTML = `<div class="empty">${{error.message}}</div>`;
        showSection('research', '/app/research', pushRoute);
        return;
      }}
      showSection('research', `/app/research?symbol=${{encodeURIComponent(symbol)}}`, pushRoute);
      output.innerHTML = `<div class="empty">Loading research state for ${{symbol}}...</div>`;
      try {{
        const data = await api(`/api/markets?symbols=${{encodeURIComponent(symbol)}}`);
        const item = data.symbols && data.symbols[0];
        if (!item) {{ output.innerHTML = `<div class="empty">No data available for ${{symbol}}.</div>`; return; }}
        const price = item.last_price === null ? 'N/A' : formatMoney(item.last_price);
        output.innerHTML = `<div class="market-card"><div class="symbol">${{symbol}}</div><div>Status: ${{item.status}}</div><div>Provider: ${{item.provider_used || 'N/A'}}</div><div>Latest Price: ${{price}}</div><div>${{item.message || 'Provider response received.'}}</div><div class="empty">Research execution remains engine-owned. No browser indicator or signal calculation was performed.</div></div>`;
      }} catch (error) {{
        output.innerHTML = `<div class="empty">Unable to load research state for ${{symbol}}.</div>`;
      }}
    }}
    function handleSymbolFromUrl() {{
      const params = new URLSearchParams(window.location.search);
      const symbol = params.get('symbol');
      if (symbol) runSymbolSearch(symbol, false);
    }}
    document.getElementById('symbol-search').addEventListener('submit', event => {{
      event.preventDefault();
      runSymbolSearch(document.getElementById('symbol-search-input').value, true);
    }});

    function formatMoney(value) {{
      return value === null || value === undefined ? 'N/A' : `$${{Number(value).toFixed(2)}}`;
    }}
    function metricLine(label, value) {{
      return `<div class="metric"><span>${{label}}</span><strong>${{value}}</strong></div>`;
    }}
    function renderSnapshot(data) {{
      const session = data.session;
      const scanner = data.scanner;
      document.getElementById('paper-session-output').innerHTML = [
        metricLine('Session Active', session.active ? 'Yes' : 'No'),
        metricLine('Strategy', session.strategy_name || 'N/A'),
        metricLine('Starting Cash', formatMoney(session.starting_cash)),
        metricLine('Cash', formatMoney(session.cash)),
        metricLine('Portfolio Value', formatMoney(session.portfolio_value)),
        metricLine('Realized P/L', formatMoney(session.realized_profit_loss)),
        metricLine('Unrealized P/L', formatMoney(session.unrealized_profit_loss)),
        metricLine('Total Return', session.total_return === null ? 'N/A' : `${{Number(session.total_return).toFixed(2)}}%`),
        metricLine('Last Scan', session.last_scan_at || 'Never'),
        metricLine('Next Scan', session.next_scan_at || 'N/A')
      ].join('');
      document.getElementById('paper-scanner-output').innerHTML = scanner.symbols.length ? scanner.symbols.map(item => `<div class="market-card"><div class="symbol">${{item.symbol}}</div><div>Status: ${{item.status}}</div><div>Provider: ${{item.provider || 'N/A'}}</div><div>Latest Price: ${{formatMoney(item.latest_price)}}</div><div>Signal: ${{item.signal}}</div><div>Action: ${{item.action_taken}}</div><div>${{item.reason}}</div></div>`).join('') : '<div class="empty">No scanner results yet.</div>';
      document.getElementById('paper-positions-output').innerHTML = data.positions.length ? data.positions.map(item => `<div class="market-card"><div class="symbol">${{item.symbol}}</div><div>Quantity: ${{item.quantity}}</div><div>Average Entry: ${{formatMoney(item.average_entry)}}</div><div>Market Value: ${{formatMoney(item.market_value)}}</div><div>Unrealized P/L: ${{formatMoney(item.unrealized_profit_loss)}}</div></div>`).join('') : '<div class="empty">No open fake-money positions.</div>';
      document.getElementById('paper-orders-output').innerHTML = data.orders.length ? data.orders.map(item => `<div class="market-card"><div class="symbol">#${{item.order_id}} ${{item.symbol}}</div><div>Side: ${{item.side}}</div><div>Status: ${{item.status}}</div><div>Quantity: ${{item.quantity}}</div><div>Fake Money: ${{item.fake_money}}</div><div>${{item.rejection_reason || ''}}</div></div>`).join('') : '<div class="empty">No fake paper orders.</div>';
      document.getElementById('paper-trades-output').innerHTML = data.completed_trades.length ? data.completed_trades.map(item => `<div class="market-card"><div class="symbol">${{item.symbol}}</div><div>Quantity: ${{item.quantity}}</div><div>Realized P/L: ${{formatMoney(item.realized_profit_loss)}}</div><div>Return: ${{Number(item.return_percentage).toFixed(2)}}%</div></div>`).join('') : '<div class="empty">No completed fake paper trades.</div>';
      document.getElementById('paper-events-output').innerHTML = data.recent_events.length ? data.recent_events.map(item => `<div class="market-card"><div class="symbol">#${{item.sequence}} ${{item.event_type}}</div><div>${{item.timestamp}}</div><div>${{item.symbol || ''}}</div><div>${{item.message}}</div></div>`).join('') : '<div class="empty">No events yet.</div>';
    }}
    async function loadPaperSnapshot() {{
      const data = await api('/api/paper/session');
      renderSnapshot(data);
    }}
    async function startFakeSession() {{
      const payload = {{
        starting_cash: Number(document.getElementById('paper-starting-cash').value),
        strategy_name: document.getElementById('paper-strategy').value,
        scan_interval_seconds: Number(document.getElementById('paper-interval').value),
        symbols: document.getElementById('paper-symbols').value
      }};
      const data = await api('/api/paper/start', {{method: 'POST', body: JSON.stringify(payload)}});
      document.getElementById('paper-control-message').textContent = data.error || data.message || 'Fake session request processed.';
      if (!data.error) renderSnapshot(data);
    }}
    async function stopFakeSession() {{
      const data = await api('/api/paper/stop', {{method: 'POST', body: JSON.stringify({{}})}});
      document.getElementById('paper-control-message').textContent = 'Stop request processed.';
      renderSnapshot(data);
    }}
    async function pollPaperState() {{
      const sessionData = await api('/api/paper/session');
      const scannerData = await api('/api/paper/scanner');
      await api('/api/paper/events?after=0');
      renderSnapshot(sessionData);
      if (scannerData.scanner) document.getElementById('paper-control-message').textContent = scannerData.scanner.message || document.getElementById('paper-control-message').textContent;
    }}
    document.getElementById('start-fake-session').addEventListener('click', startFakeSession);
    document.getElementById('stop-fake-session').addEventListener('click', stopFakeSession);
    api('/api/paper').then(data => {{
      document.getElementById('portfolio-output').textContent = data.active ? `Portfolio Value: ${{data.portfolio_value}}` : `${{data.message}} ${{data.default_cash_note}}`;
    }});
    applyRoute(false);
    loadPaperSnapshot();
    loadStatus();
    loadWatchlist();
    setInterval(pollPaperState, 5000);
  </script>
</body>
</html>"""


def run_dashboard(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the local read-only dashboard until interrupted."""
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError("Dashboard host must be localhost or 127.0.0.1.")
    application = DashboardApplication()
    handler_class = create_dashboard_handler(application)
    server = ThreadingHTTPServer((host, port), handler_class)
    url = f"http://{host}:{port}"
    print("QMR.CO Dashboard", flush=True)
    print(f"Local URL: {url}", flush=True)
    print("Mode: Local read-only dashboard", flush=True)
    print("PAPER TRADE ONLY - no real trading", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping QMR.CO dashboard.")
    finally:
        application.engine.shutdown()
        server.server_close()


def create_dashboard_handler(application: DashboardApplication) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one dashboard application."""

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        """Serve dashboard HTML and safe local JSON routes."""

        def do_GET(self) -> None:
            """Return dashboard HTML or safe JSON."""
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                _write_html(self, render_landing_html())
                return
            if parsed.path in APP_ROUTE_MAP:
                _write_html(self, render_dashboard_html(application.build_state()))
                return
            if parsed.path.startswith("/api/"):
                status, payload = application.handle_api_get(parsed.path, parse_qs(parsed.query))
                _write_json(self, payload, status)
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:
            """Handle dashboard-local watchlist mutations only."""
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self.send_error(404, "Not Found")
                return
            payload, body_error = _read_json_body(self)
            if body_error is not None:
                _write_json(self, {"error": body_error}, 400)
                return
            status, response_payload = application.handle_api_post(parsed.path, payload)
            _write_json(self, response_payload, status)

        def log_message(self, format: str, *args: object) -> None:
            """Silence per-request logs for a calmer local dashboard."""
            return

    return DashboardRequestHandler


def _write_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    """Write a local dashboard HTML response."""
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _write_json(handler: BaseHTTPRequestHandler, payload: dict[str, object], status: int = 200) -> None:
    """Write a safe JSON response."""
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> tuple[dict[str, object], str | None]:
    """Read and validate a small JSON body from a local dashboard request."""
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}, None
    if length > 16_384:
        return {}, "Request body is too large."
    body = handler.rfile.read(length).decode("utf-8")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}, "Malformed JSON request."
    if not isinstance(payload, dict):
        return {}, "JSON body must be an object."
    return payload, None


def _render_paper_summary(summary: PaperDashboardSummary | None) -> str:
    """Render read-only paper account facts or an empty state."""
    if summary is None:
        return '<div class="empty">No active paper session.</div>'
    return "\n".join(
        [
            _metric("Starting Cash", _format_currency(summary.starting_cash)),
            _metric("Current Cash", _format_currency(summary.current_cash)),
            _metric("Portfolio Value", _format_currency(summary.portfolio_value)),
            _metric("Open Positions", str(summary.open_positions)),
            _metric("Realized P/L", _format_signed_currency(summary.realized_profit_loss)),
            _metric("Unrealized P/L", _format_signed_currency(summary.unrealized_profit_loss)),
        ]
    )


def _render_live_paper_summary(summary: LivePaperDashboardSummary | None) -> str:
    """Render read-only live paper facts or an empty state."""
    if summary is None:
        return '<div class="empty">No active live paper session.</div>'
    last_price = "N/A" if summary.last_price is None else _format_currency(summary.last_price)
    return "\n".join(
        [
            _metric("Latest Symbol", summary.symbol),
            _metric("Provider Status", summary.provider_status),
            _metric("Latest Price", last_price),
            _metric("Latest Signal", summary.signal),
            _metric("Latest Risk Decision", summary.risk_decision),
            _metric("Latest Fake Order Result", summary.fake_order_result),
        ]
    )


def _metric(label: str, value: str) -> str:
    """Render one dashboard metric row."""
    return f'<div class="metric"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'


def _market_status() -> str:
    """Return a simple display-only market session status."""
    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute
    market_open = 9 * 60 + 30
    market_close = 16 * 60
    if now.weekday() < 5 and market_open <= current_minutes < market_close:
        return "OPEN"
    return "CLOSED"


def _parse_symbols(value: str) -> list[str]:
    """Parse comma-separated symbols."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_symbol(symbol: str) -> str:
    """Normalize and validate a dashboard symbol."""
    normalized_symbol = symbol.strip().upper()
    compact_symbol = normalized_symbol.replace(".", "").replace("-", "")
    if not normalized_symbol or not compact_symbol.isalpha() or len(compact_symbol) > 10:
        raise ValueError("Invalid symbol. Not added.")
    return normalized_symbol


def _is_watchable_result(result: MarketDataResult) -> bool:
    """Return whether a provider result is safe to store in the dashboard watchlist."""
    if result.status is MarketDataStatus.MISSING:
        return False
    if result.status is MarketDataStatus.ERROR and "Invalid market data symbol" in result.message:
        return False
    return True


def _format_datetime(value: datetime | None) -> str | None:
    """Format optional datetimes for JSON."""
    if value is None:
        return None
    return value.strftime("%H:%M:%S")


def _format_currency(value: float) -> str:
    """Format a positive currency value."""
    return f"${value:,.2f}"


def _format_signed_currency(value: float) -> str:
    """Format a signed currency value."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"
