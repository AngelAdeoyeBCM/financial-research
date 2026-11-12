"""Tests for v0.12: hierarchical arguments, explicit-only assumptions and warrants, trades and ratings, scenario
implications, coverage, and the deterministic repairs applied before validation."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.diagram import ArgumentMapDiagram, load_theme
from incolor.argumentation.grounding import coverage, fold, locate
from incolor.argumentation.prompt import output_schema, render_system_prompt
from incolor.argumentation.repair import repair_output
from incolor.argumentation.schema import ArgumentMap, ModelOutput
from incolor.argumentation.taxonomy import PACKAGE_DIR, Taxonomy, load_taxonomy
from incolor.argumentation.validate import ARGUMENT_ROLES, argument_edges, has_errors, validate
from incolor.argumentation.writer import argument_map_to_dict

V12_PATH = PACKAGE_DIR / "prompts" / "taxonomy_v12.yaml"
# MS gold v0.8 types -> v0.12 type and subkinds; None drops the statement (observations are evidence).
V08_TO_V12 = {
    "VIEW": ("VIEW", ["market_state"]),
    "FORECAST": ("PREDICTION", ["directional"]),
    "RECOMMENDATION": ("TRADE", ["open"]),
    "OBSERVATION": None,
    "DATA_POINT": None,
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
IMPLICATION = {
    "id": "S016",
    "brief": "Index rally and rates reversal",
    "statement": "A major index rally and a reversal in rates follow.",
    "claim_type": "PREDICTION",
    "subkinds": ["directional"],
    "modality": "SPECULATIVE",
    "modality_cue": "could trigger",
    "evidence": ["E004"],
}
SCENARIO = {"id": "SC001", "label": "Hormuz resolution", "evidence": ["E004"], "assumptions": ["S015"],
            "implications": ["S016"], "recommendations": []}

Mutation = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="module")
def v12() -> Taxonomy:
    return load_taxonomy(V12_PATH)


def _ms_v12(ms_gold: GoldCase) -> dict[str, Any]:
    """The MS gold map in v0.12 terms, plus a scenario referenced from A001's risks."""
    data = ms_gold.argument_map.model_dump()
    kept = []
    for statement in data["statements"]:
        mapped = V08_TO_V12[statement["claim_type"]]
        if mapped is not None:
            statement["claim_type"], statement["subkinds"] = mapped
            kept.append(statement)
    data["statements"] = [*kept, dict(SUPPOSITION), dict(IMPLICATION)]
    dropped = {s.id for s in ms_gold.argument_map.statements} - {s["id"] for s in kept}
    for argument in data["arguments"]:
        argument["premises"], argument["supporting"], argument["rationale"] = argument["supporting"], [], []
        for sid in dropped:
            argument["summary"] = argument["summary"].replace(f" [{sid}]", "")
    data["scenarios"] = [dict(SCENARIO)]
    data["arguments"][0]["risks"] = ["SC001"]
    return data


def _statement(data: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in data["statements"] if s["id"] == sid)


def _issues(ms_gold: GoldCase, taxonomy: Taxonomy, mutate: Mutation | None = None) -> list:
    data = _ms_v12(ms_gold)
    if mutate:
        mutate(data)
    return validate(ArgumentMap.model_validate(data), ms_gold.source, taxonomy)


def _output(data: dict[str, Any]) -> ModelOutput:
    return ModelOutput.model_validate(
        {k: v for k, v in data.items() if k not in {"schema_version", "rejected_links", "adjudication_notes"}}
    )


def test_v12_types_roles_and_settings(v12: Taxonomy) -> None:
    assert set(v12.claim_types) == {"TRADE", "RATING", "PREDICTION", "CAUSAL", "VIEW", "SUPPOSITION"}
    assert v12.core_role == "conclusion"
    assert v12.argument_roles[:3] == ["premises", "assumptions", "warrants"]
    assert set(v12.argument_roles) <= set(ARGUMENT_ROLES)
    assert v12.argument_ref_roles == ["premises", "concessions", "risks", "catalysts", "implications", "alternatives"]
    assert v12.roles["conditions"]["allowed_types"] == ["SUPPOSITION"]
    for role in ("risks", "catalysts", "concessions"):
        assert v12.roles[role]["allowed_types"] == ["PREDICTION", "VIEW", "CAUSAL", "SUPPOSITION"]
    assert v12.subkind_values("TRADE") == ["open", "maintain", "close", "adjust"]
    assert v12.subkind_values("RATING") == ["formal", "allocation"]
    assert v12.reasoning_roles == ["premises", "assumptions", "warrants"]
    assert v12.scenario_empty_severity == "error"


