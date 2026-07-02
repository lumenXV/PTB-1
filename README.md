# PTB-1

PTB-1 is an AI trading research platform. It is not a live trading bot.

Milestone 4 adds a Paper Trading Engine. PTB-1 can still run research backtests across one or many CSV datasets, and it can now run one strategy at a time with fake money only.
Milestone 4.5 adds an internal market data provider interface with CSV as the only current provider.
Milestone 5 adds an internal HTTP market data foundation without adding public market-data commands or live trading.
Milestone 5.1 adds a display-only Operations Center as the default platform entry point.

Learning Mode is a read-only companion feature. It teaches what PTB-1 is doing, explains strategy concepts, and defines research terms. It does not run backtests, place trades, change strategies, change parameters, modify risk, or influence decisions.

PTB-1 does not include Robinhood, AI, machine learning, live trading, optimization, or automation.

## Project Brain

- [Vision](VISION.md)
- [Roadmap](ROADMAP.md)
- [Architecture](ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## Run PTB-1

Launch the Operations Center:

```powershell
python -m ptb1
```

Run one dataset:

```powershell
python -m ptb1 --data datasets/sample_prices.csv
```

Run every dataset in `datasets/`:

```powershell
python -m ptb1 --all-datasets
```

Print Learning Mode education and glossary content:

```powershell
python -m ptb1 --learning
```

Run one fake-money paper session:

```powershell
python -m ptb1 --paper --strategy RSI --data datasets/sample_prices.csv
```

Print the fake paper order and trade logs:

```powershell
python -m ptb1 --paper --strategy RSI --data datasets/sample_prices.csv --paper-log
```

Run the stability harness:

```powershell
python -m unittest discover
```

The root `sample_prices.csv` still works for backward compatibility:

```powershell
python -m ptb1 --data sample_prices.csv
```

No third-party dependencies are required.

## Architecture

```mermaid
flowchart LR
    CLI --> DatasetFiles["datasets/*.csv"]
    CLI["CLI Runner\ndisplay + orchestration"] --> Operations["Operations Center\nstatus + menu"]
    CLI["CLI Runner\ndisplay + orchestration"] --> MarketData["Market Data\nprovider interface"]
    MarketData --> Historian["Historian\ncreate + validate PriceBars"]
    CLI --> Strategies["Strategies\nexplicit registry"]
    Strategies --> Researcher["Researcher\nshared strategy interface"]
    Strategies --> Learning["Learning Mode\nread-only education"]
    CLI --> Learning
    CLI --> Trader["Trader\nexecution facts only"]
    CLI --> Paper["Paper Trader\nfake-money execution only"]
    Paper --> RiskManager
    Paper --> Learning
    Trader --> RiskManager["Risk Manager\napprove position changes"]
    Trader --> ValidatorInput["Backtest Results"]
    CLI --> Validator["Validator\nmetrics + dataset summaries"]
    ValidatorInput --> Validator
```

## Responsibilities

| Employee | Module | One responsibility |
| --- | --- | --- |
| Historian | `ptb1/historian.py` | Load and validate historical market data. |
| Operations Center | `ptb1/operations.py` | Display platform status and menu options. |
| Market Data | `ptb1/market_data.py` | Provide internal CSV and HTTP market data providers. |
| Researcher | `ptb1/researcher.py` | Define strategy signals and strategy interface. |
| Strategies | `ptb1/strategies.py` | Implement independent research strategies and static education metadata. |
| Learning Mode | `ptb1/learning.py` | Provide read-only educational text and glossary entries. |
| Trader | `ptb1/trader.py` | Run backtests and record execution facts. |
| Paper Trader | `ptb1/paper.py` | Run fake-money paper sessions and record paper account facts. |
| Risk Manager | `ptb1/risk_manager.py` | Approve or reject position changes. |
| Validator | `ptb1/validator.py` | Calculate metrics, comparison winners, notes, and cross-dataset summaries. |
| CLI Runner | `ptb1/cli.py` | Orchestrate runs and display reports or Learning Mode content. |

No module should do another employee's job.

## Roadmap

1. Backtest one strategy. Done in Milestone 1.
2. Support multiple strategies. Done in Milestone 2.
3. Research Lab. Done in Milestone 2.5.
4. Dataset Engine. Done in Milestone 3.
5. Paper trading. Done in Milestone 4.
6. Market data provider interface. Done in Milestone 4.5.
7. Live market data foundation. Done in Milestone 5.
8. Operations Center. Done in Milestone 5.1.
9. Portfolio tracking.
10. Robinhood MCP.
11. AI researcher.
12. Learning engine.
13. Market Memory.
14. Mobile Dashboard.
