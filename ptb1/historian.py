"""Historian: load historical market data for research."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")


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
        _validate_columns(path, reader.fieldnames)
        for row in reader:
            bars.append(create_price_bar(row, str(path), reader.line_num))

    if not bars:
        raise ValueError(f"No historical rows found in {path}.")

    return bars


def _validate_columns(path: Path, fieldnames: list[str] | None) -> None:
    """Validate that the CSV contains the required price history columns."""
    if not fieldnames:
        raise ValueError(f"No CSV header found in {path}.")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Missing required column(s) in {path}: {missing}.")


def create_price_bar(row: Mapping[str, object], source: str, line_number: int) -> PriceBar:
    """Parse and validate one historical data row into a price bar."""
    for column in REQUIRED_COLUMNS:
        if column not in row:
            raise ValueError(f"Missing required column(s) in {source}: {column}.")
        if row[column] in ("", None):
            raise ValueError(f"Missing value for '{column}' in {source} on line {line_number}.")

    try:
        bar_date = date.fromisoformat(str(row["date"]))
    except ValueError as exc:
        raise ValueError(f"Invalid date in {source} on line {line_number}: {row['date']}.") from exc

    try:
        open_price = float(str(row["open"]))
        high_price = float(str(row["high"]))
        low_price = float(str(row["low"]))
        close_price = float(str(row["close"]))
        volume = int(str(row["volume"]))
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value in {source} on line {line_number}.") from exc

    return PriceBar(
        symbol=str(row["symbol"]),
        date=bar_date,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
