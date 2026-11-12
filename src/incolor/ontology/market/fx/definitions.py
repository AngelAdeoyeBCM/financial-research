"""FX underlyings: currencies and currency pairs."""

from typing import Self

from pydantic import Field, model_validator

from ...core.refs import CentralBankKey, CurrencyKey, RateIndexKey
from ..identity import Market, MarketType


class Currency(Market):
    """A currency, keyed by its ISO 4217 code (JPY).

    `central_bank_id` is the issuing central bank (CB.US; QLib CentralBankCode). A currency has many rate
    indices; `default_ois_id` is the one "<CCY> OIS" means and `default_ibor_id` the one "<CCY> IBOR swaps"
    means (QLib DefaultOisRateIndex, DefaultIborRateIndex). `non_deliverable` currencies trade forwards as NDFs.
    `onshore_id` links an offshore currency to its onshore one (CNH -> CNY); `anchor_id` names the currency it is
    pegged to or follows (HKD -> USD, DKK -> EUR).
    """

    entity_type = MarketType.CURRENCY

    key: str = Field(pattern=r'^[A-Z]{3}$')
    central_bank_id: CentralBankKey | None = None
    default_ois_id: RateIndexKey | None = None
    default_ibor_id: RateIndexKey | None = None
    non_deliverable: bool = False
    onshore_id: CurrencyKey | None = None
    anchor_id: CurrencyKey | None = None

    @property
    def default_swap_id(self) -> str | None:
        """The index a bare "<CCY> swap" means: the IBOR default where there is one (EUR: Euribor), else OIS (USD)."""
        return self.default_ibor_id or self.default_ois_id


class FXPair(Market):
    """Two currencies in market-convention order (EURUSD, USDJPY); the key is derived: fx:EURUSD."""

    entity_type = MarketType.FX_PAIR

    base_id: CurrencyKey
    quote_id: CurrencyKey

    @model_validator(mode='after')
    def _distinct(self) -> Self:
        if self.base_id == self.quote_id:
            raise ValueError(f'{self.base_id}: base and quote must differ')
        return self
