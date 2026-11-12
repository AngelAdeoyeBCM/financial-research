"""Taxonomy loaded from YAML: the single source of truth for labels, document types and entity naming."""

import hashlib
from pathlib import Path
from typing import Any

import yaml


class TaxonomyError(ValueError):
    """The taxonomy file is missing required sections or is internally inconsistent."""


class Taxonomy:
    """Validated view over ``taxonomy.yaml``."""

    def __init__(self, data: dict[str, Any], source_text: str = "") -> None:
        self._categories = self._load_categories(data.get("categories"))
        self.fallback_category = str(data.get("fallback_category", ""))
        if self.fallback_category not in self._categories:
            raise TaxonomyError(f"fallback_category {self.fallback_category!r} is not a category")
        self.document_types = self._string_list(data, "document_types")
        self.entity_types = self._string_list(data, "entity_types")
        review = data.get("review") or {}
        self.confidence_threshold = float(review.get("confidence_threshold", 0.7))
        self.min_body_chars = int(review.get("min_body_chars", 200))
        self._alias_to_canonical = self._load_aliases(data.get("entity_aliases") or {})
        self.digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        """Parse and validate a taxonomy YAML file.

        Raises:
            TaxonomyError: If the structure is invalid.
        """
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise TaxonomyError(f"{path}: top level must be a mapping")
        return cls(data, text)

    @property
    def categories(self) -> list[str]:
        """Category names in file order."""
        return list(self._categories)

    def subcategories(self, category: str) -> list[str]:
        """Subcategories of ``category`` in file order."""
        return list(self._categories[category])

    def check_label(self, category: str, subcategory: str) -> str | None:
        """Return a problem description if the pair is not in the taxonomy, else None."""
        if category not in self._categories:
            return f"unknown category {category!r}; choose from {self.categories}"
        if subcategory not in self._categories[category]:
            return f"unknown subcategory {subcategory!r} for {category!r}; choose from {self.subcategories(category)}"
        return None

    def normalise_entity(self, name: str) -> str:
        """Map an entity name to its canonical form via the alias table; otherwise tidy whitespace."""
        cleaned = " ".join(name.split())
        return self._alias_to_canonical.get(cleaned.casefold(), cleaned)

    @property
    def canonical_entities(self) -> list[str]:
        """Canonical names from the alias table, in file order."""
        return list(dict.fromkeys(self._alias_to_canonical.values()))

    def render_for_prompt(self) -> str:
        """Bullet list of ``Category: sub1 | sub2 ...`` for the system prompt."""
        return "\n".join(f"- {cat}: " + " | ".join(subs) for cat, subs in self._categories.items())

    @staticmethod
    def _load_categories(raw: Any) -> dict[str, tuple[str, ...]]:
        if not isinstance(raw, dict) or not raw:
            raise TaxonomyError("'categories' must be a non-empty mapping")
        result: dict[str, tuple[str, ...]] = {}
        for category, subs in raw.items():
            if not isinstance(subs, list) or not subs or not all(isinstance(s, str) and s for s in subs):
                raise TaxonomyError(f"category {category!r} needs a non-empty list of subcategory strings")
            if len(set(subs)) != len(subs):
                raise TaxonomyError(f"category {category!r} has duplicate subcategories")
            result[str(category)] = tuple(subs)
        return result

    @staticmethod
    def _string_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
        values = data.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise TaxonomyError(f"{key!r} must be a non-empty list of strings")
        return tuple(values)

    @staticmethod
    def _load_aliases(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            raise TaxonomyError("'entity_aliases' must be a mapping")
        lookup: dict[str, str] = {}
        for canonical, aliases in raw.items():
            for name in [str(canonical), *map(str, aliases or [])]:
                key = name.casefold()
                if lookup.setdefault(key, str(canonical)) != str(canonical):
                    raise TaxonomyError(f"entity alias {name!r} maps to two canonical names")
        return lookup
