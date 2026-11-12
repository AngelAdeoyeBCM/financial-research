"""Contextual interpolation: make each segment readable on its own with bracketed, source-grounded edits.

The model returns, per target segment, the rewritten ``text`` and the ordered ``edits`` behind its brackets. Every
result is checked deterministically: undoing the edits must give back the segment text exactly, and every bracket
must be built from its pointer quotes plus closed-class function words.
"""

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

PROMPT_PATH = Path(__file__).parent / "prompts" / "interpolation_v01.md"
TARGET_CONTAINERS = {"paragraph", "list_item"}
EDIT_TYPES = {"reference", "author", "inflection", "condition", "label", "ellipsis"}
GLUE = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "with", "from", "and", "or", "if", "under",
    "scenario", "case", "is", "are", "was", "were", "be", "been", "being", "that", "which", "as", "than", "there",
    "where", "when",
}  # fmt: skip
AUTHOR_FORMS = {"we", "us", "our", "we're", "we’re", "we've", "we’ve", "we'd", "we’d", "we'll", "we’ll"}
AUTHOR_BRACKET = re.compile(r"[Tt]he Author(?:'s|’s| is| has| was| would| will)?")
INFLECTIONS = {"s", "es"}
TOKEN = re.compile(r"\w+(?:[’'.\-]\w+)*|[&%$+=/]")
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["segments"],
    "properties": {"segments": {"type": "array", "items": {"type": "object", "required": ["id", "text", "edits"]}}},
}


class Backend(Protocol):
    """Text-in, text-out model call (see ``incolor.argumentation.backends``)."""

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the raw model response."""
        ...


@dataclass(frozen=True)
class Issue:
    """One validation finding; ``error`` findings make the segment fall back to its source text."""

    severity: str
    code: str
    segment: str | None
    message: str


def is_target(segment: dict[str, Any]) -> bool:
    """Return True for propositional segments: paragraph or list text that is not a question."""
    return segment["container"] in TARGET_CONTAINERS and not segment["text"].rstrip().endswith("?")


def render_document(segments: Sequence[dict[str, Any]]) -> str:
    """Return the user prompt: the full segmented document followed by the target ids."""
    lines = [f"{s['id']} ({s['container']}) {s['text']}" for s in segments]
    targets = ", ".join(s["id"] for s in segments if is_target(s))
    return "DOCUMENT\n\n" + "\n".join(lines) + f"\n\nTARGETS\n\n{targets}\n"


def extract_json(raw: str) -> dict[str, Any]:
    """Parse the first JSON object in ``raw``, tolerating code fences and surrounding prose."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(raw[start : end + 1])


