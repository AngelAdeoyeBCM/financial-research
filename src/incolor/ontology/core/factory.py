"""Factories: the one way an entity of a kind is made (QLib `IDefinitionFactory`).

Every kind has exactly one factory, registered with the `DefinitionManager`
under its identity type:

    SeedFactory    read from a YAML seed file; `build` only resolves    currency, rate index, bond programme
    BuildFactory   made from parsed parts on first mention, then stored  templates, instances, structures

`build(parts, ctx)` turns parts parsed from text into the canonical entity, so
two phrasings of one market resolve to one id. Parts that name nothing known
raise `Unresolved`; they are left for review, never given a near-miss key.
`ctx` carries the document date and the manager, for defaults read from
referenced entities (a currency's default index).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml
from pydantic import ValidationError

from .definition import Entity

if TYPE_CHECKING:
    from .manager import DefinitionManager


class Unresolved(LookupError):
    """Parts that name no known entity."""


@dataclass(frozen=True)
class BuildContext:
    """What a factory may read besides the parts: the document date and other definitions."""

    as_of: date
    manager: 'DefinitionManager'


class Factory[D: Entity](Protocol):
    """Makes and resolves one kind."""

    @property
    def definition(self) -> type[D]:
        """The definition class made; its `entity_type` is the kind the factory is registered under."""
        ...

    def seed(self) -> Iterable[D]:
        """Definitions to store when the factory is registered."""
        ...

    def build(self, parts: Mapping[str, Any], ctx: BuildContext) -> D:
        """The canonical definition these parts name."""
        ...


class SeedFactory[D: Entity]:
    """Definitions read from a YAML seed file.

    The file is a mapping `key: {fields}` for kinds with a given key, or a list
    of field mappings for kinds whose key is derived.
    """

    def __init__(self, definition: type[D], path: Path) -> None:
        self.definition = definition
        self.path = path

    def rows(self) -> list[dict[str, Any]]:
        """The seed file's field mappings, before validation; a subclass may join other files here."""
        data = yaml.safe_load(self.path.read_text(encoding='utf-8')) or []
        return [{'key': key, **fields} for key, fields in data.items()] if isinstance(data, dict) else data

    def seed(self) -> list[D]:
        """Every definition in the seed file."""
        return [self.definition.model_validate(row) for row in self.rows()]

    def build(self, parts: Mapping[str, Any], ctx: BuildContext) -> D:
        """The seeded definition the parts' key names: {'currency_id': 'USD', 'code': 'SOFR'} -> idx:USD.SOFR."""
        entity_type = self.definition.entity_type
        try:
            key = entity_type.format_key(parts) if entity_type.key_format else parts['key']
        except KeyError as missing:
            raise Unresolved(f'{entity_type}: missing part {missing}') from None
        return ctx.manager.get(entity_type.id_of(key), self.definition)


class BuildFactory[D: Entity]:
    """Definitions made from parts: canonicalise, construct, check references, store.

    Subclasses override `canonicalise` to fill defaults and normalise parts.
    """

    def __init__(self, definition: type[D]) -> None:
        self.definition = definition

    def seed(self) -> tuple[D, ...]:
        """None: built kinds are made on mention."""
        return ()

    def canonicalise(self, parts: Mapping[str, Any], ctx: BuildContext) -> dict[str, Any]:
        """Parts in canonical form, defaults filled. Raise `Unresolved` (or KeyError) when they name nothing."""
        return dict(parts)

    def build(self, parts: Mapping[str, Any], ctx: BuildContext) -> D:
        """The stored definition for these parts, made and stored if new."""
        try:
            entity = self.definition.model_validate(self.canonicalise(parts, ctx))
        except (KeyError, ValidationError) as error:
            raise Unresolved(f'{self.definition.entity_type}: {error}') from error
        if dangling := ctx.manager.dangling(entity):
            raise Unresolved(f'{entity.id}: references unknown {dangling}')
        return ctx.manager.store.add(entity)
