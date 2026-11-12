"""Transactional SQLite persistence for entity identities and aliases.

The YAML registry (config/registries) is the source of truth; this table
mirrors identities and aliases for lookup.
"""

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import NamedTuple

from ..ontology.core import Entity


class EntityRecord(NamedTuple):
    entity_id: str
    name: str
    type: str
    aliases: tuple[str, ...]


class EntityRepository:
    """Use the research database path; each write batch is one transaction."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    aliases TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def list_entities(self) -> tuple[EntityRecord, ...]:
        with closing(self._connect()) as connection:
            return tuple(
                EntityRecord(entity_id, name, kind, tuple(json.loads(aliases)))
                for entity_id, name, kind, aliases in connection.execute(
                    'SELECT entity_id, name, type, aliases FROM entities ORDER BY entity_id'
                )
            )

    def save_entities(self, entities: Iterable[Entity]) -> None:
        rows = [
            (entity.entity_id, entity.name, entity.entity_kind.value, json.dumps(sorted(entity.aliases)))
            for entity in entities
        ]
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO entities (entity_id, name, type, aliases) VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    name=excluded.name, type=excluded.type, aliases=excluded.aliases
            """,
                rows,
            )
