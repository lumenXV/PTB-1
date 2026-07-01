"""Command line runner for PTB-1 research reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from ptb1.historian import load_price_history
from ptb1.learning import GlossaryEntry, StrategyEducation, get_glossary_entries
from ptb1.risk_manager import RiskManager
from ptb1.strategies import get_available_strategies
from ptb1.trader import Backtester
from ptb1.validator import (
    ComparisonSummary,
    CrossDatasetSummary,
    DatasetMetrics,
    PerformanceMetrics,
    StrategyMetrics,
    calculate_metrics,
    compare_strategy_metrics,
    summarize_across_datasets,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(description="Run PTB-1 research strategy reports.")
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("datasets/sample_prices.csv"),
        help="Path to one historical CSV dataset.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("datasets"),
        help="Directory containing historical CSV datasets.",
    )
    parser.add_argument(
        "--all-datasets",
        action="store_true",
        help="Run all CSV datasets in the dataset directory.",
    )
    parser.add_argument(
        "--learning",
        action="store_true",
        help="Print read-only strategy education and glossary entries.",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=10_000.0,
        help="Starting cash for the research backtest.",
    )
    return parser


def main() -> None:
    """Run strategies against one dataset, all datasets, or Learning Mode."""
    args = build_parser().parse_args()
    if args.learning:
        _print_learning_mode()
        return

    dataset_paths = _discover_dataset_paths(args.data_dir) if args.all_datasets else [args.data]
    dataset_metrics = [_run_dataset(path, args.cash) for path in dataset_paths]

    print("PTB-1 Milestone 3 Dataset Engine")
    print(f"Datasets loaded: {len(dataset_metrics)}")
    print(f"Starting cash: ${args.cash:,.2f}")
    print()

    for dataset in dataset_metrics:
        _print_dataset_report(dataset)

    if len(dataset_metrics) > 1:
        _print_cross_dataset_summary(summarize_across_datasets(dataset_metrics))


def _print_learning_mode() -> None:
    """Print read-only Learning Mode content."""
    print("PTB-1 Learning Mode")
    print("Read-only educational explanations. No backtests or trades are run.")
    print()
    print("Strategy Education")
    for strategy in get_available_strategies():
        _print_strategy_education(strategy.name, strategy.education)

    print("Glossary")
    for entry in get_glossary_entries():
        _print_glossary_entry(entry)


def _print_strategy_education(strategy_name: str, education: StrategyEducation) -> None:
    """Print one strategy education card."""
    print("-" * 50)
    print(f"Strategy: {strategy_name}")
    print(f"Description: {education.description}")
    print(f"Purpose: {education.purpose}")
    print("Strengths:")
    for item in education.strengths:
        print(f"- {item}")
    print("Weaknesses:")
    for item in education.weaknesses:
        print(f"- {item}")
    print(f"Best Market Conditions: {education.best_market_conditions}")
    print(f"Worst Market Conditions: {education.worst_market_conditions}")
    print(f"Typical Holding Period: {education.typical_holding_period}")
    print(f"Risk Level: {education.risk_level}")
    print("Common Mistakes:")
    for item in education.common_mistakes:
        print(f"- {item}")
    print("-" * 50)
    print()


def _print_glossary_entry(entry: GlossaryEntry) -> None:
    """Print one glossary entry."""
    print("-" * 50)
    print(entry.term)
    print(f"What It Is: {entry.what_it_is}")
    print(f"Why Traders Use It: {entry.why_traders_use_it}")
    print("Advantages:")
    for item in entry.advantages:
        print(f"- {item}")
    print("Limitations:")
    for item in entry.limitations:
        print(f"- {item}")
    print("-" * 50)
    print()


def _discover_dataset_paths(data_dir: Path) -> list[Path]:
    """Discover CSV datasets in a directory."""
    dataset_paths = sorted(data_dir.glob("*.csv"))
    if not dataset_paths:
        raise ValueError(f"No CSV datasets found in {data_dir}.")
    return dataset_paths


def _run_dataset(path: Path, starting_cash: float) -> DatasetMetrics:
    """Run all strategies against one dataset."""
    prices = load_price_history(path)
    backtester = Backtester(starting_cash=starting_cash, risk_manager=RiskManager())
    strategy_metrics: list[StrategyMetrics] = []

    for strategy in get_available_strategies():
        result = backtester.run(prices=prices, strategy=strategy)
        strategy_metrics.append(
            StrategyMetrics(
                strategy_name=strategy.name,
                metrics=calculate_metrics(result),
            )
        )

    return DatasetMetrics(
        dataset_name=path.stem,
        strategy_metrics=strategy_metrics,
        summary=compare_strategy_metrics(strategy_metrics),
    )


def _print_dataset_report(dataset: DatasetMetrics) -> None:
    """Print the full report for one dataset."""
    print("=" * 50)
    print(f"Dataset: {dataset.dataset_name}")
    print("=" * 50)
    print()

    for item in dataset.strategy_metrics:
        _print_strategy_report(item.strategy_name, item.metrics)

    _print_summary(dataset.summary)
    print()


def _print_strategy_report(strategy_name: str, metrics: PerformanceMetrics) -> None:
    """Print a structured report for one strategy."""
    print("-" * 50)
    print(f"Strategy: {strategy_name}")
    print(f"Return: {_format_percent(metrics.total_return_percent)}")
    print(f"CAGR: {_format_optional_percent(metrics.cagr_percent)}")
    print(f"Max Drawdown: {_format_percent(metrics.max_drawdown_percent)}")
    print(f"Sharpe: {_format_optional_number(metrics.sharpe_ratio)}")
    print(f"Win Rate: {_format_optional_percent(metrics.win_rate_percent)}")
    print(f"Profit Factor: {_format_optional_number(metrics.profit_factor)}")
    print(f"Expectancy: {_format_optional_percent(metrics.expectancy_percent)}")
    print(f"Average Winner: {_format_optional_signed_percent(metrics.average_winning_trade_percent)}")
    print(f"Average Loser: {_format_optional_signed_percent(metrics.average_losing_trade_percent)}")
    print(f"Largest Winner: {_format_optional_signed_percent(metrics.largest_winner_percent)}")
    print(f"Largest Loser: {_format_optional_signed_percent(metrics.largest_loser_percent)}")
    print(f"Average Hold: {_format_optional_bars(metrics.average_holding_period_bars)}")
    print(f"Completed Trades: {metrics.total_trades}")
    print(f"Open Position: {_format_yes_no(metrics.has_open_position)}")
    print(f"Exposure: {_format_percent(metrics.exposure_time_percent)}")
    print("-" * 50)
    print()


def _print_summary(summary: ComparisonSummary) -> None:
    """Print the cross-strategy comparison summary and notes."""
    print("Comparison Summary")
    print(f"Best Return: {summary.best_return.strategy_name}")
    print(f"Best Sharpe: {_format_strategy_name(summary.best_sharpe)}")
    print(f"Lowest Drawdown: {summary.lowest_drawdown.strategy_name}")
    print(f"Highest Win Rate: {_format_strategy_name(summary.highest_win_rate)}")
    print(f"Most Trades: {summary.most_trades.strategy_name}")
    print(f"Least Trades: {summary.least_trades.strategy_name}")
    print(f"Overall Winner: {summary.overall_winner.strategy_name}")
    print()
    print("Research Notes")
    for note in summary.research_notes:
        print(f"- {note}")


def _print_cross_dataset_summary(summary: CrossDatasetSummary) -> None:
    """Print the summary of strategy behavior across datasets."""
    print("Cross-Dataset Strategy Summary")
    print(f"{'Strategy':<28} {'Avg Return':>11} {'Avg Drawdown':>14} {'Wins':>6} {'Datasets':>9}")
    print("-" * 76)
    for item in summary.strategy_summaries:
        print(
            f"{item.strategy_name:<28} "
            f"{item.average_return_percent:>10.2f}% "
            f"{item.average_drawdown_percent:>13.2f}% "
            f"{item.wins:>6} "
            f"{item.dataset_count:>9}"
        )
    print()
    print(f"Overall Cross-Dataset Winner: {summary.overall_winner.strategy_name}")


def _format_percent(value: float) -> str:
    """Format a percentage value."""
    return f"{value:.2f}%"


def _format_optional_percent(value: float | None) -> str:
    """Format an optional percentage value."""
    if value is None:
        return "N/A"
    return _format_percent(value)


def _format_optional_signed_percent(value: float | None) -> str:
    """Format an optional signed percentage value."""
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _format_optional_number(value: float | None) -> str:
    """Format an optional number value."""
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _format_optional_bars(value: float | None) -> str:
    """Format an optional holding period value."""
    if value is None:
        return "N/A"
    return f"{value:.2f} bars"


def _format_strategy_name(item: StrategyMetrics | None) -> str:
    """Format an optional strategy metric winner."""
    if item is None:
        return "N/A"
    return item.strategy_name


def _format_yes_no(value: bool) -> str:
    """Format a boolean value as Yes or No."""
    if value:
        return "Yes"
    return "No"


if __name__ == "__main__":
    main()
