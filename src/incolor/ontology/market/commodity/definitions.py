"""Commodity underlyings: benchmarks."""

from pydantic import Field

from ...core.refs import CurrencyKey
from ..enums import CommodityType
from ..identity import Market, MarketType


class Commodity(Market):
    """A commodity benchmark priced in a currency (WTI, Brent, gold): cmdty:WTI."""

    entity_type = MarketType.COMMODITY

    key: str = Field(pattern=r'^[A-Z0-9_]+$')
    commodity_type: CommodityType
    currency_id: CurrencyKey | None = None
