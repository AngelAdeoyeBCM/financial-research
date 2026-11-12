"""Tests for the v0.10 taxonomy: claim types with subkinds, suppositions, scenarios referenced from roles, diagrams."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.diagram import ArgumentMapDiagram, load_theme
from incolor.argumentation.prompt import output_schema, render_system_prompt
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import PACKAGE_DIR, Taxonomy, load_taxonomy
from incolor.argumentation.validate import ARGUMENT_ROLES, has_errors, scenario_edges, validate
from incolor.argumentation.writer import argument_map_to_dict

V09_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v09.yaml"
V10_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v10.yaml"
# How the v0.8 types in the MS gold map translate to v0.10 claim types and subkinds.
V08_TO_V10 = {
    "VIEW": ("VIEW", ["market_state"]),
    "OBSERVATION": ("OBSERVATION", []),
    "DATA_POINT": ("OBSERVATION", ["datapoint"]),
    "FORECAST": ("PREDICTION", ["directional"]),
    "RECOMMENDATION": ("RECOMMENDATION", ["trade_idea"]),
}
SUPPOSITION = {
    "id": "S015",
    "brief": "Trump headline signals Hormuz resolution",
    "statement": "A Trump pre-election headline signals a resolution in Hormuz.",
    "claim_type": "SUPPOSITION",
    "subkinds": ["event"],
    "modality": "HYPOTHETICAL",
    "modality_cue": "could",
    "evidence": ["E004"],
}
OUTCOME = {
    "id": "S016",
    "brief": "Index rally and rates reversal",
    "statement": "A major index rally and a reversal in rates follow.",
    "claim_type": "PREDICTION",
    "subkinds": ["directional"],
    "modality": "SPECULATIVE",
    "modality_cue": "could trigger",
    "evidence": ["E004"],
}
SCENARIO = {
    "id": "SC001",
    "label": "Hormuz resolution",
    "evidence": ["E004"],
    "assumptions": ["S015"],
    "outcomes": ["S016"],
    "recommendations": [],
}

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="module")
def v10() -> Taxonomy:
    return load_taxonomy(V10_PATH)


def _ms_v10(ms_gold: GoldCase) -> dict[str, Any]:
    """The MS gold map in v0.10 terms, plus one scenario referenced from A001's risks."""
    data = ms_gold.argument_map.model_dump()
    for statement in data["statements"]:
        statement["claim_type"], statement["subkinds"] = V08_TO_V10[statement["claim_type"]]
    data["statements"] += [dict(SUPPOSITION), dict(OUTCOME)]
    data["scenarios"] = [dict(SCENARIO)]
    data["arguments"][0]["risks"] = ["SC001"]
    return data


def _statement(data: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in data["statements"] if s["id"] == sid)


def _issues(ms_gold: GoldCase, taxonomy: Taxonomy, mutate: Mutation | None = None) -> list:
    data = _ms_v10(ms_gold)
    if mutate:
        mutate(data)
    return validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)


def test_v10_types_subkinds_and_roles(v10: Taxonomy) -> None:
    assert set(v10.claim_types) == {"RECOMMENDATION", "PREDICTION", "CAUSAL", "VIEW", "OBSERVATION", "SUPPOSITION"}
    assert not v10.proposition_kinds
    assert v10.subkind_values("PREDICTION") == ["event", "directional", "quantitative"]
    assert v10.subkind_values("RECOMMENDATION") == ["trade_idea", "rating"]
    assert v10.subkind_values("OBSERVATION") == ["datapoint", "estimate"]
    for claim_type in ("VIEW", "CAUSAL", "SUPPOSITION"):
        assert v10.subkind_values(claim_type) == ["market_state", "valuation", "positioning", "sentiment", "event"]
    assert v10.fixed_modality("SUPPOSITION") == "HYPOTHETICAL"
    assert v10.fixed_modality("OBSERVATION") == "ASSERTED"
    assert v10.scenario_roles == ["risks", "conditions", "catalysts", "implications", "alternatives"]
    assert set(v10.argument_roles) <= set(ARGUMENT_ROLES)
    assert v10.roles["core_claim"]["allowed_types"] == ["RECOMMENDATION", "PREDICTION", "VIEW", "CAUSAL"]


def test_undefined_subkind_set_is_rejected(tmp_path) -> None:
    text = V10_PATH.read_text(encoding="utf-8").replace("{set: topic,", "{set: missing,", 1)
    path = tmp_path / "taxonomy.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="undefined subkind set 'missing'"):
        load_taxonomy(path)


def test_theme_covers_v10(v10: Taxonomy) -> None:
    theme = load_theme()
    assert set(v10.claim_types) <= set(theme["claim_types"])
    assert set(v10.modalities) <= set(theme["modalities"])
    assert set(v10.argument_roles) <= set(theme["roles"])
    values = {value for spec in v10.subkinds.values() for value in spec["values"]}
    assert values <= set(theme["subkinds"])
    assert theme["claim_types"]["CAUSAL"]["fill"] == "#fdd9b5"
    assert theme["claim_types"]["SUPPOSITION"]["fill"] == "#c4c9cf"


