from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, TypeVar


class TaskType(StrEnum):
    EXTRACTION = 'extraction'
    CLASSIFICATION = 'classification'
    STRUCTURED = 'structured'


class LabelStatus(StrEnum):
    ACTIVE = 'active'
    DEPRECATED = 'deprecated'
    PENDING = 'pending'


@dataclass(frozen=True, slots=True)
class ItemSpec:
    """Properties shared by every vocabulary entry: labels and fields alike."""

    name: str
    description: str
    status: LabelStatus = LabelStatus.ACTIVE
    threshold: float | None = None

    @property
    def is_active(self) -> bool:
        return self.status is LabelStatus.ACTIVE


_T = TypeVar('_T', bound=ItemSpec)


def _active(items: Mapping[str, _T]) -> dict[str, _T]:
    """Entries with LabelStatus.ACTIVE, keyed by their YAML id."""
    return {key: item for key, item in items.items() if item.is_active}


@dataclass(frozen=True, slots=True)
class LabelSpec(ItemSpec):
    """A category in an extraction or classification task."""


@dataclass(frozen=True, slots=True)
class FieldSpec(ItemSpec):
    """One slot of a structured record: a free-text span or a closed-choice value."""

    dtype: Literal['str', 'list'] = 'list'  # "str" keeps the best value, "list" keeps every mention
    choices: list[str] | None = None  # non-empty makes this a closed-choice field
    allow_multiple: bool = True  # whether the field allows multiple values
    allow_none: bool = False  # whether the field allows no value to be set
    exclusive: bool = False  # whether the field is mutually exclusive with other fields

    def __post_init__(self) -> None:
        if self.dtype not in ('str', 'list'):
            raise ValueError(
                f"FieldSpec {self.name!r}: dtype must be 'str' or 'list', got {self.dtype!r}"
            )
        if self.choices is not None and len(set(self.choices)) != len(self.choices):
            raise ValueError(f'FieldSpec {self.name!r}: duplicate choices in {self.choices}')


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    version: str
    type: TaskType


@dataclass(frozen=True, slots=True)
class ExtractionTask(TaskSpec):
    type: TaskType = field(default=TaskType.EXTRACTION, init=False)
    labels: dict[str, LabelSpec]
    threshold: float | None = None

    @property
    def active_labels(self) -> dict[str, dict[str, object]]:
        """Active labels keyed by display name, shaped for the GLiNER2 schema."""
        result: dict[str, dict[str, object]] = {}
        for label in _active(self.labels).values():
            entry: dict[str, object] = {'description': label.description}
            if label.threshold is not None:
                entry['threshold'] = label.threshold
            result[label.name] = entry
        return result


@dataclass(frozen=True, slots=True)
class ClassificationTask(TaskSpec):
    type: TaskType = field(default=TaskType.CLASSIFICATION, init=False)
    labels: dict[str, LabelSpec]
    name: str
    multi_label: bool = True
    cls_threshold: float = 0.5  # classification decision threshold
    prompt: str | None = None  # compiles to the processor's `prompt` key
    examples: tuple[tuple[str, str], ...] = ()  # (text, label) few-shot pairs

    @property
    def active_labels(self) -> dict[str, str]:
        """Active labels keyed by display name, mapped to their description."""
        return {label.name: label.description for label in _active(self.labels).values()}


@dataclass(frozen=True, slots=True)
class StructuredTask(TaskSpec):
    """A record schema applied to a text span, e.g. the fields of one claim type."""

    type: TaskType = field(default=TaskType.STRUCTURED, init=False)
    fields: dict[str, FieldSpec]
    name: str
    mode: str | None = None
    anchor: str | None = None
    occurrence_policy: str | None = None

    @property
    def active_fields(self) -> dict[str, FieldSpec]:
        """Active fields keyed by YAML id, which is also the output key in the extraction result."""
        return _active(self.fields)
