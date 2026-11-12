"""Stage 1 in steps: rules, then references (candidates, referent table, decisions) and ellipsis, assembled by code.

Writes, per document, to ``--out`` (one source; default ``outputs/resolve_<references version>/<doc>/<model>``) or to
``<--out-root>/<source file stem>`` (any number of sources):

    edits.jsonl     one record per edit: offsets, original, text, kind, pointers, referent id (references)
    run.json        summary (``source``: the sample's path relative to the run folder; model, prompts, counts, cost),
                    referent table, the reference decisions that are not links (leave / ambiguous), issues, rejected
                    items per step and attempt, usage
    raw.json        every raw model answer, per step and attempt (for ``--replay``)
    resolved.txt    the resolved text with every edit in [ ], for reading

Other views come from ``scripts/render_normalise.py``; ``scripts/agreement.py`` compares two runs step by step. With
several sources, ``summary.json`` in the output root lists every document's outcome; documents whose folder already
has a ``run.json`` are skipped unless ``--force``.

Usage::

    python scripts/run_resolve.py
    python scripts/run_resolve.py --model haiku
    python scripts/run_resolve.py --source pdfs/documents --out-root pdfs/normalized --workers 6
    python scripts/run_resolve.py --replay outputs/resolve_v04/<doc>/opus --out <dir>
"""

import argparse
import json
import sys
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from incolor.propositions.annotated import rooted_share
from incolor.propositions.document import load_body
from incolor.propositions.edits import render, run_report, source_ref, write_edits
from incolor.propositions.resolve import PROMPTS, STAGE_PROMPTS, resolve
from incolor.propositions.sentences import split_sentences

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "samples" / "BofA_Sept_FOMC_-_hike_or_bond_spike.txt"


class ReplayBackend:
    """Return saved raw responses in order, per step (recognised by its system prompt)."""

    def __init__(self, run_dir: Path, prompts: dict[str, Path]) -> None:
        raw_path = run_dir / "raw.json"
        if raw_path.exists():
            saved = json.loads(raw_path.read_text(encoding="utf-8"))
        else:  # runs made before raw.json: one raw_<step>_attempt<n>.txt per answer
            saved = {
                step: [p.read_text(encoding="utf-8") for p in sorted(run_dir.glob(f"raw_{step}_attempt*.txt"))]
                for step in prompts
            }
        self.replies = {path.read_text(encoding="utf-8"): list(saved.get(step, [])) for step, path in prompts.items()}
        report = run_report(run_dir)
        # The original calls' cost and model carry over, so a replay into the same folder loses nothing.
        self.usage: list[dict[str, Any]] = report.get("usage", [])
        self.model: str | None = report.get("summary", {}).get("model")

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the next saved response for this step, or an empty answer once they run out."""
        queue = self.replies.get(system_prompt, [])
        return queue.pop(0) if queue else '{"items": []}'


def write(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings."""
    path.write_text(text, encoding="utf-8", newline="\n")


