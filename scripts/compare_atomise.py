"""Pairwise comparison of atomise runs: atom counts, claim types and, for matched atoms, label agreement.

Atoms are matched within the same sentence id by greedy text similarity (difflib ratio >= ``--threshold``). Claim-type
agreement and kappa compare claim types; label agreement also requires the same subkinds. Writes ``compare.txt`` next
to the runs (or ``--out``) and prints it.

Usage::

    python scripts/compare_atomise.py outputs/atomise_v05/norm-opus_atom-opus outputs/atomise_v05/norm-opus_atom-haiku
    python scripts/compare_atomise.py outputs/atomise_v05/*
"""

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from incolor.propositions.atomise import LEGACY_LABELS, default_labels

TYPE_ORDER = (*default_labels().claim_types, *LEGACY_LABELS.claim_types)


def load(run: Path) -> list[dict[str, Any]]:
    """Return the atoms of one run."""
    with (run / "atoms.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def by_sentence(atoms: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group atoms by Stage 1 sentence id."""
    out: dict[str, list[dict[str, Any]]] = {}
    for a in atoms:
        out.setdefault(a["sentence_id"], []).append(a)
    return out


def match(left: list[dict[str, Any]], right: list[dict[str, Any]], threshold: float) -> list[tuple[dict, dict, float]]:
    """Greedily pair atoms of one sentence by text similarity, best pairs first."""
    scored = sorted(
        (
            (SequenceMatcher(None, a["text"].lower(), b["text"].lower()).ratio(), i, j)
            for i, a in enumerate(left)
            for j, b in enumerate(right)
        ),
        reverse=True,
    )
    used_l: set[int] = set()
    used_r: set[int] = set()
    pairs = []
    for score, i, j in scored:
        if score < threshold or i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        pairs.append((left[i], right[j], score))
    return pairs


def table(rows: list[list[str]]) -> list[str]:
    """Return left-aligned text table lines."""
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    return ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip() for row in rows]


def label(atom: dict[str, Any]) -> str:
    """Return the claim type with its subkinds, such as ``PREDICTION[directional,quantitative]``."""
    subkinds = sorted(atom.get("subkinds") or [])
    return f"{atom['claim_type']}[{','.join(subkinds)}]" if subkinds else atom["claim_type"]


def compare(runs: list[Path], threshold: float) -> str:
    """Return the comparison report."""
    names = [r.name for r in runs]
    atoms = {r.name: load(r) for r in runs}
    seen = {a["claim_type"] for run in atoms.values() for a in run}
    types = sorted(seen, key=lambda t: (TYPE_ORDER.index(t) if t in TYPE_ORDER else len(TYPE_ORDER), t))
    lines = ["Per run", ""]
    rows = [["run", "atoms", *types]]
    for name in names:
        counts = Counter(a["claim_type"] for a in atoms[name])
        rows.append([name, str(len(atoms[name])), *(str(counts.get(t, 0)) for t in types)])
    lines += table(rows)

    lines += ["", f"Pairwise (atoms matched within a sentence at similarity >= {threshold})", ""]
    rows = [
        ["left", "right", "atoms L/R", "same count", "matched", "unmatched L/R", "type agree", "kappa", "label agree"]
    ]
    details: list[str] = []
    for a, b in combinations(names, 2):
        left, right = by_sentence(atoms[a]), by_sentence(atoms[b])
        sentences = sorted(set(left) | set(right))
        same = sum(len(left.get(s, [])) == len(right.get(s, [])) for s in sentences)
        pairs = [p for s in sentences for p in match(left.get(s, []), right.get(s, []), threshold)]
        agree = sum(x["claim_type"] == y["claim_type"] for x, y, _ in pairs)
        label_agree = sum(label(x) == label(y) for x, y, _ in pairs)
        rows.append(
            [
                a,
                b,
                f"{len(atoms[a])}/{len(atoms[b])}",
                f"{same}/{len(sentences)}",
                str(len(pairs)),
                f"{len(atoms[a]) - len(pairs)}/{len(atoms[b]) - len(pairs)}",
                f"{agree}/{len(pairs)} ({agree / len(pairs):.0%})" if pairs else "-",
                f"{kappa(pairs):.2f}" if pairs else "-",
                f"{label_agree}/{len(pairs)} ({label_agree / len(pairs):.0%})" if pairs else "-",
            ]
        )
        confusion = Counter(
            (x["claim_type"], y["claim_type"]) for x, y, _ in pairs if x["claim_type"] != y["claim_type"]
        )
        details += ["", f"{a}  vs  {b}: claim-type disagreements on matched atoms (left -> right)"]
        details += [f"  {n:>3}  {lt} -> {rt}" for (lt, rt), n in confusion.most_common()] or ["  none"]
        subkind_confusion = Counter(
            (label(x), label(y)) for x, y, _ in pairs if x["claim_type"] == y["claim_type"] and label(x) != label(y)
        )
        if subkind_confusion:
            details.append("  subkind disagreements on same-type atoms (left -> right)")
            details += [f"  {n:>3}  {lt} -> {rt}" for (lt, rt), n in subkind_confusion.most_common()]
        diffs = [(s, len(left.get(s, [])), len(right.get(s, []))) for s in sentences]
        diffs = [d for d in diffs if d[1] != d[2]]
        diffs.sort(key=lambda d: -abs(d[1] - d[2]))
        details.append(
            "  largest atom-count differences (sentence: left/right): "
            + ", ".join(f"{s.replace('E', 'P', 1)} {n}/{m}" for s, n, m in diffs[:8])
        )
    lines += table(rows)
    return "\n".join(lines + details) + "\n"


def kappa(pairs: list[tuple[dict, dict, float]]) -> float:
    """Cohen's kappa for claim types over matched atom pairs."""
    n = len(pairs)
    observed = sum(x["claim_type"] == y["claim_type"] for x, y, _ in pairs) / n
    left = Counter(x["claim_type"] for x, _, _ in pairs)
    right = Counter(y["claim_type"] for _, y, _ in pairs)
    expected = sum(left[t] * right[t] for t in left) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def main() -> int:
    """Compare two or more atomise run folders."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--out", type=Path, help="report path (default <parent of first run>/compare.txt)")
    args = parser.parse_args()
    runs = [r for r in args.runs if (r / "atoms.jsonl").is_file()]
    if len(runs) < 2:
        parser.error("need at least two run folders containing atoms.jsonl")
    report = compare(runs, args.threshold)
    out: Path = args.out or runs[0].parent / "compare.txt"
    out.write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
