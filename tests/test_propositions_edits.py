import json

import pytest

from incolor.propositions.annotated import AnnotatedText
from incolor.propositions.edits import (
    Edit,
    annotate,
    edits_from_annotated,
    load_run,
    read_edits,
    render,
    source_ref,
    write_edits,
)
from incolor.propositions.sentences import split_sentences

SOURCE = "Will caching cut latency? We think it will. Rates & curve."
EDITS = [
    Edit(26, 34, "The author thinks", "deixis"),
    Edit(35, 37, "caching", "anaphora", ((5, 12),)),
    Edit(42, 42, " cut latency", "ellipsis", ((13, 24),)),
    Edit(50, 51, "and", "symbol"),
]


def test_views_are_derived_from_edits():
    text = annotate(SOURCE, EDITS)
    assert text.original() == SOURCE
    assert (
        render(text, "plain")
        == "Will caching cut latency? The author thinks caching will cut latency. Rates and curve."
    )
    assert render(text, "brackets") == (
        "Will caching cut latency? [The author thinks] [caching] will [cut latency]. Rates [and] curve."
    )
    assert render(text, "marks") == (
        "Will caching cut latency? {{We think => The author thinks}} {{it => caching}} will{{ =>  cut latency}}. "
        "Rates {{& => and}} curve."
    )
    assert AnnotatedText(text.marked).resolved() == text.resolved()
    assert render(text, "sentences").splitlines()[1] == "[E002] [The author thinks] [caching] will [cut latency]."


def test_insertion_maps_back_to_its_offset():
    text = annotate(SOURCE, EDITS)
    sentence = split_sentences(text)[1]
    assert sentence.source == "We think it will."
    assert text.marks[2].src_start == text.marks[2].src_end == 42


def test_jsonl_round_trip_and_quotes_are_checked(tmp_path):
    path = tmp_path / "edits.jsonl"
    write_edits(path, SOURCE, EDITS)
    assert read_edits(path, SOURCE) == EDITS
    with pytest.raises(ValueError, match="does not match"):
        read_edits(path, SOURCE.replace("We think", "We hope "))


def test_load_run_reads_the_sample_by_reference(tmp_path):
    sample = tmp_path / "samples" / "doc.txt"
    sample.parent.mkdir()
    sample.write_bytes(f"---\nTitle: Doc\nDate: 2026-09-14\n---\n\n{SOURCE}\r\n".encode())
    run = tmp_path / "outputs" / "normalise_v99" / "opus"
    run.mkdir(parents=True)
    (run / "validation.json").write_text(json.dumps({"summary": {"source": source_ref(run, sample)}}))
    write_edits(run / "edits.jsonl", SOURCE, EDITS)
    assert source_ref(run, sample) == "../../../samples/doc.txt"
    source, edits, text = load_run(run)
    assert (source, edits) == (SOURCE, EDITS)
    assert text.resolved().endswith("Rates and curve.")
    sample.write_text(SOURCE.replace("We think", "We hope "), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_run(run)


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        ([EDITS[1], EDITS[0]], "overlaps"),
        ([Edit(42, 42, " a"), Edit(42, 42, " b")], "two insertions"),
        ([Edit(0, 4, "  ")], "empty text"),
        ([Edit(0, 4, "{{x")], "reserved"),
        ([Edit(0, 99, "x")], "outside"),
    ],
)
def test_bad_edits_are_rejected(edits, message):
    with pytest.raises(ValueError, match=message):
        annotate(SOURCE, edits)


def test_edits_from_model_marks_drop_noops_and_find_pointers():
    source = "Banks face a choice: cut costs or raise capital. This tradeoff is hard. It is here."
    marked = (
        "Banks face a choice: cut costs or raise capital. "
        "{{This tradeoff => The tradeoff to cut costs or raise capital}} is hard. {{It => It}} is here."
    )
    edits = edits_from_annotated(AnnotatedText(marked), source)
    assert len(edits) == 1
    assert source[edits[0].start : edits[0].end] == "This tradeoff"
    assert [source[a:b] for a, b in edits[0].pointers] == ["cut costs or raise capital"]
    assert annotate(source, edits).resolved() == AnnotatedText(marked).resolved()
