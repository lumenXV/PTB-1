"""Market data provider interfaces for QMR.CO."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from ptb1.historian import PriceBar, create_price_bar, load_price_history

SourceT = TypeVar("SourceT")


@dataclass(frozen=True)
class MarketDataRequest:
    """Request for recent market data from an internal provider."""

    symbol: str
    period: str
    interval: str


@dataclass(frozen=True)
class MarketQuote:
    """Read-only live market quote derived from provider price bars."""

    symbol: str
    last_price: float
    daily_change: float
    daily_percent_change: float
    last_updated: str


class MarketDataProvider(Protocol, Generic[SourceT]):
    """Interface for loading historical market data."""

    name: str

    def load(self, source: SourceT) -> list[PriceBar]:
        """Load historical price bars from a provider-specific source."""
        ...


class CSVProvider:
    """Load historical price bars from local CSV files."""

    name = "csv"

    def load(self, path: Path) -> list[PriceBar]:
        """Load CSV historical price bars through Historian validation."""
        return load_price_history(path)


HTTPFetcher = Callable[[MarketDataRequest], dict[str, Any]]


class HTTPMarketProvider:
    """Load recent market data through an internal HTTP data source."""

    name = "http"

    def __init__(self, fetcher: HTTPFetcher | None = None) -> None:
        """Create an HTTP market provider with an injectable fetcher."""
        self.fetcher = fetcher or _fetch_chart_response

    def load(self, request: MarketDataRequest) -> list[PriceBar]:
        """Load recent market data and return validated price bars."""
        _validate_request(request)
        response = self._fetch(request)
        rows = _chart_response_to_rows(response=response, symbol=request.symbol)
        if not rows:
            raise ValueError(f"Empty market data response for {request.symbol}.")

        return [
            create_price_bar(row=row, source=f"{self.name} market data for {request.symbol}", line_number=index)
            for index, row in enumerate(rows, start=1)
        ]

    def quote(self, request: MarketDataRequest) -> MarketQuote:
        """Return a read-only market quote from recent price bars."""
        bars = self.load(request)
        if not bars:
            raise ValueError(f"Empty market data response for {request.symbol}.")

        latest_bar = bars[-1]
        previous_close = bars[-2].close if len(bars) > 1 else latest_bar.close
        daily_change = latest_bar.close - previous_close
        daily_percent_change = (daily_change / previous_close) * 100 if previous_close else 0.0
        return MarketQuote(
            symbol=latest_bar.symbol,
            last_price=latest_bar.close,
            daily_change=daily_change,
            daily_percent_change=daily_percent_change,
            last_updated=datetime.now().strftime("%H:%M:%S"),
        )

    def connection_status(self) -> str:
        """Return display-only provider readiness."""
        return "Connected"

    def _fetch(self, request: MarketDataRequest) -> dict[str, Any]:
        """Fetch provider data and normalize fetch failures."""
        try:
            return self.fetcher(request)
        except TimeoutError as exc:
            raise ValueError(f"Timed out loading market data for {request.symbol}.") from exc
        except OSError as exc:
            raise ValueError(f"Network failure loading market data for {request.symbol}.") from exc


def _validate_request(request: MarketDataRequest) -> None:
    """Validate an internal market data request."""
    if not request.symbol.strip():
        raise ValueError("Market data symbol is required.")
    if not request.period.strip():
        raise ValueError("Market data period is required.")
    if not request.interval.strip():
        raise ValueError("Market data interval is required.")


def _fetch_chart_response(request: MarketDataRequest) -> dict[str, Any]:
    """Fetch chart data from the current internal HTTP source."""
    params = urlencode({"range": request.period, "interval": request.interval})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{request.symbol}?{params}"
    try:
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"Invalid market data symbol: {request.symbol}.") from exc
        raise ValueError(f"Market data provider returned HTTP {exc.code} for {request.symbol}.") from exc
    except socket.timeout as exc:
        raise TimeoutError from exc
    except URLError as exc:
        raise OSError from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed market data response for {request.symbol}.") from exc


def _chart_response_to_rows(response: dict[str, Any], symbol: str) -> list[dict[str, object]]:
    """Convert a chart-style provider response into Historian-compatible rows."""
    try:
        chart = response["chart"]
        if chart.get("error") is not None:
            raise ValueError(f"Invalid market data symbol: {symbol}.")
        result = chart["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Malformed market data response for {symbol}.") from exc

    _validate_quote_fields(quote, symbol)
    if not timestamps:
        raise ValueError(f"Empty market data response for {symbol}.")
    _validate_quote_lengths(quote, len(timestamps), symbol)

    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        rows.append(
            {
                "symbol": symbol.upper(),
                "date": _timestamp_to_date(timestamp, symbol),
                "open": quote["open"][index],
                "high": quote["high"][index],
                "low": quote["low"][index],
                "close": quote["close"][index],
                "volume": quote["volume"][index],
            }
        )
    return rows


def _validate_quote_fields(quote: dict[str, Any], symbol: str) -> None:
    """Validate the provider response has OHLCV fields."""
    required_fields = ("open", "high", "low", "close", "volume")
    missing_fields = [field for field in required_fields if field not in quote]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"Missing OHLCV field(s) for {symbol}: {missing}.")


def _validate_quote_lengths(quote: dict[str, Any], expected_length: int, symbol: str) -> None:
    """Validate OHLCV arrays match the timestamp count."""
    for field in ("open", "high", "low", "close", "volume"):
        values = quote[field]
        if not isinstance(values, list) or len(values) != expected_length:
            raise ValueError(f"Malformed market data response for {symbol}.")


def _timestamp_to_date(timestamp: object, symbol: str) -> str:
    """Convert a provider timestamp into an ISO date string."""
    try:
        return datetime.fromtimestamp(int(str(timestamp)), tz=timezone.utc).date().isoformat()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Malformed market data timestamp for {symbol}: {timestamp}.") from exc
