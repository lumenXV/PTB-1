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

Goal: compare multiple strategies through a simple strategy plugin architecture.

Planned strategies:

- Buy and Hold.
- Simple Moving Average Cross.
- RSI.
- MACD.

Display:

- Return.
- Drawdown.
- Sharpe.
- Trades.
- Winner.

Out of scope:

- Parameter optimization.
- AI.
- Machine learning.
- Robinhood.
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
