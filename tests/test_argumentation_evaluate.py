"""Tests for the M5 evaluation metrics: gold-vs-gold scores, id-independence and sensitivity to edits."""

from tests.conftest import GoldCase

from incolor.argumentation.evaluate import evaluate, main, span_overlap, token_f1
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.validate import ARGUMENT_ROLES, argument_edges


def _renumber_statements(map_: ArgumentMap) -> ArgumentMap:
    renamed = map_.model_copy(deep=True)
    mapping = {s.id: f"S{900 + i:03d}" for i, s in enumerate(renamed.statements)}
    for statement in renamed.statements:
        statement.id = mapping[statement.id]
    for argument in renamed.arguments:
        argument.conclusion = mapping[argument.conclusion]
        for role in ARGUMENT_ROLES:
            setattr(argument, role, [mapping[sid] for sid in getattr(argument, role)])
    return renamed


def test_gold_against_itself_scores_perfectly(ms_gold: GoldCase) -> None:
    report = evaluate(ms_gold.argument_map, ms_gold.argument_map)
    assert report.evidence_recall == 1.0
    assert report.statement_f1 == 1.0
    assert report.claim_type_accuracy == 1.0
    assert report.modality_accuracy == 1.0
    assert report.edge_f1 == 1.0


def test_renumbered_statement_ids_still_score_perfectly(ms_gold: GoldCase) -> None:
    pred = _renumber_statements(ms_gold.argument_map)
    report = evaluate(pred, ms_gold.argument_map)
    assert report.statement_f1 == 1.0
    assert report.edge_f1 == 1.0


def test_missing_edge_lowers_edge_recall_only(ms_gold: GoldCase) -> None:
    gold = ms_gold.argument_map
    source_id, role, target_id = argument_edges(gold, ARGUMENT_ROLES)[0]
    core = next(a.conclusion for a in gold.arguments if a.id == source_id)
    pred = gold.model_copy(deep=True)
    target = next(a for a in pred.arguments if a.id == target_id)
    setattr(target, role, [sid for sid in getattr(target, role) if sid != core])

    report = evaluate(pred, gold)
    assert report.edge_recall < 1.0
    assert report.edge_precision == 1.0


def test_changed_claim_type_lowers_accuracy_not_matching(ms_gold: GoldCase) -> None:
    gold = ms_gold.argument_map
    pred = gold.model_copy(deep=True)
    statement = pred.statements[0]
    statement.claim_type = "VIEW" if statement.claim_type != "VIEW" else "OBSERVATION"

    report = evaluate(pred, gold)
    assert report.statement_f1 == 1.0
    assert report.claim_type_accuracy is not None
    assert report.claim_type_accuracy < 1.0


def test_span_and_token_measures() -> None:
    assert span_overlap("capex-intensive", "capex-intensive sector") == 1.0
    assert span_overlap("abcdefghij", "abcdexxxxx") < 0.8
    assert token_f1("Ocado is cheap.", "ocado is cheap") == 1.0
    assert token_f1("alpha", "beta") == 0.0


def test_main_returns_one_for_missing_file(tmp_path) -> None:
    assert main([str(tmp_path / "pred.yaml"), str(tmp_path / "gold.yaml")]) == 1
