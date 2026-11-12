"""Entity base class: identity, refs, relations, labels, record loading."""

import re
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from functools import cache
from typing import Any, ClassVar, NamedTuple, Union, get_args, get_origin, get_type_hints

from ..utils import require_nonempty
from .vocab import RELATION_RANGE, Category, Relation

Lookup = Callable[[str], 'Entity | None']

_QID = re.compile(r'Q[1-9]\d*')
_WD_PATH = re.compile(r'P[1-9]\d*(?:/P[1-9]\d*)*')


@dataclass(frozen=True)
class WikidataMap:
    """How a ref is read from Wikidata. Each path is a SPARQL property path
    from the entity's own item, e.g. 'P1001' or 'P562/P1001'.

    `primary` is tried first; `fallback` only when primary reaches no
    registry entity. When several survive, `tie_break` keeps those it also
    reaches (ECB: P1001 gives EU and eurozone, P38/P1001 gives eurozone).
    Exactly one survivor is a proposal; anything else is for review.
    """

    primary: str
    fallback: str | None = None
    tie_break: str | None = None

    def __post_init__(self) -> None:
        for path in (self.primary, self.fallback, self.tie_break):
            if path is not None and not _WD_PATH.fullmatch(path):
                raise ValueError(f'Not a Wikidata property path: {path!r}')


class RefSpec(NamedTuple):
    kinds: tuple[StrEnum, ...]
    required: bool
    wikidata: WikidataMap | None


def ref(*kinds: StrEnum, required: bool = True, wikidata: WikidataMap | None = None) -> Any:
    """Single-valued, stable link to another entity, stored as its ID.

    The target must carry one of `kinds` (a category or entity kind). Refs are
    filter properties the registry indexes, never claims; multi-valued or
    time-varying links stay in `relations`.
    """
    if not kinds:
        raise TypeError('ref() needs at least one target kind')
    spec = {'ref': RefSpec(kinds, required, wikidata)}
    return field(metadata=spec) if required else field(default=None, metadata=spec)


@cache
def _ref_specs(cls: type) -> Mapping[str, RefSpec]:
    return types.MappingProxyType({f.name: f.metadata['ref'] for f in fields(cls) if 'ref' in f.metadata})


def _coerce(tp: Any, value: Any) -> Any:
    """Convert a raw (YAML/JSON) value to the annotated field type."""
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        inner = next(a for a in get_args(tp) if a is not type(None))
        return None if value is None else _coerce(inner, value)
    if origin is frozenset:
        (inner,) = get_args(tp)
        return frozenset(_coerce(inner, v) for v in value)
    if isinstance(tp, type) and issubclass(tp, StrEnum):
        return tp(value)
    return value


