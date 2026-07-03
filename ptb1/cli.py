"""Command line runner for QMR.CO reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ptb1.learning import GlossaryEntry, StrategyEducation, explain_signal, get_glossary_entries
from ptb1.live_paper import LivePaperConfig, LivePaperSession
from ptb1.market_data import CSVProvider, MarketDataProvider, MarketDataRequest, ProviderCheckResult, ProviderManager
from ptb1.operations import OperationsActions, run_operations_center
from ptb1.paper import PaperOrder, PaperPosition, PaperSession, PaperSessionResult, PaperTrade
from ptb1.researcher import Signal, Strategy
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
    parser = argparse.ArgumentParser(description="Run QMR.CO strategy reports.")
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
        "--paper",
        action="store_true",
        help="Run one strategy in fake-money paper mode.",
    )
    parser.add_argument(
        "--live-paper",
        action="store_true",
        help="Run a fake-money live paper loop with market data.",
    )
    parser.add_argument(
        "--provider-check",
        action="store_true",
        help="Run a safe market data provider diagnostic for one symbol.",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Market symbol for live paper mode. Repeat for multiple symbols.",
    )
    parser.add_argument(
        "--strategy",
        help="Strategy name for paper mode. Hyphens and spaces are treated the same.",
    )
    parser.add_argument(
        "--paper-log",
        action="store_true",
        help="Print paper order and trade logs.",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=10_000.0,
        help="Starting cash for the research backtest.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between live paper iterations.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Optional live paper iteration limit for testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run strategies against one dataset, all datasets, or Learning Mode."""
    try:
        raw_args = sys.argv[1:] if argv is None else argv
        if not raw_args:
            _run_operations_center()
            return

        args = build_parser().parse_args(raw_args)
        if args.learning:
            _print_learning_mode()
            return
        market_data_provider = CSVProvider()
        if args.provider_check:
            _run_provider_check(args.symbol)
            return
        if args.live_paper:
            _run_live_paper_mode(args.symbol, args.strategy, args.cash, args.interval, args.max_iterations)
            return
        if args.paper:
            _run_paper_mode(args.data, args.strategy, args.cash, args.paper_log, market_data_provider)
            return

        dataset_paths = _discover_dataset_paths(args.data_dir) if args.all_datasets else [args.data]
        dataset_metrics = [_run_dataset(path, args.cash, market_data_provider) for path in dataset_paths]

        print("QMR.CO Dataset Engine")
        print(f"Datasets loaded: {len(dataset_metrics)}")
        print(f"Starting cash: ${args.cash:,.2f}")
        print()

        for dataset in dataset_metrics:
            _print_dataset_report(dataset)

        if len(dataset_metrics) > 1:
            _print_cross_dataset_summary(summarize_across_datasets(dataset_metrics))
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


def _run_operations_center() -> None:
    """Launch the display-only Operations Center."""
    market_data_provider = CSVProvider()
    run_operations_center(
        data_dir=Path("datasets"),
        actions=OperationsActions(
            research=lambda: _run_default_research(market_data_provider),
            paper=lambda: _run_paper_mode(
                Path("datasets/sample_prices.csv"),
                "RSI",
                10_000.0,
                False,
                market_data_provider,
            ),
            learning=_print_learning_mode,
        ),
    )


def _run_default_research(market_data_provider: MarketDataProvider) -> None:
    """Launch the existing default research flow from Operations Center."""
    dataset = _run_dataset(Path("datasets/sample_prices.csv"), 10_000.0, market_data_provider)
    print("QMR.CO Dataset Engine")
    print("Datasets loaded: 1")
    print("Starting cash: $10,000.00")
    print()
    _print_dataset_report(dataset)


def _print_learning_mode() -> None:
    """Print read-only Learning Mode content."""
    print("QMR.CO Learning Mode")
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


def _run_paper_mode(
    path: Path,
    strategy_name: str | None,
    starting_cash: float,
    show_log: bool,
    market_data_provider: MarketDataProvider,
) -> None:
    """Run one fake-money paper session and print the result."""
    strategy = _find_strategy(strategy_name)
    prices = market_data_provider.load(path)
    result = PaperSession(starting_cash=starting_cash, risk_manager=RiskManager()).run(
        prices=prices,
        strategy=strategy,
        dataset_name=path.stem,
    )
    _print_paper_session(result, show_log)


def _run_live_paper_mode(
    symbols: list[str],
    strategy_name: str | None,
    starting_cash: float,
    interval_seconds: float,
    max_iterations: int | None,
) -> None:
    """Run one fake-money live paper session."""
    if strategy_name is None:
        names = ", ".join(strategy.name for strategy in get_available_strategies())
        raise ValueError(f"Live paper mode requires --strategy. Available strategies: {names}.")
    strategy = _find_strategy(strategy_name)
    LivePaperSession(provider=ProviderManager(), risk_manager=RiskManager()).run(
        LivePaperConfig(
            symbols=[symbol.upper() for symbol in symbols],
            strategy=strategy,
            starting_cash=starting_cash,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations,
        )
    )


def _run_provider_check(symbols: list[str]) -> None:
    """Run a safe provider diagnostic check."""
    if not symbols:
        raise ValueError("Provider check requires --symbol.")
    result = ProviderManager().check(MarketDataRequest(symbol=symbols[0], period="5d", interval="1d"))
    _print_provider_check(result)


