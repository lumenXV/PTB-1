"""Asset primitives for QMR.CO's unified research foundation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetType(Enum):
    """Supported and future-facing asset categories."""

    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    INDEX = "index"
    FOREX = "forex"
    COMMODITY = "commodity"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Asset:
    """Provider-neutral asset description for research workflows."""

    symbol: str
    display_name: str
    asset_type: AssetType
    currency: str
    exchange: str
    provider_symbol: str
    research_only: bool = False

    def __post_init__(self) -> None:
        """Validate asset metadata without changing runtime behavior."""
        _require_text(self.symbol, "Asset symbol")
        _require_text(self.display_name, "Asset display name")
        _require_text(self.currency, "Asset currency")
        _require_text(self.exchange, "Asset exchange")
        _require_text(self.provider_symbol, "Asset provider symbol")
        if not isinstance(self.asset_type, AssetType):
            raise ValueError("Asset type must be an AssetType.")


def create_stock_asset(
    symbol: str,
    display_name: str,
    currency: str = "USD",
    exchange: str = "US",
    provider_symbol: str | None = None,
) -> Asset:
    """Create a stock asset for research representation."""
    return Asset(
        symbol=symbol.strip().upper(),
        display_name=display_name,
        asset_type=AssetType.STOCK,
        currency=currency,
        exchange=exchange,
        provider_symbol=(provider_symbol or symbol).strip().upper(),
    )


def create_etf_asset(
    symbol: str,
    display_name: str,
    currency: str = "USD",
    exchange: str = "US",
    provider_symbol: str | None = None,
) -> Asset:
    """Create an ETF asset for research representation."""
    return Asset(
        symbol=symbol.strip().upper(),
        display_name=display_name,
        asset_type=AssetType.ETF,
        currency=currency,
        exchange=exchange,
        provider_symbol=(provider_symbol or symbol).strip().upper(),
    )


def create_crypto_asset(
    symbol: str,
    display_name: str,
    currency: str = "USD",
    exchange: str = "research-only",
    provider_symbol: str | None = None,
) -> Asset:
    """Create a research-only crypto asset representation."""
    return Asset(
        symbol=symbol.strip().upper(),
        display_name=display_name,
        asset_type=AssetType.CRYPTO,
        currency=currency,
        exchange=exchange,
        provider_symbol=(provider_symbol or symbol).strip().upper(),
        research_only=True,
    )


def _require_text(value: str, label: str) -> None:
    """Require a non-empty string field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
