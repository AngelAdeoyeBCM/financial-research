"""Normalisers: standardise spacing, split words, titles, headings, bullets and numbered lists."""

import re
import unicodedata
from collections import Counter

from ..core.text import EditableText
from . import patterns as p
from .steps import DocumentContext, Normaliser

_LIST_ITEM_RE = re.compile(r"\d{1,2}\. ")
# fmt: off
_SHORT_WORDS = frozenset({
    "a", "am", "an", "and", "any", "are", "as", "at", "be", "bn", "bp", "bps", "but", "by", "can", "do", "few", "for",
    "get", "go", "had", "has", "he", "her", "him", "his", "how", "if", "in", "is", "it", "its", "key", "low", "may",
    "me", "mn", "my", "new", "no", "not", "now", "of", "off", "old", "on", "one", "or", "our", "out", "own", "per",
    "pp", "ppt", "put", "say", "see", "set", "she", "so", "the", "tn", "to", "too", "two", "up", "us", "use", "vs",
    "was", "way", "we", "who", "why", "yet", "you", "yr", "yrs",
})
# fmt: on


class WhitespaceNormaliser(Normaliser):
    """Collapse whitespace runs to single spaces (chunk texts carry no line structure)."""

    rule = "whitespace"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Not logged: whitespace carries no content here."""
        text.sub(self.rule, re.compile(r"\s+"), " ", log=False)


class LoneBulletNormaliser(Normaliser):
    """Goldman Sachs extracts bullets as a lone ``n``."""

    rule = "bullet"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """``". n Next"`` becomes a bullet; any other lone ``n`` before a word is dropped."""
        text.sub(self.rule, re.compile(r"(?<=[.:;!?]) n (?=[A-Z])"), " • ")
        text.sub(self.rule, re.compile(r"(?<= )n (?=\w)"), "")


class HyphenationNormaliser(Normaliser):
    """Re-join hyphenated words split across lines (``"inter -bank"``, ``"inter- bank"``)."""

    rule = "split_word"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Keeps ``"short- and long-term"`` style suspended hyphens."""
        text.sub(self.rule, re.compile(r"(?<=\w) -(?=[A-Za-z])"), "-")
        text.sub(self.rule, re.compile(r"(?<=[A-Za-z])- (?!(?:and|or|to|nor)\b)(?=[a-z])"), "-")


class SplitWordJoiner(Normaliser):
    """Re-join words broken by a stray space (``"Governme nt"``, ``"mode ls"``) when the corpus knows the whole word."""

    rule = "split_word"
    min_count = 3
    _CANDIDATE_RE = re.compile(r"(?<![\w'’-])([A-Za-z]{3,}) ([a-z]{1,4})(?![\w'’-])")

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Join only when the fragment is rare and the joined word is common."""
        vocab = context.vocabulary
        spans = []
        for m in self._CANDIDATE_RE.finditer(text.text):
            head, tail = m.groups()
            joined = vocab[head + tail]
            if tail == "s":
                # The possessive "s" is common, so frequency cannot rule out a split plural.
                ok = len(head) >= 4 and joined >= self.min_count
            else:
                ok = (
                    tail not in _SHORT_WORDS
                    and joined >= self.min_count
                    and vocab[tail] * 5 <= joined
                    and (len(tail) <= 2 or vocab[head] * 5 <= joined)
                )
            if ok:
                spans.append((m.start(), m.end(), head + tail))
        text.apply(self.rule, spans)


class SpacingNormaliser(Normaliser):
    """No space before closing punctuation or after ``(``; no stray spaces or pipes at the ends."""

    rule = "spacing"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Whitespace collapse is silent; punctuation fixes are logged."""
        text.sub("whitespace", re.compile(r"\s+"), " ", log=False)
        text.sub(self.rule, re.compile(r" ([.,;:!?)])"), r"\1")
        text.sub(self.rule, re.compile(r"\( "), "(")
        text.sub(self.rule, re.compile(r"\A[ |]+|[ |]+\Z"), "")


class TitleNormaliser(Normaliser):
    """The title printed near the start becomes the document heading.

    With ``move_to_heading`` (default) it is removed from the content because it is rendered as ``# Title``;
    otherwise it is put on its own line, as the original compiler did.
    """

    rule = "title"

    def __init__(self, move_to_heading: bool = True) -> None:
        self.move_to_heading = move_to_heading

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Isolate or remove the printed title."""
        current = text.text
        best = context.find_printed_title(current)
        if best is None:
            if not self.move_to_heading:
                text.apply(self.rule, [(0, 0, f"{context.title}\n\n")])
            return
        title, end = best.group().strip(), best.end()
        if title.count("(") > title.count(")") and current[end : end + 1] == ")":
            title, end = title + ")", end + 1
        start = len(current[: best.start()].rstrip())
        stop = len(current) - len(current[end:].lstrip())
        replacement = "\n\n" if self.move_to_heading else f"\n\n{title}\n\n"
        text.apply(self.rule, [(start, stop, replacement)])


class BulletNormaliser(Normaliser):
    """Every bullet glyph starts a ``- `` item on its own line."""

    rule = "bullet"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Glyphs (with surrounding spaces) become a new ``- `` line."""
        text.sub(self.rule, p.BULLET_RE, "\n- ")


# Control, private-use, format and soft-hyphen characters carry no text; the bullet glyphs are gone by this point.
_INVISIBLE_RE = re.compile("[\x00-\x08\x0e-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ue000-\uf8ff\ufeff]")
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")
_STRAIGHT_QUOTE_RE = re.compile(r"[\"']")
_CURLY_QUOTE_RE = re.compile("[\u201c\u201d\u2018\u2019]")
_STRAIGHT_OF = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}


