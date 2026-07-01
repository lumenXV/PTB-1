"""Validator: calculate research performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import stdev

from ptb1.trader import BacktestResult


@dataclass(frozen=True)
class PerformanceMetrics:
    """Performance metrics for a research backtest."""

    total_return_percent: float
    max_drawdown_percent: float
    sharpe_ratio: float | None


def calculate_metrics(result: BacktestResult) -> PerformanceMetrics:
    """Calculate basic backtest performance metrics."""
    total_return = (result.ending_equity - result.starting_cash) / result.starting_cash
    return PerformanceMetrics(
        total_return_percent=total_return * 100,
        max_drawdown_percent=_max_drawdown_percent(result.equity_curve),
        sharpe_ratio=_sharpe_ratio(result.equity_curve),
    )


def _max_drawdown_percent(equity_curve: list[float]) -> float:
    """Calculate maximum drawdown as a percentage."""
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_drawdown = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown * 100


def _sharpe_ratio(equity_curve: list[float]) -> float | None:
    """Calculate annualized Sharpe ratio when enough return data exists."""
    returns = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        if previous == 0:
            continue
        returns.append((current - previous) / previous)

    if len(returns) < 2:
        return None

    volatility = stdev(returns)
    if volatility == 0:
        return None

    average_return = sum(returns) / len(returns)
    return (average_return / volatility) * sqrt(252)
