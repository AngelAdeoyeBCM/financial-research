"""Stage 1 normalisation: resolve references inline as ``{{original => resolution}}`` and store them as edits.

Reads a markdown sample (YAML front matter is dropped, line endings become LF), rewrites the whole body in one call
(``--sections`` rewrites heading-delimited sections in parallel, each seeing the whole body), retries while checks
fail and writes to ``--out`` (default ``outputs/normalise_<prompt version>/<model>``):

    edits.jsonl                 one record per edit: offsets, original, text, kind, pointers   (only if valid)
    validation.json             summary (``source``: the sample's path relative to the run folder), issues, cost
    raw_attempt<n>.txt          raw model output per attempt (sectioned mode: the combined marked text)
    sections/s<k>_attempt<n>.txt raw model output per section and attempt (sectioned mode)

The edits index the sample's body (``incolor.propositions.document.load_body``). Marked, bracketed and plain text
and the tagged sentences are derived from the sample + ``edits.jsonl``; see ``scripts/render_normalise.py``.

Usage::

    python scripts/run_normalise.py
    python scripts/run_normalise.py --model haiku
    python scripts/run_normalise.py --prompt v19 --out outputs/normalise_v19
    python scripts/run_normalise.py --replay outputs/normalise_v19/opus/raw_attempt1.txt --out <dir>
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from incolor.propositions.annotated import LOG_SEPARATOR, rooted_share
from incolor.propositions.document import load_body
from incolor.propositions.edits import Edit, annotate, edits_from_annotated, source_ref, write_edits
from incolor.propositions.normalise import PROMPT_PATH, best_of, normalise, normalise_sections
from incolor.propositions.sentences import split_sentences

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "samples" / "BofA_Sept_FOMC_-_hike_or_bond_spike.txt"
PROMPTS = PROMPT_PATH.parent


def write(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings."""
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    """Run normalisation and sentence tagging; exit 2 if no attempt passed validation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, help="output folder (default outputs/normalise_<prompt>/<model>)")
    parser.add_argument("--model", default="opus", help="Claude model alias")
    parser.add_argument("--prompt", default="v20", help="prompt version: prompts/normalise_<version>.md")
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--sections", action="store_true", help="rewrite sections in parallel instead of one call")
    parser.add_argument("--workers", type=int, default=6, help="parallel section calls (with --sections)")
    parser.add_argument("--review", action="store_true", help="one extra self-review call (not with --sections)")
    parser.add_argument("--replay", type=Path, nargs="+", help="saved raw responses to re-validate (no model call)")
    args = parser.parse_args()
    if args.review and args.sections:
        parser.error("--review cannot be combined with --sections")

    prompt_path = PROMPTS / f"normalise_{args.prompt}.md"
    run_name = f"{args.model}_review" if args.review else args.model
    out: Path = args.out or ROOT / "outputs" / f"normalise_{args.prompt}" / run_name
    body, date = load_body(args.source)
    usage: list[dict[str, Any]] = []
    if args.replay:
        with_log = LOG_SEPARATOR in prompt_path.read_text(encoding="utf-8")
        result = best_of(body, [p.read_text(encoding="utf-8") for p in args.replay], with_log)
    else:
        from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

        backend = ClaudeAgentBackend(model=args.model)
        if args.sections:
            result = normalise_sections(body, backend, args.max_repairs, prompt_path, workers=args.workers)
        else:
            result = normalise(body, backend, args.max_repairs, prompt_path, review=args.review)
        usage = backend.usage

    out.mkdir(parents=True, exist_ok=True)
    if not args.replay:
        for n, raw in enumerate(result.raw_outputs, start=1):
            write(out / f"raw_attempt{n}.txt", raw)
        for k, raws in enumerate(result.section_raws, start=1):
            (out / "sections").mkdir(exist_ok=True)
            for n, raw in enumerate(raws, start=1):
                write(out / "sections" / f"s{k:02d}_attempt{n}.txt", raw)

    edits: list[Edit] = []
    sentences = []
    if result.ok and result.text is not None:
        edits = edits_from_annotated(result.text, body)
        write_edits(out / "edits.jsonl", body, edits)
        sentences = split_sentences(annotate(body, edits))

    log = (result.text.log if result.text is not None else None) or {}
    summary = {
        "ok": result.ok,
        "source": source_ref(out, args.source),
        "model": None if args.replay else args.model,
        "prompt": None if args.replay else prompt_path.name,
        "date": date,
        "attempts": sum(map(len, result.section_raws)) or len(result.raw_outputs),
        "section_attempts": [len(r) for r in result.section_raws],
        "review_adopted": result.reviewed,
        "edits": len(edits),
        "kinds": dict(Counter(e.kind for e in edits if e.kind)),
        "unresolved": len(log.get("unresolved") or []),
        "rooted_share": None if result.text is None else rooted_share(result.text, body),
        "errors": sum(i.severity == "error" for i in result.issues),
        "warnings": dict(Counter(i.code for i in result.issues if i.severity == "warning")),
        "sentences": len(sentences),
        "splits_mark": [s.id for s in sentences if s.splits_mark],
        "cost_usd": round(sum(u.get("cost_usd") or 0 for u in usage), 4) if usage else None,
    }
    report = {"summary": summary, "issues": [asdict(i) for i in result.issues], "usage": usage}
    write(out / "validation.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
