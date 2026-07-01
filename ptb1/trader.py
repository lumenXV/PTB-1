"""Trader: run research backtests from strategy signals."""

from __future__ import annotations

from dataclasses import dataclass

from ptb1.historian import PriceBar
from ptb1.researcher import Signal, Strategy
from ptb1.risk_manager import RiskManager


@dataclass(frozen=True)
class Trade:
    """A simulated research trade."""

    symbol: str
    date: str
    side: str
    quantity: int
    price: float


@dataclass(frozen=True)
class BacktestResult:
    """Result of a completed research backtest."""

    starting_cash: float
    ending_cash: float
    ending_equity: float
    position_size: int
    trades: list[Trade]
    equity_curve: list[float]


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
        trades: list[Trade] = []
        equity_curve: list[float] = []
        history: list[PriceBar] = []

        for bar in prices:
            history.append(bar)
            signal = strategy.generate_signal(history, position_size)
            if self.risk_manager.approve(signal, cash, bar.close, position_size):
                if signal is Signal.BUY:
                    quantity = int(cash // bar.close)
                    cash -= quantity * bar.close
                    position_size += quantity
                    trades.append(
                        Trade(
                            symbol=bar.symbol,
                            date=bar.date.isoformat(),
                            side=signal.value,
                            quantity=quantity,
                            price=bar.close,
                        )
                    )
                elif signal is Signal.SELL:
                    cash += position_size * bar.close
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

            equity_curve.append(cash + position_size * bar.close)

        ending_equity = equity_curve[-1]
        return BacktestResult(
            starting_cash=self.starting_cash,
            ending_cash=cash,
            ending_equity=ending_equity,
            position_size=position_size,
            trades=trades,
            equity_curve=equity_curve,
        )
