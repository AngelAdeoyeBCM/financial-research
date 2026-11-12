import json

import pytest

from incolor.propositions.annotated import AnnotatedText, clean_response, link_antecedents, precheck, rooted_share
from incolor.propositions.normalise import (
    PROMPT_PATH,
    best_of,
    check,
    normalise,
    normalise_sections,
    split_sections,
)
from incolor.propositions.sentences import split_sentences

NO_LOG_PROMPT = PROMPT_PATH

SOURCE = (
    "We trained the model on the new dataset, but it did not converge. "
    "I think the cause may be the learning rate, and Bob the batch size."
)
MARKED = (
    "{{We => The author}} trained the model on the new dataset, but {{it => the model}} did not converge. "
    "{{I think => The author thinks}} the cause may be the learning rate, and "
    "{{Bob => Bob thinks the cause may be}} the batch size."
)


def codes(issues):
    return [i.code for i in issues]


def test_dropped_title_and_blank_lines_are_restored():
    source = "# Research Text\n\nWill it fall? We think so.\n\nRates rise.\n"
    raw = "Will it fall? {{We think so => The author thinks it will fall}}.\n\nRates rise."
    text, issues = check(source, raw)
    assert text.original() == source
    assert [i for i in issues if i.severity == "error"] == []


def test_truncated_answer_is_not_restored():
    source = "One.\nTwo.\nThree.\nFour.\n"
    text, issues = check(source, "{{One => 1}}.")
    assert text.original() != source
    assert "SOURCE_MISMATCH" in codes(issues)


def test_views_round_trip():
    text = AnnotatedText(MARKED)
    assert text.original() == SOURCE
    assert text.resolved().startswith("The author trained the model")
    assert "but [the model] did not converge" in text.resolved(brackets=True)
    assert text.issues(SOURCE) == []


def test_mark_offsets_index_both_texts():
    text = AnnotatedText(MARKED)
    for m in text.marks:
        assert SOURCE[m.src_start : m.src_end] == m.original
        assert text.resolved()[m.res_start : m.res_end] == m.resolution


def test_to_source_maps_spans_and_widens_inside_marks():
    text = AnnotatedText(MARKED)
    resolved = text.resolved()
    start = resolved.index("did not converge")
    src = SOURCE.index("did not converge")
    assert text.to_source(start, start + 16) == (src, src + 16)
    inside = resolved.index("model did")
    m = text.marks[1]
    assert text.to_source(inside, inside + 1) == (m.src_start, m.src_end)
    assert text.splits_mark(inside, inside + 1)
    assert not text.splits_mark(0, len(resolved))


def test_source_mismatch_reports_line_and_context():
    text = AnnotatedText(MARKED.replace("did not converge", "didn't converge", 1))
    issues = text.issues(SOURCE)
    assert codes(issues) == ["SOURCE_MISMATCH"]
    assert issues[0].segment == "line 1"
    assert "did not" in issues[0].message


@pytest.mark.parametrize(
    ("marked", "code"),
    [
        ("{{it -> the model}} works", "MALFORMED_MARK"),
        ("{{it\n=> the model}} works", "MALFORMED_MARK"),
        ("{{a => {{b => c}} d", "MALFORMED_MARK"),
        ("{{it => [the model]}} works", "BRACKET_IN_RESOLUTION"),
        ("{{it =>  }} works", "EMPTY_PART"),
    ],
)
def test_markup_errors(marked, code):
    assert code in codes(AnnotatedText(marked).issues(AnnotatedText(marked).original()))


def test_marks_parse_without_spaces_around_the_arrow():
    source = "Rates & curve."
    for marked in ("Rates {{&=> and}} curve.", "Rates {{& =>and}} curve.", "Rates {{&=>and}} curve."):
        text = AnnotatedText(marked)
        assert text.issues(source) == []
        assert text.resolved() == "Rates and curve."


def test_noop_mark_is_warning_only():
    issues = AnnotatedText("{{it => it}} works").issues("it works")
    assert [(i.severity, i.code) for i in issues] == [("warning", "NOOP_MARK")]


@pytest.mark.parametrize(
    ("source", "marked", "message"),
    [
        ("Rates may rise.", "{{Rates may rise => Rates rise}}.", "dropped ['may'] added []"),
        ("Yields lower.", "{{Yields lower => Yields are likely lower}}.", "dropped [] added ['likely']"),
        ("Bob won't go.", "{{Bob won't => Bob will}} go.", "dropped ['not'] added []"),
    ],
)
def test_modality_changes_warn(source, marked, message):
    issues = [i for i in AnnotatedText(marked).issues(source) if i.code == "MODALITY_CHANGED"]
    assert len(issues) == 1
    assert message in issues[0].message


