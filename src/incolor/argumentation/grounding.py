"""Locate evidence spans in the source and measure how much of the source a map accounts for."""

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .schema import ArgumentMap, ModelOutput

# One-to-one character folds, so a folded string keeps the offsets of the original.
_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u00b4": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u2009": " ",
        "\u202f": " ",
    }
)
SNAP_MIN_RATIO = 0.85
MAX_LENGTH_DRIFT = 0.25
MAX_GAP_CHARS = 400
# A page break can carry footnotes; it is recognised by the running header or footer that starts it.
MAX_PAGE_BREAK_CHARS = 3000
MIN_GAP_PART_CHARS = 15
MIN_ANCHOR_CHARS = 20
SENTENCE_COVERED_SHARE = 0.5
# A gap that contains a sentence boundary is skipped text, not page furniture.
_SENTENCE_BOUNDARY = re.compile(r"[.!?] +[A-Z][a-z]")
# Running headers and footers such as "10 September 2026 2 Barclays | FX Views" or "Liquid Insight | 14 September".
_PAGE_FURNITURE = re.compile(r"^ ?(?:\d{1,2} [A-Z][a-z]+ \d{4} \d{1,3}\b|[A-Z][\w&.\- ]{1,40} \| )")
# An omitted parenthetical such as "(see Curb your (y)enthusiasm, 6 September)", with one level of nesting.
_PARENTHETICAL = re.compile(r"^ ?\((?:[^()]|\([^()]*\))*\)$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def squash(text: str) -> str:
    """Collapse whitespace runs and strip the ends."""
    return " ".join(text.split())


def fold(text: str) -> str:
    """Map curly quotes, dash variants and special spaces to ASCII, keeping the length."""
    return text.translate(_FOLD)


@dataclass(frozen=True)
class SpanMatch:
    """Where a span sits in the source. ``method`` is exact, folded, gap or fuzzy; ``score`` is 1.0 unless fuzzy."""

    start: int
    end: int
    method: str
    score: float


def locate(span: str, source: str, folded_source: str | None = None) -> SpanMatch | None:
    """Find ``span`` in the whitespace-squashed ``source``.

    Tries, in order: an exact match; a match after folding quotes and dashes; a match across one gap of page furniture
    (headers, footers or chart labels inside the sentence); and a fuzzy alignment of at least ``SNAP_MIN_RATIO``.
    """
    text = squash(span)
    if not text:
        return None
    index = source.find(text)
    if index >= 0:
        return SpanMatch(index, index + len(text), "exact", 1.0)
    folded = folded_source if folded_source is not None else fold(source)
    folded_text = fold(text)
    index = folded.find(folded_text)
    if index >= 0:
        return SpanMatch(index, index + len(folded_text), "folded", 1.0)
    return _gap_match(folded_text, folded) or _fuzzy_match(folded_text, folded)


def _gap_match(text: str, source: str) -> SpanMatch | None:
    splits = [m.start() for m in re.finditer(r" |(?=[.,;:]$)", text)]
    for split in splits:
        head, tail = text[:split], text[split:]
        short_tail = len(tail.strip()) < MIN_GAP_PART_CHARS
        if len(head) < MIN_GAP_PART_CHARS or (short_tail and not tail.strip()):
            continue
        start = source.find(head)
        while start >= 0:
            gap_start = start + len(head)
            window = source[gap_start : gap_start + MAX_PAGE_BREAK_CHARS + len(tail)]
            offset = window.find(tail)
            # Include the characters either side of the gap, so a sentence it starts or ends is seen.
            context = source[max(0, gap_start - 1) : gap_start + offset + 3]
            furniture = offset <= MAX_GAP_CHARS and not _SENTENCE_BOUNDARY.search(context)
            page_break = _PAGE_FURNITURE.match(window)
            parenthetical = _PARENTHETICAL.match(window[:offset]) if offset > 0 else None
            if offset > 0 and (parenthetical or (not short_tail and (furniture or page_break))):
                end = gap_start + offset + len(tail)
                return SpanMatch(start, end, "gap", round(len(text) / (end - start), 3))
            start = source.find(head, start + 1)
    return None


def _fuzzy_match(text: str, source: str) -> SpanMatch | None:
    anchor = difflib.SequenceMatcher(None, source, text, autojunk=False).find_longest_match(
        0, len(source), 0, len(text)
    )
    if anchor.size < MIN_ANCHOR_CHARS:
        return None
    low = max(0, anchor.a - anchor.b - 60)
    high = min(len(source), anchor.a - anchor.b + len(text) + 60)
    window = source[low:high]
    blocks = [b for b in difflib.SequenceMatcher(None, window, text, autojunk=False).get_matching_blocks() if b.size]
    start = max(0, blocks[0].a - blocks[0].b)
    last = blocks[-1]
    end = min(len(window), last.a + last.size + len(text) - last.b - last.size)
    candidate = window[start:end]
    score = difflib.SequenceMatcher(None, candidate, text, autojunk=False).ratio()
    if score < SNAP_MIN_RATIO or abs(len(candidate) - len(text)) > MAX_LENGTH_DRIFT * len(text):
        return None
    return SpanMatch(low + start, low + end, "fuzzy", round(score, 3))


def sentence_spans(source: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` offsets of the sentences in the squashed ``source``."""
    spans, start = [], 0
    for boundary in _SENTENCE_END.finditer(source):
        spans.append((start, boundary.start()))
        start = boundary.end()
    if start < len(source):
        spans.append((start, len(source)))
    return spans


@dataclass(frozen=True)
class Coverage:
    """How the source sentences are accounted for: cited as evidence, listed as exclusions, or silently skipped.

    ``must_keep_silent`` holds the skipped sentences that match a must-keep pattern.
    """

    sentences: int
    cited: int
    excluded: int
    silent: int
    must_keep: int
    must_keep_silent: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        """Return the counts, for ``summary.json``."""
        return {
            "sentences": self.sentences,
            "cited": self.cited,
            "excluded": self.excluded,
            "silent": self.silent,
            "must_keep": self.must_keep,
            "must_keep_silent": len(self.must_keep_silent),
        }


def coverage(map_: ArgumentMap | ModelOutput, source: str, must_keep_patterns: Mapping[str, str]) -> Coverage:
    """Classify each source sentence as cited, excluded or silent; a sentence counts when half of it is covered."""
    source = squash(source)
    folded = fold(source)
    cited = _intervals((e.text for e in map_.evidence), source, folded)
    excluded = _intervals((x.text for x in map_.exclusions), source, folded)
    patterns = [re.compile(p, re.IGNORECASE) for p in must_keep_patterns.values()]
    counts = {"cited": 0, "excluded": 0, "silent": 0}
    must_keep, must_keep_silent = 0, []
    spans = sentence_spans(source)
    for start, end in spans:
        if _covered(start, end, cited):
            status = "cited"
        elif _covered(start, end, excluded):
            status = "excluded"
        else:
            status = "silent"
        counts[status] += 1
        sentence = source[start:end]
        if any(p.search(sentence) for p in patterns):
            must_keep += 1
            if status == "silent":
                must_keep_silent.append(sentence)
    return Coverage(len(spans), counts["cited"], counts["excluded"], counts["silent"], must_keep, must_keep_silent)


def _intervals(texts: Iterable[str], source: str, folded: str) -> list[tuple[int, int]]:
    found = sorted((m.start, m.end) for m in (locate(text, source, folded) for text in texts) if m is not None)
    merged: list[tuple[int, int]] = []
    for start, end in found:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _covered(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    overlap = sum(max(0, min(end, b) - max(start, a)) for a, b in intervals)
    return overlap >= SENTENCE_COVERED_SHARE * (end - start)
