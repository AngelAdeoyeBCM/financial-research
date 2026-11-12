"""The DefinitionManager: one entry point to every kind (QLib `IDefinitionManager`).

Register factories, then look definitions up or build them:

    manager.register(factory)                     one factory per identity type; seeds are stored
    manager.get('idx:USD.SOFR', RateIndex)        by id
    manager.build(IRS, {'currency_id': 'USD'}, as_of)   from parsed parts, via the kind's factory
    manager.ref(index, 'currency_id', Currency)   follow a reference field
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from .definition import Entity
from .factory import BuildContext, Factory, Unresolved
from .identity import TypeEnum
from .store import MemoryStore, Store


class DefinitionManager:
    """Routes lookups to the store and builds to the factory registered for the kind."""

    def __init__(self, store: Store | None = None) -> None:
        self.store: Store = store if store is not None else MemoryStore()
        self._factories: dict[TypeEnum, Factory[Any]] = {}

    def register(self, factory: Factory[Any]) -> None:
        """Route the factory's kind to it and store its seeds."""
        entity_type = factory.definition.entity_type
        if entity_type in self._factories:
            raise ValueError(f'{entity_type!r} already has a factory')
        self._factories[entity_type] = factory
        for entity in factory.seed():
            self.store.add(entity)

    def get[E: Entity](self, entity_id: str, kind: type[E]) -> E:
        """The stored definition with this id, which must be a `kind`."""
        entity = self.store.get(entity_id)
        if not isinstance(entity, kind):
            raise Unresolved(f'no {kind.__name__} {entity_id!r}')
        return entity

    def ref[E: Entity](self, entity: Entity, field: str, kind: type[E]) -> E:
        """The entity a single-valued reference field points at."""
        (target_id,) = entity.ref_ids()[field]
        return self.get(target_id, kind)

    def build[E: Entity](self, kind: type[E], parts: Mapping[str, Any], as_of: date) -> E:
        """The canonical `kind` these parts name, made by its factory if not yet stored."""
        entity = self._factories[kind.entity_type].build(parts, BuildContext(as_of, self))
        if not isinstance(entity, kind):
            raise TypeError(f'{kind.entity_type!r} factory made a {type(entity).__name__}')
        return entity

    def dangling(self, entity: Entity) -> list[str]:
        """References that are missing or of the wrong type, among kinds this manager holds.

        A reference to a kind with no registered factory (a country, while geography is not loaded) is not checked.
        """
        bad = []
        for field, target, entity_id in entity.refs():
            if not any(t.is_subtype(target) for t in self._factories):
                continue
            found = self.store.get(entity_id)
            if found is None or not found.entity_type.is_subtype(target):
                bad.append(f'{field}={entity_id}')
        return bad

    def check(self) -> list[str]:
        """Every stored definition's bad references, for seed integrity tests."""
        return [f'{e.id}: {bad}' for e in self.store for bad in self.dangling(e)]