def undo(text: str, edits: Sequence[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Remove the brackets of ``edits`` from ``text`` in order; return ``(restored, None)`` or ``(None, problem)``."""
    out, cursor = text, 0
    for k, edit in enumerate(edits, start=1):
        token = f"[{edit.get('bracket', '')}]"
        i = out.find(token, cursor)
        if i < 0:
            return None, f"edit {k}: {token!r} not found after offset {cursor}"
        j = i + len(token)
        if edit.get("op") == "replace":
            original = edit.get("replaces") or ""
            out, cursor = out[:i] + original + out[j:], i + len(original)
            continue
        before, after = out[:i], out[j:]
        # An inserted bracket brought one separating space with it.
        if before.endswith(" ") and (not after or after[0] in " ,.;:!?)"):
            before = before[:-1]
        elif not before and after.startswith(" "):
            after = after[1:]
        out, cursor = before + after, len(before)
    return out, None


def _tokens(text: str) -> list[str]:
    return [re.sub(r"[’']s$", "", t) for t in TOKEN.findall(text.lower())]


def check_edit(edit: dict[str, Any], seg_id: str, position: dict[str, int], texts: dict[str, str]) -> list[Issue]:
    """Return the issues for one edit of segment ``seg_id``."""
    issues: list[Issue] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append(Issue(severity, code, seg_id, message))

    op, kind, bracket = edit.get("op"), edit.get("type"), edit.get("bracket") or ""
    if op not in {"insert", "replace"} or kind not in EDIT_TYPES:
        add("error", "BAD_EDIT", f"op={op!r} type={kind!r}")
        return issues
    if (op == "replace") != bool(edit.get("replaces")):
        add("error", "BAD_EDIT", f"{op} edit with replaces={edit.get('replaces')!r}")
    if "…" in bracket or "..." in bracket:
        add("error", "ELLIPSIS_BRACKET", f"[{bracket}]")
    if kind == "author":
        if (
            op != "replace"
            or (edit.get("replaces") or "").lower() not in AUTHOR_FORMS
            or not AUTHOR_BRACKET.fullmatch(bracket)
        ):
            add("error", "BAD_AUTHOR_EDIT", f"[{bracket}] replaces {edit.get('replaces')!r}")
        return issues
    if kind == "inflection":
        if op != "insert" or bracket not in INFLECTIONS:
            add("error", "BAD_INFLECTION", f"[{bracket}]")
        return issues

    pointers = edit.get("pointers") or []
    if not pointers:
        add("error", "NO_POINTER", f"{kind} edit [{bracket}] has no pointer")
        return issues
    quote_tokens: set[str] = set()
    for p in pointers:
        pid, quote = p.get("evidence_id"), p.get("quote") or ""
        if pid not in texts:
            add("error", "UNKNOWN_POINTER", f"{pid!r}")
            continue
        if quote not in texts[pid]:
            add("error", "POINTER_QUOTE_NOT_FOUND", f"{pid}: {quote!r}")
        if position[pid] > position[seg_id]:
            add("warning", "FORWARD_POINTER", f"{pid} follows {seg_id}")
        quote_tokens.update(_tokens(quote))
    leftover = [t for t in _tokens(bracket) if t not in quote_tokens and t not in GLUE]
    variants = [t for t in leftover if len(t) >= 4 and any(q[:4] == t[:4] for q in quote_tokens)]
    if variants:
        add("warning", "MORPHOLOGICAL_VARIANT", f"[{bracket}]: {variants}")
    ungrounded = [t for t in leftover if t not in variants]
    if ungrounded:
        add("error", "UNGROUNDED_BRACKET_WORDS", f"[{bracket}]: {ungrounded}")
    return issues


def validate(segments: Sequence[dict[str, Any]], results: Sequence[dict[str, Any]]) -> list[Issue]:
    """Check model results against the segments; see the module docstring for the rules."""
    texts = {s["id"]: s["text"] for s in segments}
    position = {s["id"]: i for i, s in enumerate(segments)}
    targets = [s["id"] for s in segments if is_target(s)]
    issues: list[Issue] = []
    counts = Counter(r.get("id") for r in results)
    for seg_id in targets:
        if counts[seg_id] == 0:
            issues.append(Issue("error", "MISSING_SEGMENT", seg_id, "target not returned"))
    for seg_id, n in counts.items():
        if seg_id not in targets:
            issues.append(Issue("error", "UNEXPECTED_SEGMENT", seg_id, "not a target"))
        elif n > 1:
            issues.append(Issue("error", "DUPLICATE_SEGMENT", seg_id, f"returned {n} times"))
    returned = [r.get("id") for r in results if r.get("id") in position]
    if returned != sorted(returned, key=position.__getitem__):
        issues.append(Issue("warning", "OUT_OF_ORDER", None, "segments not in document order"))

    for r in results:
        seg_id = r.get("id")
        if seg_id not in targets:
            continue
        text, edits = r.get("text") or "", r.get("edits") or []
        restored, problem = undo(text, edits)
        if problem:
            issues.append(Issue("error", "BRACKET_ORDER", seg_id, problem))
        elif restored != texts[seg_id]:
            issues.append(Issue("error", "UNDO_MISMATCH", seg_id, f"undo gives {restored!r}"))
        for edit in edits:
            issues.extend(check_edit(edit, seg_id, position, texts))
    return issues


def repair_prompt(document_prompt: str, previous: str, issues: Sequence[Issue]) -> str:
    """Return a follow-up user prompt asking the model to fix the listed errors."""
    errors = "\n".join(f"- {i.segment}: {i.code}: {i.message}" for i in issues if i.severity == "error")
    return (
        f"{document_prompt}\nYour previous answer:\n\n{previous}\n\n"
        f"It failed these checks:\n{errors}\n\n"
        "Return the complete corrected JSON for ALL target segments, following every rule in the instructions."
    )


@dataclass
class RunResult:
    """Validated interpolation results and the record of every attempt."""

    results: list[dict[str, Any]]
    issues: list[Issue]
    raw_outputs: list[str]


def interpolate(segments: Sequence[dict[str, Any]], backend: Backend, max_repairs: int = 1) -> RunResult:
    """Call the model, validate, and retry with the errors up to ``max_repairs`` times; keep the best attempt."""
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = render_document(segments)
    raw_outputs: list[str] = []
    best: tuple[list[dict[str, Any]], list[Issue]] | None = None
    prompt = user_prompt
    for _ in range(max_repairs + 1):
        raw = backend.generate(system_prompt, prompt, JSON_SCHEMA)
        raw_outputs.append(raw)
        try:
            results = extract_json(raw)["segments"]
        except (ValueError, KeyError, TypeError) as exc:
            results, issues = [], [Issue("error", "UNPARSEABLE_RESPONSE", None, str(exc))]
        else:
            issues = validate(segments, results)
        n_errors = sum(i.severity == "error" for i in issues)
        if best is None or n_errors < sum(i.severity == "error" for i in best[1]):
            best = (results, issues)
        if n_errors == 0:
            break
        prompt = repair_prompt(user_prompt, raw, issues)
    assert best is not None
    return RunResult(best[0], best[1], raw_outputs)


def accepted(segments: Sequence[dict[str, Any]], run: RunResult) -> dict[str, dict[str, Any]]:
    """Return ``{id: result}`` for target segments whose result has no error; others fall back to the source text."""
    failed = {i.segment for i in run.issues if i.severity == "error"}
    by_id = {r.get("id"): r for r in run.results}
    out = {}
    for s in segments:
        if not is_target(s):
            continue
        r = by_id.get(s["id"])
        ok = r is not None and s["id"] not in failed
        out[s["id"]] = {
            "id": s["id"],
            "source": s["text"],
            "text": r["text"] if ok else s["text"],
            "edits": r.get("edits", []) if ok else [],
            "accepted": ok,
        }
    return out


def render_txt(source: str, segments: Sequence[dict[str, Any]], rows: dict[str, dict[str, Any]]) -> str:
    """Return the readable document: one line per segment ending in its evidence id, source paragraph breaks kept."""
    prefix = {"heading": "## ", "run_in_heading": "### ", "list_item": "- "}
    lines: list[str] = []
    prev_end = None
    for s in segments:
        if prev_end is not None and source.count("\n", prev_end, s["start"]) >= 2:
            lines.append("")
        text = rows[s["id"]]["text"] if s["id"] in rows else s["text"]
        lines.append(f"{prefix.get(s['container'], '')}{text} [{s['id']}]")
        prev_end = s["end"]
    return "\n".join(lines) + "\n"


def summary(segments: Sequence[dict[str, Any]], rows: dict[str, dict[str, Any]], run: RunResult) -> dict[str, Any]:
    """Return the validation report written to ``interpolation_validation.json``."""
    edits = [e for r in rows.values() for e in r["edits"]]
    return {
        "summary": {
            "segments": len(segments),
            "targets": len(rows),
            "accepted": sum(r["accepted"] for r in rows.values()),
            "changed": sum(r["text"] != r["source"] for r in rows.values()),
            "edits": len(edits),
            "edit_types": dict(Counter(e.get("type") for e in edits)),
            "uncertain_edits": sum(bool(e.get("uncertain")) for e in edits),
            "errors": sum(i.severity == "error" for i in run.issues),
            "warnings": sum(i.severity == "warning" for i in run.issues),
            "attempts": len(run.raw_outputs),
        },
        "issues": [asdict(i) for i in run.issues],
        "uncertain": [
            {"id": r["id"], "bracket": e.get("bracket"), "type": e.get("type"), "pointers": e.get("pointers")}
            for r in rows.values()
            for e in r["edits"]
            if e.get("uncertain")
        ],
        "rejected": [r["id"] for r in rows.values() if not r["accepted"]],
    }
