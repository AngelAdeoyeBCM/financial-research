"""Tests for validate(): gold maps produce no errors, and each issue code is raised by a targeted mutation."""

import copy
from collections.abc import Callable
from typing import Any

import pytest
from tests.conftest import GoldCase

from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import Taxonomy
from incolor.argumentation.validate import argument_edges, has_errors, validate

Mutation = Callable[[dict[str, Any]], None]


def _dup_evidence(d: dict[str, Any]) -> None:
    d["evidence"].append(copy.deepcopy(d["evidence"][0]))


def _not_verbatim(d: dict[str, Any]) -> None:
    d["evidence"][0]["text"] = "This sentence does not appear in the source."


def _unused_evidence(d: dict[str, Any]) -> None:
    d["evidence"].append({"id": "E013", "text": "Please let us know how we can help."})


def _unknown_evidence(d: dict[str, Any]) -> None:
    d["statements"][0]["evidence"] = ["E099"]


def _bad_claim_type(d: dict[str, Any]) -> None:
    d["statements"][0]["claim_type"] = "OPINION"


def _bad_modality(d: dict[str, Any]) -> None:
    d["statements"][0]["modality"] = "CERTAIN"


def _fixed_modality(d: dict[str, Any]) -> None:
    d["statements"][1]["modality"] = "HEDGED"  # S002 is OBSERVATION, which must be ASSERTED


def _cue_missing(d: dict[str, Any]) -> None:
    d["statements"][0]["modality_cue"] = "definitely not here"


def _unknown_statement_ref(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"].append("S099")


def _core_duplicate(d: dict[str, Any]) -> None:
    d["arguments"][1]["conclusion"] = "S001"  # A002 takes S001, which A001 already owns


def _role_type_mismatch(d: dict[str, Any]) -> None:
    d["arguments"][0]["rationale"].append("S006")  # S006 is VIEW; rationale allows DATA_POINT and OBSERVATION only


def _argument_without_relation(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"] = []  # A001 is left with only the S002 OBSERVATION


def _statement_unreferenced(d: dict[str, Any]) -> None:
    d["arguments"][6]["rationale"] = []  # A007 held S012 and S014 only; nothing else references them


def _self_reference(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"].append("S001")  # A001's own core claim


def _duplicate_role_member(d: dict[str, Any]) -> None:
    d["arguments"][0]["qualifiers"].append(d["arguments"][0]["supporting"][0])


def _summary_cites_non_member(d: dict[str, Any]) -> None:
    d["arguments"][0]["summary"] += " See [S010]."  # S010 is not a member of A001


def _argument_cycle(d: dict[str, Any]) -> None:
    d["arguments"][0]["supporting"].append("S008")  # A001 supports A004 via S001; A004 now supports A001 via S008


def _exclusion_not_verbatim(d: dict[str, Any]) -> None:
    d["exclusions"][0]["text"] = "This excluded sentence does not appear in the source."


def _brief_too_long(d: dict[str, Any]) -> None:
    d["statements"][0]["brief"] = "one two three four five six seven eight nine ten eleven"


MUTATIONS: list[tuple[str, Mutation, str, str]] = [
    ("duplicate evidence id", _dup_evidence, "DUPLICATE_ID", "error"),
    ("evidence not verbatim", _not_verbatim, "EVIDENCE_NOT_VERBATIM", "error"),
    ("unused evidence", _unused_evidence, "EVIDENCE_UNUSED", "warning"),
    ("unknown evidence ref", _unknown_evidence, "UNKNOWN_EVIDENCE_REF", "error"),
    ("invalid claim type", _bad_claim_type, "INVALID_CLAIM_TYPE", "error"),
    ("invalid modality", _bad_modality, "INVALID_MODALITY", "error"),
    ("fixed modality violated", _fixed_modality, "FIXED_MODALITY", "error"),
    ("cue not in evidence", _cue_missing, "CUE_NOT_IN_EVIDENCE", "error"),
    ("unknown statement ref", _unknown_statement_ref, "UNKNOWN_STATEMENT_REF", "error"),
    ("core claim duplicated", _core_duplicate, "CORE_DUPLICATE", "error"),
    ("role type mismatch", _role_type_mismatch, "ROLE_TYPE_MISMATCH", "error"),
    ("argument without relation", _argument_without_relation, "ARGUMENT_WITHOUT_RELATION", "error"),
    ("statement unreferenced", _statement_unreferenced, "STATEMENT_UNREFERENCED", "error"),
    ("self reference", _self_reference, "SELF_REFERENCE", "error"),
    ("duplicate role member", _duplicate_role_member, "DUPLICATE_ROLE_MEMBER", "error"),
    ("summary cites non-member", _summary_cites_non_member, "SUMMARY_CITES_NON_MEMBER", "error"),
    ("argument cycle", _argument_cycle, "ARGUMENT_CYCLE", "error"),
    ("exclusion not verbatim", _exclusion_not_verbatim, "EXCLUSION_NOT_VERBATIM", "warning"),
    ("brief too long", _brief_too_long, "BRIEF_TOO_LONG", "warning"),
]


def _validate_mutated(case: GoldCase, taxonomy: Taxonomy, mutate: Mutation) -> list:
    data = case.argument_map.model_dump()
    mutate(data)
    return validate(ArgumentMap.model_validate(data), case.source, taxonomy)


def test_gold_maps_have_zero_errors(gold_case: GoldCase, taxonomy: Taxonomy) -> None:
    issues = validate(gold_case.argument_map, gold_case.source, taxonomy)
    errors = [issue for issue in issues if issue.severity == "error"]
    assert errors == [], [f"{issue.code} {issue.path}: {issue.message}" for issue in errors]
    assert has_errors(issues) is False


@pytest.mark.parametrize(("label", "mutate", "code", "severity"), MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_raises_expected_issue(
    ms_gold: GoldCase, taxonomy: Taxonomy, label: str, mutate: Mutation, code: str, severity: str
) -> None:
    issues = _validate_mutated(ms_gold, taxonomy, mutate)
    matches = [issue for issue in issues if issue.code == code]
    assert matches, f"{label}: expected {code}, got {sorted({i.code for i in issues})}"
    assert all(issue.severity == severity for issue in matches)
    assert all(issue.path.startswith("$.") for issue in matches)
    assert all(issue.suggested_action for issue in matches)


def test_error_mutations_make_map_invalid(ms_gold: GoldCase, taxonomy: Taxonomy) -> None:
    for label, mutate, _code, severity in MUTATIONS:
        if severity == "error":
            assert has_errors(_validate_mutated(ms_gold, taxonomy, mutate)), label


def test_argument_edges_for_ms_gold(ms_gold: GoldCase, taxonomy: Taxonomy) -> None:
    edges = argument_edges(ms_gold.argument_map, taxonomy.argument_roles)
    assert ("A001", "supporting", "A004") in edges  # A004 cites S001, the core of A001
    assert ("A004", "supporting", "A005") in edges  # A005 cites S008, the core of A004
