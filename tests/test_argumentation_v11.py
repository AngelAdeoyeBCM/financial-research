"""Tests for the v0.11 taxonomy: no observations, premises instead of supporting, arguments grounded in evidence."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.diagram import ArgumentMapDiagram, load_theme
from incolor.argumentation.prompt import output_schema, render_system_prompt
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import PACKAGE_DIR, Taxonomy, load_taxonomy
from incolor.argumentation.validate import ARGUMENT_ROLES, has_errors, validate
from incolor.argumentation.writer import argument_map_to_dict

V10_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v10.yaml"
V11_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v11.yaml"
# MS gold v0.8 types -> v0.11 type and subkinds; None drops the statement (observations are evidence now).
V08_TO_V11 = {
    "VIEW": ("VIEW", ["market_state"]),
    "FORECAST": ("PREDICTION", ["directional"]),
    "RECOMMENDATION": ("RECOMMENDATION", ["trade_idea"]),
    "OBSERVATION": None,
    "DATA_POINT": None,
}

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="module")
def v11() -> Taxonomy:
    return load_taxonomy(V11_PATH)


def _ms_v11(ms_gold: GoldCase) -> dict[str, Any]:
    """The MS gold map in v0.11 terms: observations dropped, supporting renamed to premises."""
    data = ms_gold.argument_map.model_dump()
    kept = []
    for statement in data["statements"]:
        mapped = V08_TO_V11[statement["claim_type"]]
        if mapped is not None:
            statement["claim_type"], statement["subkinds"] = mapped
            kept.append(statement)
    data["statements"] = kept
    dropped = {s.id for s in ms_gold.argument_map.statements} - {s["id"] for s in kept}
    for argument in data["arguments"]:
        argument["premises"], argument["supporting"], argument["rationale"] = argument["supporting"], [], []
        for sid in dropped:
            argument["summary"] = argument["summary"].replace(f" [{sid}]", "")
    return data


def _issues(ms_gold: GoldCase, taxonomy: Taxonomy, mutate: Mutation | None = None) -> list:
    data = _ms_v11(ms_gold)
    if mutate:
        mutate(data)
    return validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)


def test_v11_has_no_observations_and_uses_premises(v11: Taxonomy) -> None:
    assert set(v11.claim_types) == {"RECOMMENDATION", "PREDICTION", "CAUSAL", "VIEW", "SUPPOSITION"}
    assert "observation" not in v11.subkinds
    assert v11.argument_roles[0] == "premises"
    assert not {"supporting", "rationale"} & set(v11.argument_roles)
    assert set(v11.argument_roles) <= set(ARGUMENT_ROLES)
    assert v11.bare_argument_severity == "warning"


def test_theme_covers_v11(v11: Taxonomy) -> None:
    theme = load_theme()
    assert set(v11.argument_roles) <= set(theme["roles"])
    assert theme["roles"]["premises"]["abbrev"] == "P"


def test_v11_prompt_focuses_on_core_arguments(v11: Taxonomy) -> None:
    prompt = render_system_prompt(v11)
    assert "{{" not in prompt
    assert "extract every core argument the author makes and atomise each into claims" in prompt
    assert "OBSERVATION" not in prompt
    assert "| `premises` |" in prompt
    assert "`rationale`" not in prompt
    assert "Treat two statements as distinct only if one could be true while the other is false" in prompt


def test_v11_output_schema_has_premises_only(v11: Taxonomy) -> None:
    roles = set(output_schema(v11)["$defs"]["Argument"]["properties"]) - {"id", "summary", "conclusion"}
    assert roles == set(v11.argument_roles)


def test_migrated_ms_gold_is_valid_under_v11(ms_gold: GoldCase, v11: Taxonomy) -> None:
    issues = _issues(ms_gold, v11)
    assert not has_errors(issues), [f"{i.code} {i.path}" for i in issues if i.severity == "error"]
    # A002, A003 and A007 rested only on observations; they now stand on their core claim and evidence.
    bare = [i for i in issues if i.code == "ARGUMENT_WITHOUT_RELATION"]
    assert {i.path for i in bare} == {"$.arguments[1]", "$.arguments[2]", "$.arguments[6]"}
    assert all(i.severity == "warning" for i in bare)


def _observation_statement(d: dict[str, Any]) -> None:
    d["statements"][0]["claim_type"] = "OBSERVATION"


def _rationale_used(d: dict[str, Any]) -> None:
    d["arguments"][0]["rationale"] = ["S003"]


def _supporting_used(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"] = ["S003"]


def _recommendation_as_premise(d: dict[str, Any]) -> None:
    d["arguments"][0]["premises"].append("S010")


V11_MUTATIONS: list[tuple[str, Mutation, str]] = [
    ("observation type", _observation_statement, "INVALID_CLAIM_TYPE"),
    ("rationale role", _rationale_used, "ROLE_NOT_SUPPORTED"),
    ("supporting role", _supporting_used, "ROLE_NOT_SUPPORTED"),
    ("recommendation as premise", _recommendation_as_premise, "ROLE_TYPE_MISMATCH"),
]


@pytest.mark.parametrize(("label", "mutate", "code"), V11_MUTATIONS, ids=[m[0] for m in V11_MUTATIONS])
def test_v11_mutation_raises_expected_error(
    ms_gold: GoldCase, v11: Taxonomy, label: str, mutate: Mutation, code: str
) -> None:
    matches = [issue for issue in _issues(ms_gold, v11, mutate) if issue.code == code]
    assert matches, f"{label}: expected {code}"
    assert all(issue.severity == "error" for issue in matches)


def test_v10_rejects_premises(ms_gold: GoldCase) -> None:
    data = _ms_v11(ms_gold)
    codes = {i.code for i in validate(ArgumentMap.model_validate(data), ms_gold.source, load_taxonomy(V10_PATH))}
    assert "ROLE_NOT_SUPPORTED" in codes


def test_writer_keeps_only_taxonomy_roles(ms_gold: GoldCase, v11: Taxonomy) -> None:
    written = argument_map_to_dict(ArgumentMap.model_validate(_ms_v11(ms_gold)), v11.argument_roles)
    first = written["arguments"][0]
    assert first["premises"] == ["S003", "S006"]
    assert not {"supporting", "rationale"} & set(first)
    assert {"conditions", "qualifiers", "risks", "catalysts"} <= set(first)


def test_diagram_shows_premises(ms_gold: GoldCase, v11: Taxonomy) -> None:
    amap = argument_map_to_dict(ArgumentMap.model_validate(_ms_v11(ms_gold)), v11.argument_roles)
    mermaid = ArgumentMapDiagram(amap).to_mermaid()
    assert "<b>P:</b>" in mermaid
    assert "A002 -- Premise --> A001" in mermaid
    assert "Supporting" not in mermaid


@pytest.mark.parametrize(
    ("claim_type", "subkinds", "style"),
    [
        ("PREDICTION", ["directional", "quantitative"], "FORECAST"),
        ("PREDICTION", ["directional"], "PREDICTION"),
        ("VIEW", ["valuation"], "VALUATION"),
        ("CAUSAL", ["valuation"], "VALUATION"),
        ("VIEW", ["positioning"], "POSITIONING"),
        ("CAUSAL", ["market_state"], "CAUSAL"),
        ("RECOMMENDATION", ["trade_idea"], "RECOMMENDATION"),
    ],
)
def test_subkind_overrides_type_colour(
    ms_gold: GoldCase, v11: Taxonomy, claim_type: str, subkinds: list[str], style: str
) -> None:
    diagram = ArgumentMapDiagram(argument_map_to_dict(ArgumentMap.model_validate(_ms_v11(ms_gold)), v11.argument_roles))
    assert diagram._style({"claim_type": claim_type, "subkinds": subkinds}) == style
