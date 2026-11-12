"""Sources: where research is read, one record per item received.

Not registry entities: a source holds the registry organizations, people
and geographies it is by or about, e.g. a BofA report by two analysts on DM rates.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from ..utils import require_nonempty
from .geography import Geography
from .markets import AssetClass
from .organizations import Organization
from .people import Person
from .theme import Theme


class SourceKind(StrEnum):
    DOCUMENT = 'document'
    EMAIL = 'email'
    BBG_COMMENTARY = 'bbg_commentary'


class MarketCoverage(StrEnum):
    """Markets a document substantively covers. Overlapping, multi-label."""

    GLOBAL = 'global'
    DM = 'dm'
    EM = 'em'
    NORTH_AMERICA = 'north_america'
    EUROPE = 'europe'
    ASIA = 'asia'
    AUSTRALASIA = 'australasia'
    LATAM = 'latam'
    CEEMEA = 'ceemea'
    MIDDLE_EAST = 'middle_east'
    AFRICA = 'africa'

    @property
    def display_name(self) -> str:
        return _DISPLAY[self]


_DISPLAY = {
    MarketCoverage.GLOBAL: 'Global',
    MarketCoverage.DM: 'Developed Markets',
    MarketCoverage.EM: 'Emerging Markets',
    MarketCoverage.NORTH_AMERICA: 'North America',
    MarketCoverage.EUROPE: 'Europe',
    MarketCoverage.ASIA: 'Asia',
    MarketCoverage.AUSTRALASIA: 'Australasia',
    MarketCoverage.LATAM: 'Latin America',
    MarketCoverage.CEEMEA: 'CEEMEA',
    MarketCoverage.MIDDLE_EAST: 'Middle East',
    MarketCoverage.AFRICA: 'Africa',
}
assert _DISPLAY.keys() == set(MarketCoverage)

def _require(kind: SourceKind, field: str, values: Iterable[object], cls: type) -> None:
    """Runtime guard: annotations are not enforced for records built from parsed data."""
    if not all(isinstance(v, cls) for v in values):
        raise TypeError(f'{kind}: {field} must be {cls.__name__}')


@dataclass(frozen=True, kw_only=True)
class Source:
    """Abstract. Subclasses set a unique `kind` and expose their own id as `source_id`."""

    kind: ClassVar[SourceKind]
    _classes: ClassVar[dict[SourceKind, type['Source']]] = {}

    date: dt.date
    themes: frozenset[Theme] = frozenset()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get('kind')
        if kind is None or kind in Source._classes:
            raise TypeError(f'{cls.__name__} needs its own unique kind')
        Source._classes[kind] = cls

    @classmethod
    def for_kind(cls, kind: SourceKind) -> type['Source']:
        return Source._classes[kind]

    def __post_init__(self) -> None:
        if type(self) is Source:
            raise TypeError('Source is abstract')
        _require(self.kind, 'date', (self.date,), dt.date)
        _require(self.kind, 'themes', self.themes, Theme)
        self._validate()

    def _validate(self) -> None:
        """Kind-specific invariants, checked at construction."""

    @property
    def source_id(self) -> str:
        raise NotImplementedError

    @property
    def key(self) -> str:
        """Deterministic id, e.g. SRC:DOCUMENT[929831]."""
        return f'SRC:{self.kind.name}[{self.source_id}]'


@dataclass(frozen=True, kw_only=True)
class Document(Source):
    """A research report: one publisher, authors in byline order.

    `coverage` lists geographies at any level: geo:global, geo:dm, geo:em, geo:g10, geo:latam, geo:us.
    """

    kind = SourceKind.DOCUMENT

    document_id: str
    publisher: Organization
    authors: tuple[Person, ...] = ()
    asset_classes: tuple[AssetClass, ...] = ()
    coverage: frozenset[MarketCoverage] = frozenset()
    countries: tuple[Geography, ...] = ()

    def _validate(self) -> None:
        object.__setattr__(self, 'document_id', require_nonempty(self.document_id, 'document_id'))
        object.__setattr__(self, 'asset_classes', tuple(AssetClass(a) for a in self.asset_classes))
        _require(self.kind, 'publisher', (self.publisher,), Organization)
        _require(self.kind, 'authors', self.authors, Person)
        _require(self.kind, 'coverage', self.coverage, MarketCoverage)
        _require(self.kind, 'countries', self.countries, Geography)
        for name in ('authors', 'asset_classes', 'coverage'):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f'{self.kind}: duplicate {name}')

    @property
    def source_id(self) -> str:
        return self.document_id


@dataclass(frozen=True, kw_only=True)
class Email(Source):
    """A research email; `sender` is the from-address (resweb@morganstanley.com)."""

    kind = SourceKind.EMAIL

    message_id: str
    sender: str

    def _validate(self) -> None:
        object.__setattr__(self, 'message_id', require_nonempty(self.message_id, 'message_id'))
        sender = require_nonempty(self.sender, 'sender').lower()
        if '@' not in sender:
            raise ValueError(f'{self.kind}: sender must be an email address, got {self.sender!r}')
        object.__setattr__(self, 'sender', sender)

    @property
    def source_id(self) -> str:
        return self.message_id


@dataclass(frozen=True, kw_only=True)
class BbgCommentary(Source):
    """Bloomberg commentary. Not modelled yet."""

    kind = SourceKind.BBG_COMMENTARY

    def _validate(self) -> None:
        raise NotImplementedError('BbgCommentary is not modelled yet')
