"""Stage 2: atomise tagged sentences and record the logic inside each sentence.

Per sentence the model returns atoms ``{id, text, claim_type, subkinds, modality}``, ``facts`` (atoms stated
outright), a prefix ``formula`` over the other atoms (IF / AND / OR / NOT), ``relations`` (causal, temporal, contrast,
attribution), a scenario ``topic`` and ``open_connectives`` that point to other sentences. Atom text keeps the
source's modal words. A prompt containing ``{{taxonomy}}`` inherits the claim types, subkinds and modalities of the
argument-map taxonomy, plus EVIDENCE for atoms that only report data or facts; older prompts use ``LEGACY_LABELS``.
Code parses the formula and derives each atom's ``role``; antecedents must be typed SUPPOSITION. Sentences are shown
as ``[P###]`` (Stage 1 ids ``E###`` with the letter swapped); atom ids are ``P###-n``. One call covers the whole
document; on errors the model gets its answer plus the issues and tries again.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from incolor.argumentation.taxonomy import PACKAGE_DIR as TAXONOMY_DIR
from incolor.argumentation.taxonomy import Taxonomy, load_taxonomy

from .annotated import PRONOUN
from .interpolation import Backend, Issue, extract_json

PROMPT_PATH = Path(__file__).parent / "prompts" / "atomise_v05.md"
TAXONOMY_PATH = TAXONOMY_DIR / "prompts" / "taxonomy_v12.yaml"
TAXONOMY_SLOT = "{{taxonomy}}"
SUPPOSITION = "SUPPOSITION"
EVIDENCE = "EVIDENCE"
HYPOTHETICAL = "HYPOTHETICAL"
ROLES = ("statement", "antecedent", "consequent")
RELATION_TYPES = ("causal", "temporal", "contrast", "attribution")
OPERATORS: dict[str, tuple[int, int | None]] = {"IF": (2, 2), "AND": (2, None), "OR": (2, None), "NOT": (1, 1)}
ATOM_ID = re.compile(r"P(\d{3,})-(\d+)")
FORMULA_TOKEN = re.compile(r"\s*(?:([A-Z]+)\s*\(|(P\d{3,}-\d+)|(\))|(,))")
HEDGE = re.compile(
    r"\b(?:may|might|could|can|will|would|should|must|likely|unlikely|probably|possibly|perhaps|maybe|"
    r"expects?|thinks?|guess(?:es)?|believes?)\b",
    re.IGNORECASE,
)
STRICT_CONNECTIVE = re.compile(
    r"\b(?:if|unless|because|although|though|whereas|therefore|due to|owing to|thanks to|as a result of)\b",
    re.IGNORECASE,
)
SOFT_CONNECTIVE = re.compile(r"\b(?:while|but|since|so|after|before|despite|which)\b|;", re.IGNORECASE)
LEXICAL_CHECKS = (
    ("error", "CONNECTIVE_IN_ATOM", STRICT_CONNECTIVE),
    ("warning", "SOFT_CONNECTIVE_IN_ATOM", SOFT_CONNECTIVE),
    ("warning", "PRONOUN_IN_ATOM", PRONOUN),
)
CONDITIONAL_MARKERS = ("only if", "if", "unless", "assuming", "provided", "in the event of")
LINK_MARKERS = (
    "because", "since", "due to", "owing to", "thanks to", "as a result", "therefore", "hence", "so", "after",
    "before", "although", "though", "while", "whereas", "despite", "but", "however", "implying",
)  # fmt: skip

Formula = str | tuple[str, tuple["Formula", ...]]


class FormulaError(ValueError):
    """The formula does not parse or an operator has the wrong number of operands."""


@dataclass(frozen=True)
class SubkindSpec:
    """The subkinds a claim type accepts."""

    values: tuple[str, ...]
    multiple: bool
    required: bool


@dataclass(frozen=True)
class Labels:
    """The claim types and modalities the validator accepts, with per-type subkinds and fixed modalities."""

    claim_types: tuple[str, ...]
    modalities: tuple[str, ...]
    subkinds: dict[str, SubkindSpec] = field(default_factory=dict)
    fixed_modality: dict[str, str] = field(default_factory=dict)


# Labels of atomise_v02-v04, before the prompt inherited the taxonomy.
LEGACY_LABELS = Labels(
    ("SUPPOSITION", "RECOMMENDATION", "FORECAST", "PREDICTION", "OBSERVATION", "VIEW"),
    ("ASSERTED", "HEDGED", "SPECULATIVE"),
)


@dataclass(frozen=True)
class Atom:
    """One atomic proposition; ``sentence_id`` is the Stage 1 id (``E###``); ``role`` comes from the formula."""

    id: str
    sentence_id: str
    text: str
    claim_type: str
    modality: str
    role: str
    subkinds: tuple[str, ...] = ()


@dataclass
class SentenceLogic:
    """The intra-sentence structure of one sentence; ``id`` is the Stage 1 id (``E###``)."""

    id: str
    topic: str | None
    facts: list[str]
    formula: str | None
    relations: list[dict[str, Any]]
    open_connectives: list[str]


@dataclass
class AtomiseResult:
    """Best attempt (fewest errors), its issues and every raw response."""

    atoms: list[Atom]
    sentences: list[SentenceLogic]
    issues: list[Issue]
    raw_outputs: list[str]

    @property
    def ok(self) -> bool:
        """Return True if the best attempt has no errors."""
        return bool(self.raw_outputs) and not _errors(self.issues)


def _errors(issues: Sequence[Issue]) -> int:
    return sum(i.severity == "error" for i in issues)


def labels_from_taxonomy(taxonomy: Taxonomy) -> Labels:
    """Return the taxonomy's claim types, subkinds and fixed modalities, plus EVIDENCE (no subkinds)."""
    subkinds = {}
    for name, spec in taxonomy.claim_types.items():
        sub = spec.get("subkinds")
        if sub:
            values = tuple(taxonomy.subkinds[sub["set"]]["values"])
            subkinds[name] = SubkindSpec(values, bool(sub.get("multiple")), bool(sub.get("required")))
    fixed = {name: spec["fixed_modality"] for name, spec in taxonomy.claim_types.items() if spec.get("fixed_modality")}
    return Labels((*taxonomy.claim_types, EVIDENCE), tuple(taxonomy.modalities), subkinds, fixed)


@cache
def default_labels() -> Labels:
    """Return the labels of the default taxonomy."""
    return labels_from_taxonomy(load_taxonomy(TAXONOMY_PATH))


def _bullets(title: str, items: Sequence[str] | None) -> list[str]:
    return [f"{title}:", *(f"- {item}" for item in items), ""] if items else []


def render_taxonomy(taxonomy: Taxonomy) -> str:
    """Return the taxonomy's claim types, decision order, subkinds and modalities as prompt markdown."""
    lines = ["## Claim types", ""]
    for name, spec in taxonomy.claim_types.items():
        lines += [f"### {name}", "", spec["definition"], ""]
        lines += _bullets("Include", spec.get("include")) + _bullets("Exclude", spec.get("exclude"))
        sub = spec.get("subkinds")
        if sub:
            multiple = bool(sub.get("multiple"))
            if sub.get("required"):
                count = "one or more" if multiple else "exactly one"
            else:
                count = "any number" if multiple else "at most one"
            lines += [f"Subkinds: {count} from `{sub['set']}`.", ""]
        if spec.get("fixed_modality"):
            lines += [f"Modality: always {spec['fixed_modality']}.", ""]
    lines += ["## Claim type decision order", "", "The first matching test decides.", ""]
    lines += [f"{n}. {step['type']}: {step['test']}" for n, step in enumerate(taxonomy.type_decision_order, 1)]
    lines += ["", "## Subkinds", ""]
    for name, spec in taxonomy.subkinds.items():
        lines += [f"### `{name}`", "", spec["description"], ""]
        for value, v in spec["values"].items():
            lines.append(f"- `{value}`: {v['definition']}")
            lines += [f"  - Include: {item}" for item in v.get("include") or []]
            lines += [f"  - Exclude: {item}" for item in v.get("exclude") or []]
        if spec.get("decision_order"):
            lines += ["", "The first matching test decides:", ""]
            lines += [f"{n}. `{s['value']}`: {s['test']}" for n, s in enumerate(spec["decision_order"], 1)]
        lines.append("")
    lines += ["## Modality", ""]
    for name, spec in taxonomy.modalities.items():
        lines += [f"### {name}", "", spec["definition"], ""]
        lines += [f"- {group}: {', '.join(cues)}" for group, cues in (spec.get("cues") or {}).items()]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_prompt(prompt_path: Path = PROMPT_PATH, taxonomy_path: Path = TAXONOMY_PATH) -> tuple[str, Labels]:
    """Return the system prompt with the taxonomy filled in, and the labels to validate against."""
    text = prompt_path.read_text(encoding="utf-8")
    if TAXONOMY_SLOT not in text:
        return text, LEGACY_LABELS
    taxonomy = load_taxonomy(taxonomy_path)
    return text.replace(TAXONOMY_SLOT, render_taxonomy(taxonomy).rstrip()), labels_from_taxonomy(taxonomy)


def prompt_id(sentence_id: str) -> str:
    """Return the ``P###`` tag shown to the model for a Stage 1 sentence id (``E005`` -> ``P005``)."""
    return "P" + sentence_id[1:]


def select_targets(sentences: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the sentences to atomise: everything except headings and questions."""
    return [s for s in sentences if s["kind"] != "heading" and not s["text"].rstrip().endswith("?")]


def render_user_prompt(targets: Sequence[dict[str, Any]]) -> str:
    """Return the user prompt: one ``[P###] text`` line per target sentence."""
    return "Input:\n" + "".join(f"[{prompt_id(s['id'])}] {s['text']}\n" for s in targets)


def repair_prompt(user_prompt: str, previous: str, issues: Sequence[Issue]) -> str:
    """Return a follow-up prompt with the previous answer and the errors it must fix."""
    errors = "\n".join(f"- {i.code} ({i.segment or 'document'}): {i.message}" for i in issues if i.severity == "error")
    return (
        f"{user_prompt}\nYour previous answer:\n\n{previous}\n\n"
        f"It failed these checks:\n{errors}\n\n"
        "Return the complete corrected JSON, following every rule in the instructions."
    )


def parse_formula(text: str) -> Formula:
    """Parse a prefix formula such as ``IF(NOT(P007-1), P007-2)``; raise ``FormulaError`` on bad syntax or arity."""
    pos = 0

    def node() -> Formula:
        nonlocal pos
        match = FORMULA_TOKEN.match(text, pos)
        if not match or not (match.group(1) or match.group(2)):
            raise FormulaError(f"expected an operator or atom id at {pos}: {text[pos : pos + 20]!r}")
        pos = match.end()
        if match.group(2):
            return match.group(2)
        op = match.group(1)
        if op not in OPERATORS:
            raise FormulaError(f"unknown operator {op!r}")
        args = [node()]
        while True:
            match = FORMULA_TOKEN.match(text, pos)
            if not match or not (match.group(3) or match.group(4)):
                raise FormulaError(f"expected ',' or ')' at {pos} in {op}(...)")
            pos = match.end()
            if match.group(3):
                break
            args.append(node())
        low, high = OPERATORS[op]
        if len(args) < low or (high is not None and len(args) > high):
            raise FormulaError(f"{op} takes {low}{'' if high == low else '+'} operands, got {len(args)}")
        return op, tuple(args)

    tree = node()
    if text[pos:].strip():
        raise FormulaError(f"unexpected text after formula: {text[pos:]!r}")
    return tree


def formula_roles(tree: Formula, role: str | None = None, out: dict[str, str] | None = None) -> dict[str, str]:
    """Return ``{atom_id: role}`` for the leaves of ``tree``: antecedent, consequent, or statement outside any IF."""
    out = {} if out is None else out
    if isinstance(tree, str):
        out.setdefault(tree, role or "statement")
        return out
    op, args = tree
    if op == "IF":
        formula_roles(args[0], "antecedent", out)
        formula_roles(args[1], "consequent", out)
    else:
        for arg in args:
            formula_roles(arg, role, out)
    return out


def unconsumed_connectives(
    text: str, formula: str | None, relations: Sequence[dict[str, Any]], opens: Sequence[str]
) -> list[str]:
    """Return connective words in ``text`` that no formula, relation marker or open connective accounts for."""
    lowered = text.lower()
    used = " | ".join([str(r.get("marker") or "").lower() for r in relations] + [o.lower() for o in opens])
    has_if = bool(formula and "IF(" in formula)
    missing = []
    for marker in CONDITIONAL_MARKERS + LINK_MARKERS:
        if not re.search(rf"\b{marker}\b", lowered) or marker in used:
            continue
        if marker in CONDITIONAL_MARKERS and has_if:
            continue
        missing.append(marker)
    return missing


def _str_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def _check_subkinds(item: dict[str, Any], claim_type: str, labels: Labels) -> tuple[tuple[str, ...], list[str]]:
    """Return the atom's subkinds and the problems with them."""
    raw = item.get("subkinds") or []
    if not isinstance(raw, list):
        return (), [f"subkinds must be a list, got {raw!r}"]
    subkinds = tuple(dict.fromkeys(str(v).lower() for v in raw))
    spec = labels.subkinds.get(claim_type)
    if spec is None:
        return subkinds, [f"{claim_type} takes no subkinds, got {list(subkinds)}"] if subkinds else []
    problems = []
    unknown = [v for v in subkinds if v not in spec.values]
    if unknown:
        problems.append(f"{unknown} not in {claim_type} subkinds {list(spec.values)}")
    if spec.required and not subkinds:
        problems.append(f"{claim_type} needs a subkind from {list(spec.values)}")
    if not spec.multiple and len(subkinds) > 1:
        problems.append(f"{claim_type} takes one subkind, got {list(subkinds)}")
    return subkinds, problems


def _check_sentence(
    tag: str, sentence: dict[str, Any], entry: dict[str, Any], labels: Labels
) -> tuple[list[Atom], SentenceLogic, list[Issue]]:
    issues: list[Issue] = []

    def add(severity: str, code: str, message: str, segment: str = tag) -> None:
        issues.append(Issue(severity, code, segment, message))

    items = entry.get("atoms")
    if not isinstance(items, list):
        add("error", "BAD_ENTRY", "'atoms' must be a list")
        items = []
    parsed: list[tuple[str, str, str, str, tuple[str, ...]]] = []
    known: set[str] = set()
    numbers: list[int] = []
    for item in items:
        atom_id = str(item.get("id", "")) if isinstance(item, dict) else ""
        match = ATOM_ID.fullmatch(atom_id)
        if not match or f"P{match.group(1)}" != tag:
            add("error", "BAD_ID", f"expected {tag}-n, got {item!r}")
            continue
        known.add(atom_id)
        numbers.append(int(match.group(2)))
        text = str(item.get("text") or "").strip()
        claim_type = str(item.get("claim_type") or "").upper()
        modality = str(item.get("modality") or "").upper()
        if not text:
            add("error", "EMPTY_TEXT", "atom has no text", atom_id)
            continue
        if claim_type not in labels.claim_types:
            add("error", "BAD_CLAIM_TYPE", f"{item.get('claim_type')!r}", atom_id)
            continue
        if modality not in labels.modalities:
            add("error", "BAD_MODALITY", f"{item.get('modality')!r}", atom_id)
            continue
        fixed = labels.fixed_modality.get(claim_type)
        if fixed and modality != fixed:
            add("error", "MODALITY_MISMATCH", f"{claim_type} is always {fixed}, got {modality}", atom_id)
        elif modality == HYPOTHETICAL and claim_type != SUPPOSITION:
            add("error", "MODALITY_MISMATCH", f"{HYPOTHETICAL} is only for {SUPPOSITION}, got {claim_type}", atom_id)
        subkinds, problems = _check_subkinds(item, claim_type, labels)
        for problem in problems:
            add("error", "BAD_SUBKIND", problem, atom_id)
        for severity, code, pattern in LEXICAL_CHECKS:
            found = sorted({m.group(0).lower() for m in pattern.finditer(text)})
            if found:
                add(severity, code, f"{found}: {text}", atom_id)
        parsed.append((atom_id, text, claim_type, modality, subkinds))
    if numbers != list(range(1, len(numbers) + 1)):
        add("error", "BAD_NUMBERING", f"atom numbers {numbers}, expected 1..{len(numbers)}")

    facts = _str_list(entry.get("facts"))
    if facts is None:
        add("error", "BAD_ENTRY", "'facts' must be a list of atom ids")
        facts = []
    for atom_id in facts:
        if atom_id not in known:
            add("error", "UNKNOWN_ATOM", f"fact {atom_id!r} is not an atom of {tag}")

    formula = entry.get("formula") or None
    roles: dict[str, str] = {}
    parsed_ok = True
    if formula is not None and not isinstance(formula, str):
        add("error", "FORMULA_PARSE", f"formula must be a string or null, got {formula!r}")
        formula, parsed_ok = None, False
    if formula:
        try:
            roles = formula_roles(parse_formula(formula))
        except FormulaError as exc:
            add("error", "FORMULA_PARSE", f"{exc}: {formula}")
            parsed_ok = False
        for atom_id in sorted(set(roles) - known):
            add("error", "UNKNOWN_ATOM", f"formula uses {atom_id!r}, not an atom of {tag}")
    for atom_id in facts:
        if atom_id in roles:
            add("error", "ATOM_DOUBLE_USED", f"{atom_id} is in both facts and formula", atom_id)
        roles[atom_id] = "statement"
    if parsed_ok:
        for atom_id in sorted(known - set(roles)):
            add("error", "ATOM_UNUSED", "atom is in neither facts nor formula", atom_id)

    relations = entry.get("relations") or []
    if not isinstance(relations, list):
        add("error", "BAD_ENTRY", "'relations' must be a list")
        relations = []
    for r in relations:
        if not isinstance(r, dict) or r.get("type") not in RELATION_TYPES:
            add("error", "BAD_RELATION", f"unknown relation type: {r!r}")
            continue
        sources = r.get("from") if isinstance(r.get("from"), list) else [r.get("from")]
        for atom_id in [*sources, r.get("to")]:
            if atom_id not in known:
                add("error", "BAD_RELATION", f"{r['type']} relation uses {atom_id!r}, not an atom of {tag}")
        if not str(r.get("marker") or "").strip():
            add("error", "BAD_RELATION", f"{r['type']} relation has no marker")

    opens = _str_list(entry.get("open_connectives"))
    if opens is None:
        add("error", "BAD_ENTRY", "'open_connectives' must be a list of strings")
        opens = []
    topic = entry.get("topic") or None
    if topic is not None and (not isinstance(topic, str) or topic.lower() not in sentence["text"].lower()):
        add("warning", "TOPIC_NOT_IN_SENTENCE", f"{topic!r}")
        topic = str(topic)
    missing = unconsumed_connectives(sentence["text"], formula, relations, opens)
    if missing:
        add("warning", "UNCONSUMED_CONNECTIVE", f"{missing}")
    duplicates = [t for t, n in Counter(p[1].lower() for p in parsed).items() if n > 1]
    for text in duplicates:
        add("warning", "DUPLICATE_ATOM", text)
    for atom_id, _, claim_type, _, _ in parsed:
        if (roles.get(atom_id) == "antecedent") != (claim_type == SUPPOSITION):
            add("error", "SUPPOSITION_MISMATCH", f"role {roles.get(atom_id)}, claim_type {claim_type}", atom_id)
    in_atoms = {m.group(0).lower() for p in parsed for m in HEDGE.finditer(p[1])}
    dropped = sorted({m.group(0).lower() for m in HEDGE.finditer(sentence["text"])} - in_atoms)
    if parsed and dropped:
        add("warning", "MODALITY_DROPPED", f"{dropped} in the sentence but in no atom")

    atoms = [
        Atom(atom_id, sentence["id"], text, claim_type, modality, roles.get(atom_id, "unused"), subkinds)
        for atom_id, text, claim_type, modality, subkinds in parsed
    ]
    logic = SentenceLogic(sentence["id"], topic, facts, formula, relations, opens)
    return atoms, logic, issues


def check(
    targets: Sequence[dict[str, Any]], raw: str, labels: Labels | None = None
) -> tuple[list[Atom], list[SentenceLogic], list[Issue]]:
    """Parse one raw response and return its atoms, per-sentence logic and issues; ``labels`` default to v0.12."""
    labels = labels or default_labels()
    try:
        data = extract_json(raw)
    except ValueError as exc:
        return [], [], [Issue("error", "UNPARSEABLE_RESPONSE", None, str(exc))]

    by_tag = {prompt_id(s["id"]): s for s in targets}
    atoms: list[Atom] = []
    logic: list[SentenceLogic] = []
    issues: list[Issue] = []
    for tag, entry in data.items():
        if tag not in by_tag:
            issues.append(Issue("error", "UNKNOWN_SENTENCE", tag, "not an input sentence"))
            continue
        if not isinstance(entry, dict):
            issues.append(Issue("error", "BAD_ENTRY", tag, "entry must be an object"))
            continue
        sentence_atoms, sentence_logic, sentence_issues = _check_sentence(tag, by_tag[tag], entry, labels)
        atoms += sentence_atoms
        logic.append(sentence_logic)
        issues += sentence_issues
    returned = [t for t in data if t in by_tag]
    if returned != [t for t in by_tag if t in data]:
        issues.append(Issue("warning", "OUT_OF_ORDER", None, "sentences not in input order"))
    issues += [Issue("warning", "NO_ENTRY", t, "sentence not returned") for t in by_tag if t not in data]
    return atoms, logic, issues


def best_of(
    targets: Sequence[dict[str, Any]], raw_outputs: Sequence[str], labels: Labels | None = None
) -> AtomiseResult:
    """Re-validate saved responses and keep the one with the fewest errors, then fewest warnings."""
    best: tuple[list[Atom], list[SentenceLogic], list[Issue]] | None = None
    for raw in raw_outputs:
        result = check(targets, raw, labels)
        if best is None or (_errors(result[2]), len(result[2])) < (_errors(best[2]), len(best[2])):
            best = result
    if best is None:
        return AtomiseResult([], [], [Issue("error", "NO_RESPONSE", None, "no responses")], list(raw_outputs))
    return AtomiseResult(*best, list(raw_outputs))


def atomise(
    targets: Sequence[dict[str, Any]],
    backend: Backend,
    max_repairs: int = 2,
    prompt_path: Path = PROMPT_PATH,
    taxonomy_path: Path = TAXONOMY_PATH,
) -> AtomiseResult:
    """Atomise ``targets`` in one call, retrying with the error list up to ``max_repairs`` times."""
    system_prompt, labels = load_prompt(prompt_path, taxonomy_path)
    user_prompt = prompt = render_user_prompt(targets)
    raw_outputs: list[str] = []
    for _ in range(max_repairs + 1):
        raw = backend.generate(system_prompt, prompt, {})
        raw_outputs.append(raw)
        _, _, issues = check(targets, raw, labels)
        if not _errors(issues):
            break
        prompt = repair_prompt(user_prompt, raw, issues)
    return best_of(targets, raw_outputs, labels)
