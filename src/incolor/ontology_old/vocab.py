"""Shared vocabulary: enums used by more than one entity family."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Category(StrEnum):
    """Top-level entity categories. Each answers one question:
    who acts (organization, person), where (geography), what is priced
    (market), what is measured (measure, indicator), what an authority
    sets (policy), what happens (event)."""

    ORGANIZATION = 'organization'
    PERSON = 'person'
    GEOGRAPHY = 'geography'
    MARKET = 'market'
    MEASURE = 'measure'
    INDICATOR = 'indicator'
    POLICY = 'policy'
    EVENT = 'event'


class Relation(StrEnum):
    """Multi-valued or time-varying links. Single-valued, stable links
    (currency, geography, issuer) are `ref()` fields on the entity."""

    MEMBER_OF = 'member_of'
    PUBLISHED_BY = 'published_by'
    AFFILIATED_WITH = 'affiliated_with'
    HELD_BY = 'held_by'
    DERIVED_FROM = 'derived_from'


class RiskFactor(StrEnum):
    FX = 'fx'
    RATES = 'rates'
    CREDIT = 'credit'
    EQUITY = 'equity'
    COMMODITY = 'commodity'
    INFLATION = 'inflation'
    VOL = 'vol'
    BASIS = 'basis'


class Frequency(StrEnum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'
    ANNUAL = 'annual'
    SCHEDULED = 'scheduled'  # published calendar, not periodic (CB meetings)


_ORG = frozenset({Category.ORGANIZATION})

# Allowed target categories per relation (the "range" of the relation).
RELATION_RANGE: Mapping[Relation, frozenset[Category]] = MappingProxyType(
    {
        Relation.PUBLISHED_BY: _ORG,
        Relation.AFFILIATED_WITH: _ORG,
        Relation.HELD_BY: _ORG,
        Relation.MEMBER_OF: frozenset(
            {Category.GEOGRAPHY, Category.ORGANIZATION}
        ),
        Relation.DERIVED_FROM: frozenset(
            {Category.INDICATOR, Category.MARKET}
        ),
    }
)


def label_key(label: StrEnum) -> tuple[type, StrEnum]:
    """Type-aware key: StrEnum members from different enums can share a
    string value (AssetClass.FX == RiskFactor.FX), so never index by value."""
    return type(label), label
