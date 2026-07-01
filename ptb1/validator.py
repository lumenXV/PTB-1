"""Validator: calculate research performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import stdev

from ptb1.trader import BacktestResult, CompletedTrade


@dataclass(frozen=True)
class PerformanceMetrics:
    """Performance metrics for a research backtest."""

    total_return_percent: float
    cagr_percent: float | None
    max_drawdown_percent: float
    sharpe_ratio: float | None
    profit_factor: float | None
    expectancy_percent: float | None
    win_rate_percent: float | None
    average_winning_trade_percent: float | None
    average_losing_trade_percent: float | None
    largest_winner_percent: float | None
    largest_loser_percent: float | None
    average_holding_period_bars: float | None
    total_trades: int
    exposure_time_percent: float


@dataclass(frozen=True)
class StrategyMetrics:
    """Metrics associated with one strategy name."""

    strategy_name: str
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class ComparisonSummary:
    """Cross-strategy comparison calculated from measured metrics."""

    best_return: StrategyMetrics
    best_sharpe: StrategyMetrics | None
    lowest_drawdown: StrategyMetrics
    highest_win_rate: StrategyMetrics | None
    most_trades: StrategyMetrics
    least_trades: StrategyMetrics
    overall_winner: StrategyMetrics
    research_notes: list[str]


@dataclass(frozen=True)
class DatasetMetrics:
    """Metrics and summary for one dataset."""

    dataset_name: str
    strategy_metrics: list[StrategyMetrics]
    summary: ComparisonSummary


@dataclass(frozen=True)
class CrossDatasetStrategySummary:
    """Aggregated strategy metrics across datasets."""

    strategy_name: str
    average_return_percent: float
    average_drawdown_percent: float
    wins: int
    dataset_count: int


@dataclass(frozen=True)
class CrossDatasetSummary:
    """Summary of strategy performance across datasets."""

    strategy_summaries: list[CrossDatasetStrategySummary]
    overall_winner: CrossDatasetStrategySummary


def calculate_metrics(result: BacktestResult) -> PerformanceMetrics:
    """Calculate research performance metrics for a backtest result."""
    total_return = (result.ending_equity - result.starting_cash) / result.starting_cash
    return PerformanceMetrics(
        total_return_percent=total_return * 100,
        cagr_percent=_cagr_percent(result.equity_curve),
        max_drawdown_percent=_max_drawdown_percent(result.equity_curve),
        sharpe_ratio=_sharpe_ratio(result.equity_curve),
        profit_factor=_profit_factor(result.completed_trades),
        expectancy_percent=_expectancy_percent(result.completed_trades),
        win_rate_percent=_win_rate_percent(result.completed_trades),
        average_winning_trade_percent=_average_winning_trade_percent(result.completed_trades),
        average_losing_trade_percent=_average_losing_trade_percent(result.completed_trades),
        largest_winner_percent=_largest_winner_percent(result.completed_trades),
        largest_loser_percent=_largest_loser_percent(result.completed_trades),
        average_holding_period_bars=_average_holding_period_bars(result.completed_trades),
        total_trades=len(result.completed_trades),
        exposure_time_percent=_exposure_time_percent(result.position_history),
    )


def compare_strategy_metrics(strategy_metrics: list[StrategyMetrics]) -> ComparisonSummary:
    """Calculate comparison winners and metric-supported research notes."""
    if not strategy_metrics:
        raise ValueError("At least one strategy metric is required.")

    best_return = max(strategy_metrics, key=lambda item: item.metrics.total_return_percent)
    sharpe_candidates = [item for item in strategy_metrics if item.metrics.sharpe_ratio is not None]
    win_rate_candidates = [item for item in strategy_metrics if item.metrics.win_rate_percent is not None]
    best_sharpe = max(sharpe_candidates, key=lambda item: item.metrics.sharpe_ratio or 0) if sharpe_candidates else None
    highest_win_rate = (
        max(win_rate_candidates, key=lambda item: item.metrics.win_rate_percent or 0) if win_rate_candidates else None
    )
    lowest_drawdown = min(strategy_metrics, key=lambda item: item.metrics.max_drawdown_percent)
    most_trades = max(strategy_metrics, key=lambda item: item.metrics.total_trades)
    least_trades = min(strategy_metrics, key=lambda item: item.metrics.total_trades)

    return ComparisonSummary(
        best_return=best_return,
        best_sharpe=best_sharpe,
        lowest_drawdown=lowest_drawdown,
        highest_win_rate=highest_win_rate,
        most_trades=most_trades,
        least_trades=least_trades,
        overall_winner=best_return,
        research_notes=_research_notes(
            strategy_metrics=strategy_metrics,
            best_return=best_return,
            best_sharpe=best_sharpe,
            lowest_drawdown=lowest_drawdown,
            highest_win_rate=highest_win_rate,
            most_trades=most_trades,
            least_trades=least_trades,
        ),
    )


def summarize_across_datasets(dataset_metrics: list[DatasetMetrics]) -> CrossDatasetSummary:
    """Calculate strategy averages and winner counts across datasets."""
    if not dataset_metrics:
        raise ValueError("At least one dataset metric is required.")

    strategy_names = sorted({item.strategy_name for dataset in dataset_metrics for item in dataset.strategy_metrics})
    strategy_summaries: list[CrossDatasetStrategySummary] = []

    for strategy_name in strategy_names:
        matching_metrics = [
            item.metrics
            for dataset in dataset_metrics
            for item in dataset.strategy_metrics
            if item.strategy_name == strategy_name
        ]
        wins = sum(1 for dataset in dataset_metrics if dataset.summary.overall_winner.strategy_name == strategy_name)
        strategy_summaries.append(
            CrossDatasetStrategySummary(
                strategy_name=strategy_name,
                average_return_percent=sum(metric.total_return_percent for metric in matching_metrics) / len(matching_metrics),
                average_drawdown_percent=sum(metric.max_drawdown_percent for metric in matching_metrics) / len(matching_metrics),
                wins=wins,
                dataset_count=len(matching_metrics),
            )
        )

    overall_winner = max(strategy_summaries, key=lambda item: item.average_return_percent)
    return CrossDatasetSummary(strategy_summaries=strategy_summaries, overall_winner=overall_winner)


def _cagr_percent(equity_curve: list[float]) -> float | None:
    """Calculate CAGR when at least one trading year of bars exists."""
    trading_days = len(equity_curve)
    if trading_days < 252 or not equity_curve or equity_curve[0] <= 0:
        return None

    years = trading_days / 252
    cagr = (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1
    return cagr * 100


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


def _profit_factor(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate gross profit divided by gross loss."""
    gross_profit = sum(trade.profit_loss for trade in completed_trades if trade.profit_loss > 0)
    gross_loss = abs(sum(trade.profit_loss for trade in completed_trades if trade.profit_loss < 0))
    if gross_profit == 0 or gross_loss == 0:
        return None
    return gross_profit / gross_loss


