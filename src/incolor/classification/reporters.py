"""Reporters: write classification results to CSV and HTML files."""

import csv
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from .models import DocumentResult
from .taxonomy import Taxonomy

TEMPLATE_PATH = Path(__file__).with_name("review_template.html")

CLASSIFICATION_COLUMNS = [
    "file",
    "title",
    "date",
    "countries",
    "primary_category",
    "primary_subcategory",
    "secondary",
    "document_type",
    "confidence",
    "needs_review",
    "rationale",
    "runner_up",
    "runner_up_reason",
]
ENTITY_COLUMNS = ["file", "entity", "type", "primary_category"]


class Reporter(ABC):
    """Writes one output file from a list of results."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, results: Sequence[DocumentResult]) -> Path:
        """Create parent folders, render and write the file; returns its path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write(sorted(results, key=lambda r: r.file))
        return self.path

    @abstractmethod
    def _write(self, results: Sequence[DocumentResult]) -> None:
        """Render ``results`` (already sorted by file name) to ``self.path``."""


class _CsvReporter(Reporter):
    """Shared CSV writing; subclasses supply the header and the rows."""

    columns: list[str]

    @abstractmethod
    def _rows(self, results: Sequence[DocumentResult]) -> list[dict[str, object]]:
        """One dict per CSV row."""

    def _write(self, results: Sequence[DocumentResult]) -> None:
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(self._rows(results))


class CsvReporter(_CsvReporter):
    """One row per document. Countries are ';'-joined; secondary labels are '; '-joined 'Category > Sub'."""

    columns = CLASSIFICATION_COLUMNS

    def _rows(self, results: Sequence[DocumentResult]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for r in results:
            c = r.classification
            rows.append(
                {
                    "file": r.file,
                    "title": r.title,
                    "date": r.date,
                    "countries": ";".join(c.countries),
                    "primary_category": c.primary.category,
                    "primary_subcategory": c.primary.subcategory,
                    "secondary": "; ".join(str(s) for s in c.secondary),
                    "document_type": c.document_type,
                    "confidence": f"{c.confidence:.2f}",
                    "needs_review": str(r.needs_review).lower(),
                    "rationale": c.rationale,
                    "runner_up": str(c.runner_up),
                    "runner_up_reason": c.runner_up_reason,
                }
            )
        return rows


class EntityReporter(_CsvReporter):
    """One row per entity mention, tagged with the document's primary category."""

    columns = ENTITY_COLUMNS

    def _rows(self, results: Sequence[DocumentResult]) -> list[dict[str, object]]:
        return [
            {"file": r.file, "entity": e.name, "type": e.type, "primary_category": r.classification.primary.category}
            for r in results
            for e in r.classification.entities
        ]


class HtmlReporter(Reporter):
    """Single-file review report: data is embedded as JSON in a dependency-free page."""

    def __init__(self, path: Path, taxonomy: Taxonomy, template: Path = TEMPLATE_PATH) -> None:
        super().__init__(path)
        self._taxonomy = taxonomy
        self._template = template

    def _write(self, results: Sequence[DocumentResult]) -> None:
        payload = {
            "categories": self._taxonomy.categories,
            "threshold": self._taxonomy.confidence_threshold,
            "docs": [self._doc(r) for r in results],
        }
        # "<" is escaped so document text can never close the script element.
        data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
        page = self._template.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
        self.path.write_text(page, encoding="utf-8")

    @staticmethod
    def _doc(r: DocumentResult) -> dict[str, object]:
        c = r.classification
        return {
            "file": r.file,
            "title": r.title,
            "date": r.date,
            "countries": list(c.countries),
            "category": c.primary.category,
            "subcategory": c.primary.subcategory,
            "secondary": [str(s) for s in c.secondary],
            "type": c.document_type,
            "confidence": c.confidence,
            "needs_review": r.needs_review,
            "rationale": c.rationale,
            "runner_up": str(c.runner_up),
            "runner_up_reason": c.runner_up_reason,
            "runner_up_close": c.runner_up_close,
            "text_quality": c.text_quality,
            "entities": [{"name": e.name, "type": e.type} for e in c.entities],
        }
