"""Base classes for the ordered text steps (strippers and normalisers) and the per-document context they share."""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.sections import Section
from ..core.text import EditableText
from . import patterns as p

if TYPE_CHECKING:
    from incolor.ingestion.corpus.chunks import ResearchDocument


class Vocabulary:
    """Word frequencies across the corpus, used to recognise words split by PDF extraction."""

    def __init__(self, counts: Counter[str] | None = None) -> None:
        self.counts: Counter[str] = counts or Counter()

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> "Vocabulary":
        """Count lower-cased letter runs."""
        counts: Counter[str] = Counter()
        for text in texts:
            counts.update(w.lower() for w in p.WORD_RE.findall(text))
        return cls(counts)

    def __getitem__(self, word: str) -> int:
        return self.counts[word.lower()]


@dataclass
class DocumentContext:
    """What the steps need to know about the document being cleaned."""

    doc: ResearchDocument
    vocabulary: Vocabulary = field(default_factory=Vocabulary)

    @cached_property
    def series(self) -> str:
        """Publication series from the file name ("DB_Fixed Income Blog - X" -> "Fixed Income Blog")."""
        stem = p.SOURCE_PREFIX_RE.sub("", Path(self.doc.name).stem)
        series = stem.split(" - ")[0] if " - " in stem else ""
        return re.sub(r"\s*\(.*?\)", "", series).strip()

    @cached_property
    def bare_stem(self) -> str:
        """File stem without publisher prefix or trade-idea id."""
        return p.SOURCE_PREFIX_RE.sub("", p.DOC_ID_RE.sub("", Path(self.doc.name).stem))

    @cached_property
    def title(self) -> str:
        """Title as printed in the opening text, falling back to the cleaned file name."""
        stem = Path(self.doc.name).stem
        bnp_style = bool(p.DOC_ID_RE.search(stem))
        fallback = re.sub(r"\s+", " ", self.bare_stem.replace("_", " ")).strip()
        words = [w for w in p.SPLIT_WORDS_RE.split(self.bare_stem) if w]
        first = self.doc.chunks[0].text if self.doc.chunks else ""
        # BNP file names are underscored titles that may be truncated, so a prefix of at least half is enough.
        shortest = max(3, (len(words) + 1) // 2) if bnp_style else len(words)
        for n in range(len(words), shortest - 1, -1):
            match = re.search(r"(?<!\w)" + r"[\W_]+".join(map(re.escape, words[:n])) + r"(?!\w)", first, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group()).strip()
        return fallback

    def find_printed_title(self, text: str) -> re.Match[str] | None:
        """Longest match of the title (or a ``" - "`` suffix of the file name, or a 60% prefix) near the start."""
        segments = self.bare_stem.split(" - ")
        candidates = [self.title] + [" - ".join(segments[i:]) for i in range(len(segments))]
        head = text[: p.TITLE_SEARCH_CHARS]
        best: re.Match[str] | None = None
        for candidate in candidates:
            words = [w for w in p.SPLIT_WORDS_RE.split(candidate) if w]
            if len(words) < 2:
                continue
            for size in range(len(words), max(min(len(words), 4), math.ceil(0.6 * len(words))) - 1, -1):
                pattern = r"(?<!\w)" + r"[\W_]+".join(map(re.escape, words[:size])) + r"(?!\w)(?: ?[?!])?"
                match = re.search(pattern, head, re.IGNORECASE)
                if match:
                    if best is None or len(match.group()) > len(best.group()):
                        best = match
                    break
        return best


class TextStep(ABC):
    """One ordered operation on a document's text."""

    rule: str

    @abstractmethod
    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Change ``text`` in place; every change is recorded by ``EditableText``."""


class Stripper(TextStep):
    """Removes text from the content but keeps it as ignored text, tagged with the section it came from."""

    section: Section


class Normaliser(TextStep):
    """Rewrites formatting; each change is logged as an edit."""
