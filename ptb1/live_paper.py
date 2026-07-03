"""Live Paper Trader: fake-money live market paper loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from ptb1.historian import PriceBar
from ptb1.learning import explain_signal
from ptb1.market_data import MarketDataRequest, MarketDataResult, MarketDataStatus
from ptb1.paper import PaperAccount, PaperOrder, PaperPosition, PaperTrade
from ptb1.researcher import Signal, Strategy
from ptb1.risk_manager import RiskManager


class LiveMarketProvider(Protocol):
    """Provider shape needed by the live paper loop."""

    def get_market_data(self, request: MarketDataRequest) -> MarketDataResult:
        """Return managed market data for one symbol."""
        ...


@dataclass(frozen=True)
class LivePaperConfig:
    """Configuration for one fake-money live paper session."""

    symbols: list[str]
    strategy: Strategy
    starting_cash: float
    interval_seconds: float
    max_iterations: int | None = None


@dataclass(frozen=True)
class LivePaperDecision:
    """One live paper decision record."""

    timestamp: str
    symbol: str
    last_price: float | None
    provider_status: str
    cache_status: str
    last_successful_update: datetime | None
    next_retry_time: datetime | None
    signal: Signal
    risk_decision: str
    order_result: str
    cash: float
    portfolio_value: float
    open_positions: int
    explanation: str


@dataclass(frozen=True)
class LivePaperSessionResult:
    """Final fake-money live paper session summary."""

    account: PaperAccount
    decisions: list[LivePaperDecision]
    stopped_reason: str


@dataclass
class _OpenEntry:
    """Track entry facts for a live paper round trip."""

    date: str
    index: int


class LivePaperSession:
    """Run one strategy against live provider data with fake money only."""

    def __init__(self, provider: LiveMarketProvider, risk_manager: RiskManager) -> None:
        """Create a live paper session with provider and risk manager dependencies."""
        self.provider = provider
        self.risk_manager = risk_manager

    def run(
        self,
        config: LivePaperConfig,
        emit: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
    ) -> LivePaperSessionResult:
        """Run the live paper loop until stopped or max iterations is reached."""
        _validate_config(config)
        account = PaperAccount(starting_cash=config.starting_cash, cash=config.starting_cash)
        decisions: list[LivePaperDecision] = []
        entries: dict[str, _OpenEntry] = {}
        iteration = 0
        stopped_reason = "Max iterations reached."

        emit("QMR.CO Live Paper Trading")
        emit("Mode: PAPER TRADE ONLY - fake money, no broker, no real orders")
        emit(f"Strategy: {config.strategy.name}")
        emit(f"Symbols: {', '.join(config.symbols)}")
        emit(f"Starting Cash: ${account.starting_cash:,.2f}")
        emit("")

        try:
            while config.max_iterations is None or iteration < config.max_iterations:
                iteration += 1
                emit(f"Iteration {iteration}")
                for symbol in config.symbols:
                    decision = self._process_symbol(
                        symbol=symbol,
                        strategy=config.strategy,
                        account=account,
                        entries=entries,
                    )
                    decisions.append(decision)
                    emit(format_decision(decision))
                emit("")
                if config.max_iterations is None or iteration < config.max_iterations:
                    sleep(config.interval_seconds)
        except KeyboardInterrupt:
            stopped_reason = "Stopped by user."
            emit("Stopping live paper session.")

        result = LivePaperSessionResult(account=account, decisions=decisions, stopped_reason=stopped_reason)
        emit(format_summary(result))
        return result

    def _process_symbol(
        self,
        symbol: str,
        strategy: Strategy,
        account: PaperAccount,
        entries: dict[str, _OpenEntry],
    ) -> LivePaperDecision:
        """Process one fake-money decision for one symbol."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        market_result = self.provider.get_market_data(MarketDataRequest(symbol=symbol, period="3mo", interval="1d"))
        if market_result.status is not MarketDataStatus.OK:
            return _paused_decision(timestamp, market_result, account)

        history = market_result.bars
        latest_bar = history[-1]
        account.positions = _mark_live_position(account.positions, latest_bar)
        position = account.positions.get(latest_bar.symbol)
        position_size = position.quantity if position else 0
        signal = strategy.generate_signal(history, position_size)
        if signal is Signal.HOLD:
            return _decision(
                timestamp=timestamp,
                symbol=latest_bar.symbol,
                last_price=latest_bar.close,
                market_result=market_result,
                signal=signal,
                risk_decision="NOT NEEDED",
                order_result="No fake order placed.",
                account=account,
                explanation=explain_signal(strategy.name, signal),
            )

        approved = self.risk_manager.approve(signal, account.cash, latest_bar.close, position_size)
        if not approved:
            quantity = _requested_quantity(signal, account.cash, latest_bar.close, position_size)
            reason = _rejection_reason(signal, account.cash, latest_bar.close, position_size)
            _record_order(account, latest_bar, strategy.name, signal, quantity, "REJECTED", reason)
            return _decision(
                timestamp=timestamp,
                symbol=latest_bar.symbol,
                last_price=latest_bar.close,
                market_result=market_result,
                signal=signal,
                risk_decision="REJECTED",
                order_result=reason,
                account=account,
                explanation=_paper_trade_explanation(strategy.name, signal, "rejected", reason),
            )

        if signal is Signal.BUY:
            quantity = int(account.cash // latest_bar.close)
            if quantity <= 0:
                reason = "Not enough fake cash to buy one share."
                _record_order(account, latest_bar, strategy.name, signal, 0, "REJECTED", reason)
                return _decision(
                    timestamp=timestamp,
                    symbol=latest_bar.symbol,
                    last_price=latest_bar.close,
                    market_result=market_result,
                    signal=signal,
                    risk_decision="REJECTED",
                    order_result=reason,
                    account=account,
                    explanation=_paper_trade_explanation(strategy.name, signal, "rejected", reason),
                )
            account.cash -= quantity * latest_bar.close
            account.positions[latest_bar.symbol] = PaperPosition(
                symbol=latest_bar.symbol,
                quantity=quantity,
                average_entry_price=latest_bar.close,
                last_price=latest_bar.close,
            )
            entries[latest_bar.symbol] = _OpenEntry(date=latest_bar.date.isoformat(), index=len(history) - 1)
            _record_order(account, latest_bar, strategy.name, signal, quantity, "FILLED", "Risk Manager approved the fake order.")
            return _decision(
                timestamp=timestamp,
                symbol=latest_bar.symbol,
                last_price=latest_bar.close,
                market_result=market_result,
                signal=signal,
                risk_decision="APPROVED",
                order_result=f"Filled fake BUY for {quantity} shares.",
                account=account,
                explanation=_paper_trade_explanation(strategy.name, signal, "approved", "Risk Manager approved the fake order."),
            )

        if signal is Signal.SELL and position is not None:
            account.cash += position.quantity * latest_bar.close
            realized = (latest_bar.close - position.average_entry_price) * position.quantity
            account.realized_profit_loss += realized
            entry = entries.pop(latest_bar.symbol, _OpenEntry(date=latest_bar.date.isoformat(), index=len(history) - 1))
            account.trade_log.append(
                PaperTrade(
                    symbol=latest_bar.symbol,
                    strategy_name=strategy.name,
                    entry_date=entry.date,
                    exit_date=latest_bar.date.isoformat(),
                    quantity=position.quantity,
                    entry_price=position.average_entry_price,
                    exit_price=latest_bar.close,
                    holding_period_bars=max(1, len(history) - entry.index),
                    realized_profit_loss=realized,
                    realized_profit_loss_percent=((latest_bar.close - position.average_entry_price) / position.average_entry_price) * 100,
                )
            )
            del account.positions[latest_bar.symbol]
            _record_order(account, latest_bar, strategy.name, signal, position.quantity, "FILLED", "Risk Manager approved the fake order.")
            return _decision(
                timestamp=timestamp,
                symbol=latest_bar.symbol,
                last_price=latest_bar.close,
                market_result=market_result,
                signal=signal,
                risk_decision="APPROVED",
                order_result=f"Filled fake SELL for {position.quantity} shares.",
                account=account,
                explanation=_paper_trade_explanation(strategy.name, signal, "approved", "Risk Manager approved the fake order."),
            )

        return _decision(
            timestamp=timestamp,
            symbol=latest_bar.symbol,
            last_price=latest_bar.close,
            market_result=market_result,
            signal=Signal.HOLD,
            risk_decision="SKIPPED",
            order_result="No valid fake order was available.",
            account=account,
            explanation="No fake trade was placed.",
        )


def format_decision(decision: LivePaperDecision) -> str:
    """Format one live paper decision for CLI display."""
    last_price = "N/A" if decision.last_price is None else f"${decision.last_price:,.2f}"
    last_update = "Never" if decision.last_successful_update is None else decision.last_successful_update.strftime("%H:%M:%S")
    next_retry = "N/A" if decision.next_retry_time is None else decision.next_retry_time.strftime("%H:%M:%S")
    return "\n".join(
        [
            f"Timestamp: {decision.timestamp}",
            f"Symbol: {decision.symbol}",
            f"Provider Status: {decision.provider_status}",
            f"Cache Status: {decision.cache_status}",
            f"Last Successful Update: {last_update}",
            f"Next Retry: {next_retry}",
            f"Last Price: {last_price}",
            f"Signal: {decision.signal.value.upper()}",
            f"Risk Decision: {decision.risk_decision}",
            f"Fake Order Result: {decision.order_result}",
            f"Cash: ${decision.cash:,.2f}",
            f"Portfolio Value: ${decision.portfolio_value:,.2f}",
            f"Open Positions: {decision.open_positions}",
            "Decision Explanation",
            decision.explanation,
            "PAPER TRADE ONLY",
        ]
    )


def format_summary(result: LivePaperSessionResult) -> str:
    """Format the final live paper summary."""
    account = result.account
    return "\n".join(
        [
            "Final Live Paper Summary",
            f"Stopped Reason: {result.stopped_reason}",
            f"Ending Cash: ${account.cash:,.2f}",
            f"Realized P/L: {_format_currency(account.realized_profit_loss)}",
            f"Unrealized P/L: {_format_currency(account.unrealized_profit_loss)}",
            f"Portfolio Value: ${account.portfolio_value:,.2f}",
            f"Open Positions: {len(account.positions)}",
            f"Fake Orders: {len(account.order_log)}",
            f"Completed Paper Trades: {len(account.trade_log)}",
        ]
    )


def _validate_config(config: LivePaperConfig) -> None:
    """Validate live paper settings."""
    if not config.symbols:
        raise ValueError("Live paper mode requires at least one --symbol.")
    if config.starting_cash <= 0:
        raise ValueError("Starting cash must be greater than zero.")
    if config.interval_seconds < 0:
        raise ValueError("Interval must be zero or greater.")
    if config.max_iterations is not None and config.max_iterations <= 0:
        raise ValueError("Max iterations must be greater than zero.")


def _decision(
    timestamp: str,
    symbol: str,
    last_price: float | None,
    market_result: MarketDataResult,
    signal: Signal,
    risk_decision: str,
    order_result: str,
    account: PaperAccount,
    explanation: str,
) -> LivePaperDecision:
    """Build a decision from current account state."""
    return LivePaperDecision(
        timestamp=timestamp,
        symbol=symbol,
        last_price=last_price,
        provider_status=market_result.provider_status,
        cache_status=market_result.cache_status,
        last_successful_update=market_result.last_successful_update,
        next_retry_time=market_result.next_retry_time,
        signal=signal,
        risk_decision=risk_decision,
        order_result=order_result,
        cash=account.cash,
        portfolio_value=account.portfolio_value,
        open_positions=len(account.positions),
        explanation=explanation,
    )


def _paused_decision(timestamp: str, market_result: MarketDataResult, account: PaperAccount) -> LivePaperDecision:
    """Build a no-trade decision for unsafe market data."""
    return _decision(
        timestamp=timestamp,
        symbol=market_result.symbol,
        last_price=market_result.quote.last_price if market_result.quote else None,
        market_result=market_result,
        signal=Signal.HOLD,
        risk_decision="PAUSED",
        order_result=f"{market_result.status.value}: {market_result.message} No fake trade placed.",
        account=account,
        explanation=f"Market data status is {market_result.status.value}. Live paper paused this decision and placed no fake trade.",
    )


def _mark_live_position(positions: dict[str, PaperPosition], bar: PriceBar) -> dict[str, PaperPosition]:
    """Update one open fake position with the latest live paper price."""
    if bar.symbol not in positions:
        return positions
    current = positions[bar.symbol]
    positions[bar.symbol] = PaperPosition(
        symbol=current.symbol,
        quantity=current.quantity,
        average_entry_price=current.average_entry_price,
        last_price=bar.close,
    )
    return positions


def _record_order(
    account: PaperAccount,
    bar: PriceBar,
    strategy_name: str,
    signal: Signal,
    quantity: int,
    status: str,
    reason: str,
) -> None:
    """Record a fake live paper order."""
    account.order_log.append(
        PaperOrder(
            order_id=len(account.order_log) + 1,
            symbol=bar.symbol,
            date=bar.date.isoformat(),
            strategy_name=strategy_name,
            side=signal.value.upper(),
            quantity=quantity,
            requested_price=bar.close,
            status=status,
            reason=reason,
        )
    )


def _requested_quantity(signal: Signal, cash: float, price: float, position_size: int) -> int:
    """Estimate fake order quantity for display."""
    if signal is Signal.BUY:
        return int(cash // price)
    if signal is Signal.SELL:
        return position_size
    return 0


def _rejection_reason(signal: Signal, cash: float, price: float, position_size: int) -> str:
    """Explain why a fake live paper order was rejected."""
    if signal is Signal.BUY and position_size > 0:
        return "Risk Manager rejected the fake buy because a position is already open."
    if signal is Signal.BUY and cash < price:
        return "Risk Manager rejected the fake buy because cash is below the current price."
    if signal is Signal.SELL and position_size <= 0:
        return "Risk Manager rejected the fake sell because no position is open."
    return "Risk Manager rejected the fake order."


def _paper_trade_explanation(strategy_name: str, signal: Signal, decision: str, risk_reason: str) -> str:
    """Explain a live paper decision without changing it."""
    return "\n".join(
        [
            explain_signal(strategy_name, signal),
            f"Risk Manager Decision: {decision.upper()}",
            f"Risk Reason: {risk_reason}",
        ]
    )


def _provider_error_decision(exc: ValueError) -> tuple[str, str, str]:
    """Convert provider errors into no-trade live paper decisions."""
    message = str(exc)
    if "Rate limited" in message:
        return (
            "PAUSED",
            f"Rate limited: {message} No fake trade placed.",
            "Market data provider rate limit reached. Live paper paused this decision and placed no fake trade.",
        )
    return (
        "SKIPPED",
        f"Provider failure: {message}",
        "No fake trade was placed because market data was unavailable.",
    )


def _format_currency(value: float) -> str:
    """Format a signed currency value."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"
