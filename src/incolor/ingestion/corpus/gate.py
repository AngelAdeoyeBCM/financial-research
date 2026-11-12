"""Corruption gate: documents with damaged or non-text chunks are skipped (and logged), never cleaned."""

import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from functools import cached_property

from ...parsing.corpus import patterns as p
from .chunks import ResearchDocument

SKIP = "skip"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """A gate finding. ``reprocess`` names what a later pass could recover (e.g. ``chart``).

    ``severity`` is ``skip`` (the document is not compiled) or ``warning`` (compiled, tagged with the code).
    """

    code: str
    detail: str
    chunk_id: str | None = None
    reprocess: str | None = None
    severity: str = SKIP


class ChunkProfile:
    """Token and word statistics of one chunk's text, computed once and shared by the checks."""

    def __init__(self, text: str) -> None:
        self.text = text

    @cached_property
    def tokens(self) -> list[str]:
        """Whitespace tokens."""
        return self.text.split()

    @cached_property
    def words(self) -> list[str]:
        """Lower-cased letter runs."""
        return [w.lower() for w in p.WORD_RE.findall(self.text)]

    @cached_property
    def english(self) -> int:
        """English function words."""
        return sum(w in p.ENGLISH_STOPWORDS for w in self.words)

    @cached_property
    def foreign(self) -> int:
        """French/German/Spanish/Italian/Portuguese function words."""
        return sum(w in p.FOREIGN_STOPWORDS for w in self.words)

    @cached_property
    def axis_runs(self) -> list[list[str]]:
        """Maximal runs of consecutive numeric/date tokens."""
        runs: list[list[str]] = []
        current: list[str] = []
        for token in self.tokens:
            if p.AXIS_TOKEN_RE.fullmatch(token):
                current.append(token)
                continue
            if current:
                runs.append(current)
            current = []
        if current:
            runs.append(current)
        return runs


class CorruptionCheck(ABC):
    """One test on a chunk's text; returns ``(code, detail)`` pairs."""

    reprocess: str | None = None
    severity: str = SKIP

    @abstractmethod
    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """Problems found in the chunk."""


class GarbledTextCheck(CorruptionCheck):
    """Control characters, replacement characters, maths alphanumerics and private-use glyphs (not bullets)."""

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``GARBLED_TEXT`` listing the offending code points."""
        garbled = Counter(f"U+{ord(ch):04X}" for ch in chunk.text if self._is_garbled(ch))
        if not garbled:
            return []
        return [("GARBLED_TEXT", "unrendered characters " + ", ".join(f"{k} x{v}" for k, v in garbled.items()))]

    @staticmethod
    def _is_garbled(ch: str) -> bool:
        category = unicodedata.category(ch)
        return (
            (category == "Cc" and ch not in "\t\n\r\x98")
            or ch == "\ufffd"
            or 0x1D400 <= ord(ch) <= 0x1D7FF
            or (category == "Co" and ch not in p.BULLET_CHARS)
        )


class ForeignScriptCheck(CorruptionCheck):
    """Letters from non-Latin scripts."""

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``NON_ENGLISH_SCRIPT`` listing the scripts found."""
        scripts: Counter[str] = Counter()
        for ch in chunk.text:
            if ch.isalpha() and (name := unicodedata.name(ch, "")).startswith(p.NON_LATIN_SCRIPTS):
                scripts[name.split()[0]] += 1
        if sum(scripts.values()) < p.MIN_FOREIGN_SCRIPT_LETTERS:
            return []
        return [("NON_ENGLISH_SCRIPT", "letters in " + ", ".join(f"{k} x{v}" for k, v in scripts.items()))]


