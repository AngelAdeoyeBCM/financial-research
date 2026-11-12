"""Organizations: central banks and bond issuers.

    Organization          ORGANIZATION      org:<slug>
    ├── CentralBank       CENTRAL_BANK      org:CB.US, org:CB.EZ, org:CB.DE       issues currencies
    └── Issuer            ISSUER            (abstract)                            obligor of bond programmes
        ├── SovereignIssuer   SOVEREIGN_ISSUER  org:us_treasury, org:de_finanzagentur, org:uk_dmo
        ├── SubSovereign      SUBSOVEREIGN      org:nrw, org:ontario
        ├── Agency            AGENCY            org:kfw, org:cades
        └── Supranational     SUPRANATIONAL     org:eib, org:esm, org:european_commission

Links point from the dependent side: a currency names its central bank
(`Currency.central_bank_id`), a bond programme its issuer (`BondProgramme.obligor_id`),
a national central bank its system (`CentralBank.system_id`: Bundesbank -> ECB).
Every issuer but a supranational has a home country, so "sovereign", the
country of a curve and its QLib bond convention are derived, never stated.

A sovereign issuer is the body that issues the debt: the debt office where
there is one (UK DMO, Finanzagentur, AFT), else the treasury or finance
ministry (US Treasury, Japan MoF). One per country.
"""

from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from .core import EntityType, Factory, SeedFactory, TypeEnum
from .core.definition import Entity
from .core.refs import CentralBankKey, CountryKey, JurisdictionId, PolicyRateKey

_SLUG = r'^[a-z][a-z0-9_]*$'


class OrganizationType(TypeEnum):
    """Subtypes of ORGANIZATION. All share the org prefix."""

    CENTRAL_BANK = 'central_bank', EntityType.ORGANIZATION
    ISSUER = 'issuer', EntityType.ORGANIZATION
    SOVEREIGN_ISSUER = 'sovereign_issuer', ISSUER
    SUBSOVEREIGN = 'subsovereign', ISSUER
    AGENCY = 'agency', ISSUER
    SUPRANATIONAL = 'supranational', ISSUER


class Organization(Entity):
    """Central banks, issuers; later statistics agencies, regulators, banks."""

    entity_type = EntityType.ORGANIZATION

    key: str = Field(pattern=_SLUG)


class InflationMeasure(StrEnum):
    """The price index an inflation target is set on."""

    CPI = 'cpi'
    CPIF = 'cpif'  # Riksbank: CPI at fixed interest rates
    HICP = 'hicp'
    PCE = 'pce'


class CentralBank(Organization):
    """Issues a currency and sets its policy rates (Fed, ECB, BoE).

    The key is CB.<ISO 3166 alpha-2> of its jurisdiction: CB.US, CB.DE; the ECB is CB.EZ, ISO's code reserved for
    the eurozone. QLib's CentralBankCode (FED, SRB) is in `external/qlib.py`. `name` is the official name (Federal
    Reserve System), `short_name` the one markets use (Fed). `jurisdiction_id` is the country or group the bank's
    policy covers (cntry:US, geo:euro_area); a country's code is the key's. `system_id` is the system a national
    bank belongs to (Bundesbank -> ECB).

    `policy_rate_id` is the headline rate (Fed funds target, ECB DFR, Bank Rate); the bank's other administered
    rates (IORB, ON RRP, MRO) are the other policy rates of its currency. The mandate is the inflation target:
    a point (`inflation_target`), a band around or instead of it (`inflation_band`), on `inflation_measure`.
    Its meetings are a separate schedule, mtg:<KEY> (`dates.MeetingSchedule`).
    """

    entity_type = OrganizationType.CENTRAL_BANK

    key: str = Field(pattern=r'^CB\.[A-Z]{2}$')
    short_name: str
    jurisdiction_id: JurisdictionId
    system_id: CentralBankKey | None = None
    policy_rate_id: PolicyRateKey | None = None
    inflation_target: float | None = None
    inflation_band: tuple[float, float] | None = None
    inflation_measure: InflationMeasure | None = None

    @model_validator(mode='after')
    def _consistent(self) -> Self:
        country = self.jurisdiction_id.removeprefix('cntry:')
        if country != self.jurisdiction_id and self.key != f'CB.{country}':
            raise ValueError(f'{self.key}: a bank of {self.jurisdiction_id} is keyed CB.{country}')
        has_target = self.inflation_target is not None or self.inflation_band is not None
        if has_target != (self.inflation_measure is not None):
            raise ValueError(f'{self.key}: an inflation target needs its measure, and a measure a target')
        if self.inflation_band and not self.inflation_band[0] < self.inflation_band[1]:
            raise ValueError(f'{self.key}: inflation_band must be (low, high)')
        return self


class Issuer(Organization):
    """Abstract: the obligor of bond programmes. Each kind but a supranational has a home `country_id`."""

    entity_type = OrganizationType.ISSUER


class SovereignIssuer(Issuer):
    """A country's issuing body: debt office or treasury (UK DMO, US Treasury)."""

    entity_type = OrganizationType.SOVEREIGN_ISSUER

    country_id: CountryKey


class SubSovereign(Issuer):
    """A state, province or region (German Länder, Canadian provinces)."""

    entity_type = OrganizationType.SUBSOVEREIGN

    country_id: CountryKey


class Agency(Issuer):
    """A government-owned or -guaranteed issuer (KfW, CADES, BNG)."""

    entity_type = OrganizationType.AGENCY

    country_id: CountryKey


class Supranational(Issuer):
    """Owned by several states; no home country (EIB, ESM, World Bank, the EU via the European Commission)."""

    entity_type = OrganizationType.SUPRANATIONAL


def factories(seeds: Path) -> list[Factory[Any]]:
    """Organization factories, seeds read from `seeds`."""
    return [
        SeedFactory(CentralBank, seeds / 'central_banks.yaml'),
        SeedFactory(SovereignIssuer, seeds / 'sovereign_issuers.yaml'),
        SeedFactory(SubSovereign, seeds / 'subsovereigns.yaml'),
        SeedFactory(Agency, seeds / 'agencies.yaml'),
        SeedFactory(Supranational, seeds / 'supranationals.yaml'),
    ]
