"""Score a predicted argument map against a gold map: evidence recall, statement match and argument-edge F1.

Usage: ``python -m incolor.argumentation.evaluate PRED.yaml GOLD.yaml``
"""

import argparse
import difflib
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .schema import ArgumentMap, Statement
from .validate import ARGUMENT_ROLES, argument_edges
from .writer import load_argument_map

SPAN_OVERLAP_THRESHOLD = 0.8
STATEMENT_F1_THRESHOLD = 0.5
EXIT_OK = 0
EXIT_FAILURE = 1
_TOKEN = re.compile(r"\w+")
_WHITESPACE = re.compile(r"\s+")

type _Edge = tuple[str, str, str]


@dataclass(frozen=True)
class EvaluationReport:
    """Scores for one predicted map against one gold map. Accuracies are None when no statements matched."""

    evidence_recall: float
    statement_precision: float
    statement_recall: float
    statement_f1: float
    claim_type_accuracy: float | None
    modality_accuracy: float | None
    edge_precision: float
    edge_recall: float
    edge_f1: float


def span_overlap(gold: str, pred: str) -> float:
    """Return the share of ``gold`` characters matched, in order, inside ``pred``, after whitespace squashing."""
    gold_text = _WHITESPACE.sub(" ", gold).strip()
    pred_text = _WHITESPACE.sub(" ", pred).strip()
    if not gold_text:
        return 0.0
    matcher = difflib.SequenceMatcher(None, gold_text, pred_text, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(gold_text)


def token_f1(a: str, b: str) -> float:
    """Return the case-insensitive bag-of-tokens F1 between two strings."""
    tokens_a = Counter(_TOKEN.findall(a.lower()))
    tokens_b = Counter(_TOKEN.findall(b.lower()))
    overlap = sum((tokens_a & tokens_b).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(tokens_b.values())
    recall = overlap / sum(tokens_a.values())
    return 2 * precision * recall / (precision + recall)


def match_statements(
    pred: ArgumentMap, gold: ArgumentMap, text_only_threshold: float | None = None
) -> dict[str, str]:
    """Return a one-to-one mapping from predicted statement IDs to gold statement IDs.

    Two statements are candidates when an evidence span of one covers an evidence span of the other and their
    token F1 is at least ``STATEMENT_F1_THRESHOLD``. With ``text_only_threshold``, statements that share no evidence
    are also candidates when their token F1 reaches it, so a claim grounded in differently quoted text still matches.
    Candidates are taken greedily, best F1 first.
    """
    pred_text = {item.id: item.text for item in pred.evidence}
    gold_text = {item.id: item.text for item in gold.evidence}
    shared_spans = {
        (pid, gid)
        for pid, ptext in pred_text.items()
        for gid, gtext in gold_text.items()
        if span_overlap(gtext, ptext) >= SPAN_OVERLAP_THRESHOLD
    }
    candidates: list[tuple[float, str, str]] = []
    for ps in pred.statements:
        for gs in gold.statements:
            shared = _shares_evidence(ps, gs, shared_spans)
            if not shared and text_only_threshold is None:
                continue
            score = token_f1(ps.statement, gs.statement)
            if score >= (STATEMENT_F1_THRESHOLD if shared else text_only_threshold):
                candidates.append((score, ps.id, gs.id))

    matches: dict[str, str] = {}
    used_gold: set[str] = set()
    for _score, pid, gid in sorted(candidates, key=lambda c: (-c[0], c[1], c[2])):
        if pid in matches or gid in used_gold:
            continue
        matches[pid] = gid
        used_gold.add(gid)
    return matches


def evaluate(pred: ArgumentMap, gold: ArgumentMap) -> EvaluationReport:
    """Score ``pred`` against ``gold``. Returns 1.0 for a metric whose denominator is empty on both sides."""
    mapping = match_statements(pred, gold)
    pred_by_id = {s.id: s for s in pred.statements}
    gold_by_id = {s.id: s for s in gold.statements}
    pairs = [(pred_by_id[p], gold_by_id[g]) for p, g in mapping.items()]

    stmt_precision, stmt_recall, stmt_f1 = _prf(len(mapping), len(pred.statements), len(gold.statements))
    edge_precision, edge_recall, edge_f1 = _edge_scores(pred, gold, mapping)
    return EvaluationReport(
        evidence_recall=_evidence_recall(pred, gold),
        statement_precision=stmt_precision,
        statement_recall=stmt_recall,
        statement_f1=stmt_f1,
        claim_type_accuracy=_share(pairs, lambda p, g: p.claim_type == g.claim_type),
        modality_accuracy=_share(pairs, lambda p, g: p.modality == g.modality),
        edge_precision=edge_precision,
        edge_recall=edge_recall,
        edge_f1=edge_f1,
    )


def format_report(report: EvaluationReport) -> str:
    """Render the report as one ``name: value`` line per metric."""
    lines = []
    for name, value in asdict(report).items():
        text = "n/a" if value is None else f"{value:.3f}"
        lines.append(f"{name}: {text}")
    return "\n".join(lines)


def _shares_evidence(pred_stmt: Statement, gold_stmt: Statement, shared_spans: set[tuple[str, str]]) -> bool:
    return any((pid, gid) in shared_spans for pid in pred_stmt.evidence for gid in gold_stmt.evidence)


def _evidence_recall(pred: ArgumentMap, gold: ArgumentMap) -> float:
    if not gold.evidence:
        return 1.0
    covered = sum(
        any(span_overlap(item.text, candidate.text) >= SPAN_OVERLAP_THRESHOLD for candidate in pred.evidence)
        for item in gold.evidence
    )
    return covered / len(gold.evidence)


def _prf(matched: int, predicted: int, actual: int) -> tuple[float, float, float]:
    if predicted == 0 and actual == 0:
        return 1.0, 1.0, 1.0
    precision = matched / predicted if predicted else 0.0
    recall = matched / actual if actual else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _core_edges(map_: ArgumentMap) -> set[_Edge]:
    """Return argument edges restated by conclusion statement ID, so they survive renumbering."""
    core = {argument.id: argument.conclusion for argument in map_.arguments}
    return {(core[src], role, core[tgt]) for src, role, tgt in argument_edges(map_, ARGUMENT_ROLES)}


def _edge_scores(pred: ArgumentMap, gold: ArgumentMap, mapping: dict[str, str]) -> tuple[float, float, float]:
    gold_edges = _core_edges(gold)
    pred_edges = _core_edges(pred)
    matched = 0
    for src, role, tgt in pred_edges:
        src_gold, tgt_gold = mapping.get(src), mapping.get(tgt)
        if src_gold is not None and tgt_gold is not None and (src_gold, role, tgt_gold) in gold_edges:
            matched += 1
    return _prf(matched, len(pred_edges), len(gold_edges))


def _share(
    pairs: Sequence[tuple[Statement, Statement]], same: Callable[[Statement, Statement], bool]
) -> float | None:
    if not pairs:
        return None
    return sum(same(p, g) for p, g in pairs) / len(pairs)


def main(argv: Sequence[str] | None = None) -> int:
    """Load both maps, print the report and return the exit code."""
    parser = argparse.ArgumentParser(description="Score a predicted argument map against a gold map.")
    parser.add_argument("pred", type=Path, help="Predicted map YAML.")
    parser.add_argument("gold", type=Path, help="Gold map YAML.")
    args = parser.parse_args(argv)
    try:
        pred = load_argument_map(args.pred)
        gold = load_argument_map(args.gold)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    print(format_report(evaluate(pred, gold)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