def test_theme_covers_v12(v12: Taxonomy) -> None:
    theme = load_theme()
    assert set(v12.claim_types) <= set(theme["claim_types"])
    assert set(v12.argument_roles) <= set(theme["roles"])
    values = {value for spec in v12.subkinds.values() for value in spec["values"]}
    assert values <= set(theme["subkinds"])
    assert "implications" in theme["scenario_slots"]


def test_v12_prompt_and_schema(v12: Taxonomy) -> None:
    prompt = render_system_prompt(v12)
    assert "{{" not in prompt
    assert "| Role | Definition | Allowed types | Scenarios | Arguments |" in prompt
    assert "| `assumptions` |" in prompt
    assert "| `warrants` |" in prompt
    assert "`implications` hold only PREDICTION, VIEW, CAUSAL statements." in prompt
    schema = output_schema(v12)
    argument = schema["$defs"]["Argument"]["properties"]
    assert {"conclusion", "premises", "assumptions", "warrants"} <= set(argument)
    assert not {"core_claim", "supporting", "rationale"} & set(argument)
    assert "implications" in schema["$defs"]["Scenario"]["properties"]


def test_migrated_ms_gold_is_valid_under_v12(ms_gold: GoldCase, v12: Taxonomy) -> None:
    issues = _issues(ms_gold, v12)
    assert not has_errors(issues), [f"{i.code} {i.path}" for i in issues if i.severity == "error"]


def test_old_keys_still_load() -> None:
    argument = {"id": "A001", "summary": "s", "core_claim": "S001"}
    scenario = {"id": "SC001", "label": "x", "evidence": ["E001"], "outcomes": ["S002"]}
    data = {"schema_version": "x", "document": {}, "evidence": [], "statements": [], "arguments": [argument],
            "scenarios": [scenario]}
    amap = ArgumentMap.model_validate(data)
    assert amap.arguments[0].conclusion == "S001"
    assert amap.scenarios[0].implications == ["S002"]


def _premise_is_bare_argument(d: dict[str, Any]) -> None:
    d["arguments"][0]["premises"] = ["A002", "S006"]


def _argument_in_qualifiers(d: dict[str, Any]) -> None:
    d["arguments"][3]["qualifiers"] = ["A001"]


def _unknown_argument(d: dict[str, Any]) -> None:
    d["arguments"][3]["premises"] = ["A099", "S007"]


def _argument_self_reference(d: dict[str, Any]) -> None:
    d["arguments"][0]["premises"].append("A001")


def _argument_cycle(d: dict[str, Any]) -> None:
    d["arguments"][3]["premises"] = ["A001", "S007"]
    d["arguments"][0]["premises"].append("A004")


def _trade_argument_as_premise(d: dict[str, Any]) -> None:
    d["arguments"][6]["premises"] = ["A005"]


def _assumption_without_cue(d: dict[str, Any]) -> None:
    d["arguments"][0]["assumptions"] = [d["arguments"][0]["premises"].pop()]


def _inferred_warrant(d: dict[str, Any]) -> None:
    d["statements"].append({**_statement(d, "S003"), "id": "S020", "brief": "Policy credibility drives risk",
                            "statement": "Investors always demand a premium when central banks lose credibility.",
                            "claim_type": "CAUSAL"})
    d["arguments"][0]["warrants"] = ["S020"]


def _warrant_without_premise(d: dict[str, Any]) -> None:
    d["statements"].append({**_statement(d, "S003"), "id": "S020", "claim_type": "CAUSAL"})
    d["arguments"][1]["warrants"] = ["S020"]


def _prediction_as_condition(d: dict[str, Any]) -> None:
    d["arguments"][0]["conditions"] = ["S013"]


