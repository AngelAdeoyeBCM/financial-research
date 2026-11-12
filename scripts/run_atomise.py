"""Stage 2: split Stage 1 sentences into atomic propositions and record the logic inside each sentence.

Tags the sentences of a normalise run (its sample + ``edits.jsonl``), drops headings and questions, calls Claude
once on the rest (plus
repair attempts on errors) and writes to ``--out`` (default ``outputs/atomise_<prompt version>/<model>``):

    input.txt               the user prompt sent to the model
    system_prompt.md        the system prompt, with the taxonomy filled in
    atoms.jsonl             one record per atom: id, sentence_id (E###), text, claim_type, modality, role, subkinds
    structure.jsonl         one record per sentence: topic, facts, formula, relations, open_connectives
    atoms.txt               each sentence followed by its atoms and structure, for reading
    validation.json         summary, issues, cost
    raw_attempt<n>.txt      raw model output per attempt

Usage::

    python scripts/run_atomise.py
    python scripts/run_atomise.py --model haiku
    python scripts/run_atomise.py --replay outputs/atomise_v05/opus/raw_attempt1.txt --out <dir>
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from incolor.propositions.atomise import (
    PROMPT_PATH,
    TAXONOMY_PATH,
    Atom,
    SentenceLogic,
    atomise,
    best_of,
    load_prompt,
    prompt_id,
    render_user_prompt,
    select_targets,
)
from incolor.propositions.edits import sentences as normalised_sentences

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NORMALISED = ROOT / "outputs" / "normalise_v20" / "opus"
PROMPTS = PROMPT_PATH.parent


def write(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings."""
    path.write_text(text, encoding="utf-8", newline="\n")


def render_txt(targets: list[dict[str, Any]], atoms: list[Atom], logic: list[SentenceLogic]) -> str:
    """Return each target sentence followed by its topic, atoms, formula, relations and open connectives."""
    by_sentence: dict[str, list[Atom]] = {}
    for a in atoms:
        by_sentence.setdefault(a.sentence_id, []).append(a)
    logic_by_id = {s.id: s for s in logic}
    m_width = max((len(a.modality) for a in atoms), default=0)
    r_width = max((len(a.role) for a in atoms), default=0)
    c_width = max((len(a.claim_type) for a in atoms), default=0)
    blocks = []
    for s in targets:
        lines = [f"[{prompt_id(s['id'])}] {s['text']}"]
        info = logic_by_id.get(s["id"])
        if info and info.topic:
            lines.append(f"    topic    {info.topic}")
        lines += [
            f"    {a.id:<8} {a.role:<{r_width}}  {a.claim_type:<{c_width}}  {a.modality:<{m_width}}  {a.text}"
            + (f"  [{', '.join(a.subkinds)}]" if a.subkinds else "")
            for a in by_sentence.get(s["id"], [])
        ]
        if info and info.formula:
            lines.append(f"    formula  {info.formula}")
        for r in info.relations if info else []:
            sources = " + ".join(r["from"]) if isinstance(r.get("from"), list) else r.get("from")
            flag = "  [ambiguous]" if r.get("ambiguous") else ""
            lines.append(f"    {r.get('type', ''):<8} {sources} -> {r.get('to')}  ({r.get('marker')}){flag}")
        if info and info.open_connectives:
            lines.append(f"    open     {', '.join(info.open_connectives)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def main() -> int:
    """Run atomisation; exit 2 if no attempt passed validation."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--normalised", type=Path, default=DEFAULT_NORMALISED, help="normalise run folder")
    parser.add_argument("--out", type=Path, help="output folder (default outputs/atomise_<prompt>/<model>)")
    parser.add_argument("--model", default="opus", help="Claude model alias")
    parser.add_argument("--prompt", default="v05", help="prompt version: prompts/atomise_<version>.md")
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH, help="taxonomy filled into {{taxonomy}}")
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--replay", type=Path, nargs="+", help="saved raw responses to re-validate (no model call)")
    args = parser.parse_args()

    prompt_path = PROMPTS / f"atomise_{args.prompt}.md"
    system_prompt, labels = load_prompt(prompt_path, args.taxonomy)
    out: Path = args.out or ROOT / "outputs" / f"atomise_{args.prompt}" / args.model
    sentences = [asdict(s) for s in normalised_sentences(args.normalised)]
    targets = select_targets(sentences)
    usage: list[dict[str, Any]] = []
    if args.replay:
        result = best_of(targets, [p.read_text(encoding="utf-8") for p in args.replay], labels)
    else:
        from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

        backend = ClaudeAgentBackend(model=args.model)
        result = atomise(
            targets, backend, max_repairs=args.max_repairs, prompt_path=prompt_path, taxonomy_path=args.taxonomy
        )
        usage = backend.usage

    out.mkdir(parents=True, exist_ok=True)
    write(out / "input.txt", render_user_prompt(targets))
    write(out / "system_prompt.md", system_prompt)
    if not args.replay:
        for n, raw in enumerate(result.raw_outputs, start=1):
            write(out / f"raw_attempt{n}.txt", raw)
    write(out / "atoms.jsonl", "".join(json.dumps(asdict(a), ensure_ascii=False) + "\n" for a in result.atoms))
    write(out / "structure.jsonl", "".join(json.dumps(asdict(s), ensure_ascii=False) + "\n" for s in result.sentences))
    write(out / "atoms.txt", render_txt(targets, result.atoms, result.sentences))
    relations = [r for s in result.sentences for r in s.relations if isinstance(r, dict)]

    summary = {
        "ok": result.ok,
        "normalised": args.normalised.as_posix(),
        "model": None if args.replay else args.model,
        "prompt": None if args.replay else prompt_path.name,
        "taxonomy": args.taxonomy.name,
        "attempts": len(result.raw_outputs),
        "sentences": len(sentences),
        "targets": len(targets),
        "atoms": len(result.atoms),
        "atoms_per_sentence": round(len(result.atoms) / len(targets), 2) if targets else 0,
        "claim_type": dict(Counter(a.claim_type for a in result.atoms).most_common()),
        "subkinds": dict(Counter(f"{a.claim_type}:{s}" for a in result.atoms for s in a.subkinds).most_common()),
        "modality": dict(Counter(a.modality for a in result.atoms).most_common()),
        "role": dict(Counter(a.role for a in result.atoms).most_common()),
        "formulas": sum(bool(s.formula) for s in result.sentences),
        "relations": dict(Counter(r.get("type") for r in relations).most_common()),
        "topics": sum(bool(s.topic) for s in result.sentences),
        "open_connectives": sum(len(s.open_connectives) for s in result.sentences),
        "errors": sum(i.severity == "error" for i in result.issues),
        "warnings": dict(Counter(i.code for i in result.issues if i.severity == "warning")),
        "cost_usd": round(sum(u.get("cost_usd") or 0 for u in usage), 4) if usage else None,
    }
    report = {"summary": summary, "issues": [asdict(i) for i in result.issues], "usage": usage}
    write(out / "validation.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
