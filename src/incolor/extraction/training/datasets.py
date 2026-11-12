"""Convert labeled examples into GLiNER2 training records, per task type."""

from __future__ import annotations

from gliner2 import InputExample, TrainingDataset
from gliner2.training.data import create_classification_example, create_entity_example

from ..taxonomy.types import ClassificationTask, ExtractionTask, TaskSpec


def to_example(task: TaskSpec, text: str, gold: object) -> InputExample:
    """Build one training example for ``task`` from raw gold annotations.

    ``gold`` shape depends on the task type: a mapping of label name to the
    gold spans for extraction, or a label (or list of labels, if
    ``multi_label``) for classification.
    """
    match task:
        case ExtractionTask():
            descriptions = {
                name: entry['description'] for name, entry in task.active_labels.items()
            }
            return create_entity_example(text, entities=gold, descriptions=descriptions)
        case ClassificationTask():
            return create_classification_example(
                text,
                task=task.name,
                labels=list(task.active_labels),
                true_label=gold,
                multi_label=task.multi_label,
            )
        case _:
            raise TypeError(f'Unsupported task type: {type(task).__name__}')


def build_dataset(examples: list[InputExample]) -> TrainingDataset:
    """Collect examples into a validated ``TrainingDataset``."""
    return TrainingDataset(examples)
