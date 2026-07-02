"""Built-in research strategies for LumenX Research."""

from __future__ import annotations

from ptb1.historian import PriceBar
from ptb1.learning import StrategyEducation
from ptb1.researcher import Signal, Strategy


class BuyAndHoldStrategy:
    """Buy once, then hold."""

    name = "Buy and Hold"
    education = StrategyEducation(
        description="Buys at the first available bar and holds the position.",
        purpose="Provides a simple baseline for comparing active strategies.",
        strengths=["Easy to understand.", "Useful as a benchmark."],
        weaknesses=["Can sit through large drawdowns.", "Does not react to changing conditions."],
        best_market_conditions="Long upward trends.",
        worst_market_conditions="Long downward trends or severe drawdowns.",
        typical_holding_period="Entire dataset after entry.",
        risk_level="Medium",
        common_mistakes=["Treating it as risk-free because it is simple.", "Ignoring drawdown."],
    )

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Buy on the first available bar when no position exists."""
        if position_size == 0:
            return Signal.BUY
        return Signal.HOLD


class SimpleMovingAverageCrossStrategy:
    """Trade when a short moving average crosses a long moving average."""

    name = "SMA Cross"
    education = StrategyEducation(
        description="Compares a short simple moving average with a longer simple moving average.",
        purpose="Attempts to identify changes in trend direction.",
        strengths=["Simple trend-following structure.", "Signals are easy to audit."],
        weaknesses=["Can react late.", "Can whipsaw in sideways markets."],
        best_market_conditions="Markets with sustained directional trends.",
        worst_market_conditions="Choppy or range-bound markets.",
        typical_holding_period="Multiple bars after a trend signal.",
        risk_level="Medium",
        common_mistakes=["Assuming every crossover starts a durable trend.", "Ignoring whipsaw risk."],
    )

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        """Create the strategy with short and long moving average windows."""
        self.short_window = short_window
        self.long_window = long_window

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Buy on bullish crosses and sell on bearish crosses."""
        if len(history) < self.long_window + 1:
            return Signal.HOLD

        previous_history = history[:-1]
        previous_short = _simple_moving_average(previous_history, self.short_window)
        previous_long = _simple_moving_average(previous_history, self.long_window)
        current_short = _simple_moving_average(history, self.short_window)
        current_long = _simple_moving_average(history, self.long_window)

        if previous_short <= previous_long and current_short > current_long:
            return Signal.BUY
        if position_size > 0 and previous_short >= previous_long and current_short < current_long:
            return Signal.SELL
        return Signal.HOLD


class RsiStrategy:
    """Trade simple RSI overbought and oversold conditions."""

    name = "RSI"
    education = StrategyEducation(
        description="Uses Relative Strength Index to compare recent gains and losses.",
        purpose="Attempts to identify oversold and overbought markets.",
        strengths=["Good at describing stretched conditions.", "Can find potential reversals in sideways markets."],
        weaknesses=["Can repeatedly signal buy during strong downtrends.", "Can remain overbought during strong uptrends."],
        best_market_conditions="Range-bound markets with repeated reversals.",
        worst_market_conditions="Strong one-directional trends.",
        typical_holding_period="Short to medium, depending on reversal timing.",
        risk_level="Medium",
        common_mistakes=["Buying every oversold reading without risk control.", "Treating RSI as a prediction."],
    )

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        """Create the strategy with RSI thresholds."""
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Buy when RSI is oversold and sell when it is overbought."""
        rsi = _relative_strength_index(history, self.period)
        if rsi is None:
            return Signal.HOLD
        if rsi < self.oversold:
            return Signal.BUY
        if position_size > 0 and rsi > self.overbought:
            return Signal.SELL
        return Signal.HOLD


class MacdStrategy:
    """Trade MACD line crosses against its signal line."""

    name = "MACD"
    education = StrategyEducation(
        description="Uses the relationship between fast and slow exponential moving averages.",
        purpose="Attempts to identify momentum shifts in trend behavior.",
        strengths=["Combines trend and momentum information.", "Useful for detecting momentum changes."],
        weaknesses=["Can lag major turning points.", "Can generate false signals in sideways markets."],
        best_market_conditions="Markets with sustained momentum shifts.",
        worst_market_conditions="Flat or noisy markets with frequent reversals.",
        typical_holding_period="Medium, depending on signal line crossovers.",
        risk_level="Medium",
        common_mistakes=["Assuming every MACD cross has follow-through.", "Ignoring sideways-market noise."],
    )

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> None:
        """Create the strategy with MACD periods."""
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Buy on bullish MACD crosses and sell on bearish crosses."""
        macd_values = _macd_values(history, self.fast_period, self.slow_period)
        if len(macd_values) < self.signal_period + 1:
            return Signal.HOLD

        signal_values = _ema(macd_values, self.signal_period)
        previous_macd = macd_values[-2]
        current_macd = macd_values[-1]
        previous_signal = signal_values[-2]
        current_signal = signal_values[-1]

        if previous_macd <= previous_signal and current_macd > current_signal:
            return Signal.BUY
        if position_size > 0 and previous_macd >= previous_signal and current_macd < current_signal:
            return Signal.SELL
        return Signal.HOLD


def get_available_strategies() -> list[Strategy]:
    """Return all built-in strategies available for Milestone 2."""
    return [
        BuyAndHoldStrategy(),
        SimpleMovingAverageCrossStrategy(),
        RsiStrategy(),
        MacdStrategy(),
    ]


def _simple_moving_average(history: list[PriceBar], window: int) -> float:
    """Calculate a simple moving average from the latest closing prices."""
    closes = [bar.close for bar in history[-window:]]
    return sum(closes) / len(closes)


def _relative_strength_index(history: list[PriceBar], period: int) -> float | None:
    """Calculate RSI for the latest close, if enough history exists."""
    if len(history) < period + 1:
        return None

    recent = history[-(period + 1) :]
    gains = 0.0
    losses = 0.0

    for previous, current in zip(recent, recent[1:]):
        change = current.close - previous.close
        if change > 0:
            gains += change
        else:
            losses += abs(change)

    average_gain = gains / period
    average_loss = losses / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _macd_values(history: list[PriceBar], fast_period: int, slow_period: int) -> list[float]:
    """Calculate MACD values for the available closing prices."""
    closes = [bar.close for bar in history]
    if len(closes) < slow_period:
        return []

    fast_values = _ema(closes, fast_period)
    slow_values = _ema(closes, slow_period)
    return [fast - slow for fast, slow in zip(fast_values, slow_values)]


def _ema(values: list[float], period: int) -> list[float]:
    """Calculate an exponential moving average for a list of values."""
    if not values:
        return []

    multiplier = 2 / (period + 1)
    ema_values = [values[0]]

    for value in values[1:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])

    return ema_values