def test_v10_prompt_is_top_down_with_subkinds(v10: Taxonomy) -> None:
    prompt = render_system_prompt(v10)
    assert "{{" not in prompt
    assert "**List the arguments**" in prompt
    assert "# Subkinds" in prompt
    assert "# Proposition kinds" not in prompt
    for spec in v10.subkinds.values():
        for value in spec["values"]:
            assert f"`{value}`" in prompt
    assert "Write its keys in this order: `document`, `arguments`, `scenarios`, `statements`" in prompt
    assert "| `alternatives` |" in prompt


def test_v10_output_schema_matches_taxonomy(v10: Taxonomy) -> None:
    schema = output_schema(v10)
    assert list(schema["properties"])[:4] == ["document", "arguments", "scenarios", "statements"]
    statement = schema["$defs"]["Statement"]["properties"]
    assert "subkinds" in statement
    assert "proposition_kind" not in statement
    assert not {"role", "outcome_orientation", "purpose"} & set(schema["$defs"]["Scenario"]["properties"])
    assert {"concessions", "implications", "alternatives"} <= set(schema["$defs"]["Argument"]["properties"])


def test_v09_prompt_keeps_its_scenario_settings() -> None:
    v09 = load_taxonomy(V09_PATH)
    schema = output_schema(v09)
    assert "outcome_orientation" in schema["$defs"]["Scenario"]["properties"]
    assert "alternatives" not in schema["$defs"]["Argument"]["properties"]
    assert "subkinds" not in schema["$defs"]["Statement"]["properties"]


def test_migrated_ms_gold_is_valid_under_v10(ms_gold: GoldCase, v10: Taxonomy) -> None:
    issues = _issues(ms_gold, v10)
    assert not has_errors(issues), [f"{i.code} {i.path}" for i in issues if i.severity == "error"]
    # S015 and S016 sit only in the scenario, which A001 references, so they count as referenced.
    assert not [i for i in issues if i.code in {"STATEMENT_UNREFERENCED", "SCENARIO_UNREFERENCED"}]


def _missing_subkind(d: dict[str, Any]) -> None:
    _statement(d, "S001")["subkinds"] = []


def _invalid_subkind(d: dict[str, Any]) -> None:
    _statement(d, "S001")["subkinds"] = ["trade_idea"]


def _two_view_subkinds(d: dict[str, Any]) -> None:
    _statement(d, "S001")["subkinds"] = ["market_state", "valuation"]


def _subkind_on_plain_observation(d: dict[str, Any]) -> None:
    _statement(d, "S002")["subkinds"] = ["event"]


def _proposition_kind_set(d: dict[str, Any]) -> None:
    _statement(d, "S001")["proposition_kind"] = "market_state"


def _supposition_not_hypothetical(d: dict[str, Any]) -> None:
    _statement(d, "S015")["modality"] = "SPECULATIVE"


def _supposition_as_outcome(d: dict[str, Any]) -> None:
    d["scenarios"][0]["outcomes"] = ["S015"]


def _scenario_in_qualifiers(d: dict[str, Any]) -> None:
    d["arguments"][0]["qualifiers"] = ["SC001"]


def _unknown_scenario(d: dict[str, Any]) -> None:
    d["arguments"][0]["risks"] = ["SC009"]


def _statement_in_alternatives(d: dict[str, Any]) -> None:
    d["arguments"][3]["alternatives"] = ["S007"]


def _unreferenced_scenario(d: dict[str, Any]) -> None:
    d["arguments"][0]["risks"] = []


def _scenario_setting(d: dict[str, Any]) -> None:
    d["scenarios"][0]["role"] = "alternative"


def _observation_core(d: dict[str, Any]) -> None:
    d["arguments"][0]["conclusion"] = "S002"


