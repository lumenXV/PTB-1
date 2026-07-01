# Changelog

All notable PTB-1 changes should be recorded here in plain language.

## Unreleased

## Reporting Cleanup

- Clarified `Trades` as `Completed Trades` in research reports.
- Added `Open Position: Yes/No` report metadata from Validator.
- Kept strategy logic, Trader behavior, and metric formulas unchanged.

## Milestone 3: Dataset Engine

- Added the `datasets/` folder.
- Added `datasets/sample_prices.csv` as the default dataset path.
- Added `datasets/trend_cycle.csv` demo data.
- Added `datasets/choppy_market.csv` demo data.
- Kept root `sample_prices.csv` for backward compatibility.
- Added `--all-datasets` CLI mode.
- Kept `--data` CLI mode for single-dataset runs.
- Added Validator-owned cross-dataset summaries.
- Updated GitHub Actions to run one dataset and all datasets.

## Milestone 2.5: Research Lab

- Expanded Trader execution facts without moving statistics into Trader.
- Expanded Validator metrics:
  - Total return.
  - CAGR when enough data exists.
  - Max drawdown.
  - Sharpe ratio.
  - Profit factor.
  - Expectancy.
  - Win rate.
  - Average winning trade.
  - Average losing trade.
  - Largest winner.
  - Largest loser.
  - Average holding period.
  - Total trades.
  - Exposure time.
- Added structured research reports for every strategy.
- Added comparison summary winners.
- Added mechanical research notes based only on measured statistics.
- Added archive candidate notes without creating Strategy Graveyard files.

## Milestone 2: Multiple Strategy Engine

- Added an explicit strategy registry.
- Added independent Buy and Hold, SMA Cross, RSI, and MACD strategies.
- Updated strategy signals to receive only history available up to the current bar.
- Updated the CLI to run all available strategies by default.
- Added a strategy comparison table.
- Added winner selection by highest total return.
- Added optional Sharpe ratio reporting.
- Expanded sample historical data so indicator strategies have enough bars.

## Project Brain Documentation

- Added project brain documentation:
  - `VISION.md`
  - `ROADMAP.md`
  - `ARCHITECTURE.md`
  - `CONTRIBUTING.md`
  - `CHANGELOG.md`

## Milestone 1: Basic Backtester

- Added a historical CSV data loader.
- Added a strategy interface.
- Added a Buy and Hold strategy.
- Added a simple long-only backtester.
- Added basic performance metrics.
- Added a command line runner.
- Added sample historical price data.
- Added GitHub Actions verification that runs `python -m ptb1 --data sample_prices.csv`.
