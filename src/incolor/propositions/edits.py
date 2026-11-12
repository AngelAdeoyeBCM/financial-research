"""Stage 1 edits: the one stored record of normalisation, from which every text view is derived.

A run keeps ``edits.jsonl`` and, in ``run.json`` (``validation.json`` in older runs), the path of the sample it was
made on; the offsets index that sample's body (``document.load_body``). Each edit replaces ``source[start:end]`` with
``text`` (``start == end`` inserts; spaces belong to ``text``) and records the source spans it was copied from
(``pointers``), the referent it resolves to (references only; one id per referent, so edits sharing it corefer) and,
for an ambiguous reference left unresolved, the candidate antecedents. ``annotate`` turns source and edits into an
``AnnotatedText``, so the marked text (``{{original => text}}``), the bracketed and plain resolved text, offsets and
sentences are all computed, never stored.
"""

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .annotated import RESERVED, AnnotatedText, link_antecedents
from .document import load_body
from .sentences import Sentence, split_sentences

Span = tuple[int, int]
VIEWS = ("marks", "brackets", "plain", "sentences")


@dataclass(frozen=True)
class Edit:
    """Replace ``source[start:end]`` with ``text``; ``kind`` names the phenomenon (None for legacy marks)."""

    start: int
    end: int
    text: str
    kind: str | None = None
    pointers: tuple[Span, ...] = ()
    candidates: tuple[Span, ...] = ()
    referent: str | None = None

    def to_json(self, source: str) -> dict[str, Any]:
        """Return the JSONL record; quoted ``original`` and span texts make it readable and are checked on load."""

        def spans(items: tuple[Span, ...]) -> list[dict[str, Any]]:
            return [{"start": a, "end": b, "text": source[a:b]} for a, b in items]

        record = {
            "start": self.start,
            "end": self.end,
            "original": source[self.start : self.end],
            "text": self.text,
            "kind": self.kind,
            "pointers": spans(self.pointers),
            "candidates": spans(self.candidates),
        }
        return {**record, "referent": self.referent} if self.referent else record

    @classmethod
    def from_json(cls, record: dict[str, Any], source: str) -> "Edit":
        """Parse one record, raising ``ValueError`` if a quoted text no longer matches the source."""

        def spans(key: str) -> tuple[Span, ...]:
            out = []
            for s in record.get(key) or []:
                if "text" in s and source[s["start"] : s["end"]] != s["text"]:
                    raise ValueError(f"{key} span {s['start']}-{s['end']} does not match the source: {s['text']!r}")
                out.append((s["start"], s["end"]))
            return tuple(out)

        start, end = record["start"], record["end"]
        if "original" in record and source[start:end] != record["original"]:
            raise ValueError(f"edit at {start}-{end} does not match the source: {record['original']!r}")
        return cls(
            start,
            end,
            record["text"],
            record.get("kind"),
            spans("pointers"),
            spans("candidates"),
            record.get("referent"),
        )


def check_edits(source: str, edits: Sequence[Edit]) -> None:
    """Raise ``ValueError`` unless the edits are in order, inside the source, non-overlapping and free of markup."""
    prev: Edit | None = None
    for e in edits:
        if not 0 <= e.start <= e.end <= len(source):
            raise ValueError(f"edit {e.start}-{e.end} is outside the source")
        if prev is not None and e.start < prev.end:
            raise ValueError(f"edit {e.start}-{e.end} overlaps the previous edit or is out of order")
        if prev is not None and prev.start == prev.end == e.start == e.end:
            raise ValueError(f"two insertions at offset {e.start}; merge them")
        if not e.text.strip():
            raise ValueError(f"edit {e.start}-{e.end} has empty text")
        if any(t in e.text for t in RESERVED):
            raise ValueError(f"edit {e.start}-{e.end} contains a reserved token: {e.text!r}")
        prev = e


def annotate(source: str, edits: Sequence[Edit]) -> AnnotatedText:
    """Return the ``AnnotatedText`` for ``source`` with ``edits`` applied as marks."""
    check_edits(source, edits)
    pieces: list[str] = []
    pos = 0
    for e in edits:
        pieces += [source[pos : e.start], f"{{{{{source[e.start : e.end]} => {e.text}}}}}"]
        pos = e.end
    pieces.append(source[pos:])
    text = AnnotatedText("".join(pieces))
    if text.original() != source or [m.resolution for m in text.marks] != [e.text for e in edits]:
        raise ValueError("edits do not round-trip through the marked text")
    return text


def edits_from_annotated(text: AnnotatedText, source: str) -> list[Edit]:
    """Return the edits behind a model-written marked text, dropping zero-edit marks.

    Kinds and pointers come from the reference log when there is one; otherwise pointers are the source spans the
    resolution copies verbatim.
    """
    entries = text.log_entries()
    copied = link_antecedents(text, source)
    out = []
    for k, m in enumerate(text.marks):
        if m.original == m.resolution:
            continue
        logged = text.antecedent_spans(k, source) if k < len(entries) else []
        kind = entries[k].get("type") if k < len(entries) else None
        out.append(Edit(m.src_start, m.src_end, m.resolution, kind, tuple(logged or copied[k])))
    return out


def write_edits(path: Path, source: str, edits: Iterable[Edit]) -> None:
    """Write ``edits.jsonl`` (UTF-8, LF)."""
    lines = (json.dumps(e.to_json(source), ensure_ascii=False) + "\n" for e in edits)
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def read_edits(path: Path, source: str) -> list[Edit]:
    """Read and check ``edits.jsonl`` against ``source``."""
    lines = path.read_text(encoding="utf-8").splitlines()
    edits = [Edit.from_json(json.loads(line), source) for line in lines if line.strip()]
    check_edits(source, edits)
    return edits


def source_ref(run_dir: Path, source_path: Path) -> str:
    """Return how a run records its sample: the path relative to the run folder, with forward slashes."""
    return Path(os.path.relpath(source_path.resolve(), run_dir.resolve())).as_posix()


def run_report(run_dir: Path) -> dict[str, Any]:
    """Return a run's report: ``run.json``, or ``validation.json`` for runs made before it existed."""
    path = run_dir / "run.json"
    return json.loads((path if path.exists() else run_dir / "validation.json").read_text(encoding="utf-8"))


def source_path(run_dir: Path) -> Path:
    """Return the sample file a run was made on, from ``summary.source`` in its report."""
    return (run_dir / run_report(run_dir)["summary"]["source"]).resolve()


def load_run(run_dir: Path) -> tuple[str, list[Edit], AnnotatedText]:
    """Return the source body, edits and annotated text of a normalise run folder."""
    source, _ = load_body(source_path(run_dir))
    edits = read_edits(run_dir / "edits.jsonl", source)
    return source, edits, annotate(source, edits)


def render(text: AnnotatedText, view: str) -> str:
    """Return one view of the run: ``marks``, ``brackets``, ``plain`` or ``sentences`` (``[E001] text`` lines)."""
    if view == "marks":
        return text.marked
    if view == "brackets":
        return text.resolved(brackets=True)
    if view == "plain":
        return text.resolved()
    if view == "sentences":
        return "".join(f"[{s.id}] {s.text_brackets}\n" for s in split_sentences(text)).removesuffix("\n")
    raise ValueError(f"unknown view {view!r}; expected one of {VIEWS}")


def sentences(run_dir: Path) -> list[Sentence]:
    """Return the tagged sentences of a normalise run folder."""
    return split_sentences(load_run(run_dir)[2])
