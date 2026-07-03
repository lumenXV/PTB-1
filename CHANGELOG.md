# Changelog

All notable QMR.CO changes should be recorded here in plain language.

## Unreleased

## Milestone 7.2: Stooq Primary Provider

- Added `StooqProvider` as the primary no-key read-only market data provider.
- Kept the existing HTTP provider as legacy fallback.
- Updated ProviderManager to support ordered provider attempts.
- Added provider-used and attempted-provider reporting.
- Updated provider-check output to show provider used and attempts.
- Added tests for Stooq CSV success, malformed CSV, fallback to HTTP, all-provider failure, and provider-check reporting.
- Preserved live paper fake-money-only behavior and fresh-OK-only trading rule.

## Milestone 7.1: Price Provider Recovery

- Added `ProviderCheckResult` for safe market provider diagnostics.
- Added `HTTPMarketProvider.check()` to report provider status without raising into the CLI.
- Added `python -m ptb1 --provider-check --symbol AMD`.
- Added live provider request headers for `User-Agent` and `Accept: application/json`.
- Added safe diagnostic output for provider name, symbol, status, HTTP status, last price, reason, and retry-after.
- Added provider-check tests for success, rate limit, and network error.
- Preserved live paper no-trade behavior unless market data is fresh `OK`.

## Milestone 7: Security Skeleton

- Added `ptb1/security.py`.
- Added `SecureStorage` as a compress-first protected storage placeholder.
- Added `SecretManager` for environment-backed secret validation without printing secrets.
- Added `PrivacyFilter` for redacting emails, IP addresses, tokens, API keys, credentials, account IDs, and tax IDs.
- Added `AuditLogger` for safe-to-view platform events.
- Added `ConfigValidator` with fail-closed defaults.
- Added tests for redaction, secret handling, protected storage, audit safety, and unsafe config rejection.
- Documented that true production encryption requires a future approved crypto dependency.

## Milestone 6.7: Market Layer Reliability

- Added provider-neutral market data statuses and result objects.
- Added an in-memory market data repository with freshness tracking.
- Added a ProviderManager with cache reuse and rate-limit cooldown handling.
- Updated live paper so fake trades only run on fresh valid market data.
- Updated live paper output with provider status, cache status, last successful update, and next retry time.
- Updated Operations Center watchlist display to use repository-backed market status.
- Added unit tests for fresh cache reuse, stale refresh, cooldown behavior, safe live-paper pauses, and cached watchlist status.

## Milestone 6.5: Live Paper Trading + Easier Startup

- Added `ptb1/live_paper.py` for fake-money live paper sessions.
- Added `--live-paper`, repeatable `--symbol`, `--interval`, and `--max-iterations` CLI options.
- Added live paper decision output with signal, risk decision, fake order result, account status, and `PAPER TRADE ONLY` notes.
- Added clean Ctrl+C summary handling for live paper sessions.
- Added deterministic live paper unit tests with fake provider data.
- Added `qmr.ps1` as a PowerShell launcher for `python -m ptb1`.
- Preserved existing research, dataset, learning, Operations Center, and paper trading behavior.

## Milestone 6: QMR.CO Live Market Intelligence

- Rebranded the user-facing interface and documentation from PTB-1 to QMR.CO.
- Kept the internal Python package name `ptb1` for compatibility.
- Added read-only Live Market Intelligence to the Operations Center.
- Added an in-memory watchlist with add, remove, display, and manual refresh support.
- Added read-only quote display with symbol, last price, daily change, daily percent change, and last updated time.
- Added watchlist tests for empty state, add, remove, refresh, invalid symbols, and provider failures.
- Preserved existing research, dataset, learning, stability, and paper trading commands.

## Milestone 5.1: Operations Center

- Added `ptb1/operations.py` as a display-only platform entry point.
- Added startup banner, version display, runtime display, platform status, strategy count, dataset count, market provider status, and menu rendering.
- Updated `python -m ptb1` to launch the Operations Center by default.
- Preserved all existing flag-based commands.
- Added Operations Center tests.

## Milestone 5: Live Market Data Foundation

- Added internal `MarketDataRequest`.
- Added internal `HTTPMarketProvider`.
- Added dependency-injected HTTP fetching so unit tests do not require internet access.
- Added provider response conversion into existing `PriceBar` objects.
- Reused Historian-owned PriceBar creation and validation for converted provider rows.
- Added clear errors for invalid symbols, network failures, timeouts, empty responses, malformed responses, and missing OHLCV fields.
- Kept market data retrieval internal with no user-facing market-data CLI command.

## Milestone 4.5: Market Data Provider Interface

- Added internal `MarketDataProvider` protocol.
- Added internal `CSVProvider`.
- Kept Historian as the single owner of CSV parsing, validation, and PriceBar creation.
- Updated research and paper modes to use the internal CSVProvider.
- Added provider tests without adding a user-facing provider CLI flag.

## Milestone 4: Paper Trading Engine

- Added `ptb1/paper.py` for fake-money paper trading sessions.
- Added fake cash, fake positions, fake order logs, fake trade logs, realized profit/loss, unrealized profit/loss, and portfolio value.
- Added Risk Manager approval before fake paper order fills.
- Added CLI paper mode for one strategy at a time.
- Added optional `--paper-log` output with Learning Mode trade explanations.
- Added paper trading stability tests.
- Updated GitHub Actions with a paper trading smoke test.

## Milestone 3.1: Stability Harness

- Added a small `unittest` stability harness.
- Added invalid CSV fixtures for empty, header-only, missing-column, bad-number, and bad-date datasets.
- Added Historian-owned CSV validation.
- Updated CLI error display for dataset loading failures.
- Updated GitHub Actions to run stability tests, one dataset, and all datasets.

## Learning Mode Side Feature

- Added read-only Learning Mode framework.
- Added strategy education metadata for current strategies.
- Added glossary entries for common indicators and research metrics.
- Added template-based explanation helpers.
- Added `python -m ptb1 --learning` to print education and glossary content without running backtests.

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
