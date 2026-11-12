"""Model agreement between two resolve runs on the same document, step by step.

References: candidates are found by code (recomputed from the source), so both runs decide the same list. Links come
from the reference edits in ``edits.jsonl`` (each carries its referent id), leave / ambiguous decisions and the
referent types from ``run.json``.

    decision    share of candidates given the same action (link / leave / ambiguous); leave reasons compared too
    coreference B3 F1 over candidates both runs linked: do they group the same candidates under one referent,
                whatever the referents are called
    type        share of jointly linked candidates whose referents have the same type (thing / claim)
    text        share of jointly linked candidates rendered with exactly the same text, and with equivalent text
                (case and a leading the/a/an ignored)
    extra       F1 over the phrases each run added beyond the candidates

Ellipsis (``edits.jsonl``): F1 over insertion points, and over insertion point plus text.

Writes ``agreement.txt`` (scores, then every candidate the runs treat differently) to ``--out``.

Usage::

    python scripts/agreement.py outputs/resolve_v04/<doc>/opus outputs/resolve_v04/<doc>/haiku
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incolor.propositions.edits import Edit, load_run, run_report
from incolor.propositions.referents import Candidate, find_candidates
from incolor.propositions.staging import Doc

ELLIPSIS_KINDS = {"vp", "answer", "fragment"}


@dataclass
class Run:
    """One run's reference decisions per candidate id, referent types, extra phrases and ellipsis edits."""

    candidates: list[Candidate]
    decisions: dict[str, dict[str, Any]]
    types: dict[str, str]
    extras: set[tuple[int, int]]
    gaps: list[Edit]


def load(run_dir: Path) -> Run:
    """Rebuild a run's decisions: links from its reference edits, everything else from ``run.json``."""
    source, edits, _ = load_run(run_dir)
    report = run_report(run_dir)
    candidates = find_candidates(Doc.build(source))
    starts = {c.start for c in candidates}
    links = {e.start: e for e in edits if e.referent}
    others = {d["candidate"]: d for d in report.get("decisions", []) if d.get("candidate")}
    decisions: dict[str, dict[str, Any]] = {}
    for c in candidates:
        if c.start in links:
            e = links[c.start]
            decisions[c.id] = {"action": "link", "referent": e.referent, "text": e.text}
        elif c.id in others:
            decisions[c.id] = others[c.id]
    return Run(
        candidates,
        decisions,
        {r["id"]: r["type"] for r in report.get("referents", [])},
        {(e.start, e.end) for e in edits if e.referent and e.start not in starts},
        [e for e in edits if e.kind in ELLIPSIS_KINDS],
    )


def f1(a: set[Any], b: set[Any]) -> float:
    """Return the F1 of two sets (1.0 when both are empty)."""
    return 1.0 if not a and not b else 2 * len(a & b) / (len(a) + len(b))


def equivalent_text(text: str | None) -> str:
    """Return ``text`` case-folded, with a leading the/a/an and extra spaces removed."""
    return re.sub(r"^(?:the|a|an)\s+", "", " ".join((text or "").split()).casefold())


def b_cubed(a: dict[str, str], b: dict[str, str]) -> float:
    """Return the B3 F1 of two clusterings of the same items (item -> cluster id)."""
    if not a:
        return 1.0
    precision = recall = 0.0
    for item in a:
        in_a = {i for i, c in a.items() if c == a[item]}
        in_b = {i for i, c in b.items() if c == b[item]}
        precision += len(in_a & in_b) / len(in_a)
        recall += len(in_a & in_b) / len(in_b)
    p, r = precision / len(a), recall / len(a)
    return 2 * p * r / (p + r) if p + r else 0.0


def main() -> int:
    """Print and write the agreement report; exit 1 if the runs have different candidates."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, nargs=2)
    parser.add_argument("--out", type=Path, help="folder for agreement.txt (default: parent of the first run)")
    args = parser.parse_args()

    names = [f"{p.parent.name[:24]}/{p.name}" for p in args.runs]
    runs = [load(p) for p in args.runs]
    if runs[0].candidates != runs[1].candidates:
        print("runs were made on different sources", file=sys.stderr)
        return 1
    candidates = {c.id: c for c in runs[0].candidates}
    decisions = [r.decisions for r in runs]
    types = [r.types for r in runs]

    def action(k: int, cid: str) -> str:
        d = decisions[k].get(cid)
        return "undecided" if d is None else d["action"] if d["action"] != "leave" else f"leave:{d['reason']}"

    same_action = [c for c in candidates if action(0, c).split(":")[0] == action(1, c).split(":")[0]]
    both_leave = [c for c in same_action if action(0, c).startswith("leave")]
    linked = [c for c in candidates if action(0, c) == action(1, c) == "link"]
    clusters = [{c: decisions[k][c]["referent"] for c in linked} for k in (0, 1)]
    same_type = [c for c in linked if types[0].get(clusters[0][c]) == types[1].get(clusters[1][c])]
    same_text = [c for c in linked if decisions[0][c]["text"] == decisions[1][c]["text"]]
    equivalent = [
        c for c in linked if equivalent_text(decisions[0][c]["text"]) == equivalent_text(decisions[1][c]["text"])
    ]
    extras = [r.extras for r in runs]
    gaps = [({e.start for e in r.gaps}, {(e.start, e.text) for e in r.gaps}) for r in runs]

    n = len(candidates)
    rows = [
        f"{names[1]} vs {names[0]}",
        f"references: {n} candidates; links {len(linked)} joint",
        f"  decision     {len(same_action) / n:.2f}  (leave reasons equal: "
        f"{sum(action(0, c) == action(1, c) for c in both_leave)}/{len(both_leave)})",
        f"  coreference  {b_cubed(*clusters):.2f}  (B3 F1 over jointly linked candidates)",
        f"  type         {len(same_type) / max(1, len(linked)):.2f}",
        f"  text         {len(same_text) / max(1, len(linked)):.2f}  "
        f"(equivalent: {len(equivalent) / max(1, len(linked)):.2f})",
        f"  extra        {f1(*extras):.2f}  ({len(extras[0])} vs {len(extras[1])} phrases)",
        f"ellipsis: places {f1(gaps[0][0], gaps[1][0]):.2f}, places + text {f1(gaps[0][1], gaps[1][1]):.2f} "
        f"({len(gaps[0][0])} vs {len(gaps[1][0])})",
    ]
    diffs = []
    for cid, c in candidates.items():
        texts = [decisions[k].get(cid, {}).get("text") for k in (0, 1)]
        if action(0, cid) == action(1, cid) and texts[0] == texts[1]:
            continue
        lines = [f"{cid} {c.sid} {c.token!r}"]
        for k in (0, 1):
            d = decisions[k].get(cid) or {}
            shown = d.get("text") or d.get("reason") or ",".join(d.get("referents") or []) or ""
            lines.append(f"  {names[k]:<34} {action(k, cid):<22} {d.get('referent') or '':<5} {shown}")
        diffs.append("\n".join(lines))
    report = "\n".join(rows) + "\n\n" + "\n\n".join(diffs) + "\n"
    out: Path = args.out or args.runs[0].parent
    (out / "agreement.txt").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(("\n".join(rows) + f"\n\nwritten: {out / 'agreement.txt'}\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
