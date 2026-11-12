"""Tests for prompt rendering: placeholder filling, taxonomy sections, example embedding and repair prompts."""

import json
from pathlib import Path

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.ingest import SourceDocument
from incolor.argumentation.prompt import (
    _fill,
    output_schema,
    render_repair_prompt,
    render_system_prompt,
    render_user_prompt,
)
from incolor.argumentation.schema import ModelOutput
from incolor.argumentation.taxonomy import Taxonomy
from incolor.argumentation.validate import ARGUMENT_ROLES, ValidationIssue


def _doc(text: str = "Plain text.") -> SourceDocument:
    return SourceDocument(path=Path("doc.txt"), raw_text=text, text=text, metadata={"filename": "doc.txt"})


def test_fill_rejects_unknown_placeholder() -> None:
    with pytest.raises(ValueError, match="MISSING"):
        _fill("Hello {{MISSING}}", {"OTHER": "x"})


def test_fill_does_not_rescan_substituted_values() -> None:
    result = _fill("A {{ONE}} B {{TWO}}", {"ONE": "{{TWO}}", "TWO": "end"})
    assert result == "A {{TWO}} B end"


def test_system_prompt_lists_every_claim_type_and_role(taxonomy: Taxonomy) -> None:
    prompt = render_system_prompt(taxonomy)
    assert "{{" not in prompt
    for claim_type in taxonomy.claim_types:
        assert f"### {claim_type}" in prompt
    for role in taxonomy.roles:
        assert f"`{role}`" in prompt


def test_system_prompt_embeds_valid_output_schema(taxonomy: Taxonomy) -> None:
    prompt = render_system_prompt(taxonomy)
    start = prompt.index("```json\n") + len("```json\n")
    end = prompt.index("\n```", start)
    schema = json.loads(prompt[start:end])
    assert schema == output_schema(taxonomy)
    full = ModelOutput.model_json_schema()
    assert schema["properties"] == full["properties"]
    # Only the roles and fields this taxonomy uses are shown.
    assert set(schema["$defs"]["Argument"]["properties"]) == {"id", "summary", "conclusion", *taxonomy.argument_roles}
    assert set(ARGUMENT_ROLES) - set(taxonomy.argument_roles) <= set(full["$defs"]["Argument"]["properties"])
    assert "subkinds" not in schema["$defs"]["Statement"]["properties"]


def test_system_prompt_without_example_has_no_example_section(taxonomy: Taxonomy) -> None:
    assert "# Example" not in render_system_prompt(taxonomy, example=None)


def test_system_prompt_with_example_omits_gold_only_keys(taxonomy: Taxonomy, ms_gold: GoldCase) -> None:
    prompt = render_system_prompt(taxonomy, example=ms_gold.argument_map)
    assert "# Example" in prompt
    assert "schema_version" not in prompt.split("# Example", 1)[1]
    assert "adjudication_notes" not in prompt.split("# Example", 1)[1]


def test_user_prompt_keeps_document_text_verbatim() -> None:
    text = "Quote {{NOT_A_PLACEHOLDER}} and {braces}."
    prompt = render_user_prompt(_doc(text))
    assert text in prompt
    assert "{{DOCUMENT_TEXT}}" not in prompt


def test_repair_prompt_contains_previous_output_and_each_error() -> None:
    issues = [
        ValidationIssue("EVIDENCE_NOT_VERBATIM", "error", "$.evidence[0]", "Span not found", "Copy the span exactly."),
        ValidationIssue("BRIEF_TOO_LONG", "warning", "$.statements[1]", "Too long", "Shorten the brief."),
    ]
    prompt = render_repair_prompt(_doc("Source text."), '{"previous": true}', issues)
    assert "<previous_output>\n{\"previous\": true}\n</previous_output>" in prompt
    assert prompt.count("\n{\"code\"") == 2
    assert "EVIDENCE_NOT_VERBATIM" in prompt
    assert "BRIEF_TOO_LONG" in prompt
    assert "Return the full corrected JSON object." in prompt
