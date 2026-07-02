"""Market data provider interfaces for PTB-1."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ptb1.historian import PriceBar, load_price_history


class MarketDataProvider(Protocol):
    """Interface for loading historical market data."""

    name: str

    def load(self, path: Path) -> list[PriceBar]:
        """Load historical price bars from a provider-specific source."""
        ...


class CSVProvider:
    """Load historical price bars from local CSV files."""

    name = "csv"

    def load(self, path: Path) -> list[PriceBar]:
        """Load CSV historical price bars through Historian validation."""
        return load_price_history(path)
