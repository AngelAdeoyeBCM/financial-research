"""Tenors: a count of periods, optionally forward-starting (QLib `DateInt`, `CombinedDateInt`).

    '10y'    Tenor(count=10, unit=YEARS)
    '2y2y'   Tenor(count=2, unit=YEARS, start=Tenor(2y))     2y forward, 2y long
    '120m'   -> 10y      whole years in months are written as years

A tenor is relative: a 10y swap in 2024 and in 2026 is the same market.
Only the grammar is kept from QLib; no calendars or date rolling.
"""

import re
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PeriodType(StrEnum):
    """Tenor units (QLib PeriodType D, W, M, A), written as research writes them."""

    DAYS = 'd'
    WEEKS = 'w'
    MONTHS = 'm'
    YEARS = 'y'


_PERIOD = r'(\d+)\s*([dwmy])'
_TENOR = re.compile(rf'(?:{_PERIOD})?\s*{_PERIOD}', re.IGNORECASE)


class Tenor(BaseModel):
    """A period ('10y'), optionally forward-starting ('2y2y'). Parses from text: Tenor.model_validate('6M')."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    count: int = Field(gt=0)
    unit: PeriodType
    start: 'Tenor | None' = None

    @model_validator(mode='before')
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if not isinstance(data, str):
            return data
        match = _TENOR.fullmatch(data.strip())
        if not match:
            raise ValueError(f'not a tenor: {data!r}')
        start_count, start_unit, count, unit = match.groups()
        fields: dict[str, Any] = {'count': int(count), 'unit': unit.lower()}
        if start_count:
            fields['start'] = {'count': int(start_count), 'unit': start_unit.lower()}
        return fields

    @model_validator(mode='after')
    def _canonical(self) -> Self:
        if self.unit is PeriodType.MONTHS and self.count % 12 == 0:
            object.__setattr__(self, 'count', self.count // 12)
            object.__setattr__(self, 'unit', PeriodType.YEARS)
        if self.start is not None and self.start.start is not None:
            raise ValueError('a forward start cannot itself be forward-starting')
        return self

    def __str__(self) -> str:
        length = f'{self.count}{self.unit.value}'
        return f'{self.start}{length}' if self.start else length