def _print_provider_check(result: ProviderCheckResult) -> None:
    """Print safe provider diagnostic output."""
    last_price = "N/A" if result.last_price is None else f"${result.last_price:,.2f}"
    http_status = "N/A" if result.http_status is None else str(result.http_status)
    retry_after = "N/A" if result.retry_after is None else result.retry_after
    print("QMR.CO Provider Check")
    print(f"Provider: {result.provider_name}")
    print(f"Provider Used: {result.provider_used or 'N/A'}")
    print(f"Symbol: {result.symbol}")
    print(f"Status: {result.status.value}")
    print(f"HTTP Status: {http_status}")
    print(f"Last Price: {last_price}")
    print(f"Retry After: {retry_after}")
    print(f"Reason: {result.reason}")
    print("Attempts:")
    for provider_name in result.attempted_providers:
        print(f"- {provider_name}")


def _find_strategy(strategy_name: str | None) -> Strategy:
    """Find one available strategy by display name."""
    strategies = get_available_strategies()
    if strategy_name is None:
        names = ", ".join(strategy.name for strategy in strategies)
        raise ValueError(f"Paper mode requires --strategy. Available strategies: {names}.")

    normalized_name = _normalize_strategy_name(strategy_name)
    for strategy in strategies:
        if _normalize_strategy_name(strategy.name) == normalized_name:
            return strategy

    names = ", ".join(strategy.name for strategy in strategies)
    raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {names}.")


def _normalize_strategy_name(strategy_name: str) -> str:
    """Normalize strategy names for CLI matching."""
    return strategy_name.lower().replace("-", " ").strip()


def _print_paper_session(result: PaperSessionResult, show_log: bool) -> None:
    """Print a paper trading session report."""
    account = result.account
    filled_orders = [order for order in account.order_log if order.status == "FILLED"]
    rejected_orders = [order for order in account.order_log if order.status == "REJECTED"]

    print("QMR.CO Paper Trading Engine")
    print("Mode: Paper trading with fake money only")
    print(f"Dataset: {result.dataset_name}")
    print(f"Strategy: {result.strategy_name}")
    print(f"Starting Cash: ${account.starting_cash:,.2f}")
    print(f"Ending Cash: ${account.cash:,.2f}")
    print(f"Realized P/L: {_format_currency(account.realized_profit_loss)}")
    print(f"Unrealized P/L: {_format_currency(account.unrealized_profit_loss)}")
    print(f"Portfolio Value: ${account.portfolio_value:,.2f}")
    print(f"Open Positions: {len(account.positions)}")
    print(f"Filled Orders: {len(filled_orders)}")
    print(f"Rejected Orders: {len(rejected_orders)}")
    print(f"Completed Paper Trades: {len(account.trade_log)}")
    print()

    _print_open_positions(account.positions)
    _print_paper_diagnostics(result.diagnostics)

    if show_log:
        _print_order_log(account.order_log)
        _print_trade_log(account.trade_log)


def _print_open_positions(positions: dict[str, PaperPosition]) -> None:
    """Print open paper positions."""
    print("Open Position Details")
    if not positions:
        print("None")
        print()
        return

    for position in positions.values():
        print(
            f"{position.symbol}: {position.quantity} shares, "
            f"average entry ${position.average_entry_price:,.2f}, "
            f"last price ${position.last_price:,.2f}, "
            f"unrealized P/L {_format_currency(position.unrealized_profit_loss)}"
        )
    print()


def _print_paper_diagnostics(diagnostics: list[str]) -> None:
    """Print paper session diagnostics."""
    print("Diagnostics")
    for item in diagnostics:
        print(f"- {item}")
    print()


def _print_order_log(order_log: list[PaperOrder]) -> None:
    """Print fake paper orders."""
    print("Order Log")
    if not order_log:
        print("No paper orders were created.")
        print()
        return

    for order in order_log:
        print(
            f"#{order.order_id} {order.date} {order.side} {order.quantity} {order.symbol} "
            f"at ${order.requested_price:,.2f} - {order.status}"
        )
        print(order.reason)
        print("Trade Explanation")
        print(explain_signal(order.strategy_name, Signal[order.side]))
        print()


def _print_trade_log(trade_log: list[PaperTrade]) -> None:
    """Print completed fake paper trades."""
    print("Trade Log")
    if not trade_log:
        print("No completed paper trades.")
        print()
        return

    for trade in trade_log:
        print(
            f"{trade.strategy_name}: {trade.symbol} {trade.quantity} shares, "
            f"{trade.entry_date} to {trade.exit_date}, "
            f"realized P/L {_format_currency(trade.realized_profit_loss)} "
            f"({_format_signed_percent(trade.realized_profit_loss_percent)}), "
            f"hold {trade.holding_period_bars} bars"
        )
    print()


def _run_dataset(path: Path, starting_cash: float, market_data_provider: MarketDataProvider) -> DatasetMetrics:
    """Run all strategies against one dataset."""
    prices = market_data_provider.load(path)
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


def _format_signed_percent(value: float) -> str:
    """Format a signed percentage value."""
    return f"{value:+.2f}%"


def _format_currency(value: float) -> str:
    """Format a signed currency value."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


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
