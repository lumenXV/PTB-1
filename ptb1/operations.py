"""Operations Center: display-only QMR.CO platform entry point."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ptb1.market_data import MarketDataRepository, MarketDataRequest, MarketDataResult, MarketDataStatus, ProviderManager
from ptb1.strategies import get_available_strategies

VERSION = "v0.7.3"
STABLE_BRANCH = "stable/v0.7.3"


@dataclass(frozen=True)
class OperationsStatus:
    """Display facts for the QMR.CO Operations Center."""

    version: str
    stable_branch: str
    runtime_seconds: int
    strategy_count: int
    dataset_count: int
    provider_manager_status: str
    primary_provider: str
    fallback_provider: str
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
    result: MarketDataResult | None = None


class Watchlist:
    """In-memory read-only market intelligence watchlist."""

    def __init__(self) -> None:
        """Create an empty watchlist."""
        self._entries: dict[str, WatchlistEntry] = {}

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the watchlist."""
        normalized_symbol = _normalize_symbol(symbol)
        self._entries.setdefault(normalized_symbol, WatchlistEntry(symbol=normalized_symbol))

    def add_result(self, symbol: str, result: MarketDataResult) -> None:
        """Add a symbol with its first provider result."""
        normalized_symbol = _normalize_symbol(symbol)
        self._entries[normalized_symbol] = WatchlistEntry(symbol=normalized_symbol, result=result)

    def add_validated_symbol(self, symbol: str, provider_manager: ProviderManager) -> MarketDataResult:
        """Validate, fetch, and add a watchlist symbol when safe."""
        result = _validate_and_fetch_symbol(symbol, provider_manager)
        if not _should_add_symbol(result):
            raise ValueError("Invalid symbol. Not added.")
        self.add_result(result.symbol, result)
        return result

    def remove_symbol(self, symbol: str) -> bool:
        """Remove a symbol from the watchlist."""
        normalized_symbol = _normalize_symbol(symbol)
        return self._entries.pop(normalized_symbol, None) is not None

    def entries(self) -> list[WatchlistEntry]:
        """Return watchlist entries in display order."""
        return [self._entries[symbol] for symbol in sorted(self._entries)]

    def refresh(self, provider_manager: ProviderManager) -> list[WatchlistEntry]:
        """Refresh all watched symbols on demand."""
        for entry in self._entries.values():
            entry.result = provider_manager.get_market_data(MarketDataRequest(symbol=entry.symbol, period="5d", interval="1d"))
        return self.entries()


def build_status(started_at: datetime, data_dir: Path, mode: str = "Idle") -> OperationsStatus:
    """Build the display-only platform status."""
    provider_manager = ProviderManager()
    runtime_seconds = max(0, int((datetime.now() - started_at).total_seconds()))
    return OperationsStatus(
        version=VERSION,
        stable_branch=STABLE_BRANCH,
        runtime_seconds=runtime_seconds,
        strategy_count=len(get_available_strategies()),
        dataset_count=_count_datasets(data_dir),
        provider_manager_status=provider_manager.connection_status(),
        primary_provider=provider_manager.primary_provider_name(),
        fallback_provider=provider_manager.fallback_provider_names(),
        market_status=_market_status(),
        last_update=datetime.now().strftime("%H:%M:%S"),
        mode=mode,
    )


def run_operations_center(data_dir: Path, actions: OperationsActions) -> None:
    """Display the Operations Center menu and launch existing actions."""
    started_at = datetime.now()
    watchlist = Watchlist()
    provider_manager = ProviderManager(repository=MarketDataRepository())
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
            _run_market_intelligence(watchlist, provider_manager)
        elif choice == "6":
            print("Exiting QMR.CO.")
            return
        else:
            print("Invalid selection. Enter 1, 2, 3, 4, 5, or 6.")
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
            _status_line("Provider Manager", status.provider_manager_status),
            _status_line("Primary", status.primary_provider),
            _status_line("Fallback", status.fallback_provider),
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


