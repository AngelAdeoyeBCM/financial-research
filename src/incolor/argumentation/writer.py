"""Write argument maps and issue lists to disk in the key order used by the gold files."""

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from .schema import ArgumentMap
from .validate import ValidationIssue

GOLD_KEY_ORDER = (
    "schema_version",
    "document",
    "evidence",
    "statements",
    "arguments",
    "scenarios",
    "rejected_links",
    "exclusions",
    "adjudication_notes",
)
_OMIT_WHEN_EMPTY = ("scenarios", "rejected_links", "adjudication_notes")
_OPTIONAL_STATEMENT_KEYS = ("proposition_kind", "attribution", "subkinds")
# Roles added after v0.9; omitted when empty so maps under older taxonomies are written unchanged.
_OPTIONAL_ARGUMENT_KEYS = ("premises", "assumptions", "warrants", "concessions", "implications", "alternatives")
_OPTIONAL_SCENARIO_KEYS = ("role", "outcome_orientation", "purpose")
_ARGUMENT_FIXED_KEYS = ("id", "summary", "conclusion")


def argument_map_to_dict(map_: ArgumentMap, roles: Sequence[str] | None = None) -> dict[str, Any]:
    """Return the map as a plain dict in gold-file key order, omitting empty optional keys.

    When ``roles`` is given, argument roles outside it (and empty) are dropped, so a map is written with only the
    roles of its taxonomy.
    """
    data = map_.model_dump(mode="json")
    for key in _OMIT_WHEN_EMPTY:
        if not data.get(key):
            data.pop(key, None)
    for items, keys in (
        (data["statements"], _OPTIONAL_STATEMENT_KEYS),
        (data["arguments"], _OPTIONAL_ARGUMENT_KEYS),
        (data.get("scenarios", []), _OPTIONAL_SCENARIO_KEYS),
    ):
        for item in items:
            for key in keys:
                if item.get(key) in (None, []):
                    item.pop(key, None)
    if roles is not None:
        for argument in data["arguments"]:
            for key in [k for k in argument if k not in _ARGUMENT_FIXED_KEYS and k not in roles]:
                if not argument[key]:
                    argument.pop(key)
    return {key: data[key] for key in GOLD_KEY_ORDER if key in data}


def write_argument_map(map_: ArgumentMap, path: Path, roles: Sequence[str] | None = None) -> None:
    """Write the map as YAML, creating parent directories as needed; ``roles`` as in ``argument_map_to_dict``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(argument_map_to_dict(map_, roles), sort_keys=False, allow_unicode=True, width=10_000)
    path.write_text(text, encoding="utf-8")


def write_issues(issues: list[ValidationIssue], path: Path) -> None:
    """Write the issue list as a JSON array."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [dataclasses.asdict(issue) for issue in issues]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_argument_map(path: Path) -> ArgumentMap:
    """Read a YAML argument map and validate it against the schema.

    Raises:
        pydantic.ValidationError: If the file does not match the schema.
    """
    with open(path, encoding="utf-8") as f:
        return ArgumentMap.model_validate(yaml.safe_load(f))
