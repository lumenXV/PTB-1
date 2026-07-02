"""Paper Trader: simulate fake-money strategy execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from ptb1.historian import PriceBar
from ptb1.researcher import Signal, Strategy
from ptb1.risk_manager import RiskManager


@dataclass(frozen=True)
class PaperPosition:
    """A long-only fake-money position."""

    symbol: str
    quantity: int
    average_entry_price: float
    last_price: float

    @property
    def market_value(self) -> float:
        """Return current fake market value."""
        return self.quantity * self.last_price

    @property
    def unrealized_profit_loss(self) -> float:
        """Return current fake unrealized profit or loss."""
        return (self.last_price - self.average_entry_price) * self.quantity


@dataclass(frozen=True)
class PaperOrder:
    """A simulated paper order request and outcome."""

    order_id: int
    symbol: str
    date: str
    strategy_name: str
    side: str
    quantity: int
    requested_price: float
    status: str
    reason: str


@dataclass(frozen=True)
class PaperTrade:
    """A completed fake-money round trip."""

    symbol: str
    strategy_name: str
    entry_date: str
    exit_date: str
    quantity: int
    entry_price: float
    exit_price: float
    holding_period_bars: int
    realized_profit_loss: float
    realized_profit_loss_percent: float


@dataclass
class PaperAccount:
    """Fake-money account state for one paper session."""

    starting_cash: float
    cash: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    order_log: list[PaperOrder] = field(default_factory=list)
    trade_log: list[PaperTrade] = field(default_factory=list)
    realized_profit_loss: float = 0.0

    @property
    def unrealized_profit_loss(self) -> float:
        """Return total fake unrealized profit or loss."""
        return sum(position.unrealized_profit_loss for position in self.positions.values())

    @property
    def portfolio_value(self) -> float:
        """Return fake cash plus open position market value."""
        return self.cash + sum(position.market_value for position in self.positions.values())


@dataclass(frozen=True)
class PaperSessionResult:
    """Result of a completed fake-money paper session."""

    strategy_name: str
    dataset_name: str
    account: PaperAccount
    diagnostics: list[str]


class PaperSession:
    """Run one strategy through a fake-money paper trading replay."""

    def __init__(self, starting_cash: float, risk_manager: RiskManager) -> None:
        """Create a paper session with starting cash and a risk manager."""
        if starting_cash <= 0:
            raise ValueError("Starting cash must be greater than zero.")
        self.starting_cash = starting_cash
        self.risk_manager = risk_manager

    def run(self, prices: list[PriceBar], strategy: Strategy, dataset_name: str) -> PaperSessionResult:
        """Run one paper trading replay with one strategy."""
        if not prices:
            raise ValueError("At least one price bar is required.")

        account = PaperAccount(starting_cash=self.starting_cash, cash=self.starting_cash)
        history: list[PriceBar] = []
        entry_bar: PriceBar | None = None
        entry_index: int | None = None
        diagnostics = [
            f"Loaded {len(prices)} bars from {dataset_name}.",
            f"Running one paper strategy: {strategy.name}.",
        ]

        for bar_index, bar in enumerate(prices):
            history.append(bar)
            account.positions = _mark_positions(account.positions, bar)
            position = account.positions.get(bar.symbol)
            position_size = position.quantity if position else 0
            signal = strategy.generate_signal(history, position_size)
            if signal is Signal.HOLD:
                continue

            if self.risk_manager.approve(signal, account.cash, bar.close, position_size):
                if signal is Signal.BUY:
                    quantity = int(account.cash // bar.close)
                    if quantity <= 0:
                        _record_rejected_order(account, bar, strategy.name, signal, 0, "Not enough fake cash to buy one share.")
                        continue
                    account.cash -= quantity * bar.close
                    account.positions[bar.symbol] = PaperPosition(
                        symbol=bar.symbol,
                        quantity=quantity,
                        average_entry_price=bar.close,
                        last_price=bar.close,
                    )
                    entry_bar = bar
                    entry_index = bar_index
                    _record_filled_order(account, bar, strategy.name, signal, quantity)
                elif signal is Signal.SELL and position is not None and entry_bar is not None and entry_index is not None:
                    account.cash += position.quantity * bar.close
                    realized = (bar.close - position.average_entry_price) * position.quantity
                    account.realized_profit_loss += realized
                    account.trade_log.append(
                        PaperTrade(
                            symbol=bar.symbol,
                            strategy_name=strategy.name,
                            entry_date=entry_bar.date.isoformat(),
                            exit_date=bar.date.isoformat(),
                            quantity=position.quantity,
                            entry_price=position.average_entry_price,
                            exit_price=bar.close,
                            holding_period_bars=bar_index - entry_index + 1,
                            realized_profit_loss=realized,
                            realized_profit_loss_percent=((bar.close - position.average_entry_price) / position.average_entry_price) * 100,
                        )
                    )
                    del account.positions[bar.symbol]
                    entry_bar = None
                    entry_index = None
                    _record_filled_order(account, bar, strategy.name, signal, position.quantity)
            else:
                _record_rejected_order(
                    account=account,
                    bar=bar,
                    strategy_name=strategy.name,
                    signal=signal,
                    quantity=_requested_quantity(signal, account.cash, bar.close, position_size),
                    reason=_rejection_reason(signal, account.cash, bar.close, position_size),
                )

        if prices:
            account.positions = _mark_positions(account.positions, prices[-1])

        diagnostics.append(f"Processed {len(account.order_log)} paper orders.")
        diagnostics.append(f"Completed {len(account.trade_log)} paper trades.")
        return PaperSessionResult(strategy_name=strategy.name, dataset_name=dataset_name, account=account, diagnostics=diagnostics)


def _mark_positions(positions: dict[str, PaperPosition], bar: PriceBar) -> dict[str, PaperPosition]:
    """Update open fake positions with the latest bar close."""
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


def _record_filled_order(account: PaperAccount, bar: PriceBar, strategy_name: str, signal: Signal, quantity: int) -> None:
    """Record a filled fake order."""
    account.order_log.append(
        PaperOrder(
            order_id=len(account.order_log) + 1,
            symbol=bar.symbol,
            date=bar.date.isoformat(),
            strategy_name=strategy_name,
            side=signal.value.upper(),
            quantity=quantity,
            requested_price=bar.close,
            status="FILLED",
            reason="Risk Manager approved the fake order.",
        )
    )


def _record_rejected_order(
    account: PaperAccount,
    bar: PriceBar,
    strategy_name: str,
    signal: Signal,
    quantity: int,
    reason: str,
) -> None:
    """Record a rejected fake order."""
    account.order_log.append(
        PaperOrder(
            order_id=len(account.order_log) + 1,
            symbol=bar.symbol,
            date=bar.date.isoformat(),
            strategy_name=strategy_name,
            side=signal.value.upper(),
            quantity=quantity,
            requested_price=bar.close,
            status="REJECTED",
            reason=reason,
        )
    )


def _requested_quantity(signal: Signal, cash: float, price: float, position_size: int) -> int:
    """Estimate fake order quantity for logging."""
    if signal is Signal.BUY:
        return int(cash // price)
    if signal is Signal.SELL:
        return position_size
    return 0


def _rejection_reason(signal: Signal, cash: float, price: float, position_size: int) -> str:
    """Explain why the Risk Manager rejected a fake order."""
    if signal is Signal.BUY and position_size > 0:
        return "Risk Manager rejected the fake buy because a position is already open."
    if signal is Signal.BUY and cash < price:
        return "Risk Manager rejected the fake buy because cash is below the current price."
    if signal is Signal.SELL and position_size <= 0:
        return "Risk Manager rejected the fake sell because no position is open."
    return "Risk Manager rejected the fake order."
