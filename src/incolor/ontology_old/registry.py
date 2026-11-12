"""Registry: loads entity records, validates them, answers queries."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from enum import StrEnum
from pathlib import Path

import yaml

from .base import Entity
from .vocab import Category, Relation, label_key

DATA_DIR = Path(__file__).resolve().parents[3] / 'config' / 'registries'


def normalise(text: str) -> str:
    """Key used for alias matching: case- and whitespace-insensitive."""
    return ' '.join(text.casefold().split())


class RegistryError(ValueError):
    """Raised for malformed records, duplicates or integrity failures."""


class Registry:
    def __init__(self, entities: Iterable[Entity] = ()) -> None:
        self._by_id: dict[str, Entity] = {}
        self._by_qid: dict[str, str] = {}
        self._by_label: dict[tuple, set[str]] = defaultdict(set)
        self._by_link: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._by_form: dict[str, set[str]] = defaultdict(set)
        for entity in entities:
            self.add(entity)

    # -- mutation ----------------------------------------------------------
    def add(self, entity: Entity) -> None:
        if entity.entity_id in self._by_id:
            raise RegistryError(f'Duplicate entity_id {entity.entity_id!r}')
        if (qid := entity.wikidata_id) is not None:
            if qid in self._by_qid:
                raise RegistryError(
                    f'{entity.entity_id}: wikidata_id {qid} already used by {self._by_qid[qid]!r}'
                )
            self._by_qid[qid] = entity.entity_id
        self._by_id[entity.entity_id] = entity
        for label in entity.labels:
            self._by_label[label_key(label)].add(entity.entity_id)
        for link in entity.links:
            self._by_link[link].add(entity.entity_id)
        for form in entity.surface_forms:
            self._by_form[normalise(form)].add(entity.entity_id)

    # -- lookup ------------------------------------------------------------
    def find(self, entity_id: str) -> Entity | None:
        return self._by_id.get(entity_id)

    def find_by_qid(self, qid: str) -> Entity | None:
        entity_id = self._by_qid.get(qid)
        return None if entity_id is None else self._by_id[entity_id]

    def get(self, entity_id: str) -> Entity:
        try:
            return self._by_id[entity_id]
        except KeyError:
            raise KeyError(f'Unknown entity {entity_id!r}') from None

    def __contains__(self, entity_id: object) -> bool:
        return entity_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Entity]:
        return iter(self._by_id.values())

    # -- queries -----------------------------------------------------------
    def with_label(self, label: StrEnum) -> tuple[Entity, ...]:
        ids = self._by_label.get(label_key(label), ())
        return tuple(self._by_id[i] for i in sorted(ids))

    def with_link(self, field: str, target_id: str) -> tuple[Entity, ...]:
        """Entities whose ref `field` points at `target_id`, e.g.
        with_link('currency_id', 'ccy:usd') -> SOFR, UST, ..."""
        if not any(field in cls.ref_specs() for cls in Entity._classes.values()):
            raise KeyError(f'No entity has a ref field {field!r}')
        ids = self._by_link.get((field, target_id), ())
        return tuple(self._by_id[i] for i in sorted(ids))

    def resolve(
        self, text: str, category: Category | None = None
    ) -> tuple[Entity, ...]:
        """Every entity whose name, code or alias matches `text`; more than
        one result means the mention is ambiguous."""
        ids = self._by_form.get(normalise(text), ())
        found = (self._by_id[i] for i in sorted(ids))
        return tuple(e for e in found if category is None or e.category is category)

    def alias_conflicts(self) -> dict[str, tuple[str, ...]]:
        """Surface forms shared by several entities of the same category,
        which a category filter cannot disambiguate (review, not an error).
        Cross-category sharing (BoE the bank vs BoE the meeting) is expected."""
        conflicts: dict[str, tuple[str, ...]] = {}
        for form, ids in sorted(self._by_form.items()):
            by_category: dict[Category, list[str]] = defaultdict(list)
            for entity_id in sorted(ids):
                by_category[self._by_id[entity_id].category].append(entity_id)
            for clash in by_category.values():
                if len(clash) > 1:
                    conflicts[form] = conflicts.get(form, ()) + tuple(clash)
        return conflicts

    def related(self, entity_id: str, relation: Relation) -> tuple[Entity, ...]:
        return tuple(self.get(t) for t in self.get(entity_id).related(relation))

    def ancestors(self, entity_id: str) -> tuple[Entity, ...]:
        """Transitive MEMBER_OF closure, nearest first (Brazil -> LatAm -> EM)."""
        seen: set[str] = set()
        order: list[Entity] = []
        frontier = [entity_id]
        while frontier:
            for parent_id in self.get(frontier.pop(0)).related(
                Relation.MEMBER_OF
            ):
                if parent_id not in seen:
                    seen.add(parent_id)
                    order.append(self.get(parent_id))
                    frontier.append(parent_id)
        return tuple(order)

    # -- integrity ---------------------------------------------------------
    def validate(self) -> list[str]:
        return [e for ent in self for e in ent.integrity_errors(self.find)]

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, *paths: Path | str, validate: bool = True) -> 'Registry':
        registry = cls()
        for file in _yaml_files(paths):
            for record in yaml.safe_load(file.read_text(encoding='utf-8')) or []:
                try:
                    registry.add(Entity.from_record(record))
                except (ValueError, TypeError, KeyError) as exc:
                    raise RegistryError(f'{file.name}: {exc}') from exc
        if validate and (errors := registry.validate()):
            raise RegistryError(
                f'{len(errors)} integrity error(s):\n  ' + '\n  '.join(errors)
            )
        return registry

    @classmethod
    def load_default(
        cls, *extra_paths: Path | str, validate: bool = True
    ) -> 'Registry':
        """Seed registries in config/registries plus any extra files or dirs."""
        return cls.load(DATA_DIR, *extra_paths, validate=validate)


def _yaml_files(paths: Iterable[Path | str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob('*.yaml')) if p.is_dir() else [p])
    return files
