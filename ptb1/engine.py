"""Stable dashboard-facing engine facade for QMR.CO."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ptb1.market_data import MarketDataRequest, MarketDataResult, ProviderManager
from ptb1.paper_session import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_SCANNER_UNIVERSE,
    MIN_SCAN_INTERVAL_SECONDS,
    PaperSessionConfig,
    PaperSessionController,
    normalize_symbol_universe,
)
from ptb1.security import PrivacyFilter
from ptb1.snapshots import DashboardPaperSnapshot, EventSnapshot, ScannerSnapshot, snapshot_to_dict
from ptb1.strategies import get_available_strategies


@dataclass(frozen=True)
class EnginePaperSessionConfig:
    """Dashboard-facing fake paper session request."""

    starting_cash: float = 10_000.0
    strategy_name: str = "RSI"
    scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS
    symbols: tuple[str, ...] = DEFAULT_SCANNER_UNIVERSE


class EngineFacade:
    """Single dashboard-facing boundary over QMR.CO engine capabilities."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        paper_controller: PaperSessionController | None = None,
        data_dir: Path = Path("datasets"),
    ) -> None:
        """Create an engine facade with injectable dependencies."""
        self.provider_manager = provider_manager or ProviderManager()
        self.paper_controller = paper_controller or PaperSessionController(provider_manager=self.provider_manager)
        self.data_dir = data_dir
        self.privacy_filter = PrivacyFilter()

    def start_paper_session(self, config: EnginePaperSessionConfig | Mapping[str, object]) -> tuple[int, dict[str, object]]:
        """Validate and start a fake-money paper session."""
        try:
            parsed = self._parse_config(config)
            result = self.paper_controller.start(
                PaperSessionConfig(
                    starting_cash=parsed.starting_cash,
                    strategy_name=parsed.strategy_name,
                    scan_interval_seconds=parsed.scan_interval_seconds,
                    symbols=parsed.symbols,
                )
            )
            payload = snapshot_to_dict(result.snapshot)
            payload["message"] = result.message
            payload["started"] = result.started
            return result.status_code, payload
        except ValueError as exc:
            return 400, {"error": self.privacy_filter.redact(str(exc))}

    def stop_paper_session(self) -> tuple[int, dict[str, object]]:
        """Stop the active fake-money paper session."""
        return 200, snapshot_to_dict(self.paper_controller.stop())

    def get_paper_snapshot(self) -> DashboardPaperSnapshot:
        """Return the full immutable paper dashboard snapshot."""
        return self.paper_controller.snapshot()

    def get_scanner_snapshot(self) -> ScannerSnapshot:
        """Return the immutable scanner snapshot."""
        return self.paper_controller.scanner_snapshot()

    def get_events(self, after_sequence: int | None = None) -> tuple[EventSnapshot, ...]:
        """Return safe ordered events."""
        return self.paper_controller.events(after_sequence)

    def update_scanner_symbols(self, symbols: tuple[str, ...] | list[str]) -> tuple[int, dict[str, object]]:
        """Update scanner symbols through the controller."""
        try:
            snapshot = self.paper_controller.update_symbols(tuple(symbols))
        except ValueError as exc:
            return 400, {"error": self.privacy_filter.redact(str(exc))}
        return 200, snapshot_to_dict(snapshot)

    def shutdown(self) -> None:
        """Cleanly shut down engine-managed background work."""
        self.paper_controller.shutdown()

    def market_status(self) -> dict[str, object]:
        """Return provider manager display status without exposing internals."""
        return {
            "provider_manager_status": self.provider_manager.connection_status(),
            "primary_provider": self.provider_manager.primary_provider_name(),
            "fallback_provider": self.provider_manager.fallback_provider_names(),
        }

    def market_data(self, symbol: str, period: str = "5d", interval: str = "1d") -> MarketDataResult:
        """Return market data through ProviderManager for dashboard display."""
        return self.provider_manager.get_market_data(MarketDataRequest(symbol=symbol, period=period, interval=interval))

    def available_strategies(self) -> tuple[dict[str, object], ...]:
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
        return tuple(items)

    def research_status(self) -> dict[str, object]:
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

    def _parse_config(self, config: EnginePaperSessionConfig | Mapping[str, object]) -> EnginePaperSessionConfig:
        """Parse dashboard request data into a validated engine config."""
        if isinstance(config, EnginePaperSessionConfig):
            return config
        allowed = {"starting_cash", "strategy_name", "scan_interval_seconds", "symbols"}
        unknown = set(config) - allowed
        if unknown:
            raise ValueError(f"Unknown paper session field: {sorted(unknown)[0]}.")
        starting_cash = float(config.get("starting_cash", 10_000.0))
        strategy_name = str(config.get("strategy_name", "RSI"))
        interval = int(config.get("scan_interval_seconds", DEFAULT_SCAN_INTERVAL_SECONDS))
        raw_symbols = config.get("symbols", DEFAULT_SCANNER_UNIVERSE)
        if isinstance(raw_symbols, str):
            symbols = tuple(symbol.strip() for symbol in raw_symbols.split(",") if symbol.strip())
        elif isinstance(raw_symbols, list | tuple):
            symbols = tuple(str(symbol) for symbol in raw_symbols)
        else:
            raise ValueError("Symbols must be a list or comma-separated string.")
        return EnginePaperSessionConfig(
            starting_cash=starting_cash,
            strategy_name=strategy_name,
            scan_interval_seconds=interval,
            symbols=normalize_symbol_universe(symbols),
        )
