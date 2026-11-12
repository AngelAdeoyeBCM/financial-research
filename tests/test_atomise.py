import json
import re
from pathlib import Path

import pytest

from incolor.propositions.atomise import (
    LEGACY_LABELS,
    PROMPT_PATH,
    FormulaError,
    check,
    formula_roles,
    load_prompt,
    parse_formula,
)


def _targets(lines: dict[str, str]) -> list[dict[str, str]]:
    return [{"id": "E" + tag[1:], "kind": "text", "text": text} for tag, text in lines.items()]


def _prompt_example(path: Path = PROMPT_PATH) -> tuple[list[dict[str, str]], str]:
    prompt = path.read_text(encoding="utf-8")
    example = prompt.split("# Examples", 1)[1]
    inputs = dict(re.findall(r"^\[(P\d+)\] (.+)$", example, re.M))
    output = example.split("Output:\n", 1)[1]
    return _targets(inputs), output


def test_prompt_example_is_valid() -> None:
    targets, raw = _prompt_example()
    atoms, logic, issues = check(targets, raw)
    assert [i for i in issues if i.severity == "error"] == []
    roles = {a.id: a.role for a in atoms}
    assert {k: roles[k] for k in ("P003-1", "P007-1", "P007-2", "P013-2")} == {
        "P003-1": "statement",
        "P007-1": "antecedent",
        "P007-2": "consequent",
        "P013-2": "consequent",
    }
    labels = {a.id: (a.claim_type, a.subkinds) for a in atoms}
    assert labels["P015-1"] == ("TRADE", ("open",))
    assert labels["P015-2"] == ("PREDICTION", ("directional", "quantitative"))
    assert labels["P016-1"] == ("RATING", ("allocation",))
    assert labels["P017-1"] == ("CAUSAL", ("market_state",))
    assert labels["P003-1"] == ("EVIDENCE", ())
    assert {a.id for a in atoms if a.claim_type == "SUPPOSITION"} == {"P007-1", "P013-1"}
    assert {a.modality for a in atoms if a.claim_type == "SUPPOSITION"} == {"HYPOTHETICAL"}
    assert [i.code for i in issues if i.code in ("MODALITY_DROPPED", "PRONOUN_IN_ATOM")] == []
    assert next(s for s in logic if s.id == "E013").topic == "Bear case"


def test_legacy_prompt_example_is_valid_with_legacy_labels() -> None:
    path = PROMPT_PATH.with_name("atomise_v04.md")
    assert load_prompt(path)[1] == LEGACY_LABELS
    targets, raw = _prompt_example(path)
    _, _, issues = check(targets, raw, LEGACY_LABELS)
    assert [i for i in issues if i.severity == "error"] == []


def test_prompt_inherits_taxonomy() -> None:
    prompt, labels = load_prompt()
    assert "{{" not in prompt
    for heading in ("### TRADE", "### CAUSAL", "### `trade_action`", "### HYPOTHETICAL", "Claim type decision order"):
        assert heading in prompt
    assert labels.claim_types == ("TRADE", "RATING", "PREDICTION", "CAUSAL", "VIEW", "SUPPOSITION", "EVIDENCE")
    assert labels.fixed_modality == {"TRADE": "ASSERTED", "RATING": "ASSERTED", "SUPPOSITION": "HYPOTHETICAL"}
    assert "EVIDENCE" not in labels.subkinds


def test_subkind_and_fixed_modality_errors() -> None:
    targets = _targets({"P001": "If the Fed holds, the author buys 2y notes, and USD is cheap and could fall."})
    atoms = [
        ("The Fed holds.", "SUPPOSITION", ["event"], "ASSERTED"),
        ("The author buys 2y notes.", "TRADE", ["open", "maintain"], "ASSERTED"),
        ("USD is cheap.", "VIEW", [], "ASSERTED"),
        ("USD could fall.", "PREDICTION", ["valuation"], "HYPOTHETICAL"),
        ("The author buys 2y notes.", "EVIDENCE", ["event"], "ASSERTED"),
    ]
    raw = json.dumps(
        {
            "P001": {
                "topic": None,
                "atoms": [
                    {"id": f"P001-{n}", "text": t, "claim_type": c, "subkinds": s, "modality": m}
                    for n, (t, c, s, m) in enumerate(atoms, 1)
                ],
                "facts": ["P001-3", "P001-4", "P001-5"],
                "formula": "IF(P001-1, P001-2)",
                "relations": [],
                "open_connectives": [],
            }
        }
    )
    _, _, issues = check(targets, raw)
    errors = sorted((i.segment, i.code) for i in issues if i.severity == "error")
    assert errors == [
        ("P001-1", "MODALITY_MISMATCH"),
        ("P001-2", "BAD_SUBKIND"),
        ("P001-3", "BAD_SUBKIND"),
        ("P001-4", "BAD_SUBKIND"),
        ("P001-4", "MODALITY_MISMATCH"),
        ("P001-5", "BAD_SUBKIND"),
    ]


@pytest.mark.parametrize("formula", ["IF(P001-1, P001-2", "IF(P001-1)", "NOT(P001-1, P001-2)", "XOR(P001-1, P001-2)"])
def test_bad_formulas_raise(formula: str) -> None:
    with pytest.raises(FormulaError):
        parse_formula(formula)


def test_roles_from_nested_formula() -> None:
    tree = parse_formula("AND(IF(NOT(OR(P1-1, P1-2)), AND(P1-3, P1-4)), OR(P1-5, P1-6))".replace("P1", "P001"))
    assert formula_roles(tree) == {
        "P001-1": "antecedent",
        "P001-2": "antecedent",
        "P001-3": "consequent",
        "P001-4": "consequent",
        "P001-5": "statement",
        "P001-6": "statement",
    }


def test_causal_marker_in_atom_and_unused_atom_are_errors() -> None:
    targets = _targets({"P094": "Bond yields are higher due to dovish Fed action."})
    raw = json.dumps(
        {
            "P094": {
                "topic": None,
                "atoms": [
                    {
                        "id": "P094-1",
                        "text": "Bond yields are higher due to dovish Fed action.",
                        "claim_type": "VIEW",
                        "subkinds": ["market_state"],
                        "modality": "ASSERTED",
                    },
                    {
                        "id": "P094-2",
                        "text": "The Fed's action is dovish.",
                        "claim_type": "VIEW",
                        "subkinds": ["event"],
                        "modality": "ASSERTED",
                    },
                ],
                "facts": ["P094-1"],
                "formula": None,
                "relations": [],
                "open_connectives": [],
            }
        }
    )
    _, _, issues = check(targets, raw)
    codes = {i.code for i in issues if i.severity == "error"}
    assert codes == {"CONNECTIVE_IN_ATOM", "ATOM_UNUSED"}
    assert "UNCONSUMED_CONNECTIVE" in {i.code for i in issues}
