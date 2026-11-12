"""Geographies: countries and the market region tree.

    Geography       GEOGRAPHY   geo:<key>
    ├── Country     COUNTRY     cntry:<ISO 3166-1 alpha-2>
    └── Region      REGION      geo:<slug>   market region tree   (regions.yaml)

Country keys and region members must be official ISO 3166-1 alpha-2 codes
(`Country.iso_alpha2`, checked with pycountry). Regions form one tree; each
country sits in exactly one leaf (`members`), and a region contains its own
members and every child's:

    world ─► apac ─► east_asia   members: [CN, HK, JP, KR, TW]

YAML: quote 'NO' (Norway); unquoted it loads as False and fails validation.
"""

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pycountry
import yaml
from pydantic import Field, ValidationInfo, field_validator

from .core import Entity, EntityType, TypeEnum
from .core.refs import CountryKey, CurrencyKey, RegionKey

_SLUG = r'^[a-z][a-z0-9_]*$'
_ALPHA2 = r'^[A-Z]{2}$'


class GeographyType(TypeEnum):
    """Subtypes of GEOGRAPHY."""

    COUNTRY = 'country', EntityType.GEOGRAPHY, 'cntry'  # QLib IdentityTypes.Country
    REGION = 'region', EntityType.GEOGRAPHY


class Geography(Entity):
    """Countries and regions."""

    entity_type = EntityType.GEOGRAPHY


class Region(Geography):
    """A node of the market region tree. `members` are the countries placed directly in it."""

    entity_type = GeographyType.REGION

    key: str = Field(pattern=_SLUG)
    parent_id: RegionKey | None = None
    members: tuple[CountryKey, ...] = ()

    @field_validator('members')
    @classmethod
    def _iso_members(cls, members: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(Country.iso_alpha2(code) for code in members)

    def lineage(self, regions: Mapping[str, 'Region']) -> tuple['Region', ...]:
        """This region, then each parent: east_asia -> (East Asia, Asia Pacific, World).

        KeyError for an unknown parent, ValueError for a cycle.
        """
        path: list[Region] = [self]
        while (parent_id := path[-1].parent_id) is not None:
            if any(r.key == parent_id for r in path):
                raise ValueError(f'region cycle: {" -> ".join(r.key for r in path)} -> {parent_id}')
            path.append(regions[parent_id])
        return tuple(path)

    def children(self, regions: Mapping[str, 'Region']) -> tuple['Region', ...]:
        """Regions directly below this one."""
        return tuple(r for r in regions.values() if r.parent_id == self.key)

    def countries(self, regions: Mapping[str, 'Region']) -> frozenset[str]:
        """Countries in this region or any region below it."""
        found = set(self.members)
        for child in self.children(regions):
            found |= child.countries(regions)
        return frozenset(found)


def region_of(alpha2: str, regions: Mapping[str, Region]) -> Region:
    """The region a country is placed in: JP -> East Asia."""
    for region in regions.values():
        if alpha2 in region.members:
            return region
    raise KeyError(f'{alpha2!r} is not placed in any region')


class Country(Geography):
    """A sovereign country or territory. The key is its ISO 3166-1 alpha-2 code (JP).

    The name defaults to `iso_name` (KR -> South Korea, JP -> Japan); pass
    `name` to override (RU -> Russia). Its region comes from the regions'
    member lists.
    """

    entity_type = GeographyType.COUNTRY

    key: str = Field(pattern=_ALPHA2)
    name: str = Field(default='', validate_default=True)
    currency_id: CurrencyKey

    @classmethod
    def iso_alpha2(cls, code: str) -> str:
        """`code` if it is an official ISO 3166-1 alpha-2 code; ValueError otherwise."""
        if pycountry.countries.get(alpha_2=code) is None:
            raise ValueError(f'{code!r} is not an ISO 3166-1 alpha-2 code')
        return code

    @classmethod
    def iso_name(cls, code: str) -> str:
        """pycountry's common name where it has one, else its name: KR -> South Korea."""
        country = pycountry.countries.get(alpha_2=code)
        if country is None:
            raise ValueError(f'{code!r} is not an ISO 3166-1 alpha-2 code')
        return getattr(country, 'common_name', None) or country.name

    @field_validator('key')
    @classmethod
    def _iso_key(cls, key: str) -> str:
        return cls.iso_alpha2(key)

    @field_validator('name')
    @classmethod
    def _default_name(cls, name: str, info: ValidationInfo) -> str:
        if name or 'key' not in info.data:  # explicit name, or the key already failed
            return name
        return cls.iso_name(info.data['key'])

    def regions(self, regions: Mapping[str, Region]) -> tuple[Region, ...]:
        """The country's region, then each broader one: JP -> (East Asia, Asia Pacific, World)."""
        return region_of(self.key, regions).lineage(regions)


# -- loading ------------------------------------------------------------------

def load_regions(path: Path) -> dict[str, Region]:
    """Regions from regions.yaml; checks parents, cycles and single placement."""
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    regions = {key: Region(key=key, **fields) for key, fields in data['regions'].items()}
    for region in regions.values():
        region.lineage(regions)
    placed = Counter(code for region in regions.values() for code in region.members)
    if twice := sorted(code for code, n in placed.items() if n > 1):
        raise ValueError(f'countries placed in more than one region: {twice}')
    return regions
