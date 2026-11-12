"""Tests for the v0.9 taxonomy: claim functions with proposition kinds, scenarios, prompt rendering and diagrams."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.diagram import ArgumentMapDiagram, load_theme
from incolor.argumentation.prompt import render_system_prompt
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import PACKAGE_DIR, Taxonomy, load_taxonomy
from incolor.argumentation.validate import has_errors, validate
from incolor.argumentation.writer import argument_map_to_dict

V09_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v09.yaml"
# How the v0.8 types in the MS gold map translate to v0.9 claim functions.
V08_TO_V09 = {"VIEW": "ASSESSMENT", "DATA_POINT": "OBSERVATION", "FORECAST": "PREDICTION"}
SCENARIO = {
    "id": "SC001",
    "label": "Sales sentiment turns",
    "role": "alternative",
    "outcome_orientation": "downside",
    "purpose": "forecast",
    "evidence": ["E001"],
    "assumptions": ["S001"],
    "outcomes": ["S003"],
    "recommendations": [],
}

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="module")
def v09() -> Taxonomy:
    return load_taxonomy(V09_PATH)


def _ms_v09(ms_gold: GoldCase) -> dict[str, Any]:
    data = ms_gold.argument_map.model_dump()
    for statement in data["statements"]:
        statement["claim_type"] = V08_TO_V09.get(statement["claim_type"], statement["claim_type"])
        is_rec = statement["claim_type"] == "RECOMMENDATION"
        statement["proposition_kind"] = "investment_action" if is_rec else "market_state"
    return data


def _first(data: dict[str, Any], claim_type: str) -> dict[str, Any]:
    return next(s for s in data["statements"] if s["claim_type"] == claim_type)


def _issues(ms_gold: GoldCase, taxonomy: Taxonomy, mutate: Mutation | None = None) -> list:
    data = _ms_v09(ms_gold)
    if mutate:
        mutate(data)
    return validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)


def test_v09_has_four_functions_and_seven_kinds(v09: Taxonomy) -> None:
    assert set(v09.claim_types) == {"ASSESSMENT", "PREDICTION", "RECOMMENDATION", "OBSERVATION"}
    assert len(v09.proposition_kinds) == 7
    assert {step["kind"] for step in v09.proposition_kind_decision_order} == set(v09.proposition_kinds)
    assert v09.fixed_modality("OBSERVATION") == "ASSERTED"
    assert v09.fixed_proposition_kind("RECOMMENDATION") == "investment_action"


def test_theme_covers_v09(v09: Taxonomy) -> None:
    theme = load_theme()
    assert set(v09.claim_types) <= set(theme["claim_types"])
    assert set(theme["proposition_kinds"]) == set(v09.proposition_kinds)


def test_v09_prompt_lists_kinds_and_scenarios(v09: Taxonomy) -> None:
    prompt = render_system_prompt(v09)
    assert "{{" not in prompt
    for kind in v09.proposition_kinds:
        assert f"### `{kind}`" in prompt
    assert "# Scenarios" in prompt
    assert "`outcome_orientation`" in prompt


def test_default_prompt_has_no_v09_sections(taxonomy: Taxonomy) -> None:
    prompt = render_system_prompt(taxonomy)
    assert "# Proposition kinds" not in prompt
    assert "# Scenarios" not in prompt
    assert "\n\n\n" not in prompt


def test_migrated_ms_gold_is_valid_under_v09(ms_gold: GoldCase, v09: Taxonomy) -> None:
    def add_scenario(d: dict[str, Any]) -> None:
        d["scenarios"] = [dict(SCENARIO)]

    issues = _issues(ms_gold, v09, add_scenario)
    assert not has_errors(issues), [f"{i.code} {i.path}" for i in issues if i.severity == "error"]


def _missing_kind(d: dict[str, Any]) -> None:
    d["statements"][0]["proposition_kind"] = None


def _wrong_fixed_kind(d: dict[str, Any]) -> None:
    _first(d, "RECOMMENDATION")["proposition_kind"] = "market_state"


def _bad_scenario_role(d: dict[str, Any]) -> None:
    d["scenarios"] = [{**SCENARIO, "role": "tail"}]


def _scenario_unknown_statement(d: dict[str, Any]) -> None:
    d["scenarios"] = [{**SCENARIO, "outcomes": ["S099"]}]


def _scenario_unknown_evidence(d: dict[str, Any]) -> None:
    d["scenarios"] = [{**SCENARIO, "evidence": ["E099"]}]


def _scenario_non_recommendation(d: dict[str, Any]) -> None:
    d["scenarios"] = [{**SCENARIO, "recommendations": ["S001"]}]


def _scenario_without_outcomes(d: dict[str, Any]) -> None:
    d["scenarios"] = [{**SCENARIO, "outcomes": []}]


def _duplicate_scenario(d: dict[str, Any]) -> None:
    d["scenarios"] = [dict(SCENARIO), dict(SCENARIO)]


V09_MUTATIONS: list[tuple[str, Mutation, str, str]] = [
    ("missing proposition kind", _missing_kind, "INVALID_PROPOSITION_KIND", "error"),
    ("recommendation kind not fixed", _wrong_fixed_kind, "FIXED_PROPOSITION_KIND", "error"),
    ("invalid scenario role", _bad_scenario_role, "INVALID_SCENARIO_VALUE", "error"),
    ("scenario unknown statement", _scenario_unknown_statement, "UNKNOWN_STATEMENT_REF", "error"),
    ("scenario unknown evidence", _scenario_unknown_evidence, "UNKNOWN_EVIDENCE_REF", "error"),
    ("scenario recommendation type", _scenario_non_recommendation, "SCENARIO_RECOMMENDATION_TYPE", "error"),
    ("scenario without outcomes", _scenario_without_outcomes, "SCENARIO_EMPTY", "warning"),
    ("duplicate scenario id", _duplicate_scenario, "DUPLICATE_ID", "error"),
]


@pytest.mark.parametrize(("label", "mutate", "code", "severity"), V09_MUTATIONS, ids=[m[0] for m in V09_MUTATIONS])
def test_v09_mutation_raises_expected_issue(
    ms_gold: GoldCase, v09: Taxonomy, label: str, mutate: Mutation, code: str, severity: str
) -> None:
    matches = [issue for issue in _issues(ms_gold, v09, mutate) if issue.code == code]
    assert matches, f"{label}: expected {code}"
    assert all(issue.severity == severity for issue in matches)


def test_scenarios_rejected_by_default_taxonomy(ms_gold: GoldCase, taxonomy: Taxonomy) -> None:
    data = ms_gold.argument_map.model_dump()
    data["scenarios"] = [dict(SCENARIO)]
    issues = validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)
    assert any(issue.code == "SCENARIOS_NOT_SUPPORTED" for issue in issues)


def test_writer_keeps_scenarios_and_omits_unset_kinds(ms_gold: GoldCase) -> None:
    assert "proposition_kind" not in argument_map_to_dict(ms_gold.argument_map)["statements"][0]
    data = _ms_v09(ms_gold)
    data["scenarios"] = [dict(SCENARIO)]
    written = argument_map_to_dict(ArgumentMap.model_validate(data))
    assert written["scenarios"][0]["id"] == "SC001"
    assert written["statements"][0]["proposition_kind"] == "market_state"
    assert "attribution" not in written["statements"][0]


def test_diagram_marker_shows_kind_and_scenario(ms_gold: GoldCase) -> None:
    data = _ms_v09(ms_gold)
    data["scenarios"] = [dict(SCENARIO)]
    mermaid = ArgumentMapDiagram(argument_map_to_dict(ArgumentMap.model_validate(data))).to_mermaid()
    assert "[MS·SC1]" in mermaid
    assert "[ACT]" in mermaid
    assert "A001 · ASSESSMENT · MS" in mermaid


def test_diagram_marker_falls_back_to_modality(ms_gold: GoldCase) -> None:
    mermaid = ArgumentMapDiagram(argument_map_to_dict(ms_gold.argument_map)).to_mermaid()
    assert "[A]" in mermaid or "[H]" in mermaid
    assert "[MS]" not in mermaid
