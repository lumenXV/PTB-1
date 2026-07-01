"""Risk Manager: approve position changes for research backtests."""

from __future__ import annotations

from ptb1.researcher import Signal


class RiskManager:
    """Apply simple research-only position rules."""

    def approve(self, signal: Signal, cash: float, price: float, position_size: int) -> bool:
        """Return whether a signal is allowed for the current account state."""
        if signal is Signal.BUY:
            return cash >= price and position_size == 0
        if signal is Signal.SELL:
            return position_size > 0
        return True