class UnicodeNormaliser(Normaliser):
    """Drop invisible characters and compatibility-normalise the rest (ligatures, full-width forms)."""

    rule = "unicode"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """NFKC keeps accented letters, currency, ``×``, ``≥`` and typographic quotes unchanged."""
        text.sub(self.rule, _INVISIBLE_RE, "")
        text.sub(self.rule, _NON_ASCII_RE, lambda m: unicodedata.normalize("NFKC", m.group()))


class QuoteStyleNormaliser(Normaliser):
    """One quote style per document: the majority style wins; a tie keeps typographic quotes."""

    rule = "quote_style"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Straight quotes become curly (opening or closing by position), or curly quotes become straight."""
        current = text.text
        straight = current.count('"') + current.count("'")
        curly = sum(current.count(ch) for ch in _STRAIGHT_OF)
        if straight > curly:
            text.sub(self.rule, _CURLY_QUOTE_RE, lambda m: _STRAIGHT_OF[m.group()])
        else:
            text.sub(self.rule, _STRAIGHT_QUOTE_RE, self._typographic)

    @staticmethod
    def _typographic(match: re.Match[str]) -> str:
        string, start = match.string, match.start()
        before = string[start - 1] if start else " "
        opening = before.isspace() or before in "([\u2014\u2013"
        if match.group() == '"':
            return "\u201c" if opening else "\u201d"
        if before.isalnum():
            return "\u2019"
        return "\u2018" if opening else "\u2019"


class PunctuationSpacingNormaliser(Normaliser):
    """Attach possessives and closing quotes to their word, hug quoted text, collapse runs of spaces."""

    rule = "spacing"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Silent whitespace fixes are not logged; attachments are."""
        text.sub(self.rule, re.compile(r"(?<=\w) (?=[\u2019']s\b)"), "")
        text.sub(self.rule, re.compile(r" (?=\u201d)"), "")
        text.sub(self.rule, re.compile(r"(?<=[\u201c\u2018]) "), "")
        text.sub("whitespace", re.compile(r"(?<=\S)  +(?=\S)"), " ", log=False)
        text.sub("whitespace", re.compile(r"[ \t]+$", re.M), "", log=False)


