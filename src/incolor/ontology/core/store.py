"""Where definitions live once seeded or built. Persistent storage is still to be decided."""

from collections.abc import Iterator
from typing import Protocol, cast

from .definition import Entity


class Store(Protocol):
    """Definitions by id."""

    def get(self, entity_id: str) -> Entity | None:
        """The definition with this id, if stored."""
        ...

    def add[E: Entity](self, entity: E) -> E:
        """Get-or-create: an equal definition already stored is returned; a different one is an error."""
        ...

    def __iter__(self) -> Iterator[Entity]: ...


class MemoryStore:
    """In-process store."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}

    def get(self, entity_id: str) -> Entity | None:
        """The definition with this id, if stored."""
        return self._entities.get(entity_id)

    def add[E: Entity](self, entity: E) -> E:
        """Get-or-create: an equal definition already stored is returned; a different one is an error."""
        stored = self._entities.setdefault(entity.id, entity)
        if stored != entity:
            raise ValueError(f'{entity.id}: conflicts with the stored definition')
        return cast(E, stored)

    def __iter__(self) -> Iterator[Entity]:
        return iter(self._entities.values())
