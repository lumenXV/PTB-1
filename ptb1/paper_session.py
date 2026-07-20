"""Thread-safe fake-money paper scanner session controller for QMR.CO."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Callable, Mapping

from ptb1.historian import PriceBar
from ptb1.learning import explain_signal
from ptb1.market_data import MarketDataRequest, MarketDataResult, MarketDataStatus, ProviderManager
from ptb1.paper import PaperAccount, PaperEntry, apply_paper_signal
from ptb1.researcher import Signal, Strategy
from ptb1.risk_manager import RiskManager
from ptb1.security import PrivacyFilter
from ptb1.snapshots import (
    SCHEMA_VERSION,
    DashboardPaperSnapshot,
    EventSnapshot,
    OrderSnapshot,
    PositionSnapshot,
    ScannerSnapshot,
    ScannerSymbolSnapshot,
    SessionSnapshot,
    TradeSnapshot,
)
from ptb1.strategies import get_available_strategies

DEFAULT_SCANNER_UNIVERSE: tuple[str, ...] = (
    "SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "BAC", "XOM", "CVX", "WMT", "COST", "UNH", "CAT",
)
MAX_SCANNER_SYMBOLS = 40
MIN_SCAN_INTERVAL_SECONDS = 300
DEFAULT_SCAN_INTERVAL_SECONDS = 900
MAX_OPEN_POSITIONS = 5
MAX_POSITION_ALLOCATION = 0.10
EVENT_RETENTION_LIMIT = 500


@dataclass(frozen=True)
class PaperSessionConfig:
    """Validated fake-money paper scanner configuration."""

    starting_cash: float = 10_000.0
    strategy_name: str = "RSI"
    scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS
    symbols: tuple[str, ...] = DEFAULT_SCANNER_UNIVERSE


@dataclass(frozen=True)
class PaperSessionStartResult:
    """Result of requesting a fake paper session start."""

    started: bool
    status_code: int
    message: str
    snapshot: DashboardPaperSnapshot


class PaperSessionController:
    """Own one application-wide fake-money paper scanner session."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        risk_manager: RiskManager | None = None,
        strategies: tuple[Strategy, ...] | None = None,
        now: Callable[[], datetime] | None = None,
        start_worker: bool = True,
    ) -> None:
        """Create a controller with injectable engine dependencies."""
        self.provider_manager = provider_manager or ProviderManager()
        self.risk_manager = risk_manager or RiskManager()
        self.strategies = strategies or tuple(get_available_strategies())
        self.now = now or datetime.now
        self.start_worker = start_worker
        self.privacy_filter = PrivacyFilter()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._account: PaperAccount | None = None
        self._entries: dict[str, PaperEntry] = {}
        self._config: PaperSessionConfig | None = None
        self._session_id: str | None = None
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._last_scan_at: datetime | None = None
        self._next_scan_at: datetime | None = None
        self._scanner_symbols: tuple[ScannerSymbolSnapshot, ...] = ()
        self._scanner_status = "IDLE"
        self._scanner_message = "No active fake-money session."
        self._events: list[EventSnapshot] = []
        self._next_sequence = 1

    def start(self, config: PaperSessionConfig) -> PaperSessionStartResult:
        """Start one fake-money paper scanner session."""
        validated = validate_paper_session_config(config)
        with self._lock:
            if self._account is not None and self._session_id is not None and self._stopped_at is None:
                self._record_event_locked("USER_ACTION", "Duplicate start rejected because a fake session is already active.")
                return PaperSessionStartResult(False, 409, "A fake paper session is already active.", self.snapshot())
            self._config = validated
            self._account = PaperAccount(starting_cash=validated.starting_cash, cash=validated.starting_cash)
            self._entries = {}
            self._session_id = str(uuid.uuid4())
            self._started_at = self.now()
            self._stopped_at = None
            self._last_scan_at = None
            self._next_scan_at = self._started_at
            self._scanner_symbols = tuple(
                _empty_symbol_snapshot(symbol, validated.strategy_name, "Waiting for first scan.", self._started_at)
                for symbol in validated.symbols
            )
            self._scanner_status = "WAITING"
            self._scanner_message = "Fake-money scanner is waiting for the next cycle."
            self._stop_event.clear()
            self._record_event_locked("USER_ACTION", "Started fake paper session from dashboard controls.")
            self._record_event_locked("SESSION_STARTED", "Fake-money paper session started.")
            if self.start_worker:
                self._worker = threading.Thread(target=self._worker_loop, name="qmr-paper-scanner", daemon=False)
                self._worker.start()
            return PaperSessionStartResult(True, 201, "Fake paper session started.", self.snapshot())

    def stop(self) -> DashboardPaperSnapshot:
        """Stop the active fake-money scanner safely."""
        worker: threading.Thread | None
        with self._lock:
            self._record_event_locked("USER_ACTION", "Stop fake paper session requested.")
            self._stop_event.set()
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        with self._lock:
            if self._stopped_at is None and self._session_id is not None:
                self._stopped_at = self.now()
                self._scanner_status = "STOPPED"
                self._scanner_message = "Fake-money scanner stopped."
                self._next_scan_at = None
                self._record_event_locked("SESSION_STOPPED", "Fake-money paper session stopped.")
            self._worker = None
            return self.snapshot()

    def shutdown(self) -> DashboardPaperSnapshot:
        """Stop all background scanner work and record shutdown."""
        snapshot = self.stop()
        with self._lock:
            self._record_event_locked("SHUTDOWN", "Paper session controller shutdown complete.")
            return self.snapshot()

    def update_symbols(self, symbols: tuple[str, ...]) -> DashboardPaperSnapshot:
        """Update the bounded scanner universe for the active or next session."""
        normalized = normalize_symbol_universe(symbols)
        with self._lock:
            if self._config is None:
                self._config = PaperSessionConfig(symbols=normalized)
            else:
                self._config = PaperSessionConfig(
                    starting_cash=self._config.starting_cash,
                    strategy_name=self._config.strategy_name,
                    scan_interval_seconds=self._config.scan_interval_seconds,
                    symbols=normalized,
                )
            self._record_event_locked("USER_ACTION", "Updated scanner symbols.", safe_metadata={"symbols": ",".join(normalized)})
            return self.snapshot()

    def snapshot(self) -> DashboardPaperSnapshot:
        """Return an immutable safe snapshot of the current paper session."""
        with self._lock:
            generated_at = self.now()
            session = self._session_snapshot_locked()
            scanner = self._scanner_snapshot_locked(generated_at)
            return DashboardPaperSnapshot(
                schema_version=SCHEMA_VERSION,
                session=session,
                scanner=scanner,
                positions=self._position_snapshots_locked(),
                orders=self._order_snapshots_locked(),
                completed_trades=self._trade_snapshots_locked(),
                recent_events=tuple(self._events[-100:]),
                generated_at=generated_at,
            )

    def scanner_snapshot(self) -> ScannerSnapshot:
        """Return only scanner state."""
        with self._lock:
            return self._scanner_snapshot_locked(self.now())

    def events(self, after_sequence: int | None = None) -> tuple[EventSnapshot, ...]:
        """Return ordered events, optionally after one sequence number."""
        with self._lock:
            if after_sequence is None:
                return tuple(self._events)
            return tuple(event for event in self._events if event.sequence > after_sequence)

    def run_scan_once(self) -> None:
        """Run one scan cycle for the active fake-money session."""
        with self._lock:
            if self._account is None or self._config is None or self._stopped_at is not None:
                return
            config = self._config
            account = self._account
            strategy = self._find_strategy_locked(config.strategy_name)
            self._scanner_status = "SCANNING"
            self._scanner_message = "Fake-money scan running."
            self._last_scan_at = self.now()
            self._record_event_locked("SCAN_STARTED", "Fake-money scanner cycle started.")

        results: list[ScannerSymbolSnapshot] = []
        for symbol in config.symbols:
            try:
                results.append(self._scan_symbol(symbol, strategy, account, config))
            except Exception:
                now = self.now()
                results.append(
                    ScannerSymbolSnapshot(
                        symbol=symbol,
                        status="ERROR",
                        provider=None,
                        latest_price=None,
                        signal="HOLD",
                        strategy_name=strategy.name,
                        confidence=None,
                        reason="Worker handled a symbol error safely. No fake order placed.",
                        action_taken="NONE",
                        rejection_reason="Symbol scan failed safely.",
                        data_fresh=False,
                        scanned_at=now,
                    )
                )
                with self._lock:
                    self._record_event_locked("WORKER_ERROR", "Symbol scan failed safely.", symbol=symbol)

        with self._lock:
            self._scanner_symbols = tuple(results)
            self._scanner_status = "WAITING" if self._stopped_at is None else "STOPPED"
            self._scanner_message = "Fake-money scan complete. Waiting for next interval."
            self._next_scan_at = self.now() + timedelta(seconds=config.scan_interval_seconds)
            self._record_event_locked("SCAN_COMPLETED", "Fake-money scanner cycle completed.")

    def _worker_loop(self) -> None:
        """Run scanner cycles until stopped."""
        while not self._stop_event.is_set():
            try:
                self.run_scan_once()
            except Exception:
                with self._lock:
                    self._scanner_status = "ERROR"
                    self._scanner_message = "Worker error handled safely."
                    self._record_event_locked("WORKER_ERROR", "Worker error handled safely.")
            with self._lock:
                interval = self._config.scan_interval_seconds if self._config else DEFAULT_SCAN_INTERVAL_SECONDS
            self._stop_event.wait(interval)

    def _scan_symbol(
        self,
        symbol: str,
        strategy: Strategy,
        account: PaperAccount,
        config: PaperSessionConfig,
    ) -> ScannerSymbolSnapshot:
        """Scan one symbol sequentially and place only safe fake orders."""
        scanned_at = self.now()
        result = self.provider_manager.get_market_data(MarketDataRequest(symbol=symbol, period="3mo", interval="1d"))
        provider = result.provider_name
        latest_price = result.quote.last_price if result.quote else None
        if result.status is not MarketDataStatus.OK or not result.bars or latest_price is None:
            event_type = "DATA_STALE" if result.status is MarketDataStatus.STALE else "PROVIDER_ERROR"
            reason = f"{result.status.value}: {result.message} No fake order placed."
            with self._lock:
                self._record_event_locked(event_type, reason, symbol=symbol)
            return ScannerSymbolSnapshot(symbol, result.status.value, provider, latest_price, "HOLD", strategy.name, None, reason, "NONE", reason, False, scanned_at)

        bar = result.bars[-1]
        with self._lock:
            account.positions = _mark_symbol_position(account.positions, bar)
            position = account.positions.get(bar.symbol)
            position_size = position.quantity if position else 0
        try:
            signal = strategy.generate_signal(result.bars, position_size)
        except Exception:
            reason = "Strategy error handled safely. No fake order placed."
            with self._lock:
                self._record_event_locked("STRATEGY_ERROR", reason, symbol=symbol)
            return ScannerSymbolSnapshot(symbol, "STRATEGY_ERROR", provider, latest_price, "HOLD", strategy.name, None, reason, "NONE", reason, True, scanned_at)

        reason = explain_signal(strategy.name, signal)
        with self._lock:
            self._record_event_locked("SIGNAL_GENERATED", f"{strategy.name} generated {signal.value.upper()}.", symbol=symbol)
            if signal is Signal.HOLD:
                self._record_event_locked("SYMBOL_SCANNED", "HOLD signal created no fake order.", symbol=symbol)
                return ScannerSymbolSnapshot(symbol, "OK", provider, latest_price, signal.value.upper(), strategy.name, None, reason, "HOLD", None, True, scanned_at)
            if signal is Signal.BUY and len(account.positions) >= MAX_OPEN_POSITIONS and symbol not in account.positions:
                reject = "Maximum open fake positions reached."
                self._record_event_locked("ORDER_REJECTED", reject, symbol=symbol)
                return ScannerSymbolSnapshot(symbol, "REJECTED", provider, latest_price, signal.value.upper(), strategy.name, None, reason, "REJECTED", reject, True, scanned_at)
            if signal is Signal.BUY and symbol in account.positions:
                reject = "Duplicate position entry rejected."
                self._record_event_locked("ORDER_REJECTED", reject, symbol=symbol)
                return ScannerSymbolSnapshot(symbol, "REJECTED", provider, latest_price, signal.value.upper(), strategy.name, None, reason, "REJECTED", reject, True, scanned_at)
            max_quantity = int((config.starting_cash * MAX_POSITION_ALLOCATION) // latest_price) if signal is Signal.BUY else None
            execution = apply_paper_signal(account, bar, strategy.name, signal, self.risk_manager, self._entries, len(result.bars) - 1, max_quantity)
            if execution.filled:
                self._record_event_locked("ORDER_APPROVED", execution.reason, symbol=symbol)
                self._record_event_locked("ORDER_FILLED", f"Filled fake {execution.side} for {execution.quantity} shares.", symbol=symbol)
                self._record_event_locked("POSITION_UPDATED", "Fake position state updated.", symbol=symbol)
                return ScannerSymbolSnapshot(symbol, "OK", provider, latest_price, signal.value.upper(), strategy.name, None, reason, "FILLED", None, True, scanned_at)
            self._record_event_locked("ORDER_REJECTED", execution.reason, symbol=symbol)
            return ScannerSymbolSnapshot(symbol, "REJECTED", provider, latest_price, signal.value.upper(), strategy.name, None, reason, "REJECTED", execution.reason, True, scanned_at)

    def _find_strategy_locked(self, strategy_name: str) -> Strategy:
        normalized = _normalize_strategy_name(strategy_name)
        for strategy in self.strategies:
            if _normalize_strategy_name(strategy.name) == normalized:
                return strategy
        raise ValueError(f"Unknown strategy: {strategy_name}.")

    def _record_event_locked(
        self,
        event_type: str,
        message: str,
        symbol: str | None = None,
        safe_metadata: Mapping[str, object] | None = None,
    ) -> None:
        safe_message = self.privacy_filter.redact(message)
        safe_details = {
            self.privacy_filter.redact(str(key)): self.privacy_filter.redact(str(value))
            for key, value in (safe_metadata or {}).items()
        }
        self._events.append(
            EventSnapshot(
                sequence=self._next_sequence,
                timestamp=self.now(),
                event_type=event_type,
                message=safe_message,
                symbol=symbol,
                safe_metadata=MappingProxyType(safe_details),
            )
        )
        self._next_sequence += 1
        if len(self._events) > EVENT_RETENTION_LIMIT:
            self._events = self._events[-EVENT_RETENTION_LIMIT:]

    def _session_snapshot_locked(self) -> SessionSnapshot:
        account = self._account
        config = self._config
        active = account is not None and self._session_id is not None and self._stopped_at is None
        portfolio_value = account.portfolio_value if account else None
        total_return = None
        if account and account.starting_cash:
            total_return = ((account.portfolio_value - account.starting_cash) / account.starting_cash) * 100
        return SessionSnapshot(
            session_id=self._session_id,
            active=active,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            starting_cash=account.starting_cash if account else None,
            cash=account.cash if account else None,
            portfolio_value=portfolio_value,
            realized_profit_loss=account.realized_profit_loss if account else None,
            unrealized_profit_loss=account.unrealized_profit_loss if account else None,
            total_return=total_return,
            open_position_count=len(account.positions) if account else None,
            completed_trade_count=len(account.trade_log) if account else None,
            scan_interval_seconds=config.scan_interval_seconds if config else None,
            last_scan_at=self._last_scan_at,
            next_scan_at=self._next_scan_at,
            strategy_name=config.strategy_name if config else None,
            message="Fake session active." if active else "No active fake-money session.",
        )

    def _scanner_snapshot_locked(self, generated_at: datetime) -> ScannerSnapshot:
        symbols = self._scanner_symbols
        return ScannerSnapshot(
            active=self._stopped_at is None and self._session_id is not None,
            status=self._scanner_status,
            symbols=symbols,
            last_scan_at=self._last_scan_at,
            next_scan_at=self._next_scan_at,
            scan_interval_seconds=self._config.scan_interval_seconds if self._config else None,
            scanned_count=len(symbols),
            success_count=sum(1 for item in symbols if item.status == "OK"),
            hold_count=sum(1 for item in symbols if item.signal == "HOLD"),
            approved_count=sum(1 for item in symbols if item.action_taken == "FILLED"),
            rejected_count=sum(1 for item in symbols if item.action_taken == "REJECTED"),
            error_count=sum(1 for item in symbols if item.status not in {"OK", "REJECTED"}),
            message=self._scanner_message,
            generated_at=generated_at,
        )

    def _position_snapshots_locked(self) -> tuple[PositionSnapshot, ...]:
        if self._account is None:
            return ()
        snapshots = []
        for position in self._account.positions.values():
            unrealized_return = None
            if position.average_entry_price:
                unrealized_return = ((position.last_price - position.average_entry_price) / position.average_entry_price) * 100
            entry = self._entries.get(position.symbol)
            snapshots.append(
                PositionSnapshot(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    average_entry=position.average_entry_price,
                    last_price=position.last_price,
                    market_value=position.market_value,
                    unrealized_profit_loss=position.unrealized_profit_loss,
                    unrealized_return=unrealized_return,
                    opened_at=entry.date if entry else None,
                )
            )
        return tuple(snapshots)

    def _order_snapshots_locked(self) -> tuple[OrderSnapshot, ...]:
        if self._account is None:
            return ()
        return tuple(
            OrderSnapshot(
                order_id=order.order_id,
                timestamp=order.date,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                requested_price=order.requested_price,
                filled_price=order.requested_price if order.status == "FILLED" else None,
                status=order.status,
                rejection_reason=None if order.status == "FILLED" else order.reason,
                fake_money=True,
            )
            for order in self._account.order_log
        )

    def _trade_snapshots_locked(self) -> tuple[TradeSnapshot, ...]:
        if self._account is None:
            return ()
        return tuple(
            TradeSnapshot(
                trade_id=index,
                symbol=trade.symbol,
                entry_timestamp=trade.entry_date,
                exit_timestamp=trade.exit_date,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                realized_profit_loss=trade.realized_profit_loss,
                return_percentage=trade.realized_profit_loss_percent,
                holding_period=trade.holding_period_bars,
                strategy_name=trade.strategy_name,
                fake_money=True,
            )
            for index, trade in enumerate(self._account.trade_log, start=1)
        )


def validate_paper_session_config(config: PaperSessionConfig) -> PaperSessionConfig:
    """Validate conservative fake-money paper session defaults."""
    if config.starting_cash <= 0:
        raise ValueError("Starting cash must be greater than zero.")
    if config.scan_interval_seconds < MIN_SCAN_INTERVAL_SECONDS:
        raise ValueError("Scan interval must be at least 300 seconds.")
    symbols = normalize_symbol_universe(config.symbols)
    if not config.strategy_name.strip():
        raise ValueError("Strategy is required.")
    return PaperSessionConfig(
        starting_cash=float(config.starting_cash),
        strategy_name=config.strategy_name.strip(),
        scan_interval_seconds=int(config.scan_interval_seconds),
        symbols=symbols,
    )


def normalize_symbol_universe(symbols: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Normalize, validate, de-duplicate, and bound scanner symbols."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = _normalize_symbol(raw)
        if symbol not in seen:
            normalized.append(symbol)
            seen.add(symbol)
    if not normalized:
        raise ValueError("Scanner symbol universe cannot be empty.")
    if len(normalized) > MAX_SCANNER_SYMBOLS:
        raise ValueError("Scanner symbol universe cannot exceed 40 symbols.")
    return tuple(normalized)


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    compact = normalized.replace(".", "").replace("-", "")
    if not normalized or not compact.isalpha() or len(compact) > 10:
        raise ValueError("Invalid scanner symbol.")
    return normalized


def _normalize_strategy_name(strategy_name: str) -> str:
    return strategy_name.lower().replace("-", " ").strip()


def _empty_symbol_snapshot(symbol: str, strategy_name: str, reason: str, timestamp: datetime) -> ScannerSymbolSnapshot:
    return ScannerSymbolSnapshot(
        symbol=symbol,
        status="WAITING",
        provider=None,
        latest_price=None,
        signal="HOLD",
        strategy_name=strategy_name,
        confidence=None,
        reason=reason,
        action_taken="NONE",
        rejection_reason=None,
        data_fresh=False,
        scanned_at=timestamp,
    )


def _mark_symbol_position(positions: dict[str, object], bar: PriceBar) -> dict[str, object]:
    if bar.symbol not in positions:
        return positions
    current = positions[bar.symbol]
    from ptb1.paper import PaperPosition
    positions[bar.symbol] = PaperPosition(
        symbol=current.symbol,
        quantity=current.quantity,
        average_entry_price=current.average_entry_price,
        last_price=bar.close,
    )
    return positions
