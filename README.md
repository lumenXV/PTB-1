# PTB-1

PTB-1 is an AI trading research platform. It is not a live trading bot.

## Milestones

1. Backtest one strategy.
2. Support multiple strategies.
3. Paper trading.
4. Portfolio tracking.
5. Robinhood MCP.
6. AI researcher.
7. Learning engine.

## Employees

Each module has one job:

- Researcher: defines strategy ideas and emits trade signals.
- Trader: runs backtests from approved signals.
- Historian: loads historical market data.
- Risk Manager: keeps position rules separate from strategy logic.
- Validator: calculates performance metrics.

No module should do another employee's job.

## Run Milestone 1

```powershell
python -m ptb1 --data sample_prices.csv
```