class ForeignLanguageCheck(CorruptionCheck):
    """More foreign than English function words."""

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``NON_ENGLISH_TEXT``."""
        if (
            len(chunk.words) >= p.MIN_WORDS_FOR_LANGUAGE
            and chunk.foreign >= p.MIN_FOREIGN_STOPWORDS
            and chunk.foreign > chunk.english
        ):
            return [("NON_ENGLISH_TEXT", f"{chunk.foreign} non-English vs {chunk.english} English function words")]
        return []


class ChartDebrisCheck(CorruptionCheck):
    """Flattened charts and tables: glued labels, long axis runs, numeric-heavy text, numeric rows."""

    reprocess = "chart"

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """At most one ``DISTORTED_FIGURE`` or ``DISTORTED_TABLE``."""
        runs = chunk.axis_runs
        glued = [t for t in chunk.tokens if not t.startswith("+") and p.GLUED_NUMBERS_RE.search(t)]
        glued_words = p.GLUED_WORDS_RE.findall(chunk.text)
        if glued or len(glued_words) >= p.MAX_GLUED_WORDS:
            return [("DISTORTED_FIGURE", f"chart labels without spaces: {' '.join((glued + glued_words)[:6])}")]
        long_runs = [r for r in runs if len(r) >= p.MAX_AXIS_RUN]
        if long_runs:
            figure = next((r for r in long_runs if self._looks_like_axis(r)), None)
            run = figure or max(long_runs, key=len)
            code = "DISTORTED_FIGURE" if figure else "DISTORTED_TABLE"
            return [(code, f"{len(run)} consecutive numeric/date tokens: {' '.join(run[:12])}")]
        numeric = sum(len(r) for r in runs)
        if len(chunk.tokens) >= p.MIN_TOKENS_FOR_SHARE and numeric / len(chunk.tokens) >= p.MAX_NUMERIC_SHARE:
            return [("DISTORTED_TABLE", f"{numeric / len(chunk.tokens):.0%} of tokens are numeric/date values")]
        if sum(len(r) >= 4 for r in runs) >= p.MIN_TABLE_ROWS:
            rows = [" ".join(r) for r in runs if len(r) >= 4]
            return [("DISTORTED_TABLE", f"{len(rows)} numeric rows: {' | '.join(rows[:3])}")]
        return []

    @staticmethod
    def _looks_like_axis(run: list[str]) -> bool:
        """True for evenly spaced tick values or a sequence of date labels (a flattened chart axis)."""
        dates = streak = 0
        for token in run:
            dates = dates + 1 if p.DATE_TOKEN_RE.fullmatch(token) else 0
            if dates >= 4:
                return True
        values = [
            float(m.group().replace("−", "-")) if (m := p.NUMBER_RE.fullmatch(t.rstrip("%,;"))) else None for t in run
        ]
        for a, b, c in zip(values, values[1:], values[2:], strict=False):
            streak = streak + 1 if None not in (a, b, c) and b != a and abs((b - a) - (c - b)) < 1e-9 else 0  # type: ignore[operator]
            if streak >= 3:
                return True
        return False


class TemplateTextCheck(CorruptionCheck):
    """Unfilled document-template placeholders."""

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``TEMPLATE_TEXT``."""
        if template := p.TEMPLATE_RE.search(chunk.text):
            return [("TEMPLATE_TEXT", f"document template text: {template.group()!r}")]
        return []


class UnstructuredTextCheck(CorruptionCheck):
    """Label soup: too few English function words for running text (contact lists excepted)."""

    reprocess = "chart"

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``UNSTRUCTURED_TEXT``."""
        contacts = len(p.EMAIL_RE.findall(chunk.text)) >= 2
        words = chunk.words
        if (
            len(words) >= p.MIN_WORDS_FOR_LANGUAGE
            and chunk.english / len(words) < p.MIN_STOPWORD_SHARE
            and not contacts
        ):
            return [("UNSTRUCTURED_TEXT", f"only {chunk.english / len(words):.0%} of words are English function words")]
        return []


class FigureCaptionCheck(CorruptionCheck):
    """Figure/exhibit/table titles and source lines: the chart they describe was not extracted.

    A warning only: the document is compiled and tagged, so it can be filtered out later.
    """

    reprocess = "chart"
    severity = WARNING
    _TERMINAL = (".", ":", ";", "!", "?")

    def check(self, chunk: ChunkProfile) -> list[tuple[str, str]]:
        """``FIGURE_CAPTION`` for the first caption or source line found."""
        text = chunk.text
        for match in p.FIGURE_LABEL_RE.finditer(text):
            if match.group().endswith(":") or not self._in_text_reference(text, match.start()):
                return [("FIGURE_CAPTION", f"missing chart: {text[match.start() : match.start() + 100]!r}")]
        if source := p.SOURCE_RE.search(text):
            return [("FIGURE_CAPTION", f"missing chart: {source.group()[:100]!r}")]
        return []

    @classmethod
    def _in_text_reference(cls, text: str, start: int) -> bool:
        # "as shown in Figure 4." is a reference; "... rates. Figure 4. Spreads" is a caption.
        previous = text[max(0, start - 30) : start].split()
        return bool(previous) and previous[-1][:1].islower() and not previous[-1].endswith(cls._TERMINAL)


class CorruptionGate:
    """Runs every check on every chunk. Skip-severity issues stop compilation; warnings are passed on."""

    def __init__(self, checks: list[CorruptionCheck] | None = None) -> None:
        self.checks = checks or [
            GarbledTextCheck(),
            ForeignScriptCheck(),
            ForeignLanguageCheck(),
            ChartDebrisCheck(),
            TemplateTextCheck(),
            UnstructuredTextCheck(),
            FigureCaptionCheck(),
        ]

    def inspect(self, doc: ResearchDocument) -> list[Issue]:
        """All issues in ``doc``; empty when it may be compiled."""
        issues: list[Issue] = []
        if missing := doc.missing_indices:
            issues.append(Issue("MISSING_CHUNKS", f"missing indices {missing}", reprocess="refetch"))
        for chunk in doc.chunks:
            if not chunk.text:
                issues.append(Issue("EMPTY_TEXT", "chunk has no text", chunk.chunk_id, "refetch"))
                continue
            profile = ChunkProfile(chunk.text)
            for check in self.checks:
                issues.extend(
                    Issue(code, detail, chunk.chunk_id, check.reprocess, check.severity)
                    for code, detail in check.check(profile)
                )
        return issues
