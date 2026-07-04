"""Explainable strategy result primitives for future research workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from ptb1.assets import Asset, AssetType
from ptb1.researcher import Signal


@dataclass(frozen=True)
class ResearchContext:
    """Minimal context a future strategy can use to describe its research run."""

    asset: Asset
    provider: str
    dataset: str | None
    timestamp: datetime
    timeframe: str

    def __post_init__(self) -> None:
        """Validate context facts without integrating them into runtime flows yet."""
        if not isinstance(self.asset, Asset):
            raise ValueError("ResearchContext asset must be an Asset.")
        _require_text(self.provider, "ResearchContext provider")
        if self.dataset is not None:
            _require_text(self.dataset, "ResearchContext dataset")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("ResearchContext timestamp must be a datetime.")
        _require_text(self.timeframe, "ResearchContext timeframe")


@dataclass(frozen=True)
class StrategyResult:
    """Standard explainable result shape for future strategy evaluations."""

    signal: Signal
    reason: str
    strategy_name: str | None = None
    strategy_version: str | None = None
    confidence: float | None = None
    indicators: Mapping[str, float | str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    asset_type: AssetType | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """Validate explainability fields at construction time."""
        if not isinstance(self.signal, Signal):
            raise ValueError("StrategyResult signal must be a Signal.")
        if len(self.reason.strip()) < 10:
            raise ValueError("StrategyResult reason must be descriptive.")
        if self.strategy_name is not None:
            _require_text(self.strategy_name, "StrategyResult strategy name")
        if self.strategy_version is not None:
            _require_text(self.strategy_version, "StrategyResult strategy version")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("StrategyResult confidence must be between 0.0 and 1.0.")
        if not isinstance(self.indicators, Mapping):
            raise ValueError("StrategyResult indicators must be a mapping.")
        if not isinstance(self.warnings, tuple):
            raise ValueError("StrategyResult warnings must be a tuple.")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("StrategyResult metadata must be a mapping.")
        if self.asset_type is not None and not isinstance(self.asset_type, AssetType):
            raise ValueError("StrategyResult asset_type must be an AssetType.")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("StrategyResult timestamp must be a datetime.")


def format_strategy_result(result: StrategyResult) -> str:
    """Format a strategy result as plain console text."""
    confidence = "N/A" if result.confidence is None else f"{result.confidence:.2f}"
    asset_type = "N/A" if result.asset_type is None else result.asset_type.value
    strategy_name = result.strategy_name or "N/A"
    strategy_version = result.strategy_version or "N/A"
    warnings = list(result.warnings) if result.warnings else ["None"]

    lines = [
        f"Strategy: {strategy_name}",
        f"Strategy Version: {strategy_version}",
        f"Signal: {result.signal.value.upper()}",
        f"Confidence: {confidence}",
        "Indicators:",
    ]
    if result.indicators:
        for name, value in result.indicators.items():
            lines.append(f"- {name}: {value}")
    else:
        lines.append("- None")

    lines.extend(
        [
            f"Reason: {result.reason}",
            "Warnings:",
        ]
    )
    for warning in warnings:
        lines.append(f"- {warning}")
    lines.extend(
        [
            f"Asset Type: {asset_type}",
            f"Timestamp: {result.timestamp.isoformat()}",
        ]
    )
    return "\n".join(lines)


def _require_text(value: str, label: str) -> None:
    """Require a non-empty string field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
