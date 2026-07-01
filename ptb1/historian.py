"""Historian: load historical market data for research."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class PriceBar:
    """One daily historical price bar."""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


def load_price_history(path: Path) -> list[PriceBar]:
    """Load historical price bars from a CSV file."""
    bars: list[PriceBar] = []

    with path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            bars.append(
                PriceBar(
                    symbol=row["symbol"],
                    date=date.fromisoformat(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
            )

    if not bars:
        raise ValueError(f"No historical rows found in {path}.")

    return bars
