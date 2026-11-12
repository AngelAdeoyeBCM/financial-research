"""Equity underlyings: indices."""

from pydantic import Field

from ..identity import Market, MarketType


class EquityIndex(Market):
    """An equity index, keyed by its Bloomberg ticker root: eqidx:SPX."""

    entity_type = MarketType.EQUITY_INDEX

    key: str = Field(pattern=r'^[A-Z0-9]+$')
