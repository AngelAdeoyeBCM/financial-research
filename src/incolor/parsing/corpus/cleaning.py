"""Strippers: move boilerplate, contacts, disclaimers and page furniture out of the content into ignored text."""

import re
from collections import Counter
from functools import lru_cache

from ..core.sections import Section
from ..core.text import EditableText
from . import patterns as p
from .steps import DocumentContext, Stripper

_DISCLAIMER_RE = re.compile(
    r"(?i)disclos|redistribut|certif|exclusive use|regulat|investors|intended for|prepared for|risk|FINRA|prohibited"
)


class TemplateStripper(Stripper):
    """Publisher templates: disclaimers, page headers/footers, distribution stamps."""

    rule = "template"

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Remove every template match (each becomes a space)."""
        text.sub(self.rule, _templates(context.series), " ", ignore_kind=self._section)

    @staticmethod
    def _section(removed: str) -> Section:
        return Section.DISCLAIMER if _DISCLAIMER_RE.search(removed) else Section.FOOTER


class ContactStripper(Stripper):
    """Analyst contact blocks (name, title, entity, phone, e-mail) and any masthead directly before them."""

    rule = "contact_block"
    section = Section.SIGNATURE

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Drop each block seeded by an e-mail address or international phone number."""
        tokens = [t.group() for t in text.tokens()]
        drop = [False] * len(tokens)
        seeds = [i for i in range(len(tokens)) if self._is_seed(tokens, i)]
        k = 0
        while k < len(seeds):
            first = last = seeds[k]
            k += 1
            while (
                k < len(seeds)
                and seeds[k] - last <= p.MAX_CONTACT_SPAN
                and all(self._is_contact_token(t) for t in tokens[last + 1 : seeds[k]])
            ):
                last = seeds[k]
                k += 1
            start = first
            while start > 0 and first - start < p.MAX_CONTACT_SPAN and self._is_contact_token(tokens[start - 1]):
                start -= 1
            end = last + 1
            while end < len(tokens) and (
                p.PHONE_PART_RE.fullmatch(tokens[end])
                or tokens[end].rstrip(",") in p.CONTACT_ORG_WORDS
                or tokens[end] in {"|", "-"}
            ):
                end += 1
            drop[start:end] = [True] * (end - start)
        text.drop_tokens(self.rule, drop, ignore_kind=self.section)

    @staticmethod
    def _is_contact_token(token: str) -> bool:
        if token in p.CONTACT_CONNECTORS or p.PHONE_PART_RE.fullmatch(token) or p.EMAIL_RE.search(token):
            return True
        if token.endswith(("’s", "'s")) or not p.CONTACT_TOKEN_RE.fullmatch(token):
            return False
        bare = token.strip(",|")
        return not bare.endswith(".") or bare in p.CONTACT_ABBREVIATIONS or len(bare) <= 3

    @staticmethod
    def _is_seed(tokens: list[str], i: int) -> bool:
        # An e-mail address, or an international phone number (not a signed figure such as "+0.4%").
        if p.EMAIL_RE.search(tokens[i]):
            return True
        if not tokens[i].startswith("+"):
            return False
        parts = [tokens[i].lstrip("+")] if tokens[i] != "+" else []
        parts += tokens[i + 1 : i + 5]
        digits = 0
        for part in parts:
            if not p.PHONE_PART_RE.fullmatch(part):
                return digits >= p.MIN_PHONE_DIGITS
            digits += sum(ch.isdigit() for ch in part)
        return digits >= p.MIN_PHONE_DIGITS


class RepeatedPhraseStripper(Stripper):
    """Page headers/footers: repeated capitalised phrases, phrases naming the publisher, and 8-word repeats."""

    rule = "repeated_phrase"
    section = Section.FOOTER

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Drop the repeats (the first occurrence of an 8-word phrase is kept)."""
        tokens = [t.group() for t in text.tokens()]
        n = p.REPEAT_NGRAM
        grams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
        counts = Counter(grams)
        drop = [False] * len(tokens)
        for i, gram in enumerate(grams):
            capitalised = sum(t[:1].isupper() or t[:1].isdigit() for t in gram)
            publisher = any(t.strip(",.|") in p.PROVIDER_WORDS for t in gram)
            if (counts[gram] >= 2 and publisher) or (counts[gram] >= 3 and capitalised >= n - 2):
                drop[i : i + n] = [True] * n
        m = p.REPEAT_PHRASE
        phrases = Counter(tuple(tokens[i : i + m]) for i in range(len(tokens) - m + 1))
        seen: set[tuple[str, ...]] = set()
        for i in range(len(tokens) - m + 1):
            phrase = tuple(tokens[i : i + m])
            if phrases[phrase] >= 3 and phrase in seen:
                drop[i : i + m] = [True] * m
            seen.add(phrase)
        text.drop_tokens(self.rule, drop, ignore_kind=self.section)


class SeriesHeaderStripper(Stripper):
    """The publication series name repeated as a running header (kept once)."""

    rule = "series_header"
    section = Section.HEADER

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Remove every occurrence after the first when a multi-word series name repeats."""
        series = context.series
        if len(series.split()) < 2:
            return
        pattern = re.compile(rf"\b{re.escape(series)}\b", re.IGNORECASE)
        matches = list(pattern.finditer(text.text))
        if len(matches) >= p.MAX_HEADER_REPEATS:
            text.apply(self.rule, [(m.start(), m.end(), " ") for m in matches[1:]], ignore_kind=self.section)


class PatternStripper(Stripper):
    """Removes every match of one pattern."""

    def __init__(self, rule: str, section: Section, pattern: re.Pattern[str]) -> None:
        self.rule = rule
        self.section = section
        self.pattern = pattern

    def apply(self, text: EditableText, context: DocumentContext) -> None:
        """Replace each match with a space."""
        text.sub(self.rule, self.pattern, " ", ignore_kind=self.section)


@lru_cache(maxsize=256)
def _templates(series: str) -> re.Pattern[str]:
    series_re = re.escape(series) if series else "(?!)"
    return re.compile("|".join(f"(?:{t.replace('{series}', series_re)})" for t in p.BOILERPLATE_TEMPLATES))
