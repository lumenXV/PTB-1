"""Historian: load historical market data for research."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
            bars.append(_parse_price_bar(path, reader.line_num, row))

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


def _parse_price_bar(path: Path, line_number: int, row: dict[str, str]) -> PriceBar:
    """Parse and validate one CSV row into a price bar."""
    for column in REQUIRED_COLUMNS:
        if row[column] == "":
            raise ValueError(f"Missing value for '{column}' in {path} on line {line_number}.")

    try:
        bar_date = date.fromisoformat(row["date"])
    except ValueError as exc:
        raise ValueError(f"Invalid date in {path} on line {line_number}: {row['date']}.") from exc

    try:
        open_price = float(row["open"])
        high_price = float(row["high"])
        low_price = float(row["low"])
        close_price = float(row["close"])
        volume = int(row["volume"])
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value in {path} on line {line_number}.") from exc

    return PriceBar(
        symbol=row["symbol"],
        date=bar_date,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