def test_marks_in_questions_or_headings_are_errors_and_long_resolutions_warn():
    source = "## Our view\n\nWill it last? It may. Bob likes tea."
    marked = (
        "## {{Our => The author's}} view\n\n"
        "Will {{it => the rally}} last? {{It may => The rally may last}}. "
        "{{Bob => Bob of the long-standing tea appreciation society of London, which meets on the first Monday "
        "of every month in the back room of the old station hotel}} likes tea."
    )
    codes_ = codes(AnnotatedText(marked).issues(source))
    assert codes_.count("MARK_IN_QUESTION_OR_HEADING") == 2
    assert "LONG_RESOLUTION" in codes_


LOG_SOURCE = "We think Smith will speak. If right, yields rise. Waller may dissent. This would be dovish."
LOG_MARKED = (
    "{{We think => The author thinks}} Smith will speak. {{If => If the author is}} right, yields rise. "
    "Waller may dissent. {{This => This}} would be dovish."
)


def log_response(entries, unresolved=()):
    return f"{LOG_MARKED}\n\n=== LOG ===\n" + json.dumps({"marks": entries, "unresolved": list(unresolved)})


GOOD_ENTRIES = [
    {"i": 1, "type": "deixis", "antecedent": None},
    {"i": 2, "type": "propositional", "antecedent": "Smith will speak", "polarity": "affirm"},
    {"i": 3, "type": "abstract", "antecedent": ["Waller may dissent"]},
]


def test_log_is_parsed_validated_and_located():
    text, issues = check(LOG_SOURCE, log_response(GOOD_ENTRIES, [{"surface": "yields", "reason": "x or y"}]), True)
    assert issues == []
    assert text.antecedent_spans(1, LOG_SOURCE) == [(9, 25)]
    assert [LOG_SOURCE[a:b] for a, b in text.antecedent_spans(2, LOG_SOURCE)] == ["Waller may dissent"]
    assert text.antecedent_spans(0, LOG_SOURCE) == []


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        (GOOD_ENTRIES[:2], "LOG_COUNT_MISMATCH"),
        ([*GOOD_ENTRIES[:2], {**GOOD_ENTRIES[2], "antecedent": ["Waller dissents"]}], "LOG_ANTECEDENT_NOT_FOUND"),
        ([GOOD_ENTRIES[0], {**GOOD_ENTRIES[1], "polarity": None}, GOOD_ENTRIES[2]], "LOG_BAD_POLARITY"),
        ([{**GOOD_ENTRIES[0], "type": "pronoun"}, *GOOD_ENTRIES[1:]], "LOG_BAD_ENTRY"),
    ],
)
def test_log_errors(entries, code):
    _, issues = check(LOG_SOURCE, log_response(entries), True)
    assert code in codes(issues)


def test_zero_edit_marks_are_fine_only_for_log_only_types():
    _, issues = check(LOG_SOURCE, log_response(GOOD_ENTRIES), True)
    assert "NOOP_MARK" not in codes(issues)
    entity = [*GOOD_ENTRIES[:2], {"i": 3, "type": "entity", "antecedent": "Waller"}]
    assert "NOOP_MARK" in codes(check(LOG_SOURCE, log_response(entity), True)[1])


def test_missing_log_is_an_error_only_when_required():
    assert "LOG_MISSING" in codes(check(LOG_SOURCE, LOG_MARKED, True)[1])
    assert "LOG_MISSING" not in codes(check(LOG_SOURCE, LOG_MARKED, False)[1])


def test_warnings_are_report_only():
    source = "Smith spoke. He was hawkish."
    backend = FakeBackend([source])
    result = normalise(source, backend, max_repairs=1, prompt_path=NO_LOG_PROMPT)
    assert result.ok
    assert len(result.raw_outputs) == 1
    assert [i.code for i in result.issues] == ["UNRESOLVED_PRONOUN"]


def test_ungrounded_words_trigger_a_retry_but_do_not_fail():
    source = "Smith spoke. He was hawkish."
    reworded = "Smith spoke. {{He => The chairwoman}} was hawkish."
    backend = FakeBackend([reworded, reworded])
    result = normalise(source, backend, max_repairs=1, prompt_path=NO_LOG_PROMPT)
    assert result.ok
    assert len(result.raw_outputs) == 2
    assert "UNGROUNDED_WORD" in backend.prompts[1]


def test_typography_slips_are_snapped_back_to_the_source():
    source = "Fed ability to \u201cout-hawk\u201d peers \u2013 we think so."
    raw = 'Fed ability to "out-hawk" peers - {{we think => the author thinks}} so.'
    result = normalise(source, FakeBackend([raw]), max_repairs=0, prompt_path=NO_LOG_PROMPT)
    assert result.ok
    assert result.text is not None
    assert result.text.original() == source
    assert result.text.resolved() == "Fed ability to \u201cout-hawk\u201d peers \u2013 the author thinks so."


