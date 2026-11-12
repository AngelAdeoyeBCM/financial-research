"""Typed references: how one entity names another.

A reference field stores the target's bare key and declares the target type
by its code, so `currency_id: CurrencyKey` holds 'USD' and means `ccy:USD`:

    CurrencyKey = Annotated[str, Field(pattern=...), Ref('currency')]

Every alias lives here and this module imports nothing from the ontology, so
any branch can reference any other without import cycles. A reference that
may point at several types stores the full id (`EntityId`).
"""

from dataclasses import dataclass
from typing import Annotated

from pydantic import Field


@dataclass(frozen=True)
class Ref:
    """Marks a field as a reference to the entity type with this code."""

    type_code: str


_SLUG = r'^[a-z][a-z0-9_]*$'

EntityId = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]*:\S+$')]
"""A full `prefix:key` id, for references that may point at more than one type."""

JurisdictionId = Annotated[str, Field(pattern=r'^(cntry:[A-Z]{2}|geo:[a-z][a-z0-9_]*)$')]
"""Where an authority's writ runs: a country (cntry:US) or a group of countries (geo:euro_area)."""

# geography
CountryKey = Annotated[str, Field(pattern=r'^[A-Z]{2}$'), Ref('country')]
RegionKey = Annotated[str, Field(pattern=_SLUG), Ref('region')]

# organization
OrgKey = Annotated[str, Field(pattern=_SLUG), Ref('org')]
CentralBankKey = Annotated[str, Field(pattern=r'^CB\.[A-Z]{2}$'), Ref('central_bank')]  # CB.<ISO alpha-2>: CB.US
IssuerKey = Annotated[str, Field(pattern=_SLUG), Ref('issuer')]

# market
CurrencyKey = Annotated[str, Field(pattern=r'^[A-Z]{3}$'), Ref('currency')]
FXPairKey = Annotated[str, Field(pattern=r'^[A-Z]{6}$'), Ref('fx_pair')]
RateIndexKey = Annotated[str, Field(pattern=r'^[A-Z]{3}\.[A-Z0-9_]+$'), Ref('rate_index')]
PolicyRateKey = Annotated[str, Field(pattern=r'^[A-Z]{3}\.[A-Z0-9_]+$'), Ref('policy_rate')]
BondProgrammeKey = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]*\.[A-Z]{3}\.[a-z]+(\.[a-z0-9]+)?$'),
                             Ref('bond_programme')]
BondSegmentKey = Annotated[str, Field(pattern=r'^[A-Z]{3}\.[a-z]+(\.[a-z]+)?$'), Ref('bond_segment')]
