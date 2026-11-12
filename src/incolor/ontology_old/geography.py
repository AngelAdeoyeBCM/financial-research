"""Geographies. Hierarchy is expressed with MEMBER_OF (Brazil -> LatAm -> EM)."""

from dataclasses import dataclass
from enum import StrEnum

from .base import Entity
from .vocab import Category


class GeoLevel(StrEnum):
    COUNTRY = 'country'
    REGION = 'region'                    # LatAm, CEE, Asia ex-Japan
    BLOC = 'bloc'                        # Eurozone, ASEAN
    MARKET_GROUPING = 'market_grouping'  # DM, EM, G10, frontier


@dataclass(frozen=True, kw_only=True)
class Geography(Entity):
    category = Category.GEOGRAPHY
    entity_kind = Category.GEOGRAPHY

    level: GeoLevel
    code: str | None = None  # ISO 3166-1 alpha-2 (countries, plus EU); QLib's CountryCode

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.level,)

    @property
    def surface_forms(self) -> tuple[str, ...]:
        return super().surface_forms + ((self.code,) if self.code else ())
