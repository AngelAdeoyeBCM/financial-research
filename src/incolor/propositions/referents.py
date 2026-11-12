"""Stage 1 references: code lists candidates, the model names referents and decides them, code renders the text.

1. Candidates (code): personal pronouns, this/these/those, standalone "that" and "If right"/"If wrong" in editable
   sentences, outside quotes, rule edits, figure labels and time expressions ("this week"). Each needs a decision.
2. Referents and decisions (model, one call): ``referents`` are what the document refers back to, each named once (a
   thing by its most informative name built from a quote, a claim by a full clause quoted verbatim); ``decisions``
   link each candidate to a referent (widening it to a noun phrase if needed), leave it with a reason, or mark it
   ambiguous between referents; ``extra`` adds references code cannot find (the move, the revisions).
3. Render (code): every resolution is written from its referent, so all references to one referent read the same: the
   name (possessive for his/its/their), "that" + clause, noun + connective + clause, or "If the author is right that"
   + clause. Pronouns inside a claim's clause are rendered with their own links.

Rejected items and undecided candidates go back to the model, with the referent table accepted so far.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .annotated import _markers
from .edits import Edit
from .interpolation import Backend, extract_json
from .rules import QUOTED, apply, normalise_copy
from .staging import Doc, Span, find, locate, render_document, target, words

PERSONAL = re.compile(r"\b(?:he|him|his|she|her|hers|it|its|they|them|their|theirs)\b", re.IGNORECASE)
DEMONSTRATIVE = re.compile(r"\b(?:this|these|those)\b", re.IGNORECASE)
# "that" counts only when it stands alone: followed by a verb or modal, or by punctuation.
STANDALONE_THAT = re.compile(
    r"\bthat\b(?=\s+(?:is|was|would|will|should|could|may|might|can|has|had|seems?|means?|implies|suggests|"
    r"remains?)\b|\s*[.,;:)])",
    re.IGNORECASE,
)
VERDICT = re.compile(r"\bIf (right|wrong)\b")
TIME_NOUNS = {
    "week", "weeks", "year", "years", "month", "months", "quarter", "quarters", "morning", "afternoon", "evening",
    "time", "summer", "winter", "spring", "autumn", "fall", "weekend", "decade",
}  # fmt: skip
POSSESSIVES = {"his", "her", "hers", "its", "their", "theirs"}
DEMONSTRATIVES = {"this", "that", "these", "those"}
TYPES = {"thing", "claim"}
LEAVE_REASONS = {"expletive", "relative", "generic", "time", "not_a_reference"}
CONNECTIVES = {"that", "to", "of"}
NAME_GLUE = words("the a an of")
LEADING_DETERMINER = re.compile(r"^(?:The|A|An|This|That|These|Those)\b")


@dataclass(frozen=True)
class Candidate:
    """A word code found that may refer back: its id, sentence and source span."""

    id: str
    sid: str
    start: int
    end: int
    token: str


@dataclass(frozen=True)
class Referent:
    """Something the document refers back to: a thing (``name``) or a claim (the clause quoted at ``span``)."""

    id: str
    type: str
    span: Span
    name: str


@dataclass(frozen=True)
class Decision:
    """What happens to one candidate (or extra phrase): link, leave or ambiguous; ``start``/``end`` span the phrase."""

    key: str
    start: int
    end: int
    action: str
    referent: str | None = None
    reason: str | None = None
    alternatives: tuple[str, ...] = ()
    connective: str = "that"
    candidate: str | None = None


@dataclass
class ReferenceResult:
    """The candidates, accepted referents and decisions, rejections and undecided candidates per attempt, raw output."""

    candidates: list[Candidate]
    referents: dict[str, Referent] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    rejected: list[list[tuple[dict[str, Any], str]]] = field(default_factory=list)
    undecided: list[list[str]] = field(default_factory=list)
    raw_outputs: list[str] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)

    def to_json(self, source: str) -> dict[str, Any]:
        """Return what ``run.json`` keeps of this step: the referent table and the decisions that are not links.

        Links are the reference edits in ``edits.jsonl`` (each with its referent id); candidates are recomputed from
        the source by ``find_candidates``.
        """
        return {
            "referents": [
                {
                    "id": r.id,
                    "type": r.type,
                    "start": r.span[0],
                    "end": r.span[1],
                    "quote": source[slice(*r.span)],
                    "name": r.name,
                }
                for r in self.referents.values()
            ],
            "decisions": [
                {
                    "candidate": d.candidate,
                    "phrase": source[d.start : d.end],
                    "action": d.action,
                    "reason": d.reason,
                    "referents": list(d.alternatives),
                }
                for d in sorted(self.decisions.values(), key=lambda d: d.start)
                if d.action != "link"
            ],
        }


def find_candidates(doc: Doc) -> list[Candidate]:
    """Return every word in an editable sentence that may refer back, in document order."""
    rules = [(e.start, e.end) for e in doc.rules]
    found: list[tuple[int, int, str]] = []
    for s in doc.sentences:
        if not doc.editable(s):
            continue
        quoted = [(s.src_start + a, s.src_start + b) for a, b in (m.span() for m in QUOTED.finditer(s.source))]
        blocked = quoted + rules + doc.figure_spans(s)
        hits = []
        for pattern in (VERDICT, PERSONAL, DEMONSTRATIVE, STANDALONE_THAT):
            for m in pattern.finditer(s.source):
                after = s.source[m.end() :].split(maxsplit=1)
                if pattern is DEMONSTRATIVE and after and after[0].lower().strip(".,;:") in TIME_NOUNS:
                    continue
                hits.append((s.src_start + m.start(), s.src_start + m.end(), s.id))
        for a, b, sid in sorted(hits):
            overlaps = any(x < b and a < y for x, y in blocked) or any(x < b and a < y for x, y, _ in found)
            if not overlaps:
                found.append((a, b, sid))
    return [Candidate(f"C{k:03d}", sid, a, b, doc.source[a:b]) for k, (a, b, sid) in enumerate(found, start=1)]


def render_candidates(doc: Doc, candidates: list[Candidate]) -> str:
    """Return the candidate list shown after the document: ``C### E### word: ...context «word» context...``."""
    lines = []
    for c in candidates:
        s = doc.sentence(c.sid)
        assert s is not None
        a, b = c.start - s.src_start, c.end - s.src_start
        lines.append(f"{c.id} {c.sid} {c.token}: …{s.source[max(0, a - 50) : a]}«{c.token}»{s.source[b : b + 50]}…")
    return "Candidates:\n\n" + "\n".join(lines) + "\n"