def test_sentence_count_must_not_change():
    source = "Yields may fall. Even without a cut. Spreads could tighten."
    merged = "Yields may fall. Even without a {{cut. Spreads => cut, spreads}} could tighten."
    assert "SENTENCE_COUNT_CHANGED" in codes(check(source, merged)[1])
    kept = "Yields may fall. Even without a {{cut. => cut, yields may fall.}} Spreads could tighten."
    assert check(source, kept)[1] == []


def test_if_wrong_may_become_a_negated_claim():
    source = "We think Smith will speak. If wrong, yields fall."
    marked = "{{We think => The author thinks}} Smith will speak. {{If wrong => If Smith will not speak}}, yields fall."
    assert check(source, marked)[1] == []


def test_rooted_share_counts_words_in_copied_spans():
    source = "Banks face a choice: cut costs or raise capital. This tradeoff is hard. He left."
    rooted = (
        "Banks face a choice: cut costs or raise capital. "
        "{{This tradeoff => The tradeoff to cut costs or raise capital}} is hard. {{He => Banks}} left."
    )
    assert rooted_share(AnnotatedText(rooted), source) == 1.0
    reworded = rooted.replace("to cut costs or raise capital", "of trimming costs")
    assert rooted_share(AnnotatedText(reworded), source) == pytest.approx(1 / 3)


def test_split_ignores_straight_apostrophes_as_quotes():
    text = "Total hikes to decline by end '26. Initially, 2Y lower. Buybacks' stumble hurts."
    assert [s.text for s in split_sentences(AnnotatedText(text))] == [
        "Total hikes to decline by end '26.",
        "Initially, 2Y lower.",
        "Buybacks' stumble hurts.",
    ]


def test_review_pass_is_adopted_only_when_not_worse():
    source = "Smith spoke. Bob left."
    first = "Smith spoke. Bob left."
    better = "Smith spoke. {{Bob => Bob}} left."
    broken = "Smith spoke. Bob went."
    adopted = normalise(source, FakeBackend([first, better]), review=True, prompt_path=NO_LOG_PROMPT)
    assert adopted.reviewed
    assert adopted.text is not None
    assert adopted.text.marked == better
    kept = normalise(source, FakeBackend([first, broken]), review=True, prompt_path=NO_LOG_PROMPT)
    assert not kept.reviewed
    assert kept.text is not None
    assert kept.text.marked == first
    assert len(kept.raw_outputs) == 2


def test_unresolved_pronouns_warn_outside_questions_and_headings():
    source = "## His view\n\nSmith spoke. He was hawkish. Will he stay hawkish? It is early."
    issues = AnnotatedText(source).issues(source)
    assert [(i.code, i.message.split(" in ")[0]) for i in issues] == [("UNRESOLVED_PRONOUN", "'He'")]


def test_ungrounded_words_warn_but_inflections_and_glue_pass():
    source = "The dollar has been unable to rally. Part of the puzzle lies in rates. We think so."
    ok = (
        "The dollar has been unable to rally. Part of {{the puzzle => the puzzle of the dollar being unable to rally}}"
        " lies in rates. {{We think => The author thinks}} so."
    )
    assert AnnotatedText(ok).issues(source) == []
    bad = ok.replace("the dollar being unable to rally", "the dollar failing to rally")
    issues = AnnotatedText(bad).issues(source)
    assert [(i.severity, i.code) for i in issues] == [("warning", "UNGROUNDED_WORD")]
    assert "['failing']" in issues[0].message


def test_link_antecedents_finds_verbatim_spans():
    source = "Banks face a choice: cut costs or raise capital. This tradeoff is hard. We see it."
    marked = (
        "Banks face a choice: cut costs or raise capital. "
        "{{This tradeoff => The tradeoff to cut costs or raise capital}} is hard. "
        "{{We see it => The author sees the choice}}."
    )
    text = AnnotatedText(marked)
    links = link_antecedents(text, source)
    assert [[source[a:b] for a, b in spans] for spans in links] == [["cut costs or raise capital"], ["choice"]]


def test_unresolved_word_symbols_warn_outside_headings_numbers_and_names():
    source = "## Rates & FX\n\nPricing = ~85% & rising; S&P up, shift +25bps."
    issues = AnnotatedText(source).issues(source)
    assert [(i.severity, i.code, i.segment) for i in issues] == [("warning", "UNRESOLVED_SYMBOL", "line 3")] * 3
    marked = (
        "## Rates & FX\n\nPricing {{= => is}} {{~85% => approximately 85%}} {{& => and}} rising; S&P up, shift +25bps."
    )
    assert AnnotatedText(marked).issues(source) == []


