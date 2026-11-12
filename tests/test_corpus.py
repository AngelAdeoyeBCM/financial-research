"""Corpus ingestion: dump validation, selection, gate, editable text, file round trip, normalisers and batches."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from incolor.ingestion.corpus import BatchRunner, ChunkDump, CorpusDocument, CorpusPaths, DumpError
from incolor.ingestion.corpus.chunks import DocumentAssembler, ResearchDocument
from incolor.ingestion.corpus.compiler import DocumentCompiler
from incolor.ingestion.corpus.gate import CorruptionGate
from incolor.ingestion.corpus.ledger import DocumentRecord, Ledger
from incolor.ingestion.corpus.selection import AssetClassFilter
from incolor.parsing.core.document import FrontMatter
from incolor.parsing.core.text import EditableText, IgnoredText
from incolor.parsing.corpus.normalise import (
    BulletNormaliser,
    EnumerationNormaliser,
    HeadingNormaliser,
    LayoutNormaliser,
    RunInLabelSplitter,
    SplitWordJoiner,
)
from incolor.parsing.corpus.steps import DocumentContext, Normaliser, Vocabulary
from incolor.parsing.corpus.validate import FormatValidator

DATE = "2026-10-20"
DOLLAR_TEXT = [
    "Dollar outlook The dollar should weaken further as the Fed cuts rates and growth slows.",
    "We expect the euro to gain against the dollar while the yen recovers as the BoJ hikes again.",
]
RATES_TEXT = [
    "Rates view We think the curve will steepen because the long end has to absorb more supply.",
    "Front-end yields should fall as the market prices more cuts than the central bank signals.",
]


def record(document: str, index: int, text: str, asset_class: str = "FX", date: str = DATE) -> dict[str, Any]:
    """A chunk record as returned by ``browse_metadata``."""
    return {
        "chunk_id": f"{document}-1-{index}",
        "point_id": f"{document}-{date}-{index}",
        "DocumentDate": date,
        "Source": "Test Bank",
        "DocumentType": "Research",
        "Author": [{"Name": "A. Analyst"}],
        "Asset": [{"Class": asset_class}],
        "text": text,
    }


def document(name: str, texts: list[str], asset_class: str = "FX", indices: list[int] | None = None):
    """Assemble one ``ResearchDocument`` from synthetic chunk texts."""
    assembler = DocumentAssembler()
    positions = indices or list(range(len(texts)))
    assembler.add(record(name, i, t, asset_class) for i, t in zip(positions, texts, strict=True))
    return next(assembler.documents())


def normalise(text: str, *steps: Normaliser, vocabulary: Vocabulary | None = None) -> str:
    """Run normalisers on ``text`` and return the result."""
    editable = EditableText(text)
    context = DocumentContext(ResearchDocument("x.pdf", DATE, [], {}), vocabulary or Vocabulary())
    for step in steps:
        step.apply(editable, context)
    return editable.text


# --- ChunkDump ------------------------------------------------------------------------------------------------------


def write_dump(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "dump.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_dump_loads_valid_records(tmp_path: Path) -> None:
    dump = ChunkDump.load(write_dump(tmp_path, {"count": 1, "records": [record("a.pdf", 0, "Text.")]}))
    assert len(dump.records) == 1
    assert dump.dates == [DATE]


@pytest.mark.parametrize(
    "payload",
    [
        {"count": 1, "records": [record("a.pdf", 0, "Text.")], "truncated": True},
        {"count": 2, "records": [record("a.pdf", 0, "Text.")]},
        {"count": 1, "records": [record("a.pdf", 0, "")]},
    ],
    ids=["truncated", "count_mismatch", "no_text"],
)
def test_dump_rejects_unusable_payloads(tmp_path: Path, payload: dict[str, Any]) -> None:
    with pytest.raises(DumpError):
        ChunkDump.load(write_dump(tmp_path, payload))


# --- Selection and gate ---------------------------------------------------------------------------------------------


def test_asset_class_filter_needs_one_fx_or_rates_chunk() -> None:
    assembler = DocumentAssembler()
    assembler.add([record("fx.pdf", 0, "One."), record("fx.pdf", 1, "Two.", "Equities")])
    assembler.add([record("eq.pdf", 0, "One.", "Equities")])
    kept = {d.name: AssetClassFilter().matches(d) for d in assembler.documents()}
    assert kept == {"fx.pdf": True, "eq.pdf": False}


def test_gate_flags_missing_chunks() -> None:
    doc = document("a.pdf", ["The dollar falls.", "The yen rises."], indices=[0, 2])
    assert [i.code for i in CorruptionGate().inspect(doc)] == ["MISSING_CHUNKS"]


def test_gate_flags_figure_caption_but_not_reference() -> None:
    caption = document("a.pdf", ["Inflation stays high. Figure 3: US CPI"])
    reference = document("b.pdf", ["Inflation stays high, as shown in Figure 3."])
    issues = CorruptionGate().inspect(caption)
    assert [(i.code, i.reprocess, i.severity) for i in issues] == [("FIGURE_CAPTION", "chart", "warning")]
    assert CorruptionGate().inspect(reference) == []


def test_figure_caption_compiles_with_warning_tag() -> None:
    doc = document("GS_Rates view.pdf", [*RATES_TEXT, "Inflation stays high. Figure 3: US CPI"])
    result = DocumentCompiler().compile(doc)
    assert result.status == "compiled"
    assert [i.code for i in result.issues] == ["FIGURE_CAPTION"]
    assert result.rendered is not None
    assert "Warnings:\n  - FIGURE_CAPTION\n---" in result.rendered
    parsed = CorpusDocument.parse(result.rendered)
    assert parsed.front_matter.warnings == ("FIGURE_CAPTION",)
    errors, _ = FormatValidator().validate(result.rendered, expected_content=parsed.content)
    assert errors == []


def test_clean_document_has_no_warnings_key() -> None:
    result = DocumentCompiler().compile(document("GS_Rates view.pdf", RATES_TEXT))
    assert result.status == "compiled"
    assert result.issues == []
    assert result.rendered is not None
    assert "Warnings" not in result.rendered


def test_manifest_log_reports_sections() -> None:
    doc = document("GS_Rates view.pdf", [*RATES_TEXT, "Contact: Jane Doe, jane.doe@example.com"])
    result = DocumentCompiler().compile(doc)
    assert result.status == "compiled"
    log = result.log()
    assert log["stripped"], "contact block should be stripped"
    assert all("section" in entry and "kind" not in entry for entry in log["stripped"])
    assert "signature" in {entry["section"] for entry in log["stripped"]}
    assert log["stripped_by_section"] == dict(Counter(entry["section"] for entry in log["stripped"]))


# --- EditableText ---------------------------------------------------------------------------------------------------


def test_anchor_survives_later_edits() -> None:
    text = EditableText("Hello   DISCLAIMER   world")
    text.drop_tokens("template", [False, True, False], ignore_kind="disclaimer")
    assert text.text == "Hello world"
    text.apply("greeting", [(0, 5, "Greetings"), (6, 11, "everyone")])
    (anchor,) = text.anchors
    assert text.text == "Greetings everyone"
    assert text.text[: anchor.pos].rstrip() == "Greetings"
    assert text.text[anchor.pos :].lstrip() == "everyone"
    assert anchor.item == IgnoredText("template", "disclaimer", "DISCLAIMER")
    assert [(e.before, e.after) for e in text.edits] == [("Hello", "Greetings"), ("world", "everyone")]


# --- File round trip ------------------------------------------------------------------------------------------------


def test_render_parse_round_trip_keeps_front_matter_and_content() -> None:
    content = "First paragraph.\n\nSecond paragraph.\n\n- item one\n- item two"
    front = FrontMatter("Title: with colon", "Test Bank", "Research", DATE, ("A. Analyst",))
    rendered = CorpusDocument(front, content).render()
    parsed = CorpusDocument.parse(rendered)
    assert parsed.content == content
    assert parsed.front_matter == front
    assert "```yaml ignore" not in rendered


def test_validator_rejects_ignore_blocks() -> None:
    rendered = CorpusDocument(FrontMatter("Title", None, None, DATE), "Body.").render()
    tainted = rendered.replace("Body.", "```yaml ignore\nstripped: []\n```\n\nBody.")
    errors, _ = FormatValidator().validate(tainted)
    assert [e.code for e in errors] == ["ignore_block"]


# --- Normalisers ----------------------------------------------------------------------------------------------------


def test_bullets_become_dash_items() -> None:
    assert normalise("Key points: • Rates fall • Dollar weakens", BulletNormaliser(), LayoutNormaliser()) == (
        "Key points:\n\n- Rates fall\n- Dollar weakens"
    )


def test_lettered_enumeration_is_renumbered() -> None:
    result = normalise(
        "We see two risks: (a) inflation stays high (b) growth slows.", EnumerationNormaliser(), LayoutNormaliser()
    )
    assert result == "We see two risks:\n\n1. inflation stays high\n2. growth slows."


def test_run_in_labels_become_bold_items() -> None:
    result = normalise(
        "Rates – We expect cuts in March. Currencies – The dollar weakens.", RunInLabelSplitter(), LayoutNormaliser()
    )
    assert result == "- **Rates** – We expect cuts in March.\n- **Currencies** – The dollar weakens."


def test_split_word_joined_when_vocabulary_knows_it() -> None:
    known = Vocabulary.from_texts(["government government government"])
    assert normalise("The Governme nt said so.", SplitWordJoiner(), vocabulary=known) == "The Government said so."
    rare = Vocabulary.from_texts(["government government"])
    assert normalise("The Governme nt said so.", SplitWordJoiner(), vocabulary=rare) == "The Governme nt said so."


def test_all_caps_header_becomes_heading() -> None:
    result = normalise(
        "Some text here. MARKET OUTLOOK FOR RATES The curve steepens.", HeadingNormaliser(), LayoutNormaliser()
    )
    assert result == "Some text here.\n\n## MARKET OUTLOOK FOR RATES\n\nThe curve steepens."


# --- Batches --------------------------------------------------------------------------------------------------------


def run(paths: CorpusPaths, docs: list[ResearchDocument]):
    return BatchRunner(paths).run_batch(DATE, [DATE, DATE], docs, [{"file": "synthetic"}])


def two_documents() -> list[ResearchDocument]:
    return [document("GS_Dollar outlook.pdf", DOLLAR_TEXT), document("BofA_Rates view.pdf", RATES_TEXT, "Rates")]


@pytest.fixture
def paths(tmp_path: Path) -> CorpusPaths:
    return CorpusPaths(tmp_path / "chunks", tmp_path / "pdfs")


def test_batch_writes_outputs_and_is_idempotent(paths: CorpusPaths) -> None:
    summary = run(paths, two_documents())
    assert summary.counts["compiled"] == 2
    files = {p.name: p.read_text(encoding="utf-8") for p in paths.pdfs.glob("*.txt")}
    assert set(files) == {"GS_Dollar_outlook.txt", "BofA_Rates_view.txt"}
    assert CorpusDocument.parse(files["GS_Dollar_outlook.txt"]).title == "Dollar outlook"
    assert paths.extract_manifest(DATE).is_file()
    assert paths.skip_manifest(DATE).is_file()
    ledger = Ledger.load(paths.ledger)
    assert {d.status for d in ledger.documents.values()} == {"compiled"}

    run(paths, two_documents())
    assert {p.name: p.read_text(encoding="utf-8") for p in paths.pdfs.glob("*.txt")} == files
    assert Ledger.load(paths.ledger).documents == ledger.documents


def test_batch_marks_duplicate_fingerprint(paths: CorpusPaths) -> None:
    docs = [document("GS_Dollar outlook.pdf", DOLLAR_TEXT), document("GS_Dollar outlook copy.pdf", DOLLAR_TEXT)]
    summary = run(paths, docs)
    assert (summary.counts["compiled"], summary.counts["duplicate"]) == (1, 1)
    skipped = json.loads(paths.skip_manifest(DATE).read_text(encoding="utf-8"))
    assert [d["issues"][0]["code"] for d in skipped["documents"]] == ["DUPLICATE_CONTENT"]


def test_batch_keeps_protected_stem(paths: CorpusPaths) -> None:
    ledger = Ledger(paths.ledger)
    ledger.documents["GS_Dollar_outlook"] = DocumentRecord(
        "GS_Dollar_outlook", "GS_Dollar outlook.pdf", DATE, "Test Bank", "protected", "protected"
    )
    ledger.save()
    paths.pdfs.mkdir(parents=True)
    protected = paths.pdfs / "GS_Dollar_outlook.txt"
    protected.write_text("hand repaired", encoding="utf-8")

    summary = run(paths, two_documents())
    assert (summary.counts["protected"], summary.counts["compiled"]) == (1, 1)
    assert protected.read_text(encoding="utf-8") == "hand repaired"
    assert Ledger.load(paths.ledger).documents["GS_Dollar_outlook"].status == "protected"
