"""Stage 1 in clean steps: rules, references (``referents.py``), ellipsis, assembled into edits by code.

The model never rewrites the document. Each model step answers with sentence ids plus exact words; code checks every
item, turns the good ones into ``Edit`` objects (so ``original() == source`` holds by construction) and sends the rest
back once with the reasons. An ellipsis insert is copied from the source and rendered with the rule and reference
edits that fall inside it, i.e. pronouns keep the referent they have where the words were copied from (strict
reading).
"""

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .annotated import AnnotatedText, _markers
from .edits import Edit, annotate
from .interpolation import Backend, Issue, extract_json
from .referents import ReferenceResult, run_references
from .rules import apply
from .staging import Doc, Span, find, locate, render_document, target

PROMPTS = Path(__file__).parent / "prompts"
STAGE_PROMPTS = {"references": PROMPTS / "references_v04.md", "ellipsis": PROMPTS / "ellipsis_v01.md"}
ELLIPSIS_KINDS = {"vp", "answer", "fragment"}
# Modality, hedge and polarity lemmas an elided VP must not import from its antecedent clause.
LEAKS = {
    "can", "could", "may", "might", "must", "shall", "should", "will", "would", "ought", "not", "no", "never",
    "likely", "unlikely", "probably", "possibly", "perhaps", "maybe",
}  # fmt: skip
PRIORITY = {"rules": 0, "references": 1, "ellipsis": 2}
STANDARDISATION = {"symbol", "abbreviation"}


@dataclass(frozen=True)
class Gap:
    """An accepted ellipsis item: insert ``source[copy]`` at ``at`` after ``prefix``."""

    at: int
    prefix: str
    copy: Span
    kind: str
    quote: Span


def check_ellipsis(doc: Doc, item: dict[str, Any]) -> Gap | str:
    """Return the gap for one ellipsis item, or why it is rejected."""
    kind, insert = item.get("kind"), item.get("insert")
    if kind not in ELLIPSIS_KINDS:
        return f"kind {kind!r} is not one of {sorted(ELLIPSIS_KINDS)}"
    found = target(doc, item, "remnant")
    if isinstance(found, str):
        return found
    s, _, remnant_end = found
    antecedent = item.get("antecedent")
    if not isinstance(antecedent, dict):
        return "antecedent must be an object with sid and quote"
    span = locate(doc, antecedent.get("sid"), antecedent.get("quote"))
    if isinstance(span, str):
        return span
    quote = doc.source[span[0] : span[1]]
    i = find(quote, insert) if isinstance(insert, str) else None
    if i is None:
        return f"insert {insert!r} is not one continuous span of the quote"
    copy = (span[0] + i, span[0] + i + len(insert))  # type: ignore[arg-type]
    if kind != "fragment":
        leaked = sorted(_markers(doc.source[copy[0] : copy[1]]) & LEAKS)
        if leaked:
            return f"insert carries the antecedent's modal, hedge or negation words {leaked}; copy only the verb onward"
        return Gap(remnant_end, " ", copy, kind, span)
    body = doc.source[s.src_start : s.src_end].rstrip()
    at = s.src_start + len(body) - (1 if body[-1:] in ".!" else 0)
    return Gap(at, ", ", copy, kind, span)


@dataclass
class StageResult:
    """Accepted items (with what they became), rejected items per attempt, and every raw response."""

    name: str
    accepted: list[tuple[dict[str, Any], Gap]] = field(default_factory=list)
    rejected: list[list[tuple[dict[str, Any], str]]] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)


def repair_prompt(document_prompt: str, rejected: Sequence[tuple[dict[str, Any], str]]) -> str:
    """Return a follow-up prompt with the rejected items and their reasons."""
    lines = "\n".join(f"- {json.dumps(i, ensure_ascii=False)}\n  rejected: {reason}" for i, reason in rejected)
    return (
        f"{document_prompt}\nThese items from your previous answer failed checks:\n{lines}\n\n"
        'Return {"items": [...]} with only the corrected items; leave out any item that cannot be fixed.'
    )


