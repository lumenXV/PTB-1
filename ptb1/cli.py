"""Command line runner for PTB-1 strategy comparisons."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ptb1.historian import load_price_history
from ptb1.risk_manager import RiskManager
from ptb1.strategies import get_available_strategies
from ptb1.trader import Backtester
from ptb1.validator import PerformanceMetrics, calculate_metrics


@dataclass(frozen=True)
class StrategyComparison:
    """Printable comparison result for one strategy."""

    strategy_name: str
    metrics: PerformanceMetrics
    trade_count: int


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(description="Run PTB-1 research strategy comparisons.")
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("sample_prices.csv"),
        help="Path to historical CSV data.",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=10_000.0,
        help="Starting cash for the research backtest.",
    )
    return parser


def main() -> None:
    """Run all available strategies and print a comparison table."""
    args = build_parser().parse_args()
    prices = load_price_history(args.data)
    backtester = Backtester(starting_cash=args.cash, risk_manager=RiskManager())
    comparisons: list[StrategyComparison] = []

    for strategy in get_available_strategies():
        result = backtester.run(prices=prices, strategy=strategy)
        comparisons.append(
            StrategyComparison(
                strategy_name=strategy.name,
                metrics=calculate_metrics(result),
                trade_count=len(result.trades),
            )
        )

    winner = max(comparisons, key=lambda comparison: comparison.metrics.total_return_percent)
    _print_comparison(comparisons, winner, len(prices), args.cash)


def _print_comparison(
    comparisons: list[StrategyComparison],
    winner: StrategyComparison,
    bar_count: int,
    starting_cash: float,
) -> None:
    """Print the strategy comparison table."""
    print("PTB-1 Milestone 2 Strategy Comparison")
    print(f"Bars loaded: {bar_count}")
    print(f"Starting cash: ${starting_cash:,.2f}")
    print()
    print(f"{'Strategy':<28} {'Return':>9} {'Drawdown':>11} {'Sharpe':>9} {'Trades':>7}")
    print("-" * 70)

    for comparison in comparisons:
        sharpe = "N/A"
        if comparison.metrics.sharpe_ratio is not None:
            sharpe = f"{comparison.metrics.sharpe_ratio:.2f}"

        print(
            f"{comparison.strategy_name:<28} "
            f"{comparison.metrics.total_return_percent:>8.2f}% "
            f"{comparison.metrics.max_drawdown_percent:>10.2f}% "
            f"{sharpe:>9} "
            f"{comparison.trade_count:>7}"
        )

    print()
    print(f"Winner: {winner.strategy_name}")


if __name__ == "__main__":
    main()
