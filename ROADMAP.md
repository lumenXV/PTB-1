# Roadmap

PTB-1 is built in milestones. Each milestone must leave the project runnable.

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

Out of scope:

- Parameter optimization.
- AI.
- Machine learning.
- Robinhood.
- Live trading.
- Automation.

## Milestone 3: Paper Trading

Run strategies against simulated live market conditions without placing real trades.

## Milestone 4: Portfolio Engine

Track positions, allocation, exposure, and portfolio-level performance.

## Milestone 5: Robinhood MCP Integration

Integrate Robinhood through MCP only after paper trading proves the system is ready.

## Milestone 6: AI Researcher

Use AI to assist research only after strategy validation workflows are reliable.

## Milestone 7: Learning Engine

Learn from validated results without bypassing explainability or verification.

## Milestone 8: Market Memory

Remember strategies, tests, failures, and compressed historical research summaries.

## Milestone 9: Mobile Dashboard

Provide a focused dashboard for reviewing research state and results.
