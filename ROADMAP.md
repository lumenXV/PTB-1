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

## Milestone 6.7: Market Layer Reliability

Status: complete.

Goal: make the market data layer reliable enough for fake-money live paper sessions.

Implemented:

- `MarketDataStatus` result states.
- `MarketDataResult` provider-neutral result object.
- In-memory `MarketDataRepository`.
- `ProviderManager` above the raw HTTP provider.
- Freshness checks with a default 60-second window.
- Per-symbol cooldown after rate limits.
- Cache reuse while market data is fresh.
- Repository-backed Operations Center watchlist display.
- Live paper no-trade safety for missing, stale, failed, malformed, rate-limited, or cooling-down data.

Out of scope:

- Real orders.
- Broker connections.
- Robinhood.
- Provider persistence.
- Database storage.
- Background polling.
- AI.
- Machine learning.
- Optimization.

## Milestone 7: Security Skeleton

Status: complete.

Goal: create a reusable security and trust foundation before adding more major features.

Implemented:

- `ptb1/security.py`.
- `SecureStorage` compress-first protected storage placeholder.
- `SecretManager` for environment-backed secret validation.
- `PrivacyFilter` for redacting sensitive values.
- `AuditLogger` for safe-to-view platform events.
- `ConfigValidator` with fail-closed defaults.
- Tests for redaction, secret safety, protected storage round-trip, audit safety, and unsafe config rejection.

Security honesty:

- No new crypto dependency was added.
- `SecureStorage` is not production-grade encryption.
- True production encryption requires a future approved crypto dependency.

Out of scope:

- Real trading.
- Broker connections.
- Robinhood.
- Production encryption.
- Key rotation implementation.
- User-owned key implementation.
- AI.
- Machine learning.
- Optimization.

## Milestone 7.1: Price Provider Recovery

Status: complete.

Goal: explain live price provider failures and improve request hygiene without changing trading behavior.

Implemented:

- `ProviderCheckResult` for safe provider diagnostics.
- `HTTPMarketProvider.check()` for provider health checks.
- `python -m ptb1 --provider-check --symbol AMD`.
- Request headers for `User-Agent` and `Accept: application/json`.
- Safe diagnostic output with provider name, symbol, status, HTTP status, last price, reason, and retry-after.
- Unit tests for provider-check success, rate limit, and network error.

Out of scope:

- Real trading.
- Broker connections.
- Robinhood.
- Paid API keys.
- Provider response body dumps.
- Strategy changes.
- Paper-account behavior changes.
- AI.
- Machine learning.
- Optimization.

## Milestone 7.2: Stooq Primary Provider

Status: complete.

Goal: use a no-key Stooq provider as the primary live market data source while keeping the legacy HTTP provider as fallback.

Implemented:

- `StooqProvider` for no-key read-only CSV market data.
- ProviderManager ordered providers:
  - fresh cache
  - StooqProvider
  - HTTPMarketProvider fallback
  - fail safely
- Provider result reporting with provider used and attempted provider details.
- Provider-check output showing provider used and attempts.
- Live paper still trades only on fresh `MarketDataStatus.OK`.
- Tests for Stooq success, malformed Stooq response, fallback, all-provider failure, and provider-check provider reporting.

Out of scope:

- Real trading.
- Broker connections.
- Robinhood.
- Paid API keys.
- New dependencies.
- Strategy changes.
- Paper-account behavior changes.
- AI.
- Machine learning.
- Optimization.

## Milestone 7.3: Operations Center Polish

Status: complete.

Goal: polish QMR.CO's Operations Center and Market Intelligence flow without changing engine behavior.

Implemented:

- Version banner updated to `v0.7.3`.
- Symbol validation before adding to the in-memory watchlist.
- Add-symbol flow now fetches provider data immediately.
- Clearly invalid symbols are rejected and not stored.
- Invalid menu input now gives numbered guidance.
- Provider display now separates Provider Manager, Primary, Fallback, Provider Used, and Attempts.
- Stooq malformed responses are reported clearly while preserving HTTP fallback.
- Tests for validation, auto-fetch, provider display, invalid input, and version output.

Out of scope:

- Real trading.
- Broker connections.
- Robinhood.
- Paid API keys.
- New dependencies.
- Strategy changes.
- Validator formula changes.
- Paper-account behavior changes.
- AI.
- Machine learning.
- Optimization.

## Internal Milestone 8: Unified Research Framework Foundation

Status: complete.

Goal: establish additive multi-asset and explainable-result primitives without changing runtime behavior.

Implemented:

- `ptb1/assets.py`.
- Expanded `AssetType` enum for stock, ETF, crypto, index, forex, commodity, and unknown.
- `Asset` model with provider-neutral metadata.
- Factory helpers for stock, ETF, and research-only crypto assets.
- `ptb1/strategy_result.py`.
- `ResearchContext` for future strategy evaluation context.
- `StrategyResult` with optional strategy name, strategy version, confidence, indicators, warnings, metadata, asset type, and timestamp.
- Descriptive reason validation for `StrategyResult`.
- Plain console `format_strategy_result()` helper.
- Tests for asset creation, validation, crypto research-only representation, research context, StrategyResult validation, and formatting.

Out of scope:

- Strategy migration from `Signal` to `StrategyResult`.
- Crypto market data providers.
- Wallet support.
- Broker connections.
- Exchange trading.
- Live crypto trading.
- CLI behavior changes.
- Provider behavior changes.
- Paper trading behavior changes.
- AI.
- Machine learning.
- Optimization.

## Milestone 8: Local Web Dashboard Shell

Status: complete.

Goal: start moving QMR.CO toward a local browser dashboard while preserving the existing engine architecture.

Implemented:

- `ptb1/dashboard.py`.
- `DashboardState`.
- `build_dashboard_state()`.
- `render_dashboard_html()`.
- `run_dashboard()`.
- `python -m ptb1 --dashboard`.
- Localhost-only standard-library HTTP server.
- Dark QMR.CO dashboard shell with sidebar navigation, market overview, watchlist empty state, paper/live-paper empty states, provider status, and security/trust messaging.
- Tests for dashboard state, required HTML messages, and CLI parser support.

Out of scope:

- Public hosting.
- Accounts.
- Login.
- Payments.
- Database.
- Persistence.
- Market fetching from the dashboard.
- Watchlist mutation from the dashboard.
- Real trading.
- Broker connections.
- Robinhood.
- AI.
- Machine learning.
- Strategy changes.
- Paper-account behavior changes.

## Milestone 8.1: Functional Read-Only Dashboard

Status: complete.

Goal: turn the local dashboard shell into a useful read-only interface connected to safe existing engine state.

Implemented:

- Dashboard-local `DashboardSession`.
- Functional single-page sidebar navigation.
- Safe JSON routes:
  - `GET /api/status`
  - `GET /api/markets`
  - `GET /api/watchlist`
  - `POST /api/watchlist/add`
  - `POST /api/watchlist/remove`
  - `POST /api/watchlist/refresh`
  - `GET /api/strategies`
  - `GET /api/research`
  - `GET /api/paper`
  - `GET /api/security`
- Dashboard-local in-memory watchlist add, remove, and refresh.
- Symbol validation before watchlist add.
- Market cards with status, price, provider used, and update details.
- Read-only paper and live-paper inactive states.
- Security/trust API payload with non-sensitive principles only.
- Tests for API payloads, watchlist behavior, provider usage, security safety, and bounded server handling.

Out of scope:

- Public hosting.
- Accounts.
- Login.
- Payments.
- Database.
- Persistence.
- Strategy execution from the dashboard.
- Research execution from the dashboard.
- Paper or live-paper lifecycle control.
- Fake or real order placement.
- Core engine state mutation.
- Broker connections.
- Robinhood.
- AI.
- Machine learning.


## Milestone 8.2: Dashboard Visual System and Component Cleanup

Status: complete.

Goal: make the local dashboard visually coherent and easier to maintain without changing APIs, engine behavior, or trading behavior.

Implemented:

- Centralized dashboard design tokens in `ptb1/dashboard.py`.
- Reusable render helpers for cards, empty states, status pills, and tables.
- Premium dark QMR.CO styling with blue accents, polished sidebar, topbar, cards, forms, badges, tables, and empty states.
- Responsive layout rules for narrow browser widths.
- Tests for visual-system tokens, component helpers, required safety messaging, and absence of misleading trading controls.

Out of scope:

- New dashboard APIs.
- EngineFacade or PaperSessionController.
- Browser client IDs, cookies, accounts, persistence, or database storage.
- Trading controls.
- Provider, strategy, research, paper, or live-paper behavior changes.


## Accelerated Vertical Slice: Website-Operated Fake-Money Market Scanner

Status: complete.

Goal: connect the local dashboard to one fake-money paper scanner session while preserving the approved engine boundary.

Implemented:

- `ptb1/snapshots.py` immutable dashboard transport snapshots.
- `ptb1/engine.py` with `EngineFacade` as the only dashboard-facing engine boundary.
- `ptb1/paper_session.py` with one application-wide fake paper session, one background scanner, thread-safe lifecycle access, ordered events, and clean shutdown.
- Dashboard paper routes for session, scanner, events, start, stop, and symbol updates.
- Paper Trading dashboard controls labeled as fake money only, with no manual order buttons and no broker controls.
- Bounded default universe of 20 liquid symbols, maximum 40 symbols, sequential scanning, 15-minute default interval, and 5-minute minimum interval.
- Tests for snapshots, lifecycle, events, scanner safety, dashboard paper APIs, malformed JSON, and existing dashboard compatibility.

Out of scope:

- Real trading, broker connectivity, Robinhood, wallets, accounts, login, cookies, browser client IDs, persistence, database, cloud hosting, AI/ML, new strategies, and full-market scanning.


## Milestone 8.5.1: Functional Navigation and Landing-Page Integration

Status: complete.

Goal: make QMR.CO feel like a functional local application rather than a visual-only dashboard.

Implemented:

- Public landing page served at `/`.
- Dashboard application served at `/app`.
- Direct application routes for `/app/research`, `/app/market`, `/app/strategies`, `/app/portfolio`, `/app/paper`, and `/app/reports`.
- Landing-page CTAs that route into the application.
- Sidebar navigation with route targets, active state, direct-link refresh support, and Back/Forward support.
- Functional symbol search that validates stock/ETF symbols, normalizes input, routes to research, and uses existing dashboard APIs.
- Conservative polling of paper session, scanner, and event snapshots.
- Paper-session controls remain fake-money only and use existing paper APIs.

Still unavailable:

- Full research module execution from the browser.
- Reports generation.
- Accounts, authentication, persistence, broker connectivity, real orders, and real trading.

## Milestone 9: Portfolio Engine

Track positions, allocation, exposure, and portfolio-level performance.

## Milestone 10: Robinhood MCP Integration

Integrate Robinhood through MCP only after paper trading proves the system is ready.

## Milestone 11: AI Researcher

Use AI to assist research only after strategy validation workflows are reliable.

## Milestone 12: Learning Engine

Learn from validated results without bypassing explainability or verification.

## Milestone 13: Market Memory

Remember strategies, tests, failures, and compressed historical research summaries.

## Milestone 14: Mobile Dashboard

Provide a focused dashboard for reviewing research state and results.