def test_precheck_and_clean_response():
    assert codes(precheck("a => b")) == ["RESERVED_IN_SOURCE"]
    assert precheck(SOURCE) == []
    assert clean_response(f"```text\n{MARKED}\n```\n") == MARKED


class FakeBackend:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, system_prompt, user_prompt, json_schema):
        self.prompts.append(user_prompt)
        return self.replies.pop(0)


SECTIONED = (
    "# Title\n\nIntro text.\n\n## First\n\nWe think Smith will speak. He may not.\n\n"
    "## Second\n\nBanks face a choice. This tradeoff is hard."
)


class SectionBackend:
    """Returns the requested section unchanged, or with ``edits`` applied (old -> new) when given."""

    def __init__(self, edits=None, broken=None):
        self.edits, self.broken, self.calls = edits or {}, broken, 0

    def generate(self, system_prompt, user_prompt, json_schema):
        self.calls += 1
        part = user_prompt.split("Input:\n", 1)[1].split("\nYour previous answer:", 1)[0].rstrip("\n")
        if self.broken and self.broken in part:
            return part.replace(self.broken, "garbled")
        for old, new in self.edits.items():
            part = part.replace(old, new)
        return part


def test_split_sections_tiles_the_document_at_headings():
    spans = split_sections(SECTIONED, min_chars=20)
    assert [SECTIONED[a:b].split("\n")[0] for a, b in spans] == ["# Title", "## First", "## Second"]
    assert split_sections(SECTIONED, min_chars=10_000) == [(0, len(SECTIONED))]


def test_normalise_sections_combines_sections_and_validates_the_whole():
    edits = {"We think": "{{We think => The author thinks}}", "This tradeoff": "{{This tradeoff => The choice}}"}
    result = normalise_sections(SECTIONED, SectionBackend(edits), prompt_path=NO_LOG_PROMPT, workers=1, min_chars=20)
    assert result.ok
    assert result.text is not None
    assert result.text.original() == SECTIONED
    assert len(result.text.marks) == 2


def test_failed_section_falls_back_to_source_text():
    backend = SectionBackend(broken="Banks face")
    result = normalise_sections(SECTIONED, backend, max_repairs=1, prompt_path=NO_LOG_PROMPT, workers=1, min_chars=20)
    assert result.ok
    assert result.text is not None
    assert result.text.original() == SECTIONED
    assert "SECTION_UNRESOLVED" in codes(result.issues)
    assert backend.calls == 4


def test_normalise_retries_with_errors_then_passes():
    backend = FakeBackend([MARKED.replace("did not", "didn't"), MARKED])
    result = normalise(SOURCE, backend, max_repairs=2, prompt_path=NO_LOG_PROMPT)
    assert result.ok
    assert len(result.raw_outputs) == 2
    assert "SOURCE_MISMATCH" in backend.prompts[1]


def test_normalise_fails_after_max_repairs_and_keeps_best():
    bad = MARKED.replace("did not", "didn't")
    result = normalise(SOURCE, FakeBackend([bad, bad + " extra\nline"]), max_repairs=1, prompt_path=NO_LOG_PROMPT)
    assert not result.ok
    assert result.text is not None
    assert result.text.marked == bad
    assert best_of(SOURCE, result.raw_outputs).text.marked == bad


def test_normalise_blocks_reserved_tokens_without_calling_model():
    backend = FakeBackend([])
    result = normalise("x {{y}}", backend)
    assert not result.ok
    assert backend.prompts == []


def test_split_sentences_markdown_and_offsets():
    source = "## Outlook\n\n- We expect a cut. It may come in June.\n\nIf right, our bias holds. Will it last?"
    marked = (
        "## Outlook\n\n- {{We expect => The author expects}} a cut. {{It => The cut}} may come in June.\n\n"
        "{{If => If the author is}} right, {{our => the author's}} bias holds. Will it last?"
    )
    text = AnnotatedText(marked)
    assert text.issues(source) == []
    sentences = split_sentences(text)
    assert [(s.id, s.kind) for s in sentences] == [
        ("E001", "heading"),
        ("E002", "bullet"),
        ("E003", "bullet"),
        ("E004", "text"),
        ("E005", "text"),
    ]
    assert sentences[0].text == "Outlook"
    assert sentences[1].text == "The author expects a cut."
    assert sentences[1].source == "We expect a cut."
    assert sentences[2].text_brackets == "[The cut] may come in June."
    assert sentences[3].source == "If right, our bias holds."
    assert not any(s.splits_mark for s in sentences)
    assert split_sentences(AnnotatedText(marked)) == sentences
