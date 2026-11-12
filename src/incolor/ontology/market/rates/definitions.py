"""Rates underlyings: reference rate indices, and the policy rates central banks set."""

from typing import Any

from pydantic import Field, model_validator

from ...core.refs import CurrencyKey
from ...dates import Tenor
from ..enums import Corridor
from ..identity import Market, MarketType


class RateIndex(Market):
    """A reference rate in its currency, fixed from market trades: idx:USD.SOFR, idx:EUR.EURIBOR (QLib idx).

    `code` is unique within the currency. `is_ois` marks an overnight index (QLib IsOis), swapped as an OIS; else
    the index is a term fixing (Euribor, BBSW, CD91). `default_fixing` is the tenor a swap on the index fixes on
    when a mention gives none: 1d for an overnight index unless stated; a term index states its own, since term
    tenors vary (6m Euribor, 3m CD91, 28d TIIE).
    """

    entity_type = MarketType.RATE_INDEX

    currency_id: CurrencyKey
    code: str = Field(pattern=r'^[A-Z0-9_]+$')
    is_ois: bool
    default_fixing: Tenor

    @model_validator(mode='before')
    @classmethod
    def _overnight_fixes_daily(cls, data: Any) -> Any:
        is_ois = data.get('is_ois', cls.model_fields['is_ois'].default) if isinstance(data, dict) else None
        if is_ois is True and data.get('default_fixing') is None:
            return {**data, 'default_fixing': '1d'}
        return data


class PolicyRate(RateIndex):
    """A rate a central bank sets by decision: idx:USD.FDTR, idx:EUR.DFR, idx:GBP.BANKRATE.

    Overnight, as QLib has it (IsOis), but not swapped: swaps reference the market fixing that trades around it
    (SOFR, €STR, SONIA). Its bank is its currency's central bank; the bank's headline rate is
    `CentralBank.policy_rate_id`. `corridor` is the edge of the rate corridor it sets, if any (ECB DFR floor, MLF
    ceiling). `is_range` marks a target set as a range, not a point (Fed funds target, 3.75-4.00%).
    """

    entity_type = MarketType.POLICY_RATE

    is_ois: bool = True
    corridor: Corridor | None = None
    is_range: bool = False