@dataclass(frozen=True, kw_only=True)
class Entity:
    """Canonical named entity with a stable namespaced ID.

    Concrete subclasses set `category` and `entity_kind`, the enum member naming
    the class (MarketKind.SOVEREIGN_BOND, Category.EVENT); they register under
    (category, entity_kind) so records can be built from data files. Classes
    without their own `entity_kind` are abstract layers.
    """

    category: ClassVar[Category]
    entity_kind: ClassVar[StrEnum]
    _classes: ClassVar[dict[tuple[Category, StrEnum], type['Entity']]] = {}

    entity_id: str
    name: str
    aliases: frozenset[str] = frozenset()
    relations: frozenset[tuple[Relation, str]] = frozenset()
    wikidata_id: str | None = None  # QID: external identity, never a link target

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        kind = cls.__dict__.get('entity_kind')
        if kind is None:
            return
        key = (cls.category, kind)
        if key in Entity._classes:
            raise TypeError(f'{cls.__name__}: duplicate entity_kind {kind!r}')
        Entity._classes[key] = cls

    @classmethod
    def for_kind(cls, category: Category, kind: StrEnum) -> type['Entity']:
        return Entity._classes[(category, kind)]

    @classmethod
    def for_type(cls, value: str) -> type['Entity'] | None:
        """Class for a data-file `type:` value; None if unknown or ambiguous."""
        found = [c for (_, kind), c in Entity._classes.items() if kind.value == value]
        return found[0] if len(found) == 1 else None

    @classmethod
    def ref_specs(cls) -> Mapping[str, RefSpec]:
        """Every `ref()` field of this class, by field name."""
        return _ref_specs(cls)

    def __post_init__(self) -> None:
        if 'entity_kind' not in type(self).__dict__:
            raise TypeError(f'{type(self).__name__} is abstract')
        object.__setattr__(
            self, 'entity_id', require_nonempty(self.entity_id, 'entity_id')
        )
        object.__setattr__(self, 'name', require_nonempty(self.name, 'name'))
        if self.wikidata_id is not None and not _QID.fullmatch(self.wikidata_id):
            raise ValueError(f'{self.entity_id}: wikidata_id must be a QID, got {self.wikidata_id!r}')
        self._check_refs()
        self._validate()

    def _check_refs(self) -> None:
        for name, spec in self.ref_specs().items():
            value = getattr(self, name)
            if value is None:
                if spec.required:
                    raise ValueError(f'{self.entity_id}: needs {name}')
            else:
                object.__setattr__(self, name, require_nonempty(value, name))

    # -- extension points --------------------------------------------------
    def _validate(self) -> None:
        """Local invariants, checked at construction."""

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        """Every classification this entity carries (a tuple, not a set:
        equal-valued members of different enums must not collapse)."""
        return (self.category,)

    @property
    def surface_forms(self) -> tuple[str, ...]:
        """Strings that resolve to this entity (canonical name first)."""
        return (self.name, *sorted(self.aliases))

    def integrity_errors(self, lookup: Lookup) -> list[str]:
        """Cross-entity checks; subclasses extend via super()."""
        errors: list[str] = []
        for relation, target_id in sorted(self.relations):
            target = lookup(target_id)
            allowed = RELATION_RANGE.get(relation)
            if target is None:
                errors.append(
                    f'{self.entity_id}: {relation.value} -> '
                    f'unknown {target_id!r}'
                )
            elif allowed and target.category not in allowed:
                errors.append(
                    f'{self.entity_id}: {relation.value} -> {target_id!r} '
                    f'is a {target.category.value}'
                )
        for name, target_id in self.links:
            target = lookup(target_id)
            kinds = self.ref_specs()[name].kinds
            if target is None:
                errors.append(f'{self.entity_id}: {name} -> unknown {target_id!r}')
            elif not any(target.is_kind(k) for k in kinds):
                errors.append(
                    f'{self.entity_id}: {name} -> {target_id!r} must be '
                    f'{"/".join(k.value for k in kinds)}'
                )
        return errors

    # -- queries -----------------------------------------------------------
    def is_kind(self, label: StrEnum) -> bool:
        return any(label is own for own in self.labels)

    def related(self, relation: Relation) -> tuple[str, ...]:
        return tuple(sorted(t for r, t in self.relations if r is relation))

    @property
    def links(self) -> tuple[tuple[str, str], ...]:
        """(field, target_id) for every populated ref."""
        return tuple(
            (name, value) for name in self.ref_specs()
            if (value := getattr(self, name)) is not None
        )

    # -- construction from data --------------------------------------------
    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> 'Entity':
        data = dict(record)
        key = data.pop('type', None)
        target = cls.for_type(key) if key else cls
        if target is None or not issubclass(target, cls):
            raise ValueError(f'Unknown entity type {key!r}')

        unknown = set(data) - {f.name for f in fields(target)}
        if unknown:
            raise ValueError(
                f'{data.get("entity_id")}: unknown fields {sorted(unknown)}'
            )

        hints = get_type_hints(target)
        relations = data.pop('relations', None) or {}
        kwargs = {k: _coerce(hints[k], v) for k, v in data.items()}
        kwargs['relations'] = frozenset(
            (Relation(rel), tid)
            for rel, targets in relations.items()
            for tid in targets
        )
        return target(**kwargs)
