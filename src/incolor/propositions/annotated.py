"""Stage 1 markup: source text with inline ``{{original => resolution}}`` marks, plus an optional reference log.

Three views of one marked string: ``original()`` (every mark replaced by its original; must equal the source
exactly), ``resolved()`` (every mark replaced by its resolution) and ``resolved(brackets=True)`` (resolutions wrapped
in ``[ ]`` for review). Mark offsets into both the source and the resolved text let later stages map spans back.

The log (``{"marks": [...], "unresolved": [...]}``) records, per mark in order, what kind of reference it resolved and
the verbatim source text it points to, and lists references deliberately left unresolved.
"""

import difflib
import json
import re
from dataclasses import dataclass
from typing import Any

from ..argumentation.grounding import fold
from .interpolation import GLUE, Issue

# Spaces around "=>" are optional so that slips like {{&=> and}} still parse; an empty original is an insertion.
MARK = re.compile(r"\{\{(.*?) ?=> ?(.+?)\}\}")
RESERVED = ("{{", "}}", "=>")
WORD_SYMBOL = re.compile(r"(?<=\s)[&+=](?=\s)|~(?=\d)")
# "it" is left out: expletive uses ("it would be") cannot be resolved.
PRONOUN = re.compile(r"\b(?:he|him|his|she|her|hers|they|them|their|theirs|its)\b", re.IGNORECASE)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[A-Za-z]+(?:[’'][A-Za-z]+)*")
SUFFIX = re.compile(r"(?:[’']s|ies|es|s|ed|ing)$")
# Words a resolution may add without the document using them: glue, author forms, spelled-out symbols.
ALLOWED_NEW = (GLUE - {"scenario", "case"}) | {
    "author", "approximately", "means", "shows", "it", "its", "this", "these", "those", "not",
    "between", "about", "after", "before", "during", "into", "over",
}  # fmt: skip
# Modality, polarity, condition and stance markers a mark must keep: lemma -> surface forms ("If wrong" negates).
MARKER_FORMS = {
    "can": "can", "could": "could", "may": "may", "might": "might", "must": "must", "shall": "shall",
    "should": "should", "will": "will", "would": "would", "ought": "ought",
    "not": "not wrong", "no": "no", "never": "never", "neither": "neither", "nor": "nor", "none": "none",
    "nothing": "nothing", "without": "without", "unable": "unable",
    "likely": "likely", "unlikely": "unlikely", "probably": "probably", "possibly": "possibly",
    "perhaps": "perhaps", "maybe": "maybe", "roughly": "roughly", "approximately": "approximately",
    "if": "if", "unless": "unless", "assume": "assume assumes assumed assuming", "whether": "whether",
    "think": "think thinks thought", "expect": "expect expects expected expecting",
    "guess": "guess guesses guessed", "believe": "believe believes believed", "see": "see sees saw",
    "say": "say says said", "seem": "seem seems seemed", "appear": "appear appears appeared",
}  # fmt: skip
MARKERS = {form: lemma for lemma, forms in MARKER_FORMS.items() for form in forms.split()}
MAX_DIFF_REPORTS = 8
SNIPPET = 160
MAX_ADDED_WORDS = 20
LOG_SEPARATOR = "=== LOG ==="
REF_TYPES = {"entity", "deixis", "ellipsis", "propositional", "abstract", "condition", "shorthand", "symbol"}
NO_ANTECEDENT = {"deixis", "symbol"}
# Types logged on a zero-edit mark ({{This => This}}): the text keeps the reference, the log carries the link.
LOG_ONLY = {"abstract", "condition"}
POLARITIES = {"affirm", "deny"}
SCOPES = {"preceding_paragraph"}


@dataclass(frozen=True)
class Mark:
    """One edit with its span in the source (``src_*``) and in the resolved text (``res_*``)."""

    original: str
    resolution: str
    src_start: int
    src_end: int
    res_start: int
    res_end: int


class AnnotatedText:
    """Parsed view of a marked string; malformed marks are left as plain text and reported by ``issues``."""

    def __init__(self, marked: str, log: dict[str, Any] | None = None) -> None:
        self.marked = marked
        self.log = log
        self.marks: list[Mark] = []
        self._gaps: list[str] = []
        original: list[str] = []
        resolved: list[str] = []
        src = res = cursor = 0
        for m in MARK.finditer(marked):
            gap = marked[cursor : m.start()]
            self._gaps.append(gap)
            src, res = src + len(gap), res + len(gap)
            orig, resolution = m.group(1), m.group(2)
            self.marks.append(Mark(orig, resolution, src, src + len(orig), res, res + len(resolution)))
            original += [gap, orig]
            resolved += [gap, resolution]
            src, res, cursor = src + len(orig), res + len(resolution), m.end()
        tail = marked[cursor:]
        self._gaps.append(tail)
        self._original = "".join([*original, tail])
        self._resolved = "".join([*resolved, tail])

    def original(self) -> str:
        """Return the text with every mark replaced by its original."""
        return self._original

    def resolved(self, brackets: bool = False) -> str:
        """Return the text with every mark replaced by its resolution, optionally wrapped in ``[ ]``."""
        return self.resolved_slice(0, len(self._resolved), brackets) if brackets else self._resolved

    def resolved_slice(self, start: int, end: int, brackets: bool = False) -> str:
        """Return ``resolved()[start:end]``, wrapping (the covered part of) each resolution in ``[ ]`` if asked.

        Leading and trailing spaces of a resolution are kept outside its brackets.
        """
        if not brackets:
            return self._resolved[start:end]
        pieces: list[str] = []
        pos = start
        for m in self.marks:
            if m.res_end <= start or m.res_start >= end:
                continue
            s, e = max(m.res_start, start), min(m.res_end, end)
            covered = self._resolved[s:e]
            core = covered.strip()
            if core:
                # Spaces an insertion brings with it stay outside the brackets.
                lead = covered[: len(covered) - len(covered.lstrip())]
                trail = covered[len(covered.rstrip()) :]
                covered = f"{lead}[{core}]{trail}"
            pieces += [self._resolved[pos:s], covered]
            pos = e
        pieces.append(self._resolved[pos:end])
        return "".join(pieces)

    def to_source(self, start: int, end: int) -> tuple[int, int]:
        """Map a resolved-text span to the source span; a boundary inside a mark widens to the whole mark."""
        return self._map(start, end=False), self._map(end, end=True)

    def _map(self, offset: int, *, end: bool) -> int:
        delta = 0
        for m in self.marks:
            if offset <= m.res_start:
                break
            if offset < m.res_end:
                return m.src_end if end else m.src_start
            delta = m.src_end - m.res_end
        return offset + delta

    def splits_mark(self, start: int, end: int) -> bool:
        """Return True if either boundary of the resolved span falls strictly inside a mark."""
        return any(m.res_start < b < m.res_end for m in self.marks for b in (start, end))

    def issues(self, source: str, context: str | None = None) -> list[Issue]:
        """Return markup errors, warnings (no-op marks, words or symbols not from the source) and line differences.

        ``context`` is the whole document when ``source`` is one section; resolutions may copy words from all of it.
        """
        out: list[Issue] = []
        surface = set(WORD.findall((context or source).lower()))
        entries = self.log_entries()
        for k, m in enumerate(self.marks):
            where = f"src {m.src_start}"
            label = f"{{{{{m.original} => {m.resolution}}}}}"
            if not m.resolution.strip() or (m.original and not m.original.strip()):
                out.append(Issue("error", "EMPTY_PART", where, label))
            if any(t in m.original or t in m.resolution for t in RESERVED):
                out.append(Issue("error", "MALFORMED_MARK", where, f"nested or broken mark: {label}"))
            if "[" in m.resolution or "]" in m.resolution:
                out.append(Issue("error", "BRACKET_IN_RESOLUTION", where, label))
            log_only = k < len(entries) and entries[k].get("type") in LOG_ONLY
            if m.original == m.resolution and not log_only:
                out.append(Issue("warning", "NOOP_MARK", where, label))
            own = {_stem(w) for w in WORD.findall(m.original.lower())}
            new = [
                w
                for w in dict.fromkeys(WORD.findall(m.resolution.lower()))
                if not _verbatim(w, surface) and _stem(w) not in ALLOWED_NEW | own
            ]
            if new:
                out.append(Issue("warning", "UNGROUNDED_WORD", where, f"not verbatim in source: {new} in {label}"))
            before, after = _markers(m.original), _markers(m.resolution)
            line_start = self._original.rfind("\n", 0, m.src_start) + 1
            line_end = self._original.find("\n", m.src_end)
            line = self._original[line_start : line_end if line_end >= 0 else len(self._original)]
            context = _markers(line)
            dropped, added = sorted(before - after), sorted(after - before - context)
            if dropped or added:
                message = f"dropped {dropped} added {added} in {label}"
                out.append(Issue("warning", "MODALITY_CHANGED", where, message))
            if line.startswith("#") or _sentence_at(line, m.src_start - line_start).rstrip().endswith("?"):
                out.append(Issue("error", "MARK_IN_QUESTION_OR_HEADING", where, label))
            added_words = len(WORD.findall(m.resolution)) - len(WORD.findall(m.original))
            if added_words > MAX_ADDED_WORDS:
                out.append(Issue("warning", "LONG_RESOLUTION", where, f"+{added_words} words: {label}"))
        for gap in self._gaps:
            for token in RESERVED:
                i = gap.find(token)
                if i >= 0:
                    snippet = gap[max(0, i - 40) : i + 60]
                    out.append(Issue("error", "MALFORMED_MARK", None, f"stray {token!r} near {snippet!r}"))
        for n, line in enumerate(self._resolved.split("\n"), start=1):
            if line.startswith("#"):
                continue
            for s in WORD_SYMBOL.finditer(line):
                snippet = line[max(0, s.start() - 30) : s.end() + 30]
                out.append(Issue("warning", "UNRESOLVED_SYMBOL", f"line {n}", f"{s.group()!r} in {snippet!r}"))
            for sentence in SENTENCE_BREAK.split(line):
                if sentence.rstrip().endswith("?"):
                    continue
                for p in PRONOUN.finditer(sentence):
                    snippet = sentence[max(0, p.start() - 40) : p.end() + 40]
                    out.append(Issue("warning", "UNRESOLVED_PRONOUN", f"line {n}", f"{p.group()!r} in {snippet!r}"))
        if self._original != source:
            out.extend(_line_diffs(source, self._original))
        if self.log is not None:
            out.extend(self.log_issues(source))
        return out

    def log_entries(self) -> list[dict[str, Any]]:
        """Return the log's per-mark entries (dicts only), or ``[]`` when there is no usable log."""
        entries = self.log.get("marks") if isinstance(self.log, dict) else None
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    def log_issues(self, source: str) -> list[Issue]:
        """Check the log: one entry per mark in order, known types, verbatim antecedents, polarity rules."""
        log = self.log if isinstance(self.log, dict) else {}
        entries = log.get("marks")
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            return [Issue("error", "LOG_MALFORMED", None, "log must be an object with a 'marks' list of objects")]
        out: list[Issue] = []
        if len(entries) != len(self.marks):
            message = f"{len(entries)} log entries for {len(self.marks)} marks"
            out.append(Issue("error", "LOG_COUNT_MISMATCH", None, message))
        folded = fold(source)
        for k, (entry, m) in enumerate(zip(entries, self.marks, strict=False), start=1):
            where, label = f"log {k}", f"{{{{{m.original} => {m.resolution}}}}}"
            kind, polarity = entry.get("type"), entry.get("polarity")
            if entry.get("i") != k or kind not in REF_TYPES:
                out.append(Issue("error", "LOG_BAD_ENTRY", where, f"i={entry.get('i')!r} type={kind!r} for {label}"))
            if (kind == "propositional") != (polarity in POLARITIES):
                out.append(Issue("error", "LOG_BAD_POLARITY", where, f"type={kind!r} polarity={polarity!r}"))
            if kind in LOG_ONLY and m.original != m.resolution:
                out.append(Issue("warning", "LOG_ONLY_EDITED", where, f"{kind} reference edited in text: {label}"))
            if kind in NO_ANTECEDENT:
                continue
            antecedents = _as_list(entry.get("antecedent"))
            if kind == "abstract" and not antecedents and entry.get("scope") in SCOPES:
                continue
            bad = [a for a in antecedents if not isinstance(a, str) or not a or fold(a) not in folded]
            if not antecedents or bad:
                out.append(
                    Issue("error", "LOG_ANTECEDENT_NOT_FOUND", where, f"{entry.get('antecedent')!r} for {label}")
                )
        unresolved = log.get("unresolved", [])
        for u in unresolved if isinstance(unresolved, list) else []:
            surface = u.get("surface") if isinstance(u, dict) else None
            if not isinstance(surface, str) or not re.search(rf"\b{re.escape(surface)}\b", self._resolved):
                out.append(Issue("warning", "LOG_UNRESOLVED_NOT_FOUND", None, f"{u!r}"))
        return out

    def antecedent_spans(self, k: int, source: str) -> list[tuple[int, int]]:
        """Return source spans of mark ``k``'s logged antecedents, nearest in the logged direction (default back)."""
        entries = self.log_entries()
        if k >= len(entries) or k >= len(self.marks):
            return []
        forward = entries[k].get("direction") == "forward"
        folded, m = fold(source), self.marks[k]
        spans: list[tuple[int, int]] = []
        for antecedent in _as_list(entries[k].get("antecedent")):
            if not isinstance(antecedent, str) or not antecedent:
                continue
            needle = fold(antecedent)
            near = folded.find(needle, m.src_end) if forward else folded.rfind(needle, 0, m.src_start)
            start = near if near >= 0 else folded.find(needle)
            if start >= 0:
                spans.append((start, start + len(needle)))
        return spans


def _stem(word: str) -> str:
    stem = SUFFIX.sub("", word)
    return stem + "y" if word.endswith("ies") else stem


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _sentence_at(line: str, offset: int) -> str:
    start = 0
    for brk in SENTENCE_BREAK.finditer(line):
        if brk.start() >= offset:
            return line[start : brk.start()]
        start = brk.end()
    return line[start:]


def _verbatim(word: str, surface: set[str]) -> bool:
    if word in ALLOWED_NEW or word in surface:
        return True
    # Possessive and agreement endings are allowed; -ing/-ed reshapes are paraphrase.
    return (word[-2:] in ("'s", "’s") and word[:-2] in surface) or (word.endswith("s") and word[:-1] in surface)


def restore_edges(text: AnnotatedText, source: str, max_lines: int = 2) -> AnnotatedText:
    """Re-attach source text the model left off the start or end (a title line, blank lines), unmarked.

    Applies only when ``original()`` stripped occurs exactly once in ``source`` and the missing edges hold at most
    ``max_lines`` non-blank lines, so a truncated answer still fails.
    """
    original = text.original()
    core = original.strip()
    if original == source or not core or source.count(core) != 1:
        return text
    lead = len(original) - len(original.lstrip())
    trail = len(original) - len(original.rstrip())
    marked = text.marked
    if marked[:lead] != original[:lead] or marked[len(marked) - trail :] != original[len(original) - trail :]:
        return text
    start = source.index(core)
    head, tail = source[:start], source[start + len(core) :]
    if sum(bool(line.strip()) for line in (head + "\n" + tail).split("\n")) > max_lines:
        return text
    return AnnotatedText(head + marked[lead : len(marked) - trail] + tail, log=text.log)


def snap_typography(text: AnnotatedText, source: str) -> AnnotatedText:
    """Restore the source's quote, apostrophe, dash and space characters where the model copied another variant.

    Applies only when ``original()`` differs from ``source`` in nothing but those characters; resolutions are kept.
    """
    original = text.original()
    if original == source or len(original) != len(source) or fold(original) != fold(source):
        return text
    pieces: list[str] = []
    pos = 0
    for m, gap in zip(text.marks, text._gaps, strict=False):
        pieces += [source[pos : pos + len(gap)], f"{{{{{source[m.src_start : m.src_end]} => {m.resolution}}}}}"]
        pos = m.src_end
    pieces.append(source[pos:])
    return AnnotatedText("".join(pieces), log=text.log)


def link_antecedents(text: AnnotatedText, source: str) -> list[list[tuple[int, int]]]:
    """Return, per mark, the source spans its resolution copies verbatim (nearest preceding occurrence first).

    Spans are found greedily, longest first, and must contain a content word that the mark's original lacks.
    """
    tokens = [(t.group().lower(), t.start(), t.end()) for t in WORD.finditer(source)]
    starts: dict[str, list[int]] = {}
    for k, (word, _, _) in enumerate(tokens):
        starts.setdefault(word, []).append(k)
    links: list[list[tuple[int, int]]] = []
    for m in text.marks:
        res = WORD.findall(m.resolution.lower())
        own = set(WORD.findall(m.original.lower()))
        spans: list[tuple[int, int]] = []
        i = 0
        while i < len(res):
            found = None
            for j in range(len(res), i, -1):
                seq = res[i:j]
                if all(w in ALLOWED_NEW or w in own for w in seq):
                    continue
                hits = [
                    (tokens[k][1], tokens[k + j - i - 1][2])
                    for k in starts.get(seq[0], [])
                    if [w for w, _, _ in tokens[k : k + j - i]] == seq and not (m.src_start <= tokens[k][1] < m.src_end)
                ]
                if hits:
                    before = [h for h in hits if h[1] <= m.src_start]
                    found = max(before) if before else min(hits)
                    spans.append(found)
                    i = j
                    break
            if found is None:
                i += 1
        links.append(spans)
    return links


def rooted_share(text: AnnotatedText, source: str) -> float | None:
    """Return the share of content words added by resolutions that sit in spans copied verbatim from the source.

    A copied span counts if it has at least two words, or if it is the whole addition (a name standing in for "he").
    """
    total = rooted = 0
    for m, spans in zip(text.marks, link_antecedents(text, source), strict=True):
        own = set(WORD.findall(m.original.lower()))
        added = [w for w in WORD.findall(m.resolution.lower()) if w not in own and w not in ALLOWED_NEW]
        copied = [WORD.findall(source[a:b].lower()) for a, b in spans]
        long_spans = {w for words in copied if len(words) >= 2 for w in words}
        single = {w for words in copied for w in words} if len(added) == 1 else set()
        total += len(added)
        rooted += sum(w in long_spans or w in single for w in added)
    return rooted / total if total else None


def _markers(text: str) -> set[str]:
    words = WORD.findall(text.lower().replace("cannot", "can not"))
    found = {MARKERS[w] for w in words if w in MARKERS}
    negated = [w[:-3] for w in words if w.endswith(("n't", "n’t"))]
    found |= {"not"} if negated else set()
    found |= {MARKERS["will" if b == "wo" else b] for b in negated if b in MARKERS or b == "wo"}
    if "~" in text:
        found.add("approximately")
    return found


def _line_diffs(source: str, original: str) -> list[Issue]:
    src_lines, out_lines = source.split("\n"), original.split("\n")
    issues: list[Issue] = []
    ops = difflib.SequenceMatcher(None, src_lines, out_lines, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in [op for op in ops if op[0] != "equal"][:MAX_DIFF_REPORTS]:
        where = f"line {i1 + 1}"
        if tag == "replace" and i2 - i1 == j2 - j1 == 1:
            a, b = src_lines[i1], out_lines[j1]
            k = next((n for n, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))
            lo = max(0, k - 40)
            message = f"at char {k}: input {a[lo : k + 40]!r} vs yours {b[lo : k + 40]!r}"
        else:
            message = (
                f"{tag}: input lines {i1 + 1}-{i2} {chr(10).join(src_lines[i1:i2])[:SNIPPET]!r} "
                f"vs yours {chr(10).join(out_lines[j1:j2])[:SNIPPET]!r}"
            )
        issues.append(Issue("error", "SOURCE_MISMATCH", where, message))
    return issues


def precheck(source: str) -> list[Issue]:
    """Return errors if the source already contains markup tokens, which would make the marks ambiguous."""
    return [Issue("error", "RESERVED_IN_SOURCE", None, f"source contains {t!r}") for t in RESERVED if t in source]


def clean_response(raw: str) -> str:
    """Strip surrounding whitespace and one wrapping code fence from a model response."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 : -3] if first_newline >= 0 else ""
    return text.strip()


def split_response(raw: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Split a response into marked text and log at ``LOG_SEPARATOR``; return ``(marked, log, problem)``."""
    head, separator, tail = raw.partition(LOG_SEPARATOR)
    marked = clean_response(head)
    if not separator:
        return marked, None, "no log after the document"
    try:
        log = json.loads(clean_response(tail))
    except ValueError as exc:
        return marked, None, f"log is not valid JSON: {exc}"
    return marked, log, None
