"""What every Stage 1 step shares: the document with its sentences and rule edits, and quote lookup.

A model stage sees the document one sentence per line (``E### text``) and answers with sentence ids plus words copied
from those sentences; ``find``, ``locate`` and ``target`` turn those quotes into source spans or a reason they fail.
"""

import re
from dataclasses import dataclass
from typing import Any

from ..argumentation.grounding import fold
from .annotated import WORD, AnnotatedText, _stem
from .edits import Edit
from .rules import abbreviations, closed, rule_edits
from .sentences import Sentence, split_sentences

Span = tuple[int, int]
# Exhibit, figure, chart and table labels point at graphics, not at text: never a reference to resolve.
FIGURE = re.compile(r"\b(?:Exhibits?|Figures?|Fig\.|Charts?|Tables?|Graphs?)\s+\d+[A-Za-z]?\b")


@dataclass
class Doc:
    """The source body, its sentences, its defined abbreviations and the rule edits."""

    source: str
    sentences: list[Sentence]
    defined: dict[str, tuple[str, Span]]
    rules: list[Edit]
    rule_warnings: list[str]

    @classmethod
    def build(cls, source: str) -> "Doc":
        """Split ``source`` into sentences and apply the deterministic rules."""
        rules, warnings = rule_edits(source)
        return cls(source, split_sentences(AnnotatedText(source)), abbreviations(source), rules, warnings)

    def sentence(self, sid: Any) -> Sentence | None:
        """Return the sentence with id ``sid``, or None."""
        return next((s for s in self.sentences if s.id == sid), None)

    @staticmethod
    def editable(s: Sentence) -> bool:
        """Return True unless ``s`` is a heading, a question or a figure caption (the same test the rules use)."""
        return not closed(s.kind, s.text)

    def figure_spans(self, s: Sentence) -> list[Span]:
        """Return the source spans of exhibit, figure, chart and table labels in sentence ``s``."""
        return [(s.src_start + m.start(), s.src_start + m.end()) for m in FIGURE.finditer(s.source)]


def render_document(doc: Doc) -> str:
    """Return the document as the model sees it: one ``E### text`` line per sentence, blank lines between paragraphs."""
    lines: list[str] = []
    prev_end = None
    for s in doc.sentences:
        if prev_end is not None and "\n" in doc.source[prev_end : s.src_start]:
            lines.append("")
        prefix = {"heading": "# ", "bullet": "- "}.get(s.kind, "")
        lines.append(f"{s.id} {prefix}{s.source}")
        prev_end = s.src_end
    return "Document:\n\n" + "\n".join(lines) + "\n"


def find(text: str, phrase: str, occurrence: int = 1) -> int | None:
    """Return the offset of the ``occurrence``-th whole-word match of ``phrase`` in ``text`` (typography folded)."""
    if not phrase.strip():
        return None
    left = r"\b" if phrase[0].isalnum() else ""
    right = r"\b" if phrase[-1].isalnum() else ""
    hits = list(re.finditer(left + re.escape(fold(phrase)) + right, fold(text)))
    return hits[occurrence - 1].start() if 0 < occurrence <= len(hits) else None


def locate(doc: Doc, sid: Any, quote: Any) -> Span | str:
    """Return the source span of ``quote`` inside sentence ``sid`` (any sentence), or the reason it fails."""
    s = doc.sentence(sid)
    if s is None or not isinstance(quote, str) or not quote.strip():
        return f"sid {sid!r} not found or quote empty"
    i = find(s.source, quote)
    if i is None:
        return f"quote {quote!r} is not in {s.id} as written"
    return s.src_start + i, s.src_start + i + len(quote)


def target(doc: Doc, item: dict[str, Any], key: str) -> tuple[Sentence, int, int] | str:
    """Return the sentence and source span of ``item[key]`` in editable sentence ``item.sid``, or why it fails."""
    s, phrase = doc.sentence(item.get("sid")), item.get(key)
    if s is None:
        return f"sid {item.get('sid')!r} not found"
    if not doc.editable(s):
        return f"{s.id} is a heading, question or figure caption"
    occurrence = item.get("occurrence", 1)
    i = find(s.source, phrase, occurrence if isinstance(occurrence, int) else 1) if isinstance(phrase, str) else None
    if i is None:
        return f"{key} {phrase!r} (occurrence {occurrence}) is not in {s.id} as written"
    return s, s.src_start + i, s.src_start + i + len(phrase)


def words(text: str) -> set[str]:
    """Return the stemmed, lower-cased words of ``text`` (possessive 's dropped)."""
    return {_stem(w) for w in WORD.findall(fold(text).lower().replace("'s", ""))}
