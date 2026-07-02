"""Learning Mode: read-only educational explanations for QMR.CO."""

from __future__ import annotations

from dataclasses import dataclass

from ptb1.researcher import Signal
from ptb1.validator import ComparisonSummary, StrategyMetrics


@dataclass(frozen=True)
class StrategyEducation:
    """Plain-English educational metadata for a strategy."""

    description: str
    purpose: str
    strengths: list[str]
    weaknesses: list[str]
    best_market_conditions: str
    worst_market_conditions: str
    typical_holding_period: str
    risk_level: str
    common_mistakes: list[str]


@dataclass(frozen=True)
class GlossaryEntry:
    """Educational glossary entry for a trading or research term."""

    term: str
    what_it_is: str
    why_traders_use_it: str
    advantages: list[str]
    limitations: list[str]


def get_glossary_entries() -> list[GlossaryEntry]:
    """Return the static Learning Mode glossary."""
    return [
        GlossaryEntry(
            term="RSI",
            what_it_is="Relative Strength Index, a momentum oscillator that compares recent gains and losses.",
            why_traders_use_it="Traders use RSI to identify potentially overbought or oversold conditions.",
            advantages=["Simple to interpret.", "Can highlight potential reversals in range-bound markets."],
            limitations=["Can stay overbought or oversold during strong trends.", "Does not predict price direction."],
        ),
        GlossaryEntry(
            term="SMA",
            what_it_is="Simple Moving Average, the average closing price over a fixed number of bars.",
            why_traders_use_it="Traders use SMA to smooth price movement and identify trend direction.",
            advantages=["Easy to calculate.", "Reduces short-term noise."],
            limitations=["Lags price.", "Can whipsaw in choppy markets."],
        ),
        GlossaryEntry(
            term="EMA",
            what_it_is="Exponential Moving Average, a moving average that weights recent prices more heavily.",
            why_traders_use_it="Traders use EMA to react faster to recent price movement than an SMA.",
            advantages=["More responsive than SMA.", "Useful in trend-following systems."],
            limitations=["Still lags price.", "Can react to noise."],
        ),
        GlossaryEntry(
            term="MACD",
            what_it_is="Moving Average Convergence Divergence, based on the difference between fast and slow EMAs.",
            why_traders_use_it="Traders use MACD to identify momentum shifts and trend changes.",
            advantages=["Combines trend and momentum information.", "Signals can be easy to explain."],
            limitations=["Can lag reversals.", "Can generate false signals in sideways markets."],
        ),
        GlossaryEntry(
            term="ATR",
            what_it_is="Average True Range, a measure of recent price volatility.",
            why_traders_use_it="Traders use ATR to understand volatility and size risk-aware stops.",
            advantages=["Measures volatility directly.", "Useful for risk planning."],
            limitations=["Does not indicate direction.", "Can expand after risk has already increased."],
        ),
        GlossaryEntry(
            term="VWAP",
            what_it_is="Volume Weighted Average Price, average price weighted by trading volume.",
            why_traders_use_it="Traders use VWAP to compare price against volume-weighted activity.",
            advantages=["Includes volume context.", "Common benchmark for intraday trading."],
            limitations=["Less useful for simple daily datasets.", "Does not predict future price."],
        ),
        GlossaryEntry(
            term="Bollinger Bands",
            what_it_is="Bands placed around a moving average using recent volatility.",
            why_traders_use_it="Traders use them to study volatility, extremes, and possible mean reversion.",
            advantages=["Shows price relative to recent volatility.", "Can identify stretched conditions."],
            limitations=["Band touches are not automatic reversal signals.", "Can expand during trends."],
        ),
        GlossaryEntry(
            term="Momentum",
            what_it_is="The tendency of price movement to continue in the same direction over a period.",
            why_traders_use_it="Traders use momentum to participate in sustained moves.",
            advantages=["Can work well in strong trends.", "Often easy to measure."],
            limitations=["Can reverse sharply.", "Can perform poorly in range-bound markets."],
        ),
        GlossaryEntry(
            term="Mean Reversion",
            what_it_is="The idea that price may move back toward a recent average after becoming stretched.",
            why_traders_use_it="Traders use mean reversion to look for potential reversal trades.",
            advantages=["Can work in sideways markets.", "Often has clear invalidation points."],
            limitations=["Can fail repeatedly in strong trends.", "Requires careful risk control."],
        ),
        GlossaryEntry(
            term="Trend Following",
            what_it_is="A style that attempts to participate in sustained directional moves.",
            why_traders_use_it="Traders use trend following to capture large market moves.",
            advantages=["Can capture outsized trends.", "Rules are often simple."],
            limitations=["Can suffer during choppy markets.", "Often has delayed entries and exits."],
        ),
        GlossaryEntry(
            term="Drawdown",
            what_it_is="The decline from an equity peak to a later low.",
            why_traders_use_it="Traders use drawdown to understand downside risk.",
            advantages=["Highlights risk that returns alone hide.", "Easy to compare across strategies."],
            limitations=["Depends on the tested period.", "Does not describe every risk type."],
        ),
        GlossaryEntry(
            term="Sharpe Ratio",
            what_it_is="A return-to-volatility measure.",
            why_traders_use_it="Traders use Sharpe to compare return consistency across strategies.",
            advantages=["Penalizes volatile returns.", "Useful for comparing strategies."],
            limitations=["Can be misleading on small samples.", "Assumes volatility is the main risk."],
        ),
        GlossaryEntry(
            term="Profit Factor",
            what_it_is="Gross profit divided by gross loss across completed trades.",
            why_traders_use_it="Traders use profit factor to compare trade profitability.",
            advantages=["Separates gross wins from gross losses.", "Easy to interpret."],
            limitations=["Can be distorted by few trades.", "Does not show drawdown timing."],
        ),
        GlossaryEntry(
            term="Expectancy",
            what_it_is="Average expected result per completed trade in the tested sample.",
            why_traders_use_it="Traders use expectancy to understand average trade quality.",
            advantages=["Summarizes trade outcomes.", "Pairs well with win rate and payoff size."],
            limitations=["Depends on sample quality.", "Can hide uneven trade distributions."],
        ),
    ]


