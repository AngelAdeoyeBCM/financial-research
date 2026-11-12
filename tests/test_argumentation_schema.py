"""Tests for the argument-map schema, the taxonomy loader and the ingest step."""

import datetime

import pytest
from pydantic import ValidationError
from tests.conftest import GoldCase

from incolor.argumentation.diagram import load_theme
from incolor.argumentation.ingest import InputError, PreprocessConfig, load_document, normalise
from incolor.argumentation.schema import ArgumentMap, DocumentMeta, Evidence
from incolor.argumentation.taxonomy import CORE_ROLE, Taxonomy, load_taxonomy
from incolor.argumentation.validate import ARGUMENT_ROLES

EXPECTED_COUNTS = {"ms": (9, 14, 7), "ocado": (14, 26, 8), "ing": (37, 40, 13)}


def test_gold_counts_match_expected(gold_case: GoldCase) -> None:
    amap = gold_case.argument_map
    assert (len(amap.evidence), len(amap.statements), len(amap.arguments)) == EXPECTED_COUNTS[gold_case.name]


def test_gold_schema_version_is_phase1(gold_case: GoldCase) -> None:
    assert gold_case.argument_map.schema_version == "phase1-0.6"


def test_role_fields_match_taxonomy(taxonomy: Taxonomy) -> None:
    # The Argument model covers the roles of every taxonomy version; each taxonomy uses a subset.
    assert set(taxonomy.argument_roles) <= set(ARGUMENT_ROLES)
    assert CORE_ROLE not in taxonomy.argument_roles


def test_taxonomy_fixed_modality_for_factual_types(taxonomy: Taxonomy) -> None:
    assert taxonomy.fixed_modality("OBSERVATION") == "ASSERTED"
    assert taxonomy.fixed_modality("DATA_POINT") == "ASSERTED"
    assert taxonomy.fixed_modality("VIEW") is None


def test_theme_matches_taxonomy(taxonomy: Taxonomy) -> None:
    theme = load_theme()
    # The theme also covers the experimental taxonomies, so it may define more types, modalities and roles.
    assert set(taxonomy.modalities) <= set(theme["modalities"])
    assert set(taxonomy.claim_types) <= set(theme["claim_types"])
    assert set(taxonomy.argument_roles) <= set(theme["roles"])
    assert set(theme["roles"]) == set(ARGUMENT_ROLES)


def test_taxonomy_missing_section_raises(tmp_path) -> None:
    path = tmp_path / "taxonomy.yaml"
    path.write_text("version: '0.5'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing taxonomy sections"):
        load_taxonomy(path)


def test_unknown_top_level_key_is_rejected(gold_case: GoldCase) -> None:
    data = gold_case.argument_map.model_dump()
    data["unexpected"] = 1
    with pytest.raises(ValidationError):
        ArgumentMap.model_validate(data)


def test_bad_evidence_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Evidence(id="E1", text="x")


def test_unquoted_timestamp_is_stored_as_iso_string() -> None:
    meta = DocumentMeta(source_email_sent_at=datetime.datetime(2026, 9, 28, 8, 54, 46))
    assert meta.source_email_sent_at == "2026-09-28T08:54:46"


def test_load_taxonomy_default_path_has_core_role() -> None:
    assert CORE_ROLE in load_taxonomy().roles


def test_normalise_joins_hyphenated_line_breaks() -> None:
    assert normalise("capex-\nintensive sector", []) == "capex-intensive sector"


def test_normalise_multiline_furniture_before_collapse() -> None:
    text = "value of\nOverweight\nOCDOLN\n2\ncurrent"
    assert normalise(text, [r"\nOverweight\nOCDOLN\n2\n"]) == "value of current"


def test_normalise_inline_furniture_after_collapse() -> None:
    text = "Article | 13 October 2026 4 THINK Economic and financial analysis  text"
    pattern = r"Article \| \d{1,2} \w+ \d{4} \d+ THINK Economic and financial analysis"
    assert normalise(text, [pattern]) == "text"


def test_load_document_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(InputError, match="not found"):
        load_document(tmp_path / "absent.txt", PreprocessConfig())


def test_load_document_rejects_input_over_limit(tmp_path) -> None:
    path = tmp_path / "long.txt"
    path.write_text("abcdefghij", encoding="utf-8")
    with pytest.raises(InputError, match="limit is 5"):
        load_document(path, PreprocessConfig(max_input_chars=5))


def test_load_document_normalises_text(tmp_path) -> None:
    path = tmp_path / "doc.txt"
    path.write_text("Line one\nsplit  here", encoding="utf-8")
    document = load_document(path, PreprocessConfig())
    assert document.text == "Line one split here"
    assert document.metadata["filename"] == "doc.txt"
