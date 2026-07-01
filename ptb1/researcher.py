"""Researcher: define strategy interfaces and research signals."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from ptb1.historian import PriceBar


class Signal(Enum):
    """A strategy decision for the current price history."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class Strategy(Protocol):
    """Interface every research strategy must implement."""

    name: str

    def generate_signal(self, history: list[PriceBar], position_size: int) -> Signal:
        """Return a signal using only price history available so far."""
        ...
