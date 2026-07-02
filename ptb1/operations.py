"""Operations Center: display-only QMR.CO platform entry point."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ptb1.market_data import HTTPMarketProvider, MarketDataRequest, MarketQuote
from ptb1.strategies import get_available_strategies

VERSION = "v0.6"
STABLE_BRANCH = "stable/v0.6"


@dataclass(frozen=True)
class OperationsStatus:
    """Display facts for the QMR.CO Operations Center."""

    version: str
    stable_branch: str
    runtime_seconds: int
    strategy_count: int
    dataset_count: int
    market_provider_status: str
    market_status: str
    last_update: str
    mode: str


@dataclass(frozen=True)
class OperationsActions:
    """Callbacks that launch existing QMR.CO functionality."""

    research: Callable[[], None]
    paper: Callable[[], None]
    learning: Callable[[], None]


@dataclass
class WatchlistEntry:
    """One in-memory watchlist entry."""

    symbol: str
    quote: MarketQuote | None = None
    error: str | None = None


class Watchlist:
    """In-memory read-only market intelligence watchlist."""

    def __init__(self) -> None:
        """Create an empty watchlist."""
        self._entries: dict[str, WatchlistEntry] = {}

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the watchlist."""
        normalized_symbol = _normalize_symbol(symbol)
        self._entries.setdefault(normalized_symbol, WatchlistEntry(symbol=normalized_symbol))

    def remove_symbol(self, symbol: str) -> bool:
        """Remove a symbol from the watchlist."""
        normalized_symbol = _normalize_symbol(symbol)
        return self._entries.pop(normalized_symbol, None) is not None

    def entries(self) -> list[WatchlistEntry]:
        """Return watchlist entries in display order."""
        return [self._entries[symbol] for symbol in sorted(self._entries)]

    def refresh(self, provider: HTTPMarketProvider) -> list[WatchlistEntry]:
        """Refresh all watched symbols on demand."""
        for entry in self._entries.values():
            try:
                entry.quote = provider.quote(MarketDataRequest(symbol=entry.symbol, period="5d", interval="1d"))
                entry.error = None
            except ValueError as exc:
                entry.quote = None
                entry.error = str(exc)
        return self.entries()


def build_status(started_at: datetime, data_dir: Path, mode: str = "Idle") -> OperationsStatus:
    """Build the display-only platform status."""
    market_provider = HTTPMarketProvider()
    runtime_seconds = max(0, int((datetime.now() - started_at).total_seconds()))
    return OperationsStatus(
        version=VERSION,
        stable_branch=STABLE_BRANCH,
        runtime_seconds=runtime_seconds,
        strategy_count=len(get_available_strategies()),
        dataset_count=_count_datasets(data_dir),
        market_provider_status=market_provider.connection_status(),
        market_status=_market_status(),
        last_update=datetime.now().strftime("%H:%M:%S"),
        mode=mode,
    )


def run_operations_center(data_dir: Path, actions: OperationsActions) -> None:
    """Display the Operations Center menu and launch existing actions."""
    started_at = datetime.now()
    watchlist = Watchlist()
    market_provider = HTTPMarketProvider()
    while True:
        print(render_status(build_status(started_at=started_at, data_dir=data_dir), watchlist))
        print(render_menu())
        try:
            choice = input("Select an option: ").strip()
        except EOFError:
            print("Exiting QMR.CO.")
            return

        if choice == "1":
            actions.research()
        elif choice == "2":
            actions.paper()
        elif choice == "3":
            actions.learning()
        elif choice == "4":
            continue
        elif choice == "5":
            _run_market_intelligence(watchlist, market_provider)
        elif choice == "6":
            print("Exiting QMR.CO.")
            return
        else:
            print("Invalid selection.")
        print()