def run_ellipsis(doc: Doc, backend: Backend, prompt_path: Path, max_repairs: int = 1) -> StageResult:
    """Call the model for the ellipsis step, check every item and send rejected ones back up to ``max_repairs`` times.

    A repair item at a place already filled is the model's correction: it replaces the earlier one.
    """
    system_prompt = prompt_path.read_text(encoding="utf-8")
    user_prompt = prompt = render_document(doc)
    result = StageResult("ellipsis")
    for _ in range(max_repairs + 1):
        raw = backend.generate(system_prompt, prompt, {})
        result.raw_outputs.append(raw)
        rejected: list[tuple[dict[str, Any], str]] = []
        try:
            items = extract_json(raw).get("items", [])
        except ValueError as exc:
            items, rejected = [], [({"response": raw[:200]}, f"unparseable JSON: {exc}")]
        for item in items if isinstance(items, list) else []:
            outcome = check_ellipsis(doc, item) if isinstance(item, dict) else "item is not an object"
            if isinstance(outcome, str):
                rejected.append((item, outcome))
                continue
            result.accepted = [(i, g) for i, g in result.accepted if g.at != outcome.at]
            result.accepted.append((item, outcome))
        result.rejected.append(rejected)
        if not rejected:
            break
        prompt = repair_prompt(user_prompt, rejected)
    return result


@dataclass
class ResolveResult:
    """The assembled edits, the step results and the issues found while assembling and checking."""

    edits: list[Edit]
    references: ReferenceResult
    ellipsis: StageResult
    issues: list[Issue]
    text: AnnotatedText | None


def _merge(doc: Doc, candidates: list[tuple[str, Edit]], issues: list[Issue]) -> list[Edit]:
    """Keep edits in priority order (rules, references, ellipsis); drop any that overlap one already kept."""
    kept: list[Edit] = []
    for stage, e in sorted(candidates, key=lambda c: PRIORITY[c[0]]):
        clash = next(
            (
                k
                for k in kept
                if (e.start < k.end and k.start < e.end)
                or (e.start == e.end == k.start == k.end)
                or (e.start == e.end and k.start < e.start < k.end)
            ),
            None,
        )
        if clash is not None:
            message = f"{stage} edit {doc.source[e.start : e.end]!r} -> {e.text!r} overlaps {clash.text!r}"
            issues.append(Issue("warning", "EDIT_DROPPED_OVERLAP", f"src {e.start}", message))
            continue
        kept.append(e)
    return sorted(kept, key=lambda e: (e.start, e.end))


def resolve(
    source: str, backend: Backend, max_repairs: int = 1, workers: int = 2, prompts: dict[str, Path] | None = None
) -> ResolveResult:
    """Run the rules, then the reference and ellipsis steps in parallel, and assemble the edits."""
    doc = Doc.build(source)
    prompts = {**STAGE_PROMPTS, **(prompts or {})}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        refs_future = pool.submit(run_references, doc, backend, prompts["references"], max_repairs)
        gaps_future = pool.submit(run_ellipsis, doc, backend, prompts["ellipsis"], max_repairs)
        references, ellipsis = refs_future.result(), gaps_future.result()
    issues = [Issue("warning", "DEIXIS_AGREEMENT", None, w) for w in doc.rule_warnings]
    for name, rejected in (("REFERENCES", references.rejected), ("ELLIPSIS", ellipsis.rejected)):
        for item, reason in rejected[-1] if rejected else []:
            where = item.get("candidate") or item.get("id") or item.get("sid")
            issues.append(Issue("warning", f"{name}_REJECTED", str(where), reason))
    for c in references.undecided[-1] if references.undecided else []:
        issues.append(Issue("warning", "CANDIDATE_UNDECIDED", c.split()[0], c))

    rules = [("rules", e) for e in doc.rules]
    resolved_before = _merge(doc, rules + [("references", e) for e in references.edits], issues)
    gaps = []
    for _, gap in ellipsis.accepted:
        a, b = gap.copy
        text = gap.prefix + apply(source[a:b], resolved_before, base=a)
        gaps.append(("ellipsis", Edit(gap.at, gap.at, text, gap.kind, (gap.copy,))))
    edits = _merge(doc, [("rules", e) for e in resolved_before] + gaps, issues)
    text = annotate(source, edits)
    # Headings and questions are judged by the pipeline's own sentences (pysbd), not by the marked-text check's simpler
    # splitter; symbols and defined abbreviations are standardised there too, only resolutions may not go there.
    closed = [(s.src_start, s.src_end) for s in doc.sentences if not doc.editable(s)]
    for e in edits:
        if e.kind not in STANDARDISATION and any(a <= e.start < b for a, b in closed):
            message = f"{source[e.start : e.end]!r} -> {e.text!r}"
            issues.append(Issue("error", "MARK_IN_QUESTION_OR_HEADING", f"src {e.start}", message))
    issues += [i for i in text.issues(source) if i.code != "MARK_IN_QUESTION_OR_HEADING"]
    return ResolveResult(edits, references, ellipsis, issues, text)
