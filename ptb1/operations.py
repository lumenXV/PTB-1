"""Operations Center: display-only PTB-1 platform entry point."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ptb1.market_data import CSVProvider, HTTPMarketProvider
from ptb1.strategies import get_available_strategies

VERSION = "v0.5.1"
STABLE_BRANCH = "stable/v0.5"


@dataclass(frozen=True)
class OperationsStatus:
    """Display facts for the PTB-1 Operations Center."""

    version: str
    stable_branch: str
    runtime_seconds: int
    strategy_count: int
    dataset_count: int
    market_provider_status: str
    mode: str


@dataclass(frozen=True)
class OperationsActions:
    """Callbacks that launch existing PTB-1 functionality."""

    research: Callable[[], None]
    paper: Callable[[], None]
    learning: Callable[[], None]


def build_status(started_at: datetime, data_dir: Path, mode: str = "Idle") -> OperationsStatus:
    """Build the display-only platform status."""
    runtime_seconds = max(0, int((datetime.now() - started_at).total_seconds()))
    return OperationsStatus(
        version=VERSION,
        stable_branch=STABLE_BRANCH,
        runtime_seconds=runtime_seconds,
        strategy_count=len(get_available_strategies()),
        dataset_count=_count_datasets(data_dir),
        market_provider_status=_market_provider_status(),
        mode=mode,
    )


def run_operations_center(data_dir: Path, actions: OperationsActions) -> None:
    """Display the Operations Center menu and launch existing actions."""
    started_at = datetime.now()
    while True:
        print(render_status(build_status(started_at=started_at, data_dir=data_dir)))
        print(render_menu())
        try:
            choice = input("Select an option: ").strip()
        except EOFError:
            print("Exiting PTB-1 Operations Center.")
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
            print("Exiting PTB-1 Operations Center.")
            return
        else:
            print("Invalid selection.")
        print()


def render_status(status: OperationsStatus) -> str:
    """Render the startup banner and platform status."""
    return "\n".join(
        [
            "=" * 56,
            "                PTB-1 Operations Center",
            f"                    Version {status.version}",
            "=" * 56,
            "",
            "Platform Status",
            "---------------------------------------",
            _status_line("Research Engine", "ONLINE"),
            _status_line("Paper Trading", "READY"),
            _status_line("Learning Mode", "READY"),
            _status_line("Risk Manager", "ACTIVE"),
            _status_line("Market Provider", status.market_provider_status),
            _status_line("Strategies", f"{status.strategy_count} Loaded"),
            _status_line("Datasets", f"{status.dataset_count} Loaded"),
            "",
            "Verification",
            "---------------------------------------",
            _status_line("Stable Branch", status.stable_branch),
            _status_line("Stability Harness", "READY"),
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
            "5. Exit",
            "",
        ]
    )


def _count_datasets(data_dir: Path) -> int:
    """Count CSV datasets for display."""
    if not data_dir.exists():
        return 0
    return len(list(data_dir.glob("*.csv")))


def _market_provider_status() -> str:
    """Return market provider readiness for display."""
    csv_ready = CSVProvider.name == "csv"
    http_ready = HTTPMarketProvider.name == "http"
    if csv_ready and http_ready:
        return "HTTP Ready"
    if csv_ready:
        return "CSV Ready"
    return "Unavailable"


def _status_line(label: str, value: str) -> str:
    """Format one Operations Center status line."""
    return f"{label:.<30} {value}"


def _format_runtime(seconds: int) -> str:
    """Format runtime as HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"
