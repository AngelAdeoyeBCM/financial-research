"""People: officials, analysts and other named individuals."""

from dataclasses import dataclass
from enum import StrEnum

from .base import Entity
from .vocab import Category


class PersonKind(StrEnum):
    CENTRAL_BANK_OFFICIAL = 'central_bank_official'
    PUBLIC_OFFICIAL = 'public_official'  # politicians, ministers, multilateral heads
    ANALYST = 'analyst'
    ECONOMIST = 'economist'
    STRATEGIST = 'strategist'
    QUANT = 'quant'
    RESEARCHER = 'researcher'
    OTHER = 'other'


@dataclass(frozen=True, kw_only=True)
class Person(Entity):
    category = Category.PERSON
    entity_kind = Category.PERSON

    kind: PersonKind = PersonKind.OTHER

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.kind,)