def explain_signal(strategy_name: str, signal: Signal) -> str:
    """Explain a signal without making predictions or changing decisions."""
    return (
        f"Strategy: {strategy_name}\n"
        f"Signal: {signal.value.upper()}\n"
        "Reason:\n"
        "The strategy emitted this signal according to its configured research rules.\n"
        "This is not a prediction."
    )


def explain_strategy_result(strategy_metrics: StrategyMetrics, summary: ComparisonSummary) -> list[str]:
    """Explain measured strategy results with non-speculative templates."""
    notes: list[str] = []
    metrics = strategy_metrics.metrics

    if strategy_metrics.strategy_name == summary.best_return.strategy_name:
        notes.append("This strategy had the highest measured total return in this comparison.")
    if summary.best_sharpe is not None and strategy_metrics.strategy_name == summary.best_sharpe.strategy_name:
        notes.append("This strategy had the highest measured Sharpe ratio in this comparison.")
    if strategy_metrics.strategy_name == summary.lowest_drawdown.strategy_name:
        notes.append("This strategy had the lowest measured max drawdown in this comparison.")
    if summary.highest_win_rate is not None and strategy_metrics.strategy_name == summary.highest_win_rate.strategy_name:
        notes.append("This strategy had the highest measured win rate in this comparison.")
    if strategy_metrics.strategy_name == summary.most_trades.strategy_name:
        notes.append("This strategy had the most completed trades in this comparison.")
    if strategy_metrics.strategy_name == summary.least_trades.strategy_name:
        notes.append("This strategy had the fewest completed trades in this comparison.")
    if metrics.has_open_position:
        notes.append("This strategy still had an open position at the end of the dataset.")
    if metrics.total_trades == 0:
        notes.append("This strategy had no completed round-trip trades in this dataset.")

    if not notes:
        notes.append("No standout measured condition was identified for this strategy.")

    return notes
