"""Deterministic sentence tagging of Stage 1 output: markdown lines first, then pysbd (rule-based) within each line.

Headings are one unit each; bullet markers are kept out of the sentence text. Offsets refer to ``resolved()`` and are
mapped back to the source through the marks.
"""

import re
from dataclasses import dataclass

import pysbd

from .annotated import AnnotatedText

HEADING = re.compile(r"#{1,6}[ \t]+")
BULLET = re.compile(r"[ \t]*(?:[-*•]|\d{1,2}[.)])[ \t]+")


@dataclass(frozen=True)
class Sentence:
    """One tagged sentence; ``start``/``end`` index ``resolved()``, ``src_start``/``src_end`` the source."""

    id: str
    kind: str
    text: str
    text_brackets: str
    source: str
    start: int
    end: int
    src_start: int
    src_end: int
    splits_mark: bool


def split_sentences(annotated: AnnotatedText) -> list[Sentence]:
    """Return the sentences of ``annotated.resolved()`` numbered ``E001``, ``E002``, ... (at least three digits)."""
    text = annotated.resolved()
    source = annotated.original()
    segmenter = pysbd.Segmenter(language="en", clean=False)
    spans: list[tuple[str, int, int]] = []
    line_start = 0
    for line in text.split("\n"):
        line_end = line_start + len(line)
        heading, bullet = HEADING.match(line), BULLET.match(line)
        body_start = line_start + (heading or bullet).end() if heading or bullet else line_start
        body = text[body_start:line_end].rstrip()
        if heading and body:
            spans.append(("heading", body_start, body_start + len(body)))
        elif body.strip():
            # pysbd pairs straight apostrophes ('26 ... buybacks') as quotes and stops splitting between them.
            masked = body.replace("'", "\u2019")
            cursor = 0
            for piece in segmenter.segment(masked):
                piece = piece.strip()
                if not piece:
                    continue
                i = masked.find(piece, cursor)
                if i < 0:
                    raise ValueError(f"pysbd segment not found in line: {piece!r}")
                spans.append(("bullet" if bullet else "text", body_start + i, body_start + i + len(piece)))
                cursor = i + len(piece)
        line_start = line_end + 1

    out: list[Sentence] = []
    for n, (kind, start, end) in enumerate(spans, start=1):
        src_start, src_end = annotated.to_source(start, end)
        out.append(
            Sentence(
                id=f"E{n:03d}",
                kind=kind,
                text=text[start:end],
                text_brackets=annotated.resolved_slice(start, end, brackets=True),
                source=source[src_start:src_end],
                start=start,
                end=end,
                src_start=src_start,
                src_end=src_end,
                splits_mark=annotated.splits_mark(start, end),
            )
        )
    return out
