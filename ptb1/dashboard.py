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

from ptb1.market_data import MarketDataRequest, MarketDataResult, MarketDataStatus, ProviderManager
from ptb1.operations import VERSION
from ptb1.security import PrivacyFilter
from ptb1.strategies import get_available_strategies


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
        self.provider_manager = provider_manager or ProviderManager()
        self.session = session or DashboardSession()
        self.data_dir = data_dir
        self.privacy_filter = PrivacyFilter()

    def build_state(self) -> DashboardState:
        """Build safe display state without running strategies or research."""
        return DashboardState(
            version=VERSION,
            provider_manager_status=self.provider_manager.connection_status(),
            primary_provider=self.provider_manager.primary_provider_name(),
            fallback_provider=self.provider_manager.fallback_provider_names(),
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
                self.provider_manager.get_market_data(MarketDataRequest(symbol=symbol, period="5d", interval="1d"))
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
        result = self.provider_manager.get_market_data(
            MarketDataRequest(symbol=normalized_symbol, period="5d", interval="1d")
        )
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
            self.session.watchlist[symbol] = self.provider_manager.get_market_data(
                MarketDataRequest(symbol=symbol, period="5d", interval="1d")
            )
        return self.watchlist()

    def strategies(self) -> dict[str, object]:
        """Return available strategy education without executing strategies."""
        items = []
        for strategy in get_available_strategies():
            education = strategy.education
            items.append(
                {
                    "name": strategy.name,
                    "description": education.description,
                    "purpose": education.purpose,
                    "risk_level": education.risk_level,
                }
            )
        return {"strategies": items, "execution": False}

    def research(self) -> dict[str, object]:
        """Return research capability facts without running backtests."""
        datasets = []
        if self.data_dir.exists():
            datasets = [path.name for path in sorted(self.data_dir.glob("*.csv"))]
        return {
            "research_engine": "available",
            "automatic_backtests": False,
            "datasets": datasets,
            "strategy_count": len(get_available_strategies()),
        }

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
    button, input { font: inherit; }
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
    input {
      min-width: 0;
      flex: 1;
      border: 1px solid var(--qmr-border);
      border-radius: var(--qmr-radius-control);
      background: rgba(2, 6, 14, 0.76);
      color: var(--qmr-text);
      padding: 0.78rem 0.85rem;
    }
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
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--qmr-border); }
      nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { padding: 1rem; }
      .topbar { flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
      .card.wide, .card.full { grid-column: auto; }
      .input-row, .form-row { flex-direction: column; align-items: stretch; }
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
  <div class="shell">
    <aside>
      <div class="brand">QMR.CO</div>
      <div class="version">Version {escape(state.version)}</div>
      <nav aria-label="Dashboard sections">
        <button class="active" data-section="dashboard">Dashboard</button>
        <button data-section="markets">Markets</button>
        <button data-section="watchlist">Watchlist</button>
        <button data-section="portfolio">Portfolio</button>
        <button data-section="paper-trading">Paper Trading</button>
        <button data-section="research">Research</button>
        <button data-section="strategies">Strategies</button>
        <button data-section="security">Security</button>
        <button data-section="settings">Settings</button>
      </nav>
    </aside>
    <main>
      <section class="topbar">
        <div class="headline">
          <h1>QMR.CO Local Dashboard</h1>
          <p>Research-first quantitative workspace. Localhost only. Read-only interface.</p>
        </div>
        <div class="status-pill" id="top-status">Provider Manager: {escape(state.provider_manager_status)}</div>
      </section>
      <div class="badges">
        <span class="badge blue">Local Mode</span>
        <span class="badge blue">READ ONLY</span>
        <span class="badge red">PAPER TRADE ONLY</span>
        <span class="badge red">No real trading</span>
      </div>

      <section class="section active" id="section-dashboard">
        <div class="grid">
          <article class="card wide">
            <h2>Market Overview</h2>
            <div id="market-overview">
              {_metric("Provider Manager", state.provider_manager_status)}
              {_metric("Primary", state.primary_provider)}
              {_metric("Fallback", state.fallback_provider)}
              {_metric("Market Status", state.market_status)}
              {_metric("Last Update", state.last_update)}
            </div>
          </article>
          <article class="card">
            <h2>Watchlist</h2>
            <ul id="dashboard-watchlist">{watchlist}</ul>
          </article>
          <article class="card">
            <h2>Paper Account Summary</h2>
            {paper_summary}
          </article>
          <article class="card wide">
            <h2>Live Paper Status</h2>
            {live_summary}
          </article>
          <article class="card full">
            <h2>Security & Trust</h2>
            <ul>
              <li>Research first</li>
              <li>Paper trade only</li>
              <li>No real orders</li>
              <li>No user data selling</li>
              <li>Privacy by design</li>
              <li>Logs are safe by default</li>
            </ul>
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
            <div class="empty">Read-only. Launch live paper from the CLI: python -m ptb1 --live-paper --symbol AMD --strategy RSI --cash 10000 --interval 1 --max-iterations 3</div>
            <div id="paper-output">{paper_summary}</div>
          </article>
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
        <div class="grid"><article class="card full"><h2>Settings</h2><div class="empty">Settings are read-only in this milestone. No accounts, no persistence, no broker connections.</div></article></div>
      </section>

      <footer>QMR.CO local dashboard. No public hosting, no accounts, no persistence, no trade controls.</footer>
    </main>
  </div>
  <script>
    const sections = document.querySelectorAll('.section');
    const navButtons = document.querySelectorAll('nav button');
    function showSection(name) {{
      sections.forEach(section => section.classList.toggle('active', section.id === `section-${{name}}`));
      navButtons.forEach(button => button.classList.toggle('active', button.dataset.section === name));
    }}
    navButtons.forEach(button => button.addEventListener('click', () => showSection(button.dataset.section)));

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
      document.getElementById('research-output').innerHTML = `<div class="market-card">Research Engine: ${{data.research_engine}}</div><div class="market-card">Datasets: ${{data.datasets.join(', ') || 'None'}}</div><div class="market-card">Automatic Backtests: ${{data.automatic_backtests}}</div>`;
    }});
    api('/api/strategies').then(data => {{
      document.getElementById('strategies-output').innerHTML = data.strategies.map(item => `<div class="market-card"><div class="symbol">${{item.name}}</div><div>${{item.description}}</div><div>Purpose: ${{item.purpose}}</div><div>Risk: ${{item.risk_level}}</div></div>`).join('');
    }});
    api('/api/security').then(data => {{
      document.getElementById('security-output').innerHTML = `<ul>${{data.principles.map(item => `<li>${{item}}</li>`).join('')}}</ul>`;
    }});
    api('/api/paper').then(data => {{
      document.getElementById('portfolio-output').textContent = data.active ? `Portfolio Value: ${{data.portfolio_value}}` : `${{data.message}} ${{data.default_cash_note}}`;
    }});
    loadStatus();
    loadWatchlist();
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
        server.server_close()


def create_dashboard_handler(application: DashboardApplication) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one dashboard application."""

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        """Serve dashboard HTML and safe local JSON routes."""

        def do_GET(self) -> None:
            """Return dashboard HTML or safe JSON."""
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
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
            status, payload = application.handle_api_post(parsed.path, _read_json_body(self))
            _write_json(self, payload, status)

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


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    """Read a small JSON body from a local dashboard request."""
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


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
