"""Central bank meeting schedules: the dates policy is decided (QLib `MeetingDatesFileFactory`).

    type               prefix  key        example
    MEETING_SCHEDULE   mtg     {bank_id}  mtg:CB.US

QLib keeps one schedule per currency in a tab-separated file; here a schedule is
one per central bank, seeded from dates/central_bank_meetings.yaml (written by
scripts/import_cb_meetings.py). Resolving "the next meeting" against a document
date is in `resolve.py`, as QLib keeps its `MeetingDateCalculator` apart from the data.
"""

from datetime import date
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from ..core import Entity, EntityType, Factory, SeedFactory, TypeEnum
from ..core.refs import CentralBankKey


class DateType(TypeEnum):
    """Identity types of the dates branch."""

    MEETING_SCHEDULE = 'meeting_schedule', EntityType.EVENT, 'mtg', '{bank_id}'


class Meeting(BaseModel):
    """A policy decision: the day it is announced and, where known and different, the day it takes effect."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    decided: date
    effective: date | None = None

    @model_validator(mode='before')
    @classmethod
    def _bare_date(cls, data: Any) -> Any:
        return {'decided': data} if isinstance(data, date) else data


class MeetingSchedule(Entity):
    """A central bank's policy decisions in date order, one per day: mtg:CB.US."""

    entity_type = DateType.MEETING_SCHEDULE

    bank_id: CentralBankKey
    meetings: tuple[Meeting, ...]

    @model_validator(mode='after')
    def _in_order(self) -> Self:
        days = [m.decided for m in self.meetings]
        if days != sorted(set(days)):
            raise ValueError(f'{self.bank_id}: meetings must be in date order, one per day')
        return self


class MeetingScheduleFactory(SeedFactory[MeetingSchedule]):
    """Schedules from a file keyed by bank: `CB.US: [2026-01-28, {decided: ..., effective: ...}, ...]`."""

    def __init__(self, path: Path) -> None:
        super().__init__(MeetingSchedule, path)

    def rows(self) -> list[dict[str, Any]]:
        """One row per bank: {'bank_id': 'CB.US', 'meetings': [...]}."""
        data = yaml.safe_load(self.path.read_text(encoding='utf-8')) or {}
        return [{'bank_id': bank, 'meetings': meetings} for bank, meetings in data.items()]


def factories(seeds: Path) -> list[Factory[Any]]:
    """Dates factories, seeds read from `seeds` (config/registries/dates)."""
    return [MeetingScheduleFactory(seeds / 'central_bank_meetings.yaml')]
