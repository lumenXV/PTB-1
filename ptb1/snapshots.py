"""Immutable dashboard transport snapshots for QMR.CO."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from ptb1.security import PrivacyFilter

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class SessionSnapshot:
    """Immutable fake-money paper session state for display clients."""

    session_id: str | None
    active: bool
    started_at: datetime | None
    stopped_at: datetime | None
    starting_cash: float | None
    cash: float | None
    portfolio_value: float | None
    realized_profit_loss: float | None
    unrealized_profit_loss: float | None
    total_return: float | None
    open_position_count: int | None
    completed_trade_count: int | None
    scan_interval_seconds: int | None
    last_scan_at: datetime | None
    next_scan_at: datetime | None
    strategy_name: str | None
    message: str


@dataclass(frozen=True)
class ScannerSymbolSnapshot:
    """Immutable result of scanning one symbol."""

    symbol: str
    status: str
    provider: str | None
    latest_price: float | None
    signal: str
    strategy_name: str | None
    confidence: float | None
    reason: str
    action_taken: str
    rejection_reason: str | None
    data_fresh: bool
    scanned_at: datetime | None


@dataclass(frozen=True)
class ScannerSnapshot:
    """Immutable scanner state and aggregate counts."""

    active: bool
    status: str
    symbols: tuple[ScannerSymbolSnapshot, ...]
    last_scan_at: datetime | None
    next_scan_at: datetime | None
    scan_interval_seconds: int | None
    scanned_count: int
    success_count: int
    hold_count: int
    approved_count: int
    rejected_count: int
    error_count: int
    message: str
    generated_at: datetime


@dataclass(frozen=True)
class PositionSnapshot:
    """Immutable fake-money position facts."""

    symbol: str
    quantity: int
    average_entry: float
    last_price: float | None
    market_value: float | None
    unrealized_profit_loss: float | None
    unrealized_return: float | None
    opened_at: str | None


@dataclass(frozen=True)
class OrderSnapshot:
    """Immutable fake-money order facts."""

    order_id: int
    timestamp: str
    symbol: str
    side: str
    quantity: int
    requested_price: float
    filled_price: float | None
    status: str
    rejection_reason: str | None
    fake_money: bool


@dataclass(frozen=True)
class TradeSnapshot:
    """Immutable completed fake-money trade facts."""

    trade_id: int
    symbol: str
    entry_timestamp: str
    exit_timestamp: str
    quantity: int
    entry_price: float
    exit_price: float
    realized_profit_loss: float
    return_percentage: float
    holding_period: int
    strategy_name: str
    fake_money: bool


@dataclass(frozen=True)
class EventSnapshot:
    """Immutable safe event stream entry."""

    sequence: int
    timestamp: datetime
    event_type: str
    message: str
    symbol: str | None = None
    safe_metadata: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class DashboardPaperSnapshot:
    """Top-level immutable dashboard transport snapshot."""

    schema_version: str
    session: SessionSnapshot
    scanner: ScannerSnapshot
    positions: tuple[PositionSnapshot, ...]
    orders: tuple[OrderSnapshot, ...]
    completed_trades: tuple[TradeSnapshot, ...]
    recent_events: tuple[EventSnapshot, ...]
    generated_at: datetime


def snapshot_to_dict(snapshot: object) -> dict[str, object]:
    """Serialize a snapshot object into safe JSON-compatible values."""
    serialized = _serialize(snapshot, PrivacyFilter())
    if not isinstance(serialized, dict):
        raise ValueError("Snapshot serialization must produce a dictionary.")
    return serialized


def snapshot_to_json(snapshot: object) -> str:
    """Serialize a snapshot object into safe JSON text."""
    return json.dumps(snapshot_to_dict(snapshot), sort_keys=True)


def _serialize(value: object, privacy_filter: PrivacyFilter) -> object:
    """Recursively serialize safe snapshot values."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return privacy_filter.redact(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize(item, privacy_filter) for item in value]
    if isinstance(value, list):
        raise ValueError("Snapshots must expose tuples, not mutable lists.")
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Snapshot metadata keys must be strings.")
            safe[privacy_filter.redact(key)] = _serialize(item, privacy_filter)
        return safe
    if isinstance(value, BaseException):
        raise ValueError("Raw exceptions cannot be serialized in snapshots.")
    if is_dataclass(value):
        result: dict[str, object] = {}
        for field in fields(value):
            result[field.name] = _serialize(getattr(value, field.name), privacy_filter)
        return result
    raise ValueError(f"Unsupported snapshot value: {type(value).__name__}.")