def check_referent(doc: Doc, item: dict[str, Any]) -> Referent | str:
    """Return the referent for one table row, or why it is rejected."""
    rid, kind = item.get("id"), item.get("type")
    if not isinstance(rid, str) or not rid:
        return "id is missing"
    if kind not in TYPES:
        return f"type {kind!r} is not one of {sorted(TYPES)}"
    span = locate(doc, item.get("sid"), item.get("quote"))
    if isinstance(span, str):
        return span
    quote = doc.source[slice(*span)]
    if kind == "claim":
        clause = quote.strip().rstrip(".;:,")
        if len(clause.split()) < 3:
            return f"claim {quote!r} is not a full clause with its own subject and verb"
        return Referent(rid, kind, span, clause)
    name = item.get("name") or quote
    if not isinstance(name, str):
        return "name must be a string"
    extra = sorted(words(name) - words(quote) - NAME_GLUE)
    if extra:
        return f"name {name!r} has words not in the quote: {extra}"
    if _markers(name) - _markers(quote):
        return f"name {name!r} adds modal, hedge or negation words"
    return Referent(rid, kind, span, name)


def check_decision(
    doc: Doc, item: dict[str, Any], candidates: dict[str, Candidate], referents: dict[str, Referent]
) -> Decision | str:
    """Return the decision for one candidate, or why it is rejected."""
    c = candidates.get(item.get("candidate"))  # type: ignore[arg-type]
    if c is None:
        return f"candidate {item.get('candidate')!r} is not in the list"
    action = item.get("action")
    if action == "leave":
        reason = item.get("reason")
        if reason not in LEAVE_REASONS:
            return f"reason {reason!r} is not one of {sorted(LEAVE_REASONS)}"
        return Decision(c.id, c.start, c.end, "leave", reason=reason, candidate=c.id)
    if action == "ambiguous":
        alternatives = item.get("referents")
        if not isinstance(alternatives, list) or len(set(alternatives)) < 2:
            return "ambiguous needs two or more referents"
        unknown = [r for r in alternatives if r not in referents]
        if unknown:
            return f"unknown referents {unknown}"
        return Decision(c.id, c.start, c.end, "ambiguous", alternatives=tuple(alternatives), candidate=c.id)
    if action != "link":
        return f"action {action!r} is not link, leave or ambiguous"
    phrase = item.get("phrase") or c.token
    s = doc.sentence(c.sid)
    assert s is not None
    if not isinstance(phrase, str) or find(doc.source[c.start : s.src_end], phrase) != 0:
        return f"phrase {phrase!r} must start with the candidate {c.token!r} where it stands in {c.sid}"
    return _link(doc, item, c.id, c.start, c.start + len(phrase), referents, c.id)