def render_market_intelligence(
    watchlist: Watchlist,
    provider_status: str,
    primary_provider: str = "N/A",
    fallback_provider: str = "None",
) -> str:
    """Render the read-only market intelligence screen."""
    lines = [
        "Market Intelligence",
        "---------------------------------------",
        _status_line("Provider Manager", provider_status),
        _status_line("Primary", primary_provider),
        _status_line("Fallback", fallback_provider),
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
        result = entry.result
        if result is None:
            lines.append(f"{entry.symbol}: Waiting for refresh.")
        elif result.status is MarketDataStatus.OK and result.quote is not None:
            lines.append(
                f"{result.quote.symbol}: ${result.quote.last_price:.2f}, "
                f"{result.quote.daily_percent_change:+.2f}%, updated {result.quote.last_updated}"
            )
        elif result.status is MarketDataStatus.RATE_LIMITED:
            lines.append(f"{entry.symbol}: RATE_LIMITED, {_format_next_retry(result)}, last update {_format_last_update(result)}")
        elif result.status is MarketDataStatus.STALE:
            lines.append(f"{entry.symbol}: STALE, last update {_format_last_update(result)}")
        elif result.status is MarketDataStatus.ERROR:
            lines.append(f"{entry.symbol}: ERROR, {result.message}")
        else:
            lines.append(f"{entry.symbol}: {result.status.value}, {result.message}")
        if result is not None and result.provider_name is not None:
            lines.append(f"  Provider Used: {result.provider_name}")
        if result is not None and result.attempted_providers:
            lines.append(f"  Attempts: {', '.join(result.attempted_providers)}")
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


def _run_market_intelligence(watchlist: Watchlist, provider_manager: ProviderManager) -> None:
    """Run the read-only market intelligence menu."""
    while True:
        print(
            render_market_intelligence(
                watchlist,
                provider_manager.connection_status(),
                provider_manager.primary_provider_name(),
                provider_manager.fallback_provider_names(),
            )
        )
        try:
            choice = input("Select an option: ").strip()
        except EOFError:
            return

        if choice == "1":
            try:
                symbol = input("Symbol: ").strip()
                print("Checking symbol...")
                result = watchlist.add_validated_symbol(symbol, provider_manager)
                print(_format_add_symbol_result(result))
            except (EOFError, ValueError) as exc:
                if isinstance(exc, EOFError):
                    return
                print(str(exc))
        elif choice == "2":
            try:
                symbol = input("Symbol: ").strip()
                removed = watchlist.remove_symbol(symbol)
            except EOFError:
                return
            except ValueError as exc:
                print(f"Error: {exc}")
                print()
                continue
            if not removed:
                print(f"{symbol.upper()} was not on the watchlist.")
        elif choice == "3":
            watchlist.refresh(provider_manager)
        elif choice == "4":
            return
        else:
            if _looks_like_symbol(choice):
                print("Choose 1 to add a symbol.")
            print("Invalid selection. Enter 1, 2, 3, or 4.")
        print()


def _normalize_symbol(symbol: str) -> str:
    """Normalize a market symbol for the in-memory watchlist."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("Symbol is required.")
    if not _is_supported_symbol_format(normalized_symbol):
        raise ValueError("Invalid symbol. Not added.")
    return normalized_symbol


def _validate_and_fetch_symbol(symbol: str, provider_manager: ProviderManager) -> MarketDataResult:
    """Validate a symbol and fetch its first provider result."""
    normalized_symbol = _normalize_symbol(symbol)
    return provider_manager.get_market_data(MarketDataRequest(symbol=normalized_symbol, period="5d", interval="1d"))


def _should_add_symbol(result: MarketDataResult) -> bool:
    """Return whether a provider result represents a watchable symbol."""
    if result.status is MarketDataStatus.MISSING:
        return False
    if result.status is MarketDataStatus.ERROR and "Invalid market data symbol" in result.message:
        return False
    return True


def _format_add_symbol_result(result: MarketDataResult) -> str:
    """Format the add-symbol outcome after validation and fetch."""
    if result.status is MarketDataStatus.OK and result.quote is not None:
        return (
            f"Added {result.symbol}: ${result.quote.last_price:.2f}, "
            f"{result.quote.daily_percent_change:+.2f}%."
        )
    return f"Added {result.symbol}: {result.status.value}, {result.message}"


def _is_supported_symbol_format(symbol: str) -> bool:
    """Return whether a user-entered symbol is safe to ask providers about."""
    compact_symbol = symbol.replace(".", "").replace("-", "")
    return compact_symbol.isalpha() and 1 <= len(compact_symbol) <= 5


def _looks_like_symbol(value: str) -> bool:
    """Return whether menu input looks like a symbol typed in the wrong place."""
    compact_value = value.strip().replace(".", "").replace("-", "")
    return bool(compact_value) and compact_value.isalnum() and not value.strip().isdigit()


def _format_last_update(result: MarketDataResult) -> str:
    """Format a market data result update timestamp."""
    if result.last_successful_update is None:
        return "Never"
    return result.last_successful_update.strftime("%H:%M:%S")


def _format_next_retry(result: MarketDataResult) -> str:
    """Format a market data result retry delay."""
    if result.next_retry_time is None:
        return "next retry unknown"
    seconds = max(0, int((result.next_retry_time - datetime.now()).total_seconds()))
    return f"next retry in {seconds}s"
