# Roadmap

QMR.CO is built in milestones. Each milestone must leave the project runnable.

The Python package remains `ptb1` for compatibility.

## Milestone 1: Basic Backtester

Status: complete.

Goal: backtest one strategy against historical CSV data.

Implemented:

- Historical data loader.
- Strategy interface.
- Buy and Hold strategy.
- Backtester.
- Basic performance metrics.
- Command line runner.
- GitHub Actions run verification.

## Milestone 2: Multiple Strategy Engine

Status: complete.

Goal: compare multiple strategies on the same historical dataset.

Implemented:

- Explicit strategy registry.
- Buy and Hold strategy.
- Simple Moving Average Cross strategy.
- RSI strategy.
- MACD strategy.
- Strategy comparison table.
- Winner selection by highest total return.
- Optional Sharpe ratio reporting.

## Milestone 2.5: Research Lab

Status: complete.

Goal: understand why strategies perform the way they do before any paper trading or broker integration.

Implemented:

- Expanded Validator-owned metrics.
- Structured research report per strategy.
- Comparison summary across strategies.
- Mechanical research notes based only on measured metrics.
- Archive candidate notes without creating Strategy Graveyard files.

## Milestone 3: Dataset Engine

Status: complete.

Goal: run all strategies across multiple historical datasets.

Implemented:

- `datasets/` folder.
- Default dataset at `datasets/sample_prices.csv`.
- Demo datasets for trend-cycle and choppy-market behavior.
- `--data` mode for one dataset.
- `--all-datasets` mode for every CSV dataset in `datasets/`.
- Cross-dataset strategy summaries owned by Validator.
- Overall winner by highest average total return across datasets.

Out of scope:

- Parameter optimization.
- AI.
- Machine learning.
- Robinhood.
- Live trading.
- Automation.

## Milestone 4: Paper Trading

Status: complete.

Goal: simulate real-time trading with fake money while staying separate from research backtesting.

Implemented:

- `ptb1/paper.py` fake-money paper trading engine.
- Fake cash balance.
- Fake long-only positions.
- Simulated buy and sell orders.
- In-memory order log.
- In-memory trade log.
- Realized profit/loss.
- Unrealized profit/loss.
- Portfolio value.
- Risk Manager approval before fake order fills.
- Learning Mode explanations for paper trade signals.
- Paper session diagnostics.
- CLI paper mode for one strategy at a time.

Out of scope:

- Real brokers.
- Robinhood.
- Live trading.
- AI.
- Machine learning.
- Optimization.
- Slippage, commissions, partial fills, limits, stops, or latency.
- File persistence.

## Milestone 4.5: Market Data Provider Interface

Status: complete.

Goal: prepare QMR.CO for future market data sources without changing current behavior.

Implemented:

- Internal `MarketDataProvider` protocol.
- Internal `CSVProvider`.
- CSVProvider delegates to Historian.
- Research mode uses the internal CSVProvider.
- Paper mode uses the internal CSVProvider.

Out of scope:

- User-facing data provider CLI flags.
- Yahoo implementation.
- Robinhood.
- Broker connections.
- Live trading.
- AI.
- Machine learning.
- Optimization.

## Milestone 5: Live Market Data Foundation

Status: complete.

Goal: prepare QMR.CO to retrieve live market data internally without changing the user workflow.

Implemented:

- Internal `MarketDataRequest`.
- Internal `HTTPMarketProvider`.
- Dependency-injected HTTP fetching for tests.
- Provider response conversion into existing `PriceBar` objects.
- Historian-owned PriceBar creation and validation for converted rows.
- Clear errors for invalid symbols, network failures, timeouts, empty responses, malformed responses, and missing OHLCV fields.

Out of scope:

- User-facing market-data CLI commands.
- Paper trading with live data.
- Live trading.
- Broker connections.
- Robinhood.
- Order placement.
- AI.
- Machine learning.
- Optimization.

## Milestone 5.1: Operations Center

Status: complete.

Goal: provide a unified display-only platform entry point without changing engine behavior.

Implemented:

- `ptb1/operations.py` display-only Operations Center.
- Startup banner and version display.
- Platform status display.
- Runtime display.
- Registered strategy count.
- Dataset count.
- Market provider readiness.
- Stability harness readiness display.
- Numbered menu rendering.
- Default `python -m ptb1` launcher.

Out of scope:

- Engine ownership changes.
- Research metric calculations.
- Strategy modifications.
- Paper trading behavior changes.
- Live trading.
- Broker connections.
- Robinhood.
- AI.
- Machine learning.
- Optimization.

## Milestone 6: QMR.CO Live Market Intelligence

Status: complete.

Goal: rebrand PTB-1 to QMR.CO in the user experience and add read-only live market awareness.

Implemented:

- QMR.CO user-facing branding.
- Operations Center Live Market Intelligence section.
- In-memory watchlist.
- Add symbol.
- Remove symbol.
- Display watched symbols.
- Manual refresh of watched prices.
- Read-only quote display with last price, daily change, daily percent change, and last updated time.
- Provider failure display without raising into the Operations Center.

Out of scope:

- Package rename.
- Persistent watchlist storage.
- Background polling.
- Trading signals from live prices.
- Live trading.
- Broker connections.
- Robinhood.
- Order placement.
- AI.
- Machine learning.
- Optimization.

## Milestone 6.5: Live Paper Trading + Easier Startup

Status: complete.

Goal: run a fake-money live paper loop through the provider layer and make local startup easier.

Implemented:

- `ptb1/live_paper.py` fake-money live paper coordinator.
- `--live-paper` CLI mode.
- Repeatable `--symbol` support.
- `--interval` loop timing.
- `--max-iterations` bounded test mode.
- Risk Manager approval before fake live paper order fills.
- Decision logging with clear `PAPER TRADE ONLY` output.
- Clean Ctrl+C summary handling.
- `qmr.ps1` PowerShell launcher for `python -m ptb1`.

Out of scope:

- Real orders.
- Broker connections.
- Robinhood.
- Margin.
- Short selling.
- Options.
- AI.
- Machine learning.
- Optimization.
- File persistence.
- Background services.

## Milestone 7: Portfolio Engine

Track positions, allocation, exposure, and portfolio-level performance.

## Milestone 8: Robinhood MCP Integration

Integrate Robinhood through MCP only after paper trading proves the system is ready.

## Milestone 9: AI Researcher

Use AI to assist research only after strategy validation workflows are reliable.

## Milestone 10: Learning Engine

Learn from validated results without bypassing explainability or verification.

## Milestone 11: Market Memory

Remember strategies, tests, failures, and compressed historical research summaries.

## Milestone 12: Mobile Dashboard

Provide a focused dashboard for reviewing research state and results.