def check_extra(
    doc: Doc, item: dict[str, Any], candidates: dict[str, Candidate], referents: dict[str, Referent]
) -> Decision | str:
    """Return the decision for one extra phrase (the move, the revisions), or why it is rejected."""
    found = target(doc, item, "phrase")
    if isinstance(found, str):
        return found
    s, start, end = found
    clash = next((c for c in candidates.values() if c.start < end and start < c.end), None)
    if clash is not None:
        return f"{clash.token!r} is candidate {clash.id}; decide it there"
    if any(a < end and start < b for a, b in doc.figure_spans(s) + [(e.start, e.end) for e in doc.rules]):
        return "exhibit, figure, chart and table labels (and rule edits) are not references"
    return _link(doc, item, f"X{start}", start, end, referents, None)


def _link(
    doc: Doc,
    item: dict[str, Any],
    key: str,
    start: int,
    end: int,
    referents: dict[str, Referent],
    candidate: str | None,
) -> Decision | str:
    r = referents.get(item.get("referent"))  # type: ignore[arg-type]
    if r is None:
        return f"referent {item.get('referent')!r} is not in the referent table"
    phrase = doc.source[start:end]
    first = phrase.split()[0].lower()
    if VERDICT.fullmatch(phrase) and r.type != "claim":
        return "If right / If wrong must link to a claim"
    if first in POSSESSIVES and len(phrase.split()) == 1 and r.type != "thing":
        return f"{phrase!r} is possessive; it must link to a thing"
    connective = item.get("connective", "that")
    if connective not in CONNECTIVES:
        return f"connective {connective!r} is not one of {sorted(CONNECTIVES)}"
    return Decision(key, start, end, "link", referent=r.id, connective=connective, candidate=candidate)


