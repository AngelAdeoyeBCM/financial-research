"""Build GLiNER2 schemas from validated task definitions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from gliner2.inference.schema import Schema

from .types import ClassificationTask, ExtractionTask, StructuredTask, TaskSpec


class SchemaFactory(Protocol):
    """Anything that can mint a fresh GLiNER2 Schema — e.g. a loaded GLiNER2 model."""

    def create_schema(self) -> Schema: ...


# (allow_multiple, allow_none) -> GLiNER2 field cardinality.
_CARDINALITY = {
    (False, True): 'optional_one',
    (False, False): 'required_one',
    (True, True): 'zero_or_more',
    (True, False): 'one_or_more',
}


class SchemaBuilder:
    """Compose extraction, classification and structured tasks into a GLiNER2 schema."""

    def __init__(self, model: SchemaFactory) -> None:
        self._schema = model.create_schema()

    def build(self, tasks: Iterable[TaskSpec]) -> Schema:
        """Add each task to the schema, dispatching on its type."""
        for task in tasks:
            self._add_task(task)
        return self._schema

    def _add_task(self, task: TaskSpec) -> None:
        match task:
            case ExtractionTask():
                self._schema.entities(
                    entity_types=task.active_labels,
                    threshold=task.threshold,
                )
            case ClassificationTask():
                # The model sees display names; GLiNER2 drops examples whose label isn't one.
                display_names = {label_id: label.name for label_id, label in task.labels.items()}
                self._schema.classification(
                    task=task.name,
                    labels=task.active_labels,
                    multi_label=task.multi_label,
                    cls_threshold=task.cls_threshold,
                    prompt=task.prompt,
                    examples=[
                        (text, display_names.get(label, label)) for text, label in task.examples
                    ],
                )
            case StructuredTask():
                self._add_structured(task)
            case _:
                raise TypeError(f'Unsupported task type: {type(task).__name__}')

    def _add_structured(self, task: StructuredTask) -> None:
        """Compile one structured task into a GLiNER2 structure, keyed by YAML field id."""
        builder = self._schema.structure(
            task.name,
            mode=task.mode,
            anchor=task.anchor,
            occurrence_policy=task.occurrence_policy,
        )
        for field_id, spec in task.active_fields.items():
            kwargs: dict[str, object] = {
                'dtype': spec.dtype,
                'description': spec.description,
                'threshold': spec.threshold,
            }
            if spec.choices is not None:
                kwargs['choices'] = spec.choices
            # GLiNER2 only honours cardinality and exclusivity when the structure declares a mode.
            if task.mode is not None:
                kwargs['cardinality'] = _CARDINALITY[(spec.allow_multiple, spec.allow_none)]
                kwargs['exclusive'] = spec.exclusive
            builder.field(field_id, **kwargs)