def _conditional_prediction(d: dict[str, Any]) -> None:
    _statement(d, "S013")["statement"] = "If the scheme is approved, it will support eligible new-build demand."


def _scenario_without_implications(d: dict[str, Any]) -> None:
    d["scenarios"][0]["implications"] = []


def _view_as_scenario_recommendation(d: dict[str, Any]) -> None:
    d["scenarios"][0]["recommendations"] = ["S011"]


def _old_recommendation_type(d: dict[str, Any]) -> None:
    _statement(d, "S010")["claim_type"] = "RECOMMENDATION"


def _restated_conclusion(d: dict[str, Any]) -> None:
    restated = "Sentiment across sales and trading desks into quarter-end is not encouraging."
    d["statements"].append({**_statement(d, "S001"), "id": "S021", "statement": restated})
    d["arguments"][3]["premises"] = ["S021", "S007"]


V12_MUTATIONS: list[tuple[str, Mutation, str, str]] = [
    ("bare argument referenced by ID", _premise_is_bare_argument, "SUBARGUMENT_WITHOUT_REASONING", "error"),
    ("argument in qualifiers", _argument_in_qualifiers, "ROLE_ARGUMENT_NOT_ALLOWED", "error"),
    ("unknown argument", _unknown_argument, "UNKNOWN_ARGUMENT_REF", "error"),
    ("argument references itself", _argument_self_reference, "SELF_REFERENCE", "error"),
    ("argument cycle", _argument_cycle, "ARGUMENT_CYCLE", "error"),
    ("trade argument as premise", _trade_argument_as_premise, "ROLE_TYPE_MISMATCH", "error"),
    ("assumption without explicit wording", _assumption_without_cue, "ASSUMPTION_NOT_EXPLICIT", "error"),
    ("inferred warrant", _inferred_warrant, "WARRANT_NOT_EXPLICIT", "error"),
    ("warrant without premise", _warrant_without_premise, "WARRANT_WITHOUT_PREMISE", "error"),
    ("prediction as condition", _prediction_as_condition, "ROLE_TYPE_MISMATCH", "error"),
    ("conditional clause in a prediction", _conditional_prediction, "CONDITIONAL_IN_CLAIM", "warning"),
    ("scenario without implications", _scenario_without_implications, "SCENARIO_EMPTY", "error"),
    ("view as scenario recommendation", _view_as_scenario_recommendation, "SCENARIO_RECOMMENDATION_TYPE", "error"),
    ("RECOMMENDATION type under v0.12", _old_recommendation_type, "INVALID_CLAIM_TYPE", "error"),
    ("premise restates another conclusion", _restated_conclusion, "PREMISE_DUPLICATES_CORE", "warning"),
]


@pytest.mark.parametrize(("label", "mutate", "code", "severity"), V12_MUTATIONS, ids=[m[0] for m in V12_MUTATIONS])
def test_v12_mutation_raises_expected_issue(
    ms_gold: GoldCase, v12: Taxonomy, label: str, mutate: Mutation, code: str, severity: str
) -> None:
    matches = [issue for issue in _issues(ms_gold, v12, mutate) if issue.code == code]
    assert matches, f"{label}: expected {code}"
    assert all(issue.severity == severity for issue in matches)


def test_reasoned_argument_can_be_referenced_by_id(ms_gold: GoldCase, v12: Taxonomy) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["arguments"][3]["premises"] = ["A001", "S007"]  # A001 has premises of its own

    issues = _issues(ms_gold, v12, mutate)
    assert not has_errors(issues), [f"{i.code} {i.path}" for i in issues if i.severity == "error"]
    edges = argument_edges(ArgumentMap.model_validate({**_ms_v12(ms_gold), "arguments": _mutated_arguments(ms_gold)}))
    assert ("A001", "premises", "A004") in edges


def _mutated_arguments(ms_gold: GoldCase) -> list[dict[str, Any]]:
    data = _ms_v12(ms_gold)
    data["arguments"][3]["premises"] = ["A001", "S007"]
    return data["arguments"]


