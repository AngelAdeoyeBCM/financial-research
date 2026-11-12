"""Organisations: central banks, governments, banks, agencies."""

from dataclasses import dataclass
from enum import StrEnum

from .base import Entity, WikidataMap, ref
from .vocab import Category


class OrgKind(StrEnum):
    CENTRAL_BANK = 'central_bank'
    GOVERNMENT = 'government'  # executives, ministries, treasuries, debt offices, fiscal councils
    POLITICAL_PARTY = 'political_party'
    STATISTICS_AGENCY = 'statistics_agency'
    MULTILATERAL = 'multilateral'  # IMF, BIS, EU institutions
    REGULATOR = 'regulator'
    RATING_AGENCY = 'rating_agency'
    INDEX_PROVIDER = 'index_provider'
    MARKET_PARTICIPANT = 'market_participant'  # banks, funds, companies, exchanges


@dataclass(frozen=True, kw_only=True)
class Organization(Entity):
    category = Category.ORGANIZATION
    entity_kind = Category.ORGANIZATION

    kinds: frozenset[OrgKind]
    # Jurisdiction, not headquarters (ECB: euro area, not Germany); none for global bodies.
    geography_id: str | None = ref(
        Category.GEOGRAPHY, required=False,
        wikidata=WikidataMap('P1001', tie_break='P38/P1001'),
    )

    def _validate(self) -> None:
        if not self.kinds:
            raise ValueError(f'{self.entity_id}: needs at least one kind')

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + tuple(sorted(self.kinds))