def render_status(status: OperationsStatus, watchlist: Watchlist | None = None) -> str:
    """Render the startup banner and platform status."""
    watching_lines = _render_watchlist_lines(watchlist)
    return "\n".join(
        [
            "=" * 56,
            "                 QMR.CO",
            f"                  Version {status.version}",
            "=" * 56,
            "",
            "Platform Status",
            "---------------------------------------",
            _status_line("Research Engine", "ONLINE"),
            _status_line("Paper Trading", "READY"),
            _status_line("Learning Mode", "READY"),
            _status_line("Risk Manager", "ACTIVE"),
            "",
            "Market Intelligence",
            "---------------------------------------",
            _status_line("Provider", status.market_provider_status),
            _status_line("Mode", "Read Only"),
            _status_line("Market Status", status.market_status),
            _status_line("Last Update", status.last_update),
            "",
            "System Inventory",
            "---------------------------------------",
            _status_line("Strategies", f"{status.strategy_count} Loaded"),
            _status_line("Datasets", f"{status.dataset_count} Loaded"),
            "",
            "Watching",
            "---------------------------------------",
            *watching_lines,
            "",
            "Session",
            "---------------------------------------",
            _status_line("Mode", status.mode),
            _status_line("Runtime", _format_runtime(status.runtime_seconds)),
            "",
            "=" * 56,
        ]
    )


def render_menu() -> str:
    """Render the Operations Center menu."""
    return "\n".join(
        [
            "",
            "Menu",
            "",
            "1. Research",
            "2. Paper Trading",
            "3. Learning Mode",
            "4. System Status",
            "5. Market Intelligence",
            "6. Exit",
            "",
        ]
    )


def render_market_intelligence(watchlist: Watchlist, provider_status: str) -> str:
    """Render the read-only market intelligence screen."""
    lines = [
        "Market Intelligence",
        "---------------------------------------",
        _status_line("Provider", provider_status),
        _status_line("Mode", "Read Only"),
        "",
        "Watchlist",
        "---------------------------------------",
    ]
    lines.extend(_render_watchlist_lines(watchlist))
    lines.extend(
        [
            "",
            "1. Add Symbol",
            "2. Remove Symbol",
            "3. Refresh Watched Prices",
            "4. Return",
            "",
        ]
    )
    return "\n".join(lines)


def _render_watchlist_lines(watchlist: Watchlist | None) -> list[str]:
    """Render watchlist entries for display-only status screens."""
    entries = [] if watchlist is None else watchlist.entries()
    if not entries:
        return ["No symbols selected."]

    lines = []
    for entry in entries:
        if entry.quote is not None:
            lines.append(
                f"{entry.quote.symbol}: ${entry.quote.last_price:.2f} "
                f"({entry.quote.daily_change:+.2f}, {entry.quote.daily_percent_change:+.2f}%) "
                f"updated {entry.quote.last_updated}"
            )
        elif entry.error is not None:
            lines.append(f"{entry.symbol}: {entry.error}")
        else:
            lines.append(f"{entry.symbol}: Waiting for refresh.")
    return lines


def _count_datasets(data_dir: Path) -> int:
    """Count CSV datasets for display."""
    if not data_dir.exists():
        return 0
    return len(list(data_dir.glob("*.csv")))


def _status_line(label: str, value: str) -> str:
    """Format one Operations Center status line."""
    return f"{label:.<30} {value}"


def _format_runtime(seconds: int) -> str:
    """Format runtime as HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"


def _market_status() -> str:
    """Return a simple display-only market session status."""
    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute
    market_open = 9 * 60 + 30
    market_close = 16 * 60
    if now.weekday() < 5 and market_open <= current_minutes < market_close:
        return "OPEN"
    return "CLOSED"


def _run_market_intelligence(watchlist: Watchlist, provider: HTTPMarketProvider) -> None:
    """Run the read-only market intelligence menu."""
    while True:
        print(render_market_intelligence(watchlist, provider.connection_status()))
        try:
            choice = input("Select an option: ").strip()
        except EOFError:
            return

        if choice == "1":
            try:
                symbol = input("Symbol: ").strip()
                watchlist.add_symbol(symbol)
            except (EOFError, ValueError) as exc:
                if isinstance(exc, ValueError):
                    print(f"Error: {exc}")
                return
        elif choice == "2":
            try:
                symbol = input("Symbol: ").strip()
            except EOFError:
                return
            if not watchlist.remove_symbol(symbol):
                print(f"{symbol.upper()} was not on the watchlist.")
        elif choice == "3":
            watchlist.refresh(provider)
        elif choice == "4":
            return
        else:
            print("Invalid selection.")
        print()


def _normalize_symbol(symbol: str) -> str:
    """Normalize a market symbol for the in-memory watchlist."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("Symbol is required.")
    return normalized_symbol
