"""Document classification against a YAML taxonomy (see README.md in this folder)."""

from .classifier import ClassificationError, Classifier, ClaudeClassifier
from .models import Classification, Document, DocumentResult, Entity, Label
from .pipeline import Pipeline, PipelineSummary
from .reporters import CsvReporter, EntityReporter, HtmlReporter, Reporter
from .taxonomy import Taxonomy

__all__ = [
    "Classification",
    "ClassificationError",
    "Classifier",
    "ClaudeClassifier",
    "CsvReporter",
    "Document",
    "DocumentResult",
    "Entity",
    "EntityReporter",
    "HtmlReporter",
    "Label",
    "Pipeline",
    "PipelineSummary",
    "Reporter",
    "Taxonomy",
]