def _possessive(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def _case(text: str, phrase: str) -> str:
    """Capitalise like the phrase; a leading determiner of the text is lower-cased mid-sentence."""
    if phrase[:1].isupper():
        return text[0].upper() + text[1:]
    return text[0].lower() + text[1:] if LEADING_DETERMINER.match(text) else text


def clause(doc: Doc, r: Referent, edits: list[Edit]) -> str:
    """Return a claim's clause with the rule and link edits inside it applied, ready to follow "that"."""
    text = apply(doc.source[slice(*r.span)], [*doc.rules, *edits], base=r.span[0]).strip().rstrip(".;:,")
    return text[0].lower() + text[1:] if LEADING_DETERMINER.match(text) else text


def render(doc: Doc, d: Decision, r: Referent, clause_text: str | None) -> Edit:
    """Return the edit for one link: the phrase replaced by text written from its referent."""
    phrase = doc.source[d.start : d.end]
    tokens = phrase.split()
    first = tokens[0].lower()

    def edit(text: str, kind: str) -> Edit:
        return Edit(d.start, d.end, text, kind, (r.span,), referent=r.id)

    verdict = VERDICT.fullmatch(phrase)
    if verdict:
        return edit(f"{tokens[0]} the author is {verdict.group(1)} that {clause_text}", "verdict")
    if r.type == "thing":
        name = normalise_copy(r.name, doc.defined)
        if len(tokens) == 1 and first in POSSESSIVES:
            return edit(_case(_possessive(name), phrase), "possessive")
        kind = "pronoun" if PERSONAL.fullmatch(phrase) else "demonstrative" if len(tokens) == 1 else "noun_phrase"
        return edit(_case(name, phrase), kind)
    if len(tokens) == 1:
        return edit(_case(f"that {clause_text}", phrase), "proposition")
    head = " ".join(["the", *tokens[1:]]) if first in DEMONSTRATIVES else phrase
    return edit(_case(f"{head} {d.connective} {clause_text}", phrase), "shell")


def render_all(doc: Doc, referents: dict[str, Referent], decisions: dict[str, Decision]) -> list[Edit]:
    """Render every link: links to things first, then claims, whose clauses carry the thing links inside them."""
    links = [d for d in decisions.values() if d.action == "link" and d.referent in referents]
    things = [render(doc, d, referents[d.referent], None) for d in links if referents[d.referent].type == "thing"]  # type: ignore[index]
    clauses = {rid: clause(doc, r, things) for rid, r in referents.items() if r.type == "claim"}
    claims = [
        render(doc, d, referents[d.referent], clauses[d.referent])  # type: ignore[index]
        for d in links
        if referents[d.referent].type == "claim"  # type: ignore[index]
    ]
    # A phrase linked to a referent named by that same phrase changes nothing; it is not an edit.
    return sorted((e for e in things + claims if e.text != doc.source[e.start : e.end]), key=lambda e: e.start)


def repair_prompt(
    user_prompt: str, result: ReferenceResult, rejected: list[tuple[dict[str, Any], str]], undecided: list[str]
) -> str:
    """Return the follow-up prompt: the accepted referent table, the rejected items and the undecided candidates."""
    table = "\n".join(
        f"{r.id} {r.type}: {r.name}" for r in result.referents.values()
    )  # names of claims are their clauses
    parts = [user_prompt, f"Referent table accepted so far:\n{table}\n"]
    if rejected:
        lines = "\n".join(f"- {json.dumps(i, ensure_ascii=False)}\n  rejected: {why}" for i, why in rejected)
        parts.append(f"These items from your previous answer failed checks:\n{lines}\n")
    if undecided:
        lines = "\n".join(f"- {c}" for c in undecided)
        parts.append(f"These candidates have no decision yet; decide each one:\n{lines}\n")
    parts.append(
        'Return {"referents": [...], "decisions": [...], "extra": [...]} with only corrected and new items; '
        "new referents may use new ids, and decisions may link to any referent in the table above."
    )
    return "\n".join(parts)


def run_references(doc: Doc, backend: Backend, prompt_path: Path, max_repairs: int = 1) -> ReferenceResult:
    """Run the references step: candidates, model decisions with repairs, then rendered edits."""
    system_prompt = prompt_path.read_text(encoding="utf-8")
    result = ReferenceResult(find_candidates(doc))
    by_id = {c.id: c for c in result.candidates}
    user_prompt = prompt = render_document(doc) + "\n" + render_candidates(doc, result.candidates)
    for _ in range(max_repairs + 1):
        raw = backend.generate(system_prompt, prompt, {})
        result.raw_outputs.append(raw)
        rejected: list[tuple[dict[str, Any], str]] = []
        try:
            answer = extract_json(raw)
        except ValueError as exc:
            answer, rejected = {}, [({"response": raw[:200]}, f"unparseable JSON: {exc}")]
        for item in _items(answer, "referents"):
            outcome = check_referent(doc, item)
            if isinstance(outcome, str):
                rejected.append((item, outcome))
            else:
                result.referents[outcome.id] = outcome
        for key, check in (("decisions", check_decision), ("extra", check_extra)):
            for item in _items(answer, key):
                outcome = check(doc, item, by_id, result.referents)
                if isinstance(outcome, str):
                    rejected.append((item, outcome))
                else:
                    result.decisions[outcome.key] = outcome
        undecided = [f"{c.id} {c.sid} {c.token}" for c in result.candidates if c.id not in result.decisions]
        result.rejected.append(rejected)
        result.undecided.append(undecided)
        if not rejected and not undecided:
            break
        prompt = repair_prompt(user_prompt, result, rejected, undecided)
    result.edits = render_all(doc, result.referents, result.decisions)
    return result


def _items(answer: Any, key: str) -> list[dict[str, Any]]:
    items = answer.get(key, []) if isinstance(answer, dict) else []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
