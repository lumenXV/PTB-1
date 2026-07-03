"""Market data provider interfaces for QMR.CO."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
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


class MarketDataStatus(Enum):
    """Repository-backed market data state."""

    OK = "OK"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"
    STALE = "STALE"
    MISSING = "MISSING"


@dataclass(frozen=True)
class MarketDataResult:
    """Provider-neutral market data result for live paper and watchlists."""

    symbol: str
    status: MarketDataStatus
    bars: list[PriceBar]
    quote: MarketQuote | None
    message: str
    provider_status: str
    cache_status: str
    last_successful_update: datetime | None
    next_retry_time: datetime | None = None


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
        except HTTPError as exc:
            if exc.code == 429:
                raise ValueError(f"Rate limited loading market data for {request.symbol}.") from exc
            raise ValueError(f"Market data provider returned HTTP {exc.code} for {request.symbol}.") from exc
        except TimeoutError as exc:
            raise ValueError(f"Timed out loading market data for {request.symbol}.") from exc
        except OSError as exc:
            raise ValueError(f"Network failure loading market data for {request.symbol}.") from exc


class MarketDataRepository:
    """In-memory market data cache and provider status store."""

    def __init__(self, freshness_seconds: int = 60, now: Callable[[], datetime] | None = None) -> None:
        """Create an in-memory repository with a freshness window."""
        self.freshness_seconds = freshness_seconds
        self.now = now or datetime.now
        self._results: dict[str, MarketDataResult] = {}
        self._next_retry_times: dict[str, datetime] = {}

    def get_cached_result(self, symbol: str) -> MarketDataResult:
        """Return cached data, marking it stale or missing when appropriate."""
        normalized_symbol = _normalize_symbol(symbol)
        result = self._results.get(normalized_symbol)
        if result is None:
            return MarketDataResult(
                symbol=normalized_symbol,
                status=MarketDataStatus.MISSING,
                bars=[],
                quote=None,
                message="No cached market data.",
                provider_status="MISSING",
                cache_status="MISSING",
                last_successful_update=None,
                next_retry_time=self._next_retry_times.get(normalized_symbol),
            )

        if result.status is MarketDataStatus.OK and not self.is_fresh(normalized_symbol):
            return MarketDataResult(
                symbol=result.symbol,
                status=MarketDataStatus.STALE,
                bars=result.bars,
                quote=result.quote,
                message="Cached market data is stale.",
                provider_status=result.provider_status,
                cache_status="STALE",
                last_successful_update=result.last_successful_update,
                next_retry_time=self._next_retry_times.get(normalized_symbol),
            )
        return result

    def store_success(self, symbol: str, bars: list[PriceBar], provider_status: str) -> MarketDataResult:
        """Store fresh validated bars and return an OK result."""
        normalized_symbol = _normalize_symbol(symbol)
        updated_at = self.now()
        quote = _quote_from_bars(bars, updated_at)
        result = MarketDataResult(
            symbol=normalized_symbol,
            status=MarketDataStatus.OK,
            bars=bars,
            quote=quote,
            message="Fresh market data.",
            provider_status=provider_status,
            cache_status="FRESH",
            last_successful_update=updated_at,
            next_retry_time=None,
        )
        self._results[normalized_symbol] = result
        self._next_retry_times.pop(normalized_symbol, None)
        return result

    def store_status(
        self,
        symbol: str,
        status: MarketDataStatus,
        message: str,
        provider_status: str,
        next_retry_time: datetime | None = None,
    ) -> MarketDataResult:
        """Store a non-OK provider status without inventing fresh data."""
        normalized_symbol = _normalize_symbol(symbol)
        cached = self.get_cached_result(normalized_symbol)
        if next_retry_time is not None:
            self._next_retry_times[normalized_symbol] = next_retry_time
        result = MarketDataResult(
            symbol=normalized_symbol,
            status=status,
            bars=cached.bars,
            quote=cached.quote,
            message=message,
            provider_status=provider_status,
            cache_status=cached.cache_status,
            last_successful_update=cached.last_successful_update,
            next_retry_time=next_retry_time or self._next_retry_times.get(normalized_symbol),
        )
        self._results[normalized_symbol] = result
        return result

    def is_fresh(self, symbol: str) -> bool:
        """Return whether cached data is inside the freshness window."""
        result = self._results.get(_normalize_symbol(symbol))
        if result is None or result.last_successful_update is None:
            return False
        return self.now() - result.last_successful_update <= timedelta(seconds=self.freshness_seconds)

    def is_cooling_down(self, symbol: str) -> bool:
        """Return whether a symbol is still inside a provider cooldown window."""
        next_retry = self._next_retry_times.get(_normalize_symbol(symbol))
        return next_retry is not None and self.now() < next_retry

    def next_retry_time(self, symbol: str) -> datetime | None:
        """Return the next retry time for a symbol, if one exists."""
        return self._next_retry_times.get(_normalize_symbol(symbol))


class ProviderManager:
    """Provider-neutral reliability layer for live market data."""

    def __init__(
        self,
        provider: HTTPMarketProvider | None = None,
        repository: MarketDataRepository | None = None,
        cooldown_seconds: int = 60,
    ) -> None:
        """Create a manager over the available market data provider."""
        self.provider = provider or HTTPMarketProvider()
        self.repository = repository or MarketDataRepository()
        self.cooldown_seconds = cooldown_seconds

    def get_market_data(self, request: MarketDataRequest) -> MarketDataResult:
        """Return fresh, cached, or paused market data for one symbol."""
        _validate_request(request)
        symbol = _normalize_symbol(request.symbol)
        cached = self.repository.get_cached_result(symbol)
        if cached.status is MarketDataStatus.OK and self.repository.is_fresh(symbol):
            return cached

        if self.repository.is_cooling_down(symbol):
            next_retry = self.repository.next_retry_time(symbol)
            return self.repository.store_status(
                symbol=symbol,
                status=MarketDataStatus.RATE_LIMITED,
                message="Provider is cooling down after a rate limit.",
                provider_status="RATE_LIMITED",
                next_retry_time=next_retry,
            )

        try:
            bars = self.provider.load(request)
        except ValueError as exc:
            message = str(exc)
            if "Rate limited" in message:
                next_retry = self.repository.now() + timedelta(seconds=self.cooldown_seconds)
                return self.repository.store_status(
                    symbol=symbol,
                    status=MarketDataStatus.RATE_LIMITED,
                    message=message,
                    provider_status="RATE_LIMITED",
                    next_retry_time=next_retry,
                )
            return self.repository.store_status(
                symbol=symbol,
                status=MarketDataStatus.ERROR,
                message=message,
                provider_status="ERROR",
            )

        if not bars:
            return self.repository.store_status(
                symbol=symbol,
                status=MarketDataStatus.MISSING,
                message="Provider returned no market data.",
                provider_status="MISSING",
            )

        return self.repository.store_success(symbol=symbol, bars=bars, provider_status=self.provider.connection_status())

    def cached_result(self, symbol: str) -> MarketDataResult:
        """Return repository state without calling a provider."""
        return self.repository.get_cached_result(symbol)

    def connection_status(self) -> str:
        """Return provider readiness for display."""
        return self.provider.connection_status()


def _validate_request(request: MarketDataRequest) -> None:
    """Validate an internal market data request."""
    if not request.symbol.strip():
        raise ValueError("Market data symbol is required.")
    if not request.period.strip():
        raise ValueError("Market data period is required.")
    if not request.interval.strip():
        raise ValueError("Market data interval is required.")


def _normalize_symbol(symbol: str) -> str:
    """Normalize a provider symbol."""
    return symbol.strip().upper()


def _quote_from_bars(bars: list[PriceBar], updated_at: datetime) -> MarketQuote | None:
    """Build a display quote from validated price bars."""
    if not bars:
        return None
    latest_bar = bars[-1]
    previous_close = bars[-2].close if len(bars) > 1 else latest_bar.close
    daily_change = latest_bar.close - previous_close
    daily_percent_change = (daily_change / previous_close) * 100 if previous_close else 0.0
    return MarketQuote(
        symbol=latest_bar.symbol,
        last_price=latest_bar.close,
        daily_change=daily_change,
        daily_percent_change=daily_percent_change,
        last_updated=updated_at.strftime("%H:%M:%S"),
    )


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
        if exc.code == 429:
            raise ValueError(f"Rate limited loading market data for {request.symbol}.") from exc
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
