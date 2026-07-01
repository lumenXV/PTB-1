"""Command line runner for PTB-1 milestone backtests."""

from __future__ import annotations

import argparse
from pathlib import Path

from ptb1.historian import load_price_history
from ptb1.researcher import BuyAndHoldStrategy
from ptb1.risk_manager import RiskManager
from ptb1.trader import Backtester
from ptb1.validator import calculate_metrics


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(description="Run a PTB-1 research backtest.")
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
    """Run the command line backtest."""
    args = build_parser().parse_args()
    prices = load_price_history(args.data)
    strategy = BuyAndHoldStrategy()
    backtester = Backtester(starting_cash=args.cash, risk_manager=RiskManager())
    result = backtester.run(prices=prices, strategy=strategy)
    metrics = calculate_metrics(result)

    print("PTB-1 Milestone 1 Backtest")
    print(f"Strategy: {strategy.name}")
    print(f"Bars loaded: {len(prices)}")
    print(f"Trades: {len(result.trades)}")
    print(f"Starting equity: ${result.starting_cash:,.2f}")
    print(f"Ending equity: ${result.ending_equity:,.2f}")
    print(f"Total return: {metrics.total_return_percent:.2f}%")
    print(f"Max drawdown: {metrics.max_drawdown_percent:.2f}%")


if __name__ == "__main__":
    main()
