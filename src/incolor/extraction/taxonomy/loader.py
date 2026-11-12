"""Load, validate, save, and construct task definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ...utils import (
    require_dict,
    require_enum,
    require_mapping,
    require_nonempty,
    require_probability,
    require_type,
)
from .types import (
    ClassificationTask,
    ExtractionTask,
    FieldSpec,
    LabelSpec,
    LabelStatus,
    StructuredTask,
    TaskSpec,
    TaskType,
)

# Values GLiNER2 accepts for a structure's record mode and occurrence policy.
_MODES = ('natural', 'latent', 'anchorless')
_OCCURRENCE_POLICIES = ('all', 'first', 'error_on_ambiguous', 'latent_all')


class TaskLoader:
    """Load YAML, validate format, build a typed TaskSpec, and save it back out."""

    # --- Public API ------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> TaskSpec:
        with path.open(encoding='utf-8') as file:
            taxonomy = yaml.safe_load(file)

        return cls._parse(taxonomy, path.name)

    @classmethod
    def save(cls, task: TaskSpec, path: Path) -> None:
        """Serialize a TaskSpec back to a taxonomy YAML file."""
        with path.open('w', encoding='utf-8') as file:
            yaml.safe_dump(cls._dump(task), file, sort_keys=False)

    @classmethod
    def validate(cls, taxonomy: dict[str, Any], source: str = 'taxonomy') -> tuple[bool, list[str]]:
        try:
            cls._parse(taxonomy, source)
            return True, []
        except (TypeError, ValueError) as exc:
            return False, [str(exc)]

    # --- Dispatch ----------------------------------------------------------

    @classmethod
    def _parse(cls, taxonomy: dict[str, Any], source: str) -> TaskSpec:
        """Validate and build an in-memory taxonomy."""
        taxonomy = require_mapping(taxonomy, source)
        require_nonempty(taxonomy.get('version'), f'{source}: version')
        require_nonempty(taxonomy.get('id'), f'{source}: id')
        task_type = require_enum(taxonomy.get('type'), TaskType, f'{source}: type')

        match task_type:
            case TaskType.EXTRACTION:
                return cls._parse_extraction(taxonomy, source)
            case TaskType.CLASSIFICATION:
                return cls._parse_classification(taxonomy, source)
            case TaskType.STRUCTURED:
                return cls._parse_structured(taxonomy, source)
            case _:
                raise ValueError(f'Unsupported task type: {task_type}')

    @classmethod
    def _dump(cls, task: TaskSpec) -> dict:
        match task:
            case ExtractionTask():
                return cls._dump_extraction(task)
            case ClassificationTask():
                return cls._dump_classification(task)
            case StructuredTask():
                return cls._dump_structured(task)
            case _:
                raise TypeError(f'Unsupported task type: {type(task).__name__}')

    # --- Extraction ----------------------------------------------------------

    @classmethod
    def _parse_extraction(cls, taxonomy: dict[str, Any], source: str) -> ExtractionTask:
        """Validate and construct an extraction task."""
        threshold = taxonomy.get('threshold')
        if threshold is not None:
            threshold = require_probability(threshold, f'{source}: threshold')

        return ExtractionTask(
            id=taxonomy.get('id'),
            version=taxonomy.get('version'),
            labels=cls._parse_labels(taxonomy, source),
            threshold=threshold,
        )

    @staticmethod
    def _dump_extraction(task: ExtractionTask) -> dict:
        return {
            'version': task.version,
            'id': task.id,
            'type': task.type.value,
            'threshold': task.threshold,
            'labels': TaskLoader._dump_labels(task.labels),
        }

    # --- Classification ----------------------------------------------------------

    @classmethod
    def _parse_classification(cls, taxonomy: dict[str, Any], source: str) -> ClassificationTask:
        """Validate and construct a classification task."""
        multi_label = require_type(taxonomy.get('multi_label'), bool, f'{source}: multi_label')
        cls_threshold = require_probability(taxonomy.get('threshold'), f'{source}: threshold')
        name = require_nonempty(taxonomy.get('name'), f'{source}: name')
        prompt = taxonomy.get('prompt')
        if prompt is not None:
            prompt = require_type(prompt, str, f'{source}: prompt')
        examples = cls._parse_examples(taxonomy.get('examples', ()), f'{source}: examples')

        return ClassificationTask(
            id=taxonomy.get('id'),
            version=taxonomy.get('version'),
            labels=cls._parse_labels(taxonomy, source),
            name=name,
            multi_label=multi_label,
            cls_threshold=cls_threshold,
            prompt=prompt,
            examples=examples,
        )

    @staticmethod
    def _dump_classification(task: ClassificationTask) -> dict:
        return {
            'version': task.version,
            'id': task.id,
            'type': task.type.value,
            'multi_label': task.multi_label,
            'threshold': task.cls_threshold,
            'name': task.name,
            'prompt': task.prompt,
            'labels': TaskLoader._dump_labels(task.labels),
            'examples': TaskLoader._dump_examples(task.examples),
        }

    # --- Structured ----------------------------------------------------------

    @classmethod
    def _parse_structured(cls, taxonomy: dict[str, Any], source: str) -> StructuredTask:
        """Validate and construct a structured (record) task."""
        name = require_nonempty(taxonomy.get('name'), f'{source}: name')
        mode = cls._parse_choice(taxonomy.get('mode'), _MODES, f'{source}: mode')
        policy = cls._parse_choice(
            taxonomy.get('occurrence_policy'), _OCCURRENCE_POLICIES, f'{source}: occurrence_policy'
        )
        anchor = taxonomy.get('anchor')
        if anchor is not None:
            anchor = require_nonempty(anchor, f'{source}: anchor')
        fields = cls._parse_fields(taxonomy, source)

        if anchor is not None:
            if mode != 'natural':
                raise ValueError(f"{source}: anchor is only valid with mode 'natural'")
            if anchor not in fields or not fields[anchor].is_active:
                raise ValueError(f'{source}: anchor {anchor!r} is not an active field')

        return StructuredTask(
            id=taxonomy.get('id'),
            version=taxonomy.get('version'),
            fields=fields,
            name=name,
            mode=mode,
            anchor=anchor,
            occurrence_policy=policy,
        )

    @staticmethod
    def _dump_structured(task: StructuredTask) -> dict:
        return {
            'version': task.version,
            'id': task.id,
            'type': task.type.value,
            'name': task.name,
            'mode': task.mode,
            'anchor': task.anchor,
            'occurrence_policy': task.occurrence_policy,
            'fields': TaskLoader._dump_fields(task.fields),
        }

    @staticmethod
    def _parse_choice(value: object, allowed: tuple[str, ...], source: str) -> str | None:
        """Validate an optional string against a fixed set of values."""
        if value is None:
            return None
        value = require_type(value, str, source)
        if value not in allowed:
            raise ValueError(
                f'{source} has invalid value: {value!r} (expected one of {list(allowed)})'
            )
        return value

    @staticmethod
    def _parse_fields(taxonomy: dict[str, Any], source: str) -> dict[str, FieldSpec]:
        """Validate the `fields` mapping and build FieldSpec records, keyed by YAML id."""
        raw = require_dict(taxonomy.get('fields'), str, dict, f'{source}: fields')

        fields: dict[str, FieldSpec] = {}
        for field_id, config in raw.items():
            where = f'{source}: fields.{field_id}'
            require_nonempty(field_id, f'{source}: field id')

            threshold = config.get('threshold')
            if threshold is not None:
                threshold = require_probability(threshold, f'{where}.threshold')

            choices = config.get('choices')
            if choices is not None:
                choices = require_type(choices, list, f'{where}.choices')
                if not choices:
                    raise ValueError(f'{where}.choices must not be empty')
                choices = [require_nonempty(choice, f'{where}.choices[]') for choice in choices]

            fields[field_id] = FieldSpec(
                name=require_nonempty(config.get('name'), f'{where}.name'),
                description=require_nonempty(config.get('description'), f'{where}.description'),
                status=require_enum(config.get('status'), LabelStatus, f'{where}.status'),
                threshold=threshold,
                dtype=require_type(config.get('dtype', 'list'), str, f'{where}.dtype'),
                choices=choices,
                allow_multiple=require_type(
                    config.get('allow_multiple', True), bool, f'{where}.allow_multiple'
                ),
                allow_none=require_type(
                    config.get('allow_none', False), bool, f'{where}.allow_none'
                ),
                exclusive=require_type(config.get('exclusive', False), bool, f'{where}.exclusive'),
            )

        active_names = [spec.name for spec in fields.values() if spec.is_active]
        if not active_names:
            raise ValueError(f'{source}: fields has no active entries')
        if len(active_names) != len(set(active_names)):
            dupes = sorted({name for name in active_names if active_names.count(name) > 1})
            raise ValueError(f'{source}: duplicate active field name(s): {dupes}')

        return fields

    @staticmethod
    def _dump_fields(fields: dict[str, FieldSpec]) -> dict:
        return {
            field_id: {
                'name': spec.name,
                'description': spec.description,
                'status': spec.status.value,
                'threshold': spec.threshold,
                'dtype': spec.dtype,
                'choices': spec.choices,
                'allow_multiple': spec.allow_multiple,
                'allow_none': spec.allow_none,
                'exclusive': spec.exclusive,
            }
            for field_id, spec in fields.items()
        }

    # --- Shared label / example helpers ----------------------------------------------

    @staticmethod
    def _parse_labels(taxonomy: object, source: str) -> dict[str, LabelSpec]:
        """Validate the `labels` mapping and build LabelSpec records, keyed by YAML id."""
        raw = require_dict(taxonomy.get('labels'), str, dict, f'{source}: labels')

        labels: dict[str, LabelSpec] = {}
        for label_id, config in raw.items():
            require_nonempty(label_id, f'{source}: label id')

            threshold = config.get('threshold')
            if threshold is not None:
                threshold = require_probability(threshold, f'{source}: labels.{label_id}.threshold')

            labels[label_id] = LabelSpec(
                name=require_nonempty(config.get('name'), f'{source}: labels.{label_id}.name'),
                description=require_nonempty(
                    config.get('description'), f'{source}: labels.{label_id}.description'
                ),
                status=require_enum(
                    config.get('status'), LabelStatus, f'{source}: labels.{label_id}.status'
                ),
                threshold=threshold,
            )

        active_names = [
            label.name for label in labels.values() if label.status is LabelStatus.ACTIVE
        ]
        if not active_names:
            raise ValueError(f'{source}: labels has no active entries')
        if len(active_names) != len(set(active_names)):
            dupes = sorted({name for name in active_names if active_names.count(name) > 1})
            raise ValueError(f'{source}: duplicate active label name(s): {dupes}')

        return labels

    @staticmethod
    def _dump_labels(labels: dict[str, LabelSpec]) -> dict:
        return {
            label_id: {
                'name': label.name,
                'description': label.description,
                'status': label.status.value,
                'threshold': label.threshold,
            }
            for label_id, label in labels.items()
        }

    @staticmethod
    def _parse_examples(value: object, source: str) -> tuple[tuple[str, str], ...]:
        """Validate and convert a list of few-shot examples."""
        examples = require_type(value, list, source)

        return tuple(
            (
                require_nonempty(example['text'], f'{source}: text'),
                require_nonempty(example['label'], f'{source}: label'),
            )
            for example in examples
        )

    @staticmethod
    def _dump_examples(examples: tuple[tuple[str, str], ...]) -> list[dict]:
        return [{'text': text, 'label': label} for text, label in examples]