class EnumerationNormaliser(Normaliser):
    """Sequential enumerations (``1.``, ``1)``, ``(1)``, ``(a)``, ``(i)``) start numbered items on their own lines.

    With ``renumber`` (default) every style becomes ``1.``, ``2.`` ...; otherwise the original markers are kept.
    """

    rule = "numbered_list"

    def __init__(self, renumber: bool = True) -> None:
        self.renumber = renumber

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Only runs of at least two consecutive values in one style are treated as lists."""
        current = text.text
        candidates: list[tuple[re.Match[str], str, int]] = []
        for match in p.ENUM_RE.finditer(current):
            before = current[max(0, match.start() - 40) : match.start()].split()
            value = self._value(match)
            lowercase_after_period = match.group("marker").endswith(".") and current[match.end()].islower()
            if value is None or lowercase_after_period:
                continue
            if before and before[-1].lower().strip(".,:;(") in p.ENUM_BLOCKERS:
                continue
            candidates.append((match, *value))
        accepted: list[tuple[re.Match[str], int]] = []
        for style in {s for _, s, _ in candidates}:
            sequence: list[tuple[re.Match[str], int]] = []
            for match, s, value in candidates:
                if s != style:
                    continue
                if value == len(sequence) + 1 and (
                    not sequence or match.start() - sequence[-1][0].end() <= p.MAX_ENUM_GAP
                ):
                    sequence.append((match, value))
                elif value == 1:
                    accepted.extend(sequence if len(sequence) >= 2 else [])
                    sequence = [(match, value)]
            accepted.extend(sequence if len(sequence) >= 2 else [])
        text.apply(self.rule, [(m.start(), m.end(), f"\n{self._marker(m, value)} ") for m, value in accepted])

    def _marker(self, match: re.Match[str], value: int) -> str:
        if self.renumber or match.group("digit"):
            return f"{value}."
        return f"- {match.group('marker')}"

    @staticmethod
    def _value(match: re.Match[str]) -> tuple[str, int] | None:
        """``(style, ordinal)`` for an enumeration marker, or None for an unknown numeral.

        Digits share one style whatever the delimiter, so ``(1)``, ``2)`` and ``3.`` form one list.
        """
        if match.group("digit"):
            return "n", int(match.group("digit"))
        inner = match.group("paren") or match.group("bare")
        if inner.isdigit():
            return "n", int(inner)
        if inner in p.ROMAN:
            return "(r)", p.ROMAN[inner]
        if len(inner) == 1 and inner <= "h":
            return "(a)", ord(inner) - ord("a") + 1
        return None


class HeadingNormaliser(Normaliser):
    """All-caps section headers go on their own ``## `` lines; repeated page furniture stays inline."""

    rule = "heading"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Headers repeated 3+ times, used inline, or made of tickers/acronyms are left alone."""
        current = text.text
        counts = Counter(self._parts(m)[1] for m in p.HEADER_RE.finditer(current))

        def replace(match: re.Match[str]) -> str:
            lead, header, tail = self._parts(match)
            before = current[max(0, match.start() - 20) : match.start()].rstrip()[-1:]
            after = current[match.end() : match.end() + 20].lstrip()[:1]
            inline = before in {",", ";"} or (not tail and after in {".", ":", ",", ";"})
            if inline or counts[header] >= p.MAX_HEADER_REPEATS or not self._is_header(header):
                return match.group()
            return f"{lead}\n\n## {header}\n\n{tail}"

        text.sub(self.rule, p.HEADER_RE, replace)

    @staticmethod
    def _parts(match: re.Match[str]) -> tuple[str, str, str]:
        """Split off leading tickers/acronyms and a trailing ``A``/``I``/short number from the header words."""
        words = match.group().split()
        lead: list[str] = []
        tail: list[str] = []
        while words and (_is_currency_pair(words[0]) or sum(ch in "AEIOUY" for ch in words[0]) < 2):
            lead.append(words.pop(0))
        while words and (words[-1] in {"A", "I"} or (words[-1].isdigit() and len(words[-1]) <= 2)):
            tail.insert(0, words.pop())
        return " ".join(lead), " ".join(words).strip(" -/&"), " ".join(tail)

    @staticmethod
    def _is_header(candidate: str) -> bool:
        """An all-caps phrase of 2-8 distinct words with at least one pronounceable word (not just acronyms)."""
        words = candidate.split()
        if not 2 <= len(words) <= 8 or sum(len(w) for w in words) < 8 or len(set(words)) < len(words):
            return False
        for word in words:
            letters = re.sub(r"[^A-Z]", "", word)
            if _is_currency_pair(word):
                continue
            if len(letters) >= 4 and sum(ch in "AEIOUY" for ch in letters) >= 2:
                return True
        return False


class RunInLabelSplitter(Normaliser):
    """Paragraphs of ``Label – text. Label – text`` become ``- **Label** – text`` items."""

    rule = "run_in_label"
    min_labels = 2
    max_label_words = 12
    _LABEL_RE = re.compile(r"(?:^|(?<=[.!?] ))([A-Z][^.!?:;\n–—]{2,90}?) ([–—]) (?=[A-Z0-9“\"‘'(])", re.M)

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Only plain paragraph lines with at least two labels are split."""
        spans = []
        offset = 0
        for line in text.text.split("\n"):
            if line.strip() and not re.match(r"\s*(?:- |#|\d{1,2}\. )", line):
                labels = [m for m in self._LABEL_RE.finditer(line) if len(m.group(1).split()) <= self.max_label_words]
                if len(labels) >= self.min_labels:
                    spans += [
                        (offset + m.start(), offset + m.end(), f"\n- **{m.group(1)}** {m.group(2)} ") for m in labels
                    ]
            offset += len(line) + 1
        text.apply(self.rule, spans)


class LayoutNormaliser(Normaliser):
    """One block per line: blank lines between paragraphs, headers and lists; list items stay together."""

    rule = "layout"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Normalise inner spacing of each line, drop empty lines and empty bullets, then set the separators."""
        current = text.text
        lines: list[tuple[int, int]] = []
        start = 0
        for line in current.split("\n"):
            lines.append((start, start + len(line)))
            start += len(line) + 1
        kept: list[tuple[int, int, str, bool, str]] = []  # start, end, normalised line, is_item, separator before
        blank_pending = False
        for s, e in lines:
            line = re.sub(r"[ \t]+", " ", current[s:e]).strip()
            if not line or line == "-":
                if line:
                    text.note(self.rule, line, "")
                blank_pending = blank_pending or bool(kept)
                continue
            is_item = line.startswith("- ") or bool(_LIST_ITEM_RE.match(line))
            if not kept:
                separator = ""
            elif blank_pending or is_item != kept[-1][3] or not is_item:
                separator = "\n\n"
            else:
                separator = "\n"
            kept.append((s, e, line, is_item, separator))
            blank_pending = False
        spans: list[tuple[int, int, str]] = []
        previous_end = 0
        for s, e, line, _, separator in kept:
            spans.append((previous_end, s, separator))
            spans.append((s, e, line))
            previous_end = e
        spans.append((previous_end, len(current), ""))
        text.apply(self.rule, [span for span in spans if span[0] < span[1] or span[2]], log=False)


def _is_currency_pair(word: str) -> bool:
    letters = re.sub(r"[^A-Z]", "", word)
    return len(letters) == 6 and letters[:3] in p.CURRENCIES and letters[3:] in p.CURRENCIES
