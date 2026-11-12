"""Load source documents and normalise them so evidence spans can be matched verbatim."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class InputError(ValueError):
    """Raised when an input file cannot be used (missing, empty, or too long)."""


@dataclass(frozen=True)
class PreprocessConfig:
    """Preprocessing settings: page-furniture regexes and the input size limit."""

    furniture_patterns: list[str] = field(default_factory=list)
    max_input_chars: int = 120_000


@dataclass
class SourceDocument:
    """A loaded document. Evidence is matched against ``text``, the normalised form."""

    path: Path
    raw_text: str
    text: str
    metadata: dict[str, Any]


def load_document(path: Path, config: PreprocessConfig) -> SourceDocument:
    """Load a ``.pdf`` or text file and normalise it.

    Raises:
        InputError: If the file is missing or the normalised text exceeds ``max_input_chars``.
    """
    path = Path(path)
    if not path.is_file():
        raise InputError(f"Input file not found: {path}")
    metadata: dict[str, Any] = {"filename": path.name}
    if path.suffix.lower() == ".pdf":
        raw_text, page_count = _read_pdf(path)
        metadata["page_count"] = page_count
    else:
        raw_text = path.read_text(encoding="utf-8-sig")
    text = normalise(raw_text, config.furniture_patterns)
    if not text:
        raise InputError(f"Input file has no text after normalisation: {path}")
    if len(text) > config.max_input_chars:
        raise InputError(
            f"Input is {len(text)} characters after normalisation; the limit is {config.max_input_chars}. "
            "Chunking is not supported in v1."
        )
    metadata["char_count"] = len(text)
    return SourceDocument(path=path, raw_text=raw_text, text=text, metadata=metadata)


def normalise(text: str, furniture_patterns: list[str]) -> str:
    r"""Normalise source text in the four fixed steps the gold files depend on.

    Furniture patterns are regular expressions. A pattern that contains ``\\n`` matches the raw line layout, so it is
    applied before whitespace collapse. All other patterns are applied after collapse.

    1. Replace each multi-line furniture pattern with a single space.
    2. Join line-break hyphenation (``capex-\\nintensive`` becomes ``capex-intensive``).
    3. Collapse all whitespace runs to single spaces.
    4. Replace each remaining furniture pattern with a single space, then collapse whitespace again.
    """
    multiline = [p for p in furniture_patterns if r"\n" in p]
    inline = [p for p in furniture_patterns if r"\n" not in p]
    for pattern in multiline:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"-\n(?=\w)", "-", text)
    text = re.sub(r"\s+", " ", text)
    for pattern in inline:
        text = re.sub(pattern, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _read_pdf(path: Path) -> tuple[str, int]:
    """Extract text from every page of a PDF, joined by blank lines."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise InputError("Reading PDF input requires pypdf: pip install 'pypdf>=4'") from exc
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), len(pages)
