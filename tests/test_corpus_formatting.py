"""Corpus formatting and cleaning fixes: enumerations, words, characters, quotes, banners, promos, rules and warnings."""

import re

from incolor.ingestion.corpus.chunks import ResearchDocument
from incolor.parsing.core.sections import Section
from incolor.parsing.core.text import EditableText
from incolor.parsing.corpus import patterns as p
from incolor.parsing.corpus.cleaning import PatternStripper, TemplateStripper
from incolor.parsing.corpus.normalise import (
    EnumerationNormaliser,
    PunctuationSpacingNormaliser,
    QuoteStyleNormaliser,
    SplitWordJoiner,
    UnicodeNormaliser,
)
from incolor.parsing.corpus.steps import DocumentContext, Normaliser, Vocabulary
from incolor.parsing.corpus.validate import FormatValidator


def run(text: str, step: Normaliser | TemplateStripper | PatternStripper, vocabulary: Vocabulary | None = None):
    """Apply one step to ``text`` and return the editable result (content plus ignored text)."""
    editable = EditableText(text)
    context = DocumentContext(ResearchDocument("x.pdf", "2026-10-20", [], {}), vocabulary or Vocabulary())
    step.apply(editable, context)
    return editable


def test_enumeration_joins_mixed_delimiters() -> None:
    text = run("Points: (1) alpha (2) beta and 3) gamma", EnumerationNormaliser()).text
    assert re.findall(r"^(\d)\. (\w+)", text, re.M) == [("1", "alpha"), ("2", "beta"), ("3", "gamma")]


def test_enumeration_accepts_letter_markers() -> None:
    text = run("Steps: a) first b) second", EnumerationNormaliser()).text
    assert re.findall(r"^(\d)\. (\w+)", text, re.M) == [("1", "first"), ("2", "second")]


def test_enumeration_ignores_single_marker() -> None:
    assert run("See (1) only here", EnumerationNormaliser()).text == "See (1) only here"


def test_split_word_joins_plural_s() -> None:
    vocabulary = Vocabulary.from_texts(["pressures rise", "pressures ease", "pressures again"])
    assert run("pressure s rise", SplitWordJoiner(), vocabulary).text == "pressures rise"


def test_unicode_drops_invisible_and_normalises_compatibility_forms() -> None:
    text = run("\ufb01nance\u00ad co\u200bst \u00d7 \u2265 \u20ac", UnicodeNormaliser()).text
    assert text == "finance cost \u00d7 \u2265 \u20ac"


def test_quotes_majority_straight_keeps_straight() -> None:
    assert run('a "b" c "d" \u201ce\u201d', QuoteStyleNormaliser()).text == 'a "b" c "d" "e"'


def test_quotes_tie_becomes_typographic() -> None:
    assert run('say \u201chi\u201d and "bye" fine', QuoteStyleNormaliser()).text == "say \u201chi\u201d and \u201cbye\u201d fine"


def test_quotes_majority_curly_converts_apostrophe() -> None:
    text = run("say \u201chi\u201d and \u201cbye\u201d it's", QuoteStyleNormaliser()).text
    assert text == "say \u201chi\u201d and \u201cbye\u201d it\u2019s"


def test_punctuation_spacing_attaches_possessive_and_quotes() -> None:
    text = run("bank \u2019s  rate \u201c quoted \u201d end", PunctuationSpacingNormaliser()).text
    assert text == "bank\u2019s rate \u201cquoted\u201d end"


def test_rule_line_is_stripped_as_artefact() -> None:
    editable = run("Intro ____________ Body", PatternStripper("rule_line", Section.ARTEFACT, p.RULE_LINE_RE))
    assert "_" not in editable.text
    assert [i.kind for i in editable.ignored] == ["artefact"]


def test_letter_spaced_banner_is_stripped_as_header() -> None:
    editable = run(
        "TRADE IDEA T R A D E I D E A 08/07/2026 1 Rates view",
        PatternStripper("letter_spaced", Section.HEADER, p.LETTER_SPACED_RE),
    )
    assert "T R A D" not in editable.text
    assert [i.kind for i in editable.ignored] == ["header"]


def test_app_promo_is_stripped_as_promotion() -> None:
    text = (
        "BNP PARIBAS GLOBAL MARKETS APP: SCAN THE QR CODE TO READ OUR PUBLICATIONS ON OUR MOBILE APP KEY MESSAGES We think"
    )
    editable = run(text, PatternStripper("app_promo", Section.PROMOTION, p.APP_PROMO_RE))
    assert "QR" not in editable.text
    assert "KEY MESSAGES" in editable.text
    assert [i.kind for i in editable.ignored] == ["promotion"]


def test_bnp_disclaimer_with_asas_prefix_is_stripped_as_disclaimer() -> None:
    text = "asas Please refer to important information at the end of the report and MAR disclosures 11 August 2026 1 Body text"
    editable = run(text, TemplateStripper())
    assert "asas" not in editable.text
    assert "MAR" not in editable.text
    assert "Body text" in editable.text
    assert [i.kind for i in editable.ignored] == ["disclaimer"]


def test_trade_idea_banner_with_date_is_stripped() -> None:
    editable = run("TRADE IDEA T R A D E I D E A 08/07/2026 1 Rates view", TemplateStripper())
    assert "TRADE" not in editable.text
    assert "Rates view" in editable.text


def test_keep_page_gutter_footer_is_stripped_as_footer() -> None:
    editable = run("Body keep page margin clear keep page gutter clear more", TemplateStripper())
    assert "keep page" not in editable.text
    assert [i.kind for i in editable.ignored] == ["footer"]


def test_validator_warns_on_letter_spaced_text_and_rule_lines() -> None:
    codes = {w.code for w in FormatValidator.content_warnings("T R A D E I D E A\n____\nfoo")}
    assert {"letter_spaced", "rule_line"} <= codes


def test_validator_warns_on_mixed_quotes() -> None:
    codes = {w.code for w in FormatValidator.content_warnings('He said "hi\u201d ok')}
    assert "mixed_quotes" in codes