def _supposition_in_supporting(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"].append("S015")


def _must_keep_exclusion(d: dict[str, Any]) -> None:
    d["exclusions"] = [{"text": "We stay overweight UK housebuilders.", "reason": "Not load-bearing."}]


V10_MUTATIONS: list[tuple[str, Mutation, str, str]] = [
    ("missing subkind", _missing_subkind, "MISSING_SUBKIND", "error"),
    ("subkind from another set", _invalid_subkind, "INVALID_SUBKIND", "error"),
    ("two subkinds on a VIEW", _two_view_subkinds, "MULTIPLE_SUBKINDS", "error"),
    ("observation subkind outside its set", _subkind_on_plain_observation, "INVALID_SUBKIND", "error"),
    ("proposition kind under v0.10", _proposition_kind_set, "PROPOSITION_KIND_NOT_SUPPORTED", "error"),
    ("supposition not hypothetical", _supposition_not_hypothetical, "FIXED_MODALITY", "error"),
    ("supposition as scenario outcome", _supposition_as_outcome, "SCENARIO_SLOT_TYPE", "error"),
    ("scenario in qualifiers", _scenario_in_qualifiers, "ROLE_SCENARIO_NOT_ALLOWED", "error"),
    ("unknown scenario", _unknown_scenario, "UNKNOWN_SCENARIO_REF", "error"),
    ("statement in alternatives", _statement_in_alternatives, "ROLE_TYPE_MISMATCH", "error"),
    ("unreferenced scenario", _unreferenced_scenario, "SCENARIO_UNREFERENCED", "warning"),
    ("v0.9 scenario setting", _scenario_setting, "INVALID_SCENARIO_VALUE", "error"),
    ("observation as core claim", _observation_core, "ROLE_TYPE_MISMATCH", "error"),
    ("supposition as supporting claim", _supposition_in_supporting, "ROLE_TYPE_MISMATCH", "error"),
    ("recommendation excluded", _must_keep_exclusion, "MUST_KEEP_EXCLUDED", "warning"),
]


@pytest.mark.parametrize(("label", "mutate", "code", "severity"), V10_MUTATIONS, ids=[m[0] for m in V10_MUTATIONS])
def test_v10_mutation_raises_expected_issue(
    ms_gold: GoldCase, v10: Taxonomy, label: str, mutate: Mutation, code: str, severity: str
) -> None:
    matches = [issue for issue in _issues(ms_gold, v10, mutate) if issue.code == code]
    assert matches, f"{label}: expected {code}"
    assert all(issue.severity == severity for issue in matches)


def test_prediction_takes_several_subkinds(ms_gold: GoldCase, v10: Taxonomy) -> None:
    def mutate(d: dict[str, Any]) -> None:
        _statement(d, "S013")["subkinds"] = ["directional", "quantitative"]

    assert not [i for i in _issues(ms_gold, v10, mutate) if "SUBKIND" in i.code]


def test_older_taxonomies_reject_v10_features(ms_gold: GoldCase, taxonomy: Taxonomy) -> None:
    data = ms_gold.argument_map.model_dump()
    data["statements"][0]["subkinds"] = ["market_state"]
    data["arguments"][0]["alternatives"] = ["SC001"]
    data["arguments"][1]["risks"] = ["SC001"]
    codes = {issue.code for issue in validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)}
    assert {"SUBKINDS_NOT_SUPPORTED", "ROLE_NOT_SUPPORTED", "ROLE_SCENARIO_NOT_ALLOWED"} <= codes


def test_scenario_edges(ms_gold: GoldCase) -> None:
    amap = ArgumentMap.model_validate(_ms_v10(ms_gold))
    assert scenario_edges(amap) == [("SC001", "risks", "A001")]


def test_writer_keeps_subkinds_and_omits_unused_fields(ms_gold: GoldCase) -> None:
    written = argument_map_to_dict(ArgumentMap.model_validate(_ms_v10(ms_gold)))
    assert written["statements"][0]["subkinds"] == ["market_state"]
    assert "subkinds" not in _statement(written, "S002")
    assert "proposition_kind" not in written["statements"][0]
    assert written["arguments"][0]["risks"] == ["SC001"]
    assert not {"concessions", "implications", "alternatives"} & set(written["arguments"][0])
    assert not {"role", "outcome_orientation", "purpose"} & set(written["scenarios"][0])


def test_writer_leaves_v08_maps_unchanged(ms_gold: GoldCase) -> None:
    written = argument_map_to_dict(ms_gold.argument_map)
    assert "subkinds" not in written["statements"][0]
    # The core claim is written under its v0.12 name, conclusion; old maps with core_claim still load.
    assert set(written["arguments"][0]) == {
        "id", "summary", "conclusion", "supporting", "rationale", "risks", "conditions", "catalysts", "qualifiers",
    }


def test_diagram_draws_scenarios_like_arguments(ms_gold: GoldCase) -> None:
    mermaid = ArgumentMapDiagram(argument_map_to_dict(ArgumentMap.model_validate(_ms_v10(ms_gold)))).to_mermaid()
    assert "SC001 · Scenario · Hormuz resolution" in mermaid
    assert "SC001 -- Risk --> A001" in mermaid
    assert "<b>RI:</b> <b>SC001 - Hormuz resolution</b>" in mermaid
    assert "<b>IF:</b> A Trump" not in mermaid  # briefs are shown, not full statements
    assert "<b>IF:</b> Trump headline signals Hormuz resolution</span><b>[EVT]</b>" in mermaid
    assert "[EVT·SC1]" not in mermaid
    assert "A007 · PREDICTION · DIR" in mermaid
    assert "[TRADE]" in mermaid
    assert "classDef scn" in mermaid
    assert "class SC001 scn" in mermaid


def test_diagram_list_view_stacks_scenarios(ms_gold: GoldCase) -> None:
    diagram = ArgumentMapDiagram(argument_map_to_dict(ArgumentMap.model_validate(_ms_v10(ms_gold))), view="list")
    mermaid = diagram.to_mermaid()
    assert "A007 ~~~ SC001" in mermaid
    assert "-- Risk -->" not in mermaid
