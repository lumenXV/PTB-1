"""Researcher: define strategy interfaces and research strategies."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from ptb1.historian import PriceBar


class Signal(Enum):
    """A strategy decision for a single bar."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class Strategy(Protocol):
    """Interface every research strategy must implement."""

    name: str

    def generate_signal(self, current_bar: PriceBar, position_size: int) -> Signal:
        """Return the strategy signal for the current price bar."""
        ...


class BuyAndHoldStrategy:
    """A tiny first strategy: buy once, then hold."""

    name = "Buy and Hold"

    def generate_signal(self, current_bar: PriceBar, position_size: int) -> Signal:
        """Buy on the first available bar when no position exists."""
        if position_size == 0:
            return Signal.BUY
        return Signal.HOLD
