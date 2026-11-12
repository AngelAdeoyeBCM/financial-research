"""Deterministic Stage 1 edits: symbols used as words, abbreviations the document defines, and author deixis.

Every function returns ``Edit`` objects over the text it is given (offsets shifted by ``base``) and skips
``protected`` spans; only deixis is kept out of headings and questions, since symbols and abbreviations are
standardisation, not resolution. ``apply`` renders edits onto a string, so the same rules also normalise text copied
into a resolution.
"""

import re
from collections.abc import Sequence

from .annotated import AnnotatedText
from .edits import Edit
from .sentences import split_sentences

Span = tuple[int, int]

SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<=\s)[&+](?=\s)"), "and"),
    (re.compile(r"(?<=\s)=(?=\s)"), "is"),
    (re.compile(r"(?<=\s)/(?=\s)"), "or"),
    (re.compile(r"~(?=\d)"), "approximately "),
)
# "Oct/Dec" -> "Oct or Dec"; "and/or" stays.
WORD_SLASH = re.compile(r"\b([A-Za-z]{2,})/([A-Za-z]{2,})\b")
# Abbreviation definitions: "Long Form (ABBR)" and "ABBR (Long Form)".
ABBR_IN_PARENS = re.compile(r"\(([A-Z]{2,6})\)")
ABBR_THEN_LONG = re.compile(r"\b([A-Z]{2,6})\s+\(([^()]{3,80})\)")
DEFINITION_WORD = re.compile(r"[A-Za-z][\w’'-]*|&")
LINK_WORDS = {"and", "of", "the", "for", "in", "on", "to", "&"}
QUOTED = re.compile(r"“[^”]*”|\"[^\"\n]*\"")
CAPTION = re.compile(r"^(?:(?:Exhibits?|Figures?|Fig\.|Charts?|Tables?|Graphs?)\s+\d+[A-Za-z]?\s*[:.]|Sources?:)")

AUTHOR_WORDS = {
    "we": "the author", "us": "the author", "our": "the author's", "ours": "the author's",
    "we're": "the author is", "we’re": "the author is", "we've": "the author has", "we’ve": "the author has",
    "we'll": "the author will", "we’ll": "the author will", "we'd": "the author would", "we’d": "the author would",
}  # fmt: skip
# Lower-case "us" only: "US" is the country.
AUTHOR = re.compile(r"\b(?:[Ww]e(?:['’](?:re|ve|ll|d))?|us|[Oo]urs?)\b")
ADVERBS = {
    "also", "still", "now", "currently", "therefore", "thus", "generally", "broadly", "only", "just", "already",
    "again", "too", "all", "both", "probably", "certainly", "really",
}  # fmt: skip
UNCHANGED_VERBS = {
    "will", "would", "may", "might", "can", "could", "should", "must", "shall", "did", "had", "found", "saw",
    "thought", "said", "made", "took", "wrote", "held", "kept", "felt", "left", "got", "gave", "became", "began",
    "came", "went", "knew", "met", "put", "set", "cut", "read", "won't", "wouldn't", "can't", "don't", "didn't",
}  # fmt: skip
IRREGULAR = {"are": "is", "were": "was", "have": "has", "do": "does", "go": "goes", "be": "is"}
BASE_VERBS = {
    "think", "expect", "see", "believe", "guess", "offer", "suspect", "prefer", "like", "recommend", "favour",
    "favor", "argue", "estimate", "forecast", "project", "maintain", "note", "view", "doubt", "want", "need", "hold",
    "keep", "stay", "retain", "look", "find", "assume", "anticipate", "worry", "agree", "suggest", "highlight",
    "reiterate", "raise", "lower", "revise", "upgrade", "downgrade", "turn", "add", "move", "change", "stick",
    "acknowledge", "caution", "consider", "wonder", "know", "feel", "hope", "fear", "show", "use", "take", "buy",
    "sell", "get", "make", "discuss", "flag", "focus", "emphasise", "emphasize", "stress", "warn", "judge",
    "reckon", "sense", "interpret", "include", "count", "calculate", "remain", "continue", "track", "monitor",
    "watch", "publish", "identify", "measure", "model", "target", "remove", "adjust",
    *IRREGULAR,
}  # fmt: skip
NEXT_WORD = re.compile(r"\s+([A-Za-z’']+)")


def closed(kind: str, text: str) -> bool:
    """Return True for a sentence no resolution may edit: a heading, a question or a figure caption."""
    return kind == "heading" or text.rstrip().endswith("?") or bool(CAPTION.match(text))


def protected_spans(source: str) -> list[Span]:
    """Return the source spans of headings, questions and figure captions, where no resolution may go."""
    return [(s.src_start, s.src_end) for s in split_sentences(AnnotatedText(source)) if closed(s.kind, s.text)]


def _initials(words: Sequence[str]) -> str:
    return "".join(w[0] for w in words if w.lower() not in LINK_WORDS).upper()


def abbreviations(source: str) -> dict[str, tuple[str, Span]]:
    """Return ``{ABBR: (long form, span of its definition)}`` for abbreviations the document defines.

    ``Long Form (ABBR)``: the long form is the shortest run of words before the parenthesis whose initials spell ABBR,
    link words (and, of, the, ...) and commas skipped ("Food, Alcohol and Tobacco (FAT)"). ``ABBR (Long Form)``: the
    parenthesis is the long form if its initials spell ABBR. The first definition of an abbreviation wins.
    """
    out: dict[str, tuple[str, Span]] = {}
    for m in ABBR_IN_PARENS.finditer(source):
        abbr = m.group(1)
        before = list(DEFINITION_WORD.finditer(source, max(0, m.start() - 160), m.start()))
        for k in range(len(before) - 1, -1, -1):
            words = [w.group() for w in before[k:]]
            initials = _initials(words)
            if len(initials) > len(abbr):
                break
            if initials == abbr and words[0].lower() not in LINK_WORDS:
                out.setdefault(abbr, (source[before[k].start() : before[-1].end()], (before[k].start(), m.end())))
                break
    for m in ABBR_THEN_LONG.finditer(source):
        abbr, long = m.group(1), m.group(2).strip()
        if _initials(DEFINITION_WORD.findall(long)) == abbr:
            out.setdefault(abbr, (long, m.span()))
    return out


