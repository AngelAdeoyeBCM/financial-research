"""Points: what pins an instance on its template. Values, never referenced on their own.

Each template type takes one kind of point:

    Tenor          10y, 2y2y                 IRS, cash bond, FX forward
    OptionPoint     2yx30y, 2yx30y.call       swaption
    ContractMonth   2025-12                   futures (deferred)
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from ...dates import ContractMonth, Tenor
from ..enums import CallPut


class OptionPoint(BaseModel):
    """Expiry into an underlying tenor, optionally a side: a 2y30y payer is expiry 2y, tenor 30y, call.

    Parses '2yx30y' and '2yx30y.call'.
    """

    model_config = ConfigDict(frozen=True, extra='forbid')

    expiry: Tenor
    tenor: Tenor
    call_put: CallPut | None = None

    @model_validator(mode='before')
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if not isinstance(data, str):
            return data
        terms, _, side = data.strip().lower().partition('.')
        expiry, _, tenor = terms.partition('x')
        return {'expiry': expiry, 'tenor': tenor, 'call_put': side or None}

    @model_validator(mode='after')
    def _spot_expiry(self) -> 'OptionPoint':
        if self.expiry.start is not None:
            raise ValueError('an option expiry is a plain tenor')
        return self

    def __str__(self) -> str:
        terms = f'{self.expiry}x{self.tenor}'
        return f'{terms}.{self.call_put.value}' if self.call_put else terms


Point = Tenor | OptionPoint | ContractMonth
PointType = type[Tenor] | type[OptionPoint] | type[ContractMonth]
