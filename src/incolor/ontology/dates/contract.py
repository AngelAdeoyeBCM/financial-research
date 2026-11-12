"""Contract months: an absolute futures delivery month (QLib `YearMonth`, `DeliveryMonth`).

Written '2025-12'. Mention forms with a short year ('Z5', 'Dec-25') need the
document date to resolve: see `resolve.parse_contract`.
"""

import calendar
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MONTH_CODES = 'FGHJKMNQUVXZ'
"""Futures month codes, January to December."""

QUARTERLY = (3, 6, 9, 12)
"""IMM months: H, M, U, Z."""


class ContractMonth(BaseModel):
    """A delivery month: ContractMonth(year=2025, month=12) is Z25, written '2025-12'."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    year: int = Field(ge=1900, le=2200)
    month: int = Field(ge=1, le=12)

    @model_validator(mode='before')
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if isinstance(data, str) and (match := re.fullmatch(r'(\d{4})-(\d{2})', data.strip())):
            return {'year': int(match[1]), 'month': int(match[2])}
        return data

    @property
    def code(self) -> str:
        """Month code and two-digit year: Z25."""
        return f'{MONTH_CODES[self.month - 1]}{self.year % 100:02d}'

    @property
    def imm_date(self) -> date:
        """Third Wednesday of the month."""
        first_wednesday = 1 + (calendar.WEDNESDAY - date(self.year, self.month, 1).weekday()) % 7
        return date(self.year, self.month, first_wednesday + 14)

    def __str__(self) -> str:
        return f'{self.year}-{self.month:02d}'