def _expectancy_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate average percent return per completed trade."""
    if not completed_trades:
        return None
    return sum(trade.profit_loss_percent for trade in completed_trades) / len(completed_trades)


def _win_rate_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate the percentage of completed trades with positive profit."""
    if not completed_trades:
        return None
    winners = [trade for trade in completed_trades if trade.profit_loss > 0]
    return (len(winners) / len(completed_trades)) * 100


def _average_winning_trade_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate average percent return for winning trades."""
    winners = [trade.profit_loss_percent for trade in completed_trades if trade.profit_loss > 0]
    if not winners:
        return None
    return sum(winners) / len(winners)


def _average_losing_trade_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate average percent return for losing trades."""
    losers = [trade.profit_loss_percent for trade in completed_trades if trade.profit_loss < 0]
    if not losers:
        return None
    return sum(losers) / len(losers)


def _largest_winner_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Return the largest winning trade percent."""
    winners = [trade.profit_loss_percent for trade in completed_trades if trade.profit_loss > 0]
    if not winners:
        return None
    return max(winners)


def _largest_loser_percent(completed_trades: list[CompletedTrade]) -> float | None:
    """Return the largest losing trade percent."""
    losers = [trade.profit_loss_percent for trade in completed_trades if trade.profit_loss < 0]
    if not losers:
        return None
    return min(losers)


def _average_holding_period_bars(completed_trades: list[CompletedTrade]) -> float | None:
    """Calculate average holding period in bars for completed trades."""
    if not completed_trades:
        return None
    return sum(trade.holding_period_bars for trade in completed_trades) / len(completed_trades)


def _exposure_time_percent(position_history: list[bool]) -> float:
    """Calculate percentage of bars with an open position."""
    if not position_history:
        return 0.0
    invested_bars = sum(1 for is_invested in position_history if is_invested)
    return (invested_bars / len(position_history)) * 100


def _research_notes(
    strategy_metrics: list[StrategyMetrics],
    best_return: StrategyMetrics,
    best_sharpe: StrategyMetrics | None,
    lowest_drawdown: StrategyMetrics,
    highest_win_rate: StrategyMetrics | None,
    most_trades: StrategyMetrics,
    least_trades: StrategyMetrics,
) -> list[str]:
    """Generate mechanical notes directly supported by measured metrics."""
    notes: list[str] = []

    if best_return.strategy_name == least_trades.strategy_name and best_return.metrics.total_trades < most_trades.metrics.total_trades:
        notes.append(f"{best_return.strategy_name} produced the highest return with the fewest completed trades.")

    if most_trades.metrics.total_trades > least_trades.metrics.total_trades:
        notes.append(f"{most_trades.strategy_name} generated the most completed trades.")

    if best_sharpe is not None and best_sharpe.strategy_name != best_return.strategy_name:
        notes.append(f"{best_sharpe.strategy_name} had the highest Sharpe ratio, while {best_return.strategy_name} had the highest return.")

    if lowest_drawdown.strategy_name != best_return.strategy_name:
        notes.append(f"{lowest_drawdown.strategy_name} had the lowest drawdown, while {best_return.strategy_name} had the highest return.")

    if highest_win_rate is not None and highest_win_rate.strategy_name != best_return.strategy_name:
        notes.append(f"{highest_win_rate.strategy_name} had the highest win rate, while {best_return.strategy_name} had the highest return.")

    dominated_metrics = [best_return.strategy_name, lowest_drawdown.strategy_name]
    if best_sharpe is not None:
        dominated_metrics.append(best_sharpe.strategy_name)
    if highest_win_rate is not None:
        dominated_metrics.append(highest_win_rate.strategy_name)
    if dominated_metrics.count(best_return.strategy_name) == len(dominated_metrics):
        notes.append(f"{best_return.strategy_name} led every available comparison metric.")

    for item in strategy_metrics:
        if item.metrics.total_return_percent < 0:
            notes.append(f"Archive candidate: {item.strategy_name} had a negative total return.")

    if not notes:
        notes.append("No archive candidates or metric disagreements were found.")

    return notes