def test_explicit_assumption_passes(ms_gold: GoldCase, v12: Taxonomy) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["evidence"].append({"id": "E099", "text": "Our base case assumes no Hormuz resolution before the election."})
        d["statements"].append({**SUPPOSITION, "id": "S022", "evidence": ["E099"], "modality_cue": "assumes"})
        d["arguments"][0]["assumptions"] = ["S022"]

    source = ms_gold.source + " Our base case assumes no Hormuz resolution before the election."
    data = _ms_v12(ms_gold)
    mutate(data)
    issues = validate(ArgumentMap.model_validate(data), source, v12)
    assert not [i for i in issues if i.code == "ASSUMPTION_NOT_EXPLICIT"]


def test_locate_matches_folded_gap_and_fuzzy_spans() -> None:
    source = (
        "Friday\u2019s CPI data all but lock in a rate hike this week. We also expect the core projections for 2027 "
        "to be Liquid Insight | 14 September 2026 3 revised down by 0.1pp. Warsh will probably say that progress "
        "on underlying inflation has been insufficient."
    )
    assert locate("Friday's CPI data all but lock in a rate hike this week.", source).method == "folded"
    gap = locate("We also expect the core projections for 2027 to be revised down by 0.1pp.", source)
    assert gap is not None
    assert gap.method == "gap"
    assert "Liquid Insight" in source[gap.start : gap.end]
    # A dropped word is bridged as a gap; a reworded span needs fuzzy alignment.
    dropped = locate("Warsh will probably say progress on underlying inflation has been insufficient.", source)
    assert dropped is not None
    assert dropped.method == "gap"
    fuzzy = locate("Warsh will likely say that progress on underlying inflation was insufficient.", source)
    assert fuzzy is not None
    assert fuzzy.method == "fuzzy"
    assert fuzzy.score >= 0.85
    assert locate("An unrelated sentence about Norwegian salmon prices.", source) is None


def test_gap_does_not_skip_whole_sentences() -> None:
    source = "The USD should weaken into year-end. Oil fell sharply on Monday. Rates should rally as growth slows."
    assert locate("The USD should weaken into year-end. Rates should rally as growth slows.", source) is None


def test_repair_snaps_spans_cues_and_links(ms_gold: GoldCase, v12: Taxonomy) -> None:
    data = _ms_v12(ms_gold)
    curly = next(e for e in data["evidence"] if fold(e["text"]) != e["text"])
    curly["text"] = fold(curly["text"])
    s001 = _statement(data, "S001")
    s001["modality_cue"] = s001["modality_cue"].upper()
    data["arguments"][3]["premises"] = ["S001", "S007"]  # S001 concludes A001, which has premises
    output = _output(data)
    assert any(i.code == "EVIDENCE_NOT_VERBATIM" for i in validate(output, ms_gold.source, v12))

    repaired, issues = repair_output(output, ms_gold.source, v12)
    codes = {i.code for i in issues}
    assert {"EVIDENCE_SNAPPED", "CUE_SNAPPED", "LINK_CANONICALISED"} <= codes
    assert repaired.arguments[3].premises == ["A001", "S007"]
    assert not has_errors(validate(repaired, ms_gold.source, v12))


def test_coverage_counts_cited_excluded_and_silent(ms_gold: GoldCase, v12: Taxonomy) -> None:
    amap = ArgumentMap.model_validate(_ms_v12(ms_gold))
    result = coverage(amap, ms_gold.source, v12.must_keep_patterns)
    assert result.sentences == result.cited + result.excluded + result.silent
    assert result.cited > 0
    empty = amap.model_copy(update={"evidence": [], "exclusions": []})
    assert coverage(empty, ms_gold.source, v12.must_keep_patterns).silent == result.sentences


def test_diagram_draws_argument_references(ms_gold: GoldCase, v12: Taxonomy) -> None:
    data = _ms_v12(ms_gold)
    data["arguments"][3]["premises"] = ["A001", "S007"]
    amap = argument_map_to_dict(ArgumentMap.model_validate(data), v12.argument_roles)
    assert "conclusion" in amap["arguments"][0]
    assert "core_claim" not in amap["arguments"][0]
    mermaid = ArgumentMapDiagram(amap).to_mermaid()
    assert "<b>P:</b> <b>A001 - VIEW</b>" in mermaid
    assert "A001 -- Premise --> A004" in mermaid
    assert "<b>THEN:</b>" in mermaid