def run_one(
    source: Path, out: Path, model: str, prompts: dict[str, Path], max_repairs: int, replay: Path | None
) -> dict:
    """Resolve one document and write its run folder; return the summary."""
    body, date = load_body(source)
    if replay:
        backend: Any = ReplayBackend(replay, prompts)
    else:
        from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

        backend = ClaudeAgentBackend(model=model)
    result = resolve(body, backend, max_repairs, prompts=prompts)
    refs, gaps = result.references, result.ellipsis

    out.mkdir(parents=True, exist_ok=True)
    write_edits(out / "edits.jsonl", body, result.edits)
    if result.text is not None:
        write(out / "resolved.txt", render(result.text, "brackets") + "\n")
    if not replay:
        raw = {"references": refs.raw_outputs, "ellipsis": gaps.raw_outputs}
        write(out / "raw.json", json.dumps(raw, indent=1, ensure_ascii=False) + "\n")

    errors = [i for i in result.issues if i.severity == "error"]
    decisions = list(refs.decisions.values())
    summary = {
        "ok": not errors,
        "source": source_ref(out, source),
        "model": backend.model if replay else model,
        "replayed": bool(replay),
        "prompts": {name: path.name for name, path in prompts.items()},
        "date": date,
        "stages": {
            "references": {
                "attempts": len(refs.raw_outputs),
                "candidates": len(refs.candidates),
                "referents": dict(Counter(r.type for r in refs.referents.values())),
                "decisions": dict(Counter(d.action for d in decisions if d.candidate)),
                "leave_reasons": dict(Counter(d.reason for d in decisions if d.action == "leave")),
                "extra": sum(d.candidate is None for d in decisions),
                "rejected_per_attempt": [len(r) for r in refs.rejected],
                "undecided_per_attempt": [len(u) for u in refs.undecided],
            },
            "ellipsis": {
                "attempts": len(gaps.raw_outputs),
                "accepted": len(gaps.accepted),
                "rejected_per_attempt": [len(r) for r in gaps.rejected],
            },
        },
        "edits": len(result.edits),
        "kinds": dict(Counter(e.kind for e in result.edits).most_common()),
        "rooted_share": None if result.text is None else rooted_share(result.text, body),
        "errors": len(errors),
        "warnings": dict(Counter(i.code for i in result.issues if i.severity == "warning")),
        "sentences": len(split_sentences(result.text)) if result.text is not None else 0,
        "cost_usd": round(sum(u.get("cost_usd") or 0 for u in backend.usage), 4) if backend.usage else None,
    }
    report = {
        "summary": summary,
        **refs.to_json(body),
        "issues": [asdict(i) for i in result.issues],
        "rejected": {
            name: [[{"item": item, "reason": reason} for item, reason in attempt] for attempt in attempts]
            for name, attempts in (("references", refs.rejected), ("ellipsis", gaps.rejected))
        },
        "usage": backend.usage,
    }
    write(out / "run.json", json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return summary


def main() -> int:
    """Run one or many documents; exit 2 if any document failed or has errors."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, nargs="+", default=[DEFAULT_SOURCE], help="files or folders of .txt")
    parser.add_argument("--out", type=Path, help="output folder for a single source")
    parser.add_argument("--out-root", type=Path, help="one folder per source, named after the file stem")
    parser.add_argument("--model", default="opus", help="Claude model alias")
    parser.add_argument("--references", default=STAGE_PROMPTS["references"].stem.split("_")[-1], help="prompt version")
    parser.add_argument("--ellipsis", default=STAGE_PROMPTS["ellipsis"].stem.split("_")[-1], help="prompt version")
    parser.add_argument("--max-repairs", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1, help="documents in parallel")
    parser.add_argument("--force", action="store_true", help="redo documents that already have a run.json")
    parser.add_argument("--replay", type=Path, help="run folder whose raw answers to re-check (single source)")
    args = parser.parse_args()

    sources = sorted(p for s in args.source for p in (s.glob("*.txt") if s.is_dir() else [s]))
    prompts = {stage: PROMPTS / f"{stage}_{getattr(args, stage)}.md" for stage in STAGE_PROMPTS}
    if len(sources) > 1 and not args.out_root:
        parser.error("several sources need --out-root")
    if args.replay and len(sources) > 1:
        parser.error("--replay takes a single source")

    def out_dir(source: Path) -> Path:
        if args.out_root:
            return args.out_root / source.stem
        doc_name = source.stem[:40].rstrip("_-")
        return args.out or ROOT / "outputs" / f"resolve_{args.references}" / doc_name / args.model

    todo = [s for s in sources if args.force or args.replay or not (out_dir(s) / "run.json").exists()]
    print(f"{len(sources)} sources, {len(sources) - len(todo)} already done, {len(todo)} to run", flush=True)

    def job(source: Path) -> dict:
        try:
            summary = run_one(source, out_dir(source), args.model, prompts, args.max_repairs, args.replay)
        except Exception as exc:  # one document's failure must not stop the batch
            traceback.print_exc()
            return {"document": source.stem, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"{'ok ' if summary['ok'] else 'ERR'} {source.stem[:70]}  edits={summary['edits']} "
              f"cost={summary['cost_usd']}", flush=True)  # fmt: skip
        return {"document": source.stem, **summary}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(job, todo))
    if len(sources) == 1:
        print(json.dumps(results[0] if results else {}, indent=2))
    else:
        done = {r["document"]: r for r in results}
        rows = []
        for s in sources:
            report_path = out_dir(s) / "run.json"
            if s.stem in done:
                rows.append(done[s.stem])
            elif report_path.exists():
                rows.append({"document": s.stem, **json.loads(report_path.read_text(encoding="utf-8"))["summary"]})
        totals = {
            "documents": len(sources),
            "ok": sum(bool(r.get("ok")) for r in rows),
            "failed": [r["document"] for r in rows if not r.get("ok")],
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 2),
        }
        write(args.out_root / "summary.json", json.dumps({"totals": totals, "documents": rows}, indent=1) + "\n")
        print(json.dumps(totals, indent=2))
    return 0 if all(r.get("ok") for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
