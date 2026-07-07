"""Local read-only web dashboard shell for QMR.CO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ptb1.market_data import ProviderManager
from ptb1.operations import VERSION


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


def build_dashboard_state(data_dir: Path | None = None) -> DashboardState:
    """Build safe display state without running strategies or fetching market data."""
    _ = data_dir
    provider_manager = ProviderManager()
    return DashboardState(
        version=VERSION,
        provider_manager_status=provider_manager.connection_status(),
        primary_provider=provider_manager.primary_provider_name(),
        fallback_provider=provider_manager.fallback_provider_names(),
        market_status=_market_status(),
        last_update=datetime.now().strftime("%H:%M:%S"),
        watchlist_lines=("No symbols selected.",),
        paper_summary=None,
        live_paper_summary=None,
    )


def render_dashboard_html(state: DashboardState) -> str:
    """Render the local dashboard as standalone HTML and CSS."""
    watchlist = "".join(f"<li>{escape(line)}</li>" for line in state.watchlist_lines)
    paper_summary = _render_paper_summary(state.paper_summary)
    live_summary = _render_live_paper_summary(state.live_paper_summary)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QMR.CO Local Dashboard</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #07111f;
      --panel: #0d1b2d;
      --panel-2: #10243b;
      --border: #213955;
      --text: #e8f1ff;
      --muted: #91a6bf;
      --blue: #3aa3ff;
      --blue-soft: rgba(58, 163, 255, 0.14);
      --green: #48d597;
      --red: #ff6f7a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }}
    .shell {{
      display: grid;
      grid-template-columns: 240px 1fr;
      min-height: 100vh;
    }}
    aside {{
      border-right: 1px solid var(--border);
      background: #081526;
      padding: 24px 18px;
    }}
    .brand {{
      font-size: 26px;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .version {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 28px;
    }}
    nav a {{
      display: block;
      color: var(--muted);
      text-decoration: none;
      padding: 11px 12px;
      border-radius: 8px;
      margin-bottom: 6px;
    }}
    nav a.active, nav a:hover {{
      color: var(--text);
      background: var(--blue-soft);
    }}
    main {{
      padding: 24px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .headline h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    .headline p {{
      margin: 0;
      color: var(--muted);
    }}
    .search {{
      min-width: 260px;
      color: var(--muted);
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: 8px;
      padding: 10px 12px;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 16px 0 24px;
    }}
    .badge {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 7px 10px;
      color: var(--muted);
      background: var(--panel);
      font-size: 13px;
      font-weight: 700;
    }}
    .badge.blue {{ color: var(--blue); background: var(--blue-soft); }}
    .badge.red {{ color: var(--red); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 16px;
    }}
    .card {{
      grid-column: span 4;
      min-height: 164px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      padding: 18px;
    }}
    .card.wide {{ grid-column: span 8; }}
    .card.full {{ grid-column: span 12; }}
    h2 {{
      margin: 0 0 14px;
      font-size: 16px;
    }}
    .metric {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 8px 0;
      border-bottom: 1px solid rgba(145, 166, 191, 0.16);
      color: var(--muted);
    }}
    .metric:last-child {{ border-bottom: 0; }}
    .metric strong {{ color: var(--text); text-align: right; }}
    .empty {{
      color: var(--muted);
      border: 1px dashed var(--border);
      border-radius: 8px;
      padding: 16px;
      background: rgba(16, 36, 59, 0.7);
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }}
    li {{ margin: 8px 0; }}
    .trust li::marker {{ color: var(--blue); }}
    footer {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--border); }}
      .topbar {{ align-items: stretch; flex-direction: column; }}
      .search {{ min-width: 0; }}
      .card, .card.wide {{ grid-column: span 12; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">QMR.CO</div>
      <div class="version">Version {escape(state.version)}</div>
      <nav aria-label="Dashboard sections">
        <a class="active" href="#">Dashboard</a>
        <a href="#">Research</a>
        <a href="#">Markets</a>
        <a href="#">Watchlist</a>
        <a href="#">Portfolio</a>
        <a href="#">Strategies</a>
        <a href="#">Security</a>
        <a href="#">Settings</a>
      </nav>
    </aside>
    <main>
      <section class="topbar">
        <div class="headline">
          <h1>QMR.CO Local Dashboard</h1>
          <p>Research-first quantitative workspace. Localhost only. Read-only shell.</p>
        </div>
        <div class="search">Search placeholder - browser actions are disabled</div>
      </section>
      <div class="badges">
        <span class="badge blue">Local Mode</span>
        <span class="badge blue">READ ONLY</span>
        <span class="badge red">PAPER TRADE ONLY</span>
        <span class="badge red">No real trading</span>
      </div>
      <section class="grid">
        <article class="card">
          <h2>Market Overview</h2>
          {_metric("Provider Manager", state.provider_manager_status)}
          {_metric("Primary", state.primary_provider)}
          {_metric("Fallback", state.fallback_provider)}
          {_metric("Market Status", state.market_status)}
          {_metric("Last Update", state.last_update)}
        </article>
        <article class="card">
          <h2>Watchlist</h2>
          <ul>{watchlist}</ul>
        </article>
        <article class="card">
          <h2>Paper Account Summary</h2>
          {paper_summary}
        </article>
        <article class="card wide">
          <h2>Live Paper Status</h2>
          {live_summary}
        </article>
        <article class="card">
          <h2>Provider Status</h2>
          {_metric("Mode", "Read Only")}
          {_metric("Data Fetching", "Not started by dashboard")}
          {_metric("Orders", "Disabled")}
        </article>
        <article class="card full">
          <h2>Security & Trust</h2>
          <ul class="trust">
            <li>Research first</li>
            <li>Paper trade only</li>
            <li>No real orders</li>
            <li>No user data selling</li>
            <li>Privacy by design</li>
            <li>Logs are safe by default</li>
          </ul>
        </article>
      </section>
      <footer>QMR.CO local dashboard shell. No public hosting, no accounts, no persistence.</footer>
    </main>
  </div>
</body>
</html>"""


def run_dashboard(host: str = "localhost", port: int = 8000) -> None:
    """Run the local read-only dashboard until interrupted."""
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError("Dashboard host must be localhost or 127.0.0.1.")
    server = ThreadingHTTPServer((host, port), _DashboardRequestHandler)
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


class _DashboardRequestHandler(BaseHTTPRequestHandler):
    """Serve the dashboard HTML from a local-only HTTP request."""

    def do_GET(self) -> None:
        """Return dashboard HTML for the root route."""
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not Found")
            return
        body = render_dashboard_html(build_dashboard_state()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence per-request logs for a calmer local dashboard."""
        return


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


def _format_currency(value: float) -> str:
    """Format a positive currency value."""
    return f"${value:,.2f}"


def _format_signed_currency(value: float) -> str:
    """Format a signed currency value."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"
