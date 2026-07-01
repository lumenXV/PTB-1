"""Trader: run research backtests from strategy signals."""

from __future__ import annotations

from dataclasses import dataclass

from ptb1.historian import PriceBar
from ptb1.researcher import Signal, Strategy
from ptb1.risk_manager import RiskManager


@dataclass(frozen=True)
class Trade:
    """A simulated research trade event."""

    symbol: str
    date: str
    side: str
    quantity: int
    price: float


@dataclass(frozen=True)
class CompletedTrade:
    """Execution facts for a completed simulated trade."""

    symbol: str
    entry_date: str
    exit_date: str
    quantity: int
    entry_price: float
    exit_price: float
    holding_period_bars: int
    profit_loss: float
    profit_loss_percent: float


@dataclass(frozen=True)
class BacktestResult:
    """Result of a completed research backtest."""

    starting_cash: float
    ending_cash: float
    ending_equity: float
    position_size: int
    trades: list[Trade]
    completed_trades: list[CompletedTrade]
    equity_curve: list[float]
    position_history: list[bool]


class Backtester:
    """Simple long-only backtester for research strategies."""

    def __init__(self, starting_cash: float, risk_manager: RiskManager) -> None:
        """Create a backtester with starting cash and a risk manager."""
        if starting_cash <= 0:
            raise ValueError("Starting cash must be greater than zero.")
        self.starting_cash = starting_cash
        self.risk_manager = risk_manager

    def run(self, prices: list[PriceBar], strategy: Strategy) -> BacktestResult:
        """Run one strategy over historical price bars."""
        if not prices:
            raise ValueError("At least one price bar is required.")

        cash = self.starting_cash
        position_size = 0
        entry_bar: PriceBar | None = None
        entry_index: int | None = None
        trades: list[Trade] = []
        completed_trades: list[CompletedTrade] = []
        equity_curve: list[float] = []
        position_history: list[bool] = []
        history: list[PriceBar] = []

        for bar_index, bar in enumerate(prices):
            history.append(bar)
            signal = strategy.generate_signal(history, position_size)
            if self.risk_manager.approve(signal, cash, bar.close, position_size):
                if signal is Signal.BUY:
                    quantity = int(cash // bar.close)
                    cash -= quantity * bar.close
                    position_size += quantity
                    entry_bar = bar
                    entry_index = bar_index
                    trades.append(
                        Trade(
                            symbol=bar.symbol,
                            date=bar.date.isoformat(),
                            side=signal.value,
                            quantity=quantity,
                            price=bar.close,
                        )
                    )
                elif signal is Signal.SELL and entry_bar is not None and entry_index is not None:
                    cash += position_size * bar.close
                    completed_trades.append(
                        CompletedTrade(
                            symbol=bar.symbol,
                            entry_date=entry_bar.date.isoformat(),
                            exit_date=bar.date.isoformat(),
                            quantity=position_size,
                            entry_price=entry_bar.close,
                            exit_price=bar.close,
                            holding_period_bars=bar_index - entry_index + 1,
                            profit_loss=(bar.close - entry_bar.close) * position_size,
                            profit_loss_percent=((bar.close - entry_bar.close) / entry_bar.close) * 100,
                        )
                    )
                    trades.append(
                        Trade(
                            symbol=bar.symbol,
                            date=bar.date.isoformat(),
                            side=signal.value,
                            quantity=position_size,
                            price=bar.close,
                        )
                    )
                    position_size = 0
                    entry_bar = None
                    entry_index = None

            equity_curve.append(cash + position_size * bar.close)
            position_history.append(position_size > 0)

        ending_equity = equity_curve[-1]
        return BacktestResult(
            starting_cash=self.starting_cash,
            ending_cash=cash,
            ending_equity=ending_equity,
            position_size=position_size,
            trades=trades,
            completed_trades=completed_trades,
            equity_curve=equity_curve,
            position_history=position_history,
        )
