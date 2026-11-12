"""End-to-end inference: a taxonomy directory, compiled once, extracted many times."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..taxonomy.loader import TaskLoader
from ..taxonomy.schema import SchemaBuilder
from ..taxonomy.types import TaskType

if TYPE_CHECKING:
    from gliner2.inference.engine import GLiNER2


class InferencePipeline:
    """Compile every document-level task in a taxonomy directory into one schema, then extract."""

    def __init__(self, model: GLiNER2, taxonomy_dir: Path) -> None:
        self._model = model
        tasks = [TaskLoader.load(path) for path in sorted(taxonomy_dir.glob('**/*.yaml'))]
        # Structured tasks run per claim span, not on the whole document.
        tasks = [task for task in tasks if task.type is not TaskType.STRUCTURED]
        self._schema = SchemaBuilder(model).build(tasks)

    def extract(self, text: str, **kwargs: object) -> dict:
        """Run extraction and classification for every compiled task against ``text``."""
        return self._model.extract(text, self._schema, **kwargs)
