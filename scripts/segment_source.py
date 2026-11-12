"""Stage 0 source segmentation for markdown-structured research samples (YAML front matter, ``#`` headings, lists).

Writes one JSON record per segment with ``id``, ``kind`` (sentence | fragment | heading), ``container`` (metadata |
heading | run_in_heading | paragraph | list_item), ``text`` and ``start``/``end`` offsets into the source. YAML front
matter is not segmented; it is read only for the ``Title``. Every segment is checked to be an exact substring of the
unchanged source before anything is written.

Usage::

    python scripts/segment_source.py
    python scripts/segment_source.py --input samples/<doc>.txt --out outputs/framing_v02
"""

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from incolor.propositions.document import front_matter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "samples" / "BofA_Sept_FOMC_-_hike_or_bond_spike.txt"
DEFAULT_OUT = ROOT / "outputs" / "framing_v02"

HEADING = re.compile(r"(#{1,6})[ \t]+")
LIST_MARKER = re.compile(r"[ \t]*(?:[-*•]|\d{1,2}[.)])[ \t]+")
SENTENCE_END = re.compile(r"[.!?][”\"’)\]]*(?=\s+[A-Z0-9“\"‘’'(\[])")
TERMINAL = re.compile(r"[.!?][”\"’)\]]*$")
# Run-in label such as "Hawkish presser:" or "Bullish USD case:": 1-3 words, no comma, text after the colon.
RUN_IN = re.compile(r"[A-Z][\w’'&/-]*(?: [\w’'&/-]+){0,2}:(?=[ \t]+\S)")
ABBREVIATIONS = {
    "gov",
    "vs",
    "dr",
    "mr",
    "mrs",
    "ms",
    "st",
    "no",
    "e.g",
    "i.e",
    "etc",
    "inc",
    "co",
    "jr",
    "approx",
    "fig",
    "u.s",
    "u.k",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}
# Coarse finite-verb signal; strings with none of these are treated as verbless fragments.
VERBISH = re.compile(
    r"\b(?:is|are|was|were|be|been|being|am|will|would|could|should|may|might|can|must|shall|do|"
    r"does|did|has|have|had|to \w+)\b|\b\w+(?:ed|ing|[^s\W]s)\b|="
)
ELLIPTICAL_START = re.compile(r"(?:Or|And|But) (?:if|when|unless|because|although|though|while)\b")


@dataclass(frozen=True)
class Segment:
    """One evidence unit; ``start``/``end`` are character offsets into the unchanged source."""

    id: str
    kind: str
    container: str
    text: str
    start: int
    end: int

    def record(self) -> dict[str, str | int]:
        """Return the output record."""
        return {
            "id": self.id,
            "kind": self.kind,
            "container": self.container,
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }


def lines_with_offsets(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Return ``(start, end)`` of each line in ``text[start:end]``, excluding line terminators."""
    spans, pos = [], start
    while pos < end:
        nl = text.find("\n", pos, end)
        stop = end if nl < 0 else nl
        spans.append((pos, stop - 1 if stop > pos and text[stop - 1] == "\r" else stop))
        pos = stop + 1
    return spans


def strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink ``[start, end)`` so it excludes surrounding whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into sentence spans without breaking after abbreviations or initials."""
    spans, begin = [], start
    for m in SENTENCE_END.finditer(text, start, end):
        word = re.search(r"(?:^|[\s(])([A-Za-z][A-Za-z.]*)$", text[begin : m.start()])
        if word and (word.group(1).lower() in ABBREVIATIONS or (len(word.group(1)) == 1 and word.group(1).isupper())):
            continue
        spans.append(strip_span(text, begin, m.end()))
        begin = m.end()
    spans.append(strip_span(text, begin, end))
    return [s for s in spans if s[0] < s[1]]


def grammatical_kind(sentence: str) -> str:
    """Return ``sentence`` for terminated clauses with a verb signal, else ``fragment``."""
    if not TERMINAL.search(sentence) or ELLIPTICAL_START.match(sentence) or not VERBISH.search(sentence):
        return "fragment"
    return "sentence"


def segment(source: str) -> list[Segment]:
    """Segment ``source`` into evidence units in document order."""
    out: list[Segment] = []

    def add(kind: str, container: str, start: int, end: int) -> None:
        out.append(Segment(f"E{len(out) + 1:03d}", kind, container, source[start:end], start, end))

    body_start, title = front_matter(source)
    seen_section = False
    lines = [strip_span(source, *span) for span in lines_with_offsets(source, body_start, len(source))]
    i = 0
    while i < len(lines):
        start, end = lines[i]
        if start == end:
            i += 1
            continue
        heading = HEADING.match(source, start, end)
        if heading:
            seen_section = seen_section or len(heading.group(1)) >= 2
            add("heading", "heading", heading.end(), end)
            i += 1
            continue
        marker = LIST_MARKER.match(source, start, end)
        if marker:
            container, block = "list_item", (marker.end(), end)
            i += 1
        else:
            j = i
            while (
                j + 1 < len(lines)
                and lines[j + 1][0] < lines[j + 1][1]
                and not HEADING.match(source, *lines[j + 1])
                and not LIST_MARKER.match(source, *lines[j + 1])
            ):
                j += 1
            container, block = "paragraph", (start, lines[j][1])
            i = j + 1
            text = source[block[0] : block[1]]
            if not seen_section and "\n" not in text and not TERMINAL.search(text):
                # Standalone pre-section line: the document title or masthead metadata (e.g. series name).
                if text == title:
                    add("heading", "heading", *block)
                else:
                    add("fragment", "metadata", *block)
                continue
        for s_start, s_end in split_sentences(source, *block):
            label = RUN_IN.match(source, s_start, s_end)
            if label:
                add("heading", "run_in_heading", s_start, label.end())
                s_start, s_end = strip_span(source, label.end(), s_end)
            add(grammatical_kind(source[s_start:s_end]), container, s_start, s_end)
    return out


def validate(source: str, segments: list[Segment]) -> None:
    """Raise if a segment is not an exact substring or segments overlap or run out of document order."""
    for a, b in pairwise(segments):
        if b.start < a.end:
            raise ValueError(f"{b.id} overlaps or precedes {a.id}")
    for s in segments:
        if source[s.start : s.end] != s.text or not s.text:
            raise ValueError(f"{s.id} does not match the source at [{s.start}:{s.end}]")


def main() -> None:
    """Segment the input document and write ``segments.jsonl``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="source document")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as f:
        source = f.read()
    segments = segment(source)
    validate(source, segments)
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "segments.jsonl"
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for s in segments:
            f.write(json.dumps(s.record(), ensure_ascii=False) + "\n")
    counts = Counter((s.kind, s.container) for s in segments)
    print(f"wrote {len(segments)} segments to {out_path}")
    for (kind, container), n in sorted(counts.items()):
        print(f"  {kind:<9} {container:<15} {n}")


if __name__ == "__main__":
    main()
