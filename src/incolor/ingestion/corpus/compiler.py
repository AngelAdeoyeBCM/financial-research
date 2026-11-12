"""Compile one document: corruption gate, then cleaning (stripped text kept), then formatting, then validation."""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ...parsing.core.document import CorpusDocument, FrontMatter
from ...parsing.core.sections import Section
from ...parsing.core.text import Edit, EditableText, IgnoredText
from ...parsing.corpus import patterns as p
from ...parsing.corpus.cleaning import (
    ContactStripper,
    PatternStripper,
    RepeatedPhraseStripper,
    SeriesHeaderStripper,
    TemplateStripper,
)
from ...parsing.corpus.normalise import (
    BulletNormaliser,
    EnumerationNormaliser,
    HeadingNormaliser,
    HyphenationNormaliser,
    LayoutNormaliser,
    LoneBulletNormaliser,
    PunctuationSpacingNormaliser,
    QuoteStyleNormaliser,
    RunInLabelSplitter,
    SpacingNormaliser,
    SplitWordJoiner,
    TitleNormaliser,
    UnicodeNormaliser,
    WhitespaceNormaliser,
)
from ...parsing.corpus.steps import DocumentContext, TextStep, Vocabulary
from ...parsing.corpus.validate import Finding, FormatValidator
from .chunks import ResearchDocument
from .gate import SKIP, CorruptionGate, Issue

MAX_LOGGED_EXAMPLES = 5


def cleaning_steps() -> list[TextStep]:
    """Strip boilerplate, contacts, disclaimers and page furniture; fix spacing and split words (original order)."""
    return [
        WhitespaceNormaliser(),
        TemplateStripper(),
        ContactStripper(),
        TemplateStripper(),
        RepeatedPhraseStripper(),
        SeriesHeaderStripper(),
        PatternStripper("letter_spaced", Section.HEADER, p.LETTER_SPACED_RE),
        PatternStripper("app_promo", Section.PROMOTION, p.APP_PROMO_RE),
        PatternStripper("rule_line", Section.ARTEFACT, p.RULE_LINE_RE),
        LoneBulletNormaliser(),
        PatternStripper("email", Section.SIGNATURE, p.EMAIL_RE),
        PatternStripper("url", Section.PROMOTION, p.URL_RE),
        HyphenationNormaliser(),
        SplitWordJoiner(),
        SpacingNormaliser(),
    ]


def formatting_steps() -> list[TextStep]:
    """Title, bullets, characters, quotes, numbered lists, headings, run-in labels, punctuation, then layout."""
    return [
        TitleNormaliser(),
        BulletNormaliser(),
        UnicodeNormaliser(),
        QuoteStyleNormaliser(),
        EnumerationNormaliser(),
        HeadingNormaliser(),
        RunInLabelSplitter(),
        PunctuationSpacingNormaliser(),
        LayoutNormaliser(),
    ]


def front_matter(doc: ResearchDocument, title: str, warnings: tuple[str, ...] = ()) -> FrontMatter:
    """Metadata from the chunks; ``Author`` may be a list of ``{Name, Role}`` or a ``;``-separated string."""
    meta = doc.metadata
    raw = meta.get("Author") or []
    names = [a.get("Name") if isinstance(a, dict) else a for a in (raw if isinstance(raw, list) else [raw])]
    authors = [a.strip() for name in names if name for a in re.split(r"[;|]", str(name))]
    source = meta.get("Source")
    return FrontMatter(
        title=title,
        publisher=source if source and source != "Unknown" else None,
        document_type=meta.get("DocumentType"),
        date=meta.get("DocumentDate") or doc.date or None,
        authors=tuple(a for a in authors if a),
        warnings=tuple(warnings),
    )


@dataclass
class Compilation:
    """Outcome for one document; ``rendered`` is set only when it compiled."""

    doc: ResearchDocument
    status: str
    issues: list[Issue] = field(default_factory=list)
    rendered: str | None = None
    ignored: list[IgnoredText] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    fingerprint: str | None = None
    title_in_text: bool = False

    def log(self) -> dict[str, Any]:
        """Cleaning and formatting log for the extract manifest."""
        by_rule: dict[str, list[Edit]] = {}
        for edit in self.edits:
            by_rule.setdefault(edit.rule, []).append(edit)
        return {
            "stripped": [{"rule": i.rule, "section": i.kind, "text": i.text} for i in self.ignored],
            "stripped_by_section": dict(Counter(i.kind for i in self.ignored)),
            "edits": {
                rule: {
                    "count": len(edits),
                    "examples": [{"before": e.before, "after": e.after} for e in edits[:MAX_LOGGED_EXAMPLES]],
                }
                for rule, edits in by_rule.items()
            },
            "warnings": [{"code": w.code, "context": w.detail} for w in self.warnings],
        }


class DocumentCompiler:
    """Turns a ``ResearchDocument`` into a rendered corpus file, or a list of reasons to skip it."""

    def __init__(
        self,
        gate: CorruptionGate | None = None,
        cleaning: list[TextStep] | None = None,
        formatting: list[TextStep] | None = None,
        validator: FormatValidator | None = None,
    ) -> None:
        self.gate = gate or CorruptionGate()
        self.cleaning = cleaning if cleaning is not None else cleaning_steps()
        self.formatting = formatting if formatting is not None else formatting_steps()
        self.validator = validator or FormatValidator()

    def compile(self, doc: ResearchDocument, vocabulary: Vocabulary | None = None) -> Compilation:
        """Gate, clean, format, render and validate ``doc``.

        Skip-severity gate issues stop compilation. Warning-severity issues are kept on the compiled result and
        listed in the front matter as ``Warnings``.
        """
        issues = self.gate.inspect(doc)
        if skips := [i for i in issues if i.severity == SKIP]:
            return Compilation(doc, "skipped", skips)
        warnings_codes = tuple(sorted({i.code for i in issues}))
        context = DocumentContext(doc, vocabulary or Vocabulary())
        text = EditableText(doc.merged_text())
        for step in self.cleaning:
            step.apply(text, context)
        key = re.sub(r"\W+", "", text.text[:3000]).lower()
        fingerprint = hashlib.sha1(key.encode("utf-8")).hexdigest()
        title_in_text = "".join(p.SPLIT_WORDS_RE.split(context.bare_stem)).lower() in key
        for step in self.formatting:
            step.apply(text, context)
        front = front_matter(doc, context.title, warnings_codes)
        document = CorpusDocument(front, text.text)
        rendered = document.render()
        errors, warnings = self.validator.validate(rendered, expected_content=text.text)
        result = Compilation(
            doc, "compiled", issues, rendered, text.ignored, text.edits, warnings, fingerprint, title_in_text
        )
        if errors:
            result.status, result.rendered = "skipped", None
            result.issues = [Issue("VALIDATION_ERROR", f"{e.code}: {e.detail}") for e in errors]
        return result
