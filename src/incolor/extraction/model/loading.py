"""Load a GLiNER2 extractor from the Hub or a local checkpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gliner2.inference.engine import GLiNER2


def load_model(source: str, **kwargs: object) -> GLiNER2:
    """Load a GLiNER2 extractor, auto-detecting its architecture.

    ``source`` may be a Hugging Face Hub repo id or a local checkpoint
    directory — ``AutoExtractor`` resolves both the same way.
    """
    from gliner2 import AutoExtractor

    return AutoExtractor.from_pretrained(source, **kwargs)
