"""Stage 1 contextual interpolation: rewrite each propositional segment so it is readable on its own.

Reads ``segments.jsonl`` (from ``scripts/segment_source.py``) and the source document, calls Claude once with the
whole document (plus repair attempts if the deterministic checks fail) and writes to ``--out``:

    interpolated.txt                one line per segment ending in ``[E###]``; failed segments keep source text
    interpolation.jsonl             id, source, text, edits, accepted (target segments only)
    interpolation_validation.json   summary, issues, uncertain edits, rejected segments
    raw_response_attempt<n>.txt     raw model output per attempt

``--replay`` re-validates saved raw responses without calling the model.

Usage::

    python scripts/interpolate_context.py
    python scripts/interpolate_context.py --model sonnet
    python scripts/interpolate_context.py --replay outputs/framing_v02/raw_response_attempt1.txt
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from incolor.propositions.interpolation import (
    RunResult,
    accepted,
    extract_json,
    interpolate,
    render_txt,
    summary,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "outputs" / "framing_v02"
DEFAULT_SOURCE = ROOT / "samples" / "BofA_Sept_FOMC_-_hike_or_bond_spike.txt"


def load_inputs(segments_path: Path, source_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Load segments and source, and check every segment's offsets against the source."""
    segments = [json.loads(line) for line in segments_path.read_text(encoding="utf-8").splitlines() if line]
    with source_path.open(encoding="utf-8-sig", newline="") as f:
        source = f.read()
    bad = [s["id"] for s in segments if source[s["start"] : s["end"]] != s["text"]]
    if bad:
        raise SystemExit(f"segments do not match {source_path.name} at {bad[:5]}; re-run scripts/segment_source.py")
    return segments, source


def replay(segments: list[dict[str, Any]], raw_paths: list[Path]) -> RunResult:
    """Validate saved raw responses and keep the one with the fewest errors."""
    best: RunResult | None = None
    for path in raw_paths:
        raw = path.read_text(encoding="utf-8")
        results = extract_json(raw)["segments"]
        run = RunResult(results, validate(segments, results), [raw])
        if best is None or sum(i.severity == "error" for i in run.issues) < sum(
            i.severity == "error" for i in best.issues
        ):
            best = run
    assert best is not None
    return best


def main() -> int:
    """Run interpolation and write the outputs; exit 2 if any target segment was rejected."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--segments", type=Path, default=DEFAULT_OUT / "segments.jsonl")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default="opus", help="Claude model alias")
    parser.add_argument("--max-repairs", type=int, default=1)
    parser.add_argument("--replay", type=Path, nargs="+", help="saved raw responses to re-validate (no model call)")
    args = parser.parse_args()

    segments, source = load_inputs(args.segments, args.source)
    usage: list[dict[str, Any]] = []
    if args.replay:
        run = replay(segments, args.replay)
    else:
        from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

        backend = ClaudeAgentBackend(model=args.model)
        run = interpolate(segments, backend, max_repairs=args.max_repairs)
        usage = backend.usage

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.replay:
        for n, raw in enumerate(run.raw_outputs, start=1):
            (args.out / f"raw_response_attempt{n}.txt").write_text(raw, encoding="utf-8")
    rows = accepted(segments, run)
    with (args.out / "interpolation.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in rows.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.out / "interpolated.txt").write_text(render_txt(source, segments, rows), encoding="utf-8")
    report = summary(segments, rows, run)
    report["summary"]["model"] = None if args.replay else args.model
    report["summary"]["cost_usd"] = round(sum(u.get("cost_usd") or 0 for u in usage), 4) if usage else None
    (args.out / "interpolation_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], indent=2))
    return 2 if report["rejected"] else 0


if __name__ == "__main__":
    sys.exit(main())
