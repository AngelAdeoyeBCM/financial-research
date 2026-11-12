"""Compare Stage 1 normalisation runs on the same source (e.g. Opus vs Haiku).

Edits (``edits.jsonl``) from all runs are grouped by overlapping source spans; each group shows the source text and
how each run rewrote it. Writes ``compare.txt`` (summary table + every group where the runs differ) to ``--out``.

Usage::

    python scripts/compare_normalise.py outputs/normalise_v20/opus outputs/normalise_v20/haiku
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any

from incolor.propositions.document import load_body
from incolor.propositions.edits import Edit, read_edits, source_path


def load_run(path: Path) -> dict[str, Any]:
    """Return a run's source, edits (none if the run failed) and validation report."""
    report = json.loads((path / "validation.json").read_text(encoding="utf-8"))
    source, _ = load_body(source_path(path))
    edits_path = path / "edits.jsonl"
    return {
        "name": f"{path.parent.name.removeprefix('normalise_')}/{path.name}",
        "source": source,
        "edits": read_edits(edits_path, source) if edits_path.exists() else [],
        "summary": report["summary"],
        "codes": Counter(i["code"] for i in report["issues"]),
    }


def groups(runs: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return the merged source spans covered by any run's edits (an insertion covers its offset)."""
    spans = sorted((e.start, e.end) for r in runs for e in r["edits"])
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and (a < merged[-1][1] or a == merged[-1][0]):
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def render(source: str, edits: list[Edit], a: int, b: int) -> str:
    """Return ``source[a:b]`` with the run's edits inside the span applied."""
    out, pos = [], a
    for e in edits:
        if a <= e.start and e.end <= b:
            out += [source[pos : e.start], e.text]
            pos = e.end
    out.append(source[pos:b])
    return "".join(out)


def f1(reference: list[Edit], other: list[Edit], key: Callable[[Edit], Hashable]) -> float:
    """Return the F1 of ``other``'s edits against ``reference``'s, matching on ``key``."""
    ref, out = {key(e) for e in reference}, {key(e) for e in other}
    if not ref and not out:
        return 1.0
    return 2 * len(ref & out) / (len(ref) + len(out))


def main() -> int:
    """Write and print the comparison; exit 1 if the runs were made on different sources."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, help="folder for compare.txt (default: parent of the first run)")
    args = parser.parse_args()

    runs = [load_run(p) for p in args.runs]
    if len({r["source"] for r in runs}) > 1:
        print("runs were made on different sources", file=sys.stderr)
        return 1
    source = runs[0]["source"]
    width = max(len(r["name"]) for r in runs)

    head = "ok  attempts  cost_usd  edits  rooted  ungrounded  symbols  pronouns  modality  long  sentences"
    rows = [f"{'run':<{width}} {head}"]
    for r in runs:
        s, c = r["summary"], r["codes"]
        # Staged (resolve) runs count attempts per stage.
        s.setdefault("attempts", sum(st["attempts"] for st in s.get("stages", {}).values()))
        rooted = "-" if s.get("rooted_share") is None else f"{s['rooted_share']:.2f}"
        rows.append(
            f"{r['name']:<{width}} {'y' if s['ok'] else 'n':<3} {s['attempts']:<9} {s.get('cost_usd') or '-':<9} "
            f"{len(r['edits']):<6} {rooted:<7} {c['UNGROUNDED_WORD']:<11} {c['UNRESOLVED_SYMBOL']:<8} "
            f"{c['UNRESOLVED_PRONOUN']:<9} {c['MODALITY_CHANGED']:<9} {c['LONG_RESOLUTION']:<5} {s['sentences']}"
        )

    spans = groups(runs)
    diffs: list[str] = []
    for a, b in spans:
        rendered = [render(source, r["edits"], a, b) for r in runs]
        if len(set(rendered)) == 1:
            continue
        lines = [f"src {a}  {source[a:b]!r}"]
        lines += [f"  {r['name']:<{width}} : {text}" for r, text in zip(runs, rendered, strict=True)]
        diffs.append("\n".join(lines))
    rows.append(f"\nspans touched by any run: {len(spans)}; identical: {len(spans) - len(diffs)}; differ: {len(diffs)}")
    for r in runs[1:]:
        exact = f1(runs[0]["edits"], r["edits"], lambda e: (e.start, e.end, e.text))
        span = f1(runs[0]["edits"], r["edits"], lambda e: (e.start, e.end))
        rows.append(f"edit F1 {r['name']} vs {runs[0]['name']}: exact {exact:.2f}, span only {span:.2f}")

    report = "\n".join(rows) + "\n\n" + "\n\n".join(diffs) + "\n"
    out: Path = args.out or args.runs[0].parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.txt").write_text(report, encoding="utf-8", newline="\n")
    print("\n".join(rows))
    print(f"\nwritten: {out / 'compare.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