def third_person(verb: str) -> str:
    """Return the third-person singular present of a base-form verb."""
    lower = verb.lower()
    if lower in IRREGULAR:
        return IRREGULAR[lower]
    if re.search(r"(?:s|sh|ch|x|z|o)$", lower):
        return verb + "es"
    if re.search(r"[^aeiou]y$", lower):
        return verb[:-1] + "ies"
    return verb + "s"


def _inside(spans: Sequence[Span], start: int, end: int) -> bool:
    return any(a <= start and end <= b for a, b in spans)


def _match_case(original: str, text: str) -> str:
    return text[0].upper() + text[1:] if original[:1].isupper() else text


def symbol_edits(text: str, protected: Sequence[Span] = (), base: int = 0) -> list[Edit]:
    """Return edits spelling out ``& + = / ~`` used as words."""
    found = [(m.start(), m.end(), word) for pattern, word in SYMBOLS for m in pattern.finditer(text)]
    found += [
        (m.end(1), m.start(2), " or ")
        for m in WORD_SLASH.finditer(text)
        if (m.group(1).lower(), m.group(2).lower()) != ("and", "or")
    ]
    return [
        Edit(base + a, base + b, word, "symbol")
        for a, b, word in sorted(found)
        if not _inside(protected, base + a, base + b)
    ]


def abbreviation_edits(
    text: str, defined: dict[str, tuple[str, Span]], protected: Sequence[Span] = (), base: int = 0
) -> list[Edit]:
    """Return edits expanding defined abbreviations wherever used (before it too), except in their definition."""
    out = []
    for abbr, (long, definition) in defined.items():
        for m in re.finditer(rf"(?<!\()\b{re.escape(abbr)}\b(?!\))", text):
            start, end = base + m.start(), base + m.end()
            if not _inside([definition, *protected], start, end):
                out.append(Edit(start, end, long, "abbreviation"))
    return out


def deixis_edits(text: str, protected: Sequence[Span] = (), base: int = 0) -> tuple[list[Edit], list[str]]:
    """Return edits replacing the author's we/us/our with "the author" (verb agreement included), and warnings.

    "we" followed (after adverbs) by a known base-form verb takes the third person; an unknown next word is left as
    it is and reported. Quoted text is skipped.
    """
    quoted = [m.span() for m in QUOTED.finditer(text)]
    out: list[Edit] = []
    warnings: list[str] = []
    for m in AUTHOR.finditer(text):
        if _inside(quoted, m.start(), m.end()) or _inside(protected, base + m.start(), base + m.end()):
            continue
        word = m.group()
        replacement = _match_case(word, AUTHOR_WORDS[word.lower()])
        end = m.end()
        if word.lower() == "we":
            pos = m.end()
            while (nxt := NEXT_WORD.match(text, pos)) and nxt.group(1).lower() in ADVERBS:
                pos = nxt.end()
            nxt = NEXT_WORD.match(text, pos)
            verb = nxt.group(1) if nxt else ""
            if verb.lower() in BASE_VERBS:
                replacement += text[m.end() : nxt.start(1)] + third_person(verb)
                end = nxt.end()
            elif verb and verb.lower() not in UNCHANGED_VERBS and not verb.lower().endswith("ed"):
                warnings.append(f"agreement unknown after {text[m.start() : nxt.end()]!r} at {base + m.start()}")
        out.append(Edit(base + m.start(), base + end, replacement, "deixis"))
    return out, warnings


def rule_edits(source: str) -> tuple[list[Edit], list[str]]:
    """Return all deterministic edits for a document, in order, and the deixis warnings.

    Symbols and defined abbreviations are standardised everywhere, headings and questions included; author deixis
    (a resolution) stays out of headings and questions like every other resolution.
    """
    deixis, warnings = deixis_edits(source, protected_spans(source))
    edits = symbol_edits(source) + abbreviation_edits(source, abbreviations(source)) + deixis
    return sorted(edits, key=lambda e: (e.start, e.end)), warnings


def apply(text: str, edits: Sequence[Edit], base: int = 0) -> str:
    """Return ``text`` (which starts at offset ``base``) with the edits that lie wholly inside it applied."""
    pieces: list[str] = []
    pos = 0
    for e in sorted(edits, key=lambda e: (e.start, e.end)):
        a, b = e.start - base, e.end - base
        if a < pos or b > len(text):
            continue
        pieces += [text[pos:a], e.text]
        pos = b
    pieces.append(text[pos:])
    return "".join(pieces)


def normalise_copy(text: str, defined: dict[str, tuple[str, Span]]) -> str:
    """Return copied text with symbols, defined abbreviations and author deixis normalised."""
    deixis, _ = deixis_edits(text)
    expanded = abbreviation_edits(text, {k: (v, (0, 0)) for k, (v, _) in defined.items()})
    edits = sorted(symbol_edits(text) + expanded + deixis, key=lambda e: (e.start, e.end))
    return apply(text, edits)
