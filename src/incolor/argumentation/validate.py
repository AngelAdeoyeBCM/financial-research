"""Semantic checks for argument maps: verbatim spans, taxonomy membership, roles and graph structure."""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from .grounding import coverage
from .schema import Argument, ArgumentMap, Evidence, Exclusion, ModelOutput, Scenario, Statement
from .taxonomy import CORE_ROLES, Taxonomy

Severity = Literal["error", "warning"]
MAX_BRIEF_WORDS = 10
_SUMMARY_CITATION = re.compile(r"\bS\d{3}\b")
_ARGUMENT_ID = re.compile(r"A\d{3}")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "from", "is", "are", "was",
    "were", "be", "been", "will", "would", "could", "may", "might", "should", "that", "this", "these", "those", "it",
    "its", "as", "than", "more", "less", "into", "over", "under", "after", "before", "also", "has", "have", "had",
    "not", "no", "can",
})  # fmt: skip
_SCENARIO_MEMBER_FIELDS = ("assumptions", "implications", "recommendations")
# Scenario field -> taxonomy key listing its allowed values.
_SCENARIO_VALUE_FIELDS = {"role": "roles", "outcome_orientation": "outcome_orientations", "purpose": "purposes"}
# Scenario slot -> taxonomy keys (current name first) listing the claim types it may hold.
_SCENARIO_SLOT_TYPES = {"assumptions": ("assumption_types",), "implications": ("implication_types", "outcome_types")}
ARGUMENT_ROLES: tuple[str, ...] = tuple(
    name for name in Argument.model_fields if name not in {"id", "summary", "conclusion"}
)


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found in an argument map, with a stable code and a concrete fix."""

    code: str
    severity: Severity
    path: str
    message: str
    suggested_action: str


@dataclass(frozen=True)
class _Ref:
    """A reference inside an argument (statement, scenario or argument ID), with the JSONPath of the reference."""

    argument_index: int
    role: str
    statement_id: str
    path: str


@dataclass(frozen=True)
class _Context:
    """Lookup tables shared by every check. ``source`` is whitespace-squashed."""

    source: str
    taxonomy: Taxonomy
    evidence: list[Evidence]
    statements: list[Statement]
    arguments: list[Argument]
    exclusions: list[Exclusion]
    scenarios: list[Scenario]
    evidence_by_id: dict[str, Evidence]
    statement_by_id: dict[str, Statement]
    scenario_by_id: dict[str, Scenario]
    argument_by_id: dict[str, Argument]
    edges: list[tuple[str, str, str]]
    map_: ArgumentMap | ModelOutput


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    """Return True if any issue has error severity."""
    return any(issue.severity == "error" for issue in issues)


def is_scenario_ref(ref: str) -> bool:
    """Return True if an argument-role entry is a scenario ID rather than a statement ID."""
    return ref.startswith("SC")


def is_argument_ref(ref: str) -> bool:
    """Return True if an argument-role entry is an argument ID (v0.12)."""
    return _ARGUMENT_ID.fullmatch(ref) is not None


def argument_edges(
    map_: ArgumentMap | ModelOutput, roles: Sequence[str] = ARGUMENT_ROLES
) -> list[tuple[str, str, str]]:
    """Return ``(source_argument, role, target_argument)`` for each argument referenced in another argument's role.

    An argument is referenced either by its ID or by its conclusion's statement ID.
    """
    return _edges_from(map_.arguments, roles)


def scenario_edges(
    map_: ArgumentMap | ModelOutput, roles: Sequence[str] = ARGUMENT_ROLES
) -> list[tuple[str, str, str]]:
    """Return ``(scenario, role, target_argument)`` for each scenario referenced in an argument's role."""
    return [
        (ref, role, argument.id)
        for argument in map_.arguments
        for role in roles
        for ref in getattr(argument, role)
        if is_scenario_ref(ref)
    ]


def validate(map_: ArgumentMap | ModelOutput, source_text: str, taxonomy: Taxonomy) -> list[ValidationIssue]:
    """Run every registered check and return all issues, errors and warnings alike.

    Args:
        map_: The map to check.
        source_text: The normalised source text that evidence and exclusions must match.
        taxonomy: The taxonomy that defines claim types, modalities and roles.
    """
    ctx = _build_context(map_, _squash(source_text), taxonomy)
    issues: list[ValidationIssue] = []
    for check in CHECKS:
        issues.extend(check(ctx))
    return issues


def _squash(text: str) -> str:
    """Collapse whitespace runs and strip the ends; the only normalisation applied to span matching."""
    return " ".join(text.split())


def _edges_from(arguments: Sequence[Argument], roles: Sequence[str]) -> list[tuple[str, str, str]]:
    owner: dict[str, str] = {}
    for argument in arguments:
        owner.setdefault(argument.conclusion, argument.id)
    ids = {argument.id for argument in arguments}
    edges: list[tuple[str, str, str]] = []
    for argument in arguments:
        for role in roles:
            for ref in getattr(argument, role):
                source = ref if ref in ids else owner.get(ref)
                if source is not None and source != argument.id:
                    edges.append((source, role, argument.id))
    return edges


def _build_context(map_: ArgumentMap | ModelOutput, source: str, taxonomy: Taxonomy) -> _Context:
    evidence_by_id: dict[str, Evidence] = {}
    for item in map_.evidence:
        evidence_by_id.setdefault(item.id, item)
    statement_by_id: dict[str, Statement] = {}
    for statement in map_.statements:
        statement_by_id.setdefault(statement.id, statement)
    scenario_by_id: dict[str, Scenario] = {}
    for scenario in map_.scenarios:
        scenario_by_id.setdefault(scenario.id, scenario)
    argument_by_id: dict[str, Argument] = {}
    for argument in map_.arguments:
        argument_by_id.setdefault(argument.id, argument)
    return _Context(
        source=source,
        taxonomy=taxonomy,
        evidence=list(map_.evidence),
        statements=list(map_.statements),
        arguments=list(map_.arguments),
        exclusions=list(map_.exclusions),
        scenarios=list(map_.scenarios),
        evidence_by_id=evidence_by_id,
        statement_by_id=statement_by_id,
        scenario_by_id=scenario_by_id,
        argument_by_id=argument_by_id,
        edges=_edges_from(map_.arguments, taxonomy.argument_roles),
        map_=map_,
    )


def _iter_refs(ctx: _Context) -> Iterator[_Ref]:
    """Yield every reference in every argument, conclusion first."""
    core = ctx.taxonomy.core_role
    for i, argument in enumerate(ctx.arguments):
        yield _Ref(i, core, argument.conclusion, f"$.arguments[{i}].{core}")
        for role in ctx.taxonomy.argument_roles:
            for j, statement_id in enumerate(getattr(argument, role)):
                yield _Ref(i, role, statement_id, f"$.arguments[{i}].{role}[{j}]")


def _members(ctx: _Context, argument: Argument) -> set[str]:
    ids = {argument.conclusion}
    for role in ctx.taxonomy.argument_roles:
        ids.update(getattr(argument, role))
    # A referenced argument contributes its conclusion, which the summary may cite.
    ids.update(ctx.argument_by_id[ref].conclusion for ref in list(ids) if ref in ctx.argument_by_id)
    return ids


def _has_reasoning(ctx: _Context, argument: Argument) -> bool:
    return any(getattr(argument, role) for role in ctx.taxonomy.reasoning_roles)


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _check_duplicate_ids(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name, items in (
        ("evidence", ctx.evidence),
        ("statements", ctx.statements),
        ("arguments", ctx.arguments),
        ("scenarios", ctx.scenarios),
    ):
        seen: set[str] = set()
        for index, item in enumerate(items):
            if item.id in seen:
                issues.append(
                    ValidationIssue(
                        "DUPLICATE_ID",
                        "error",
                        f"$.{name}[{index}].id",
                        f"{item.id} appears more than once in {name}.",
                        "Give every item a unique ID and number the items in document order.",
                    )
                )
            seen.add(item.id)
    return issues


def _check_evidence_verbatim(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "EVIDENCE_NOT_VERBATIM",
            "error",
            f"$.evidence[{i}].text",
            f"{item.id} is not a substring of the source.",
            "Copy the span exactly from the document; only whitespace may differ.",
        )
        for i, item in enumerate(ctx.evidence)
        if not _squash(item.text) or _squash(item.text) not in ctx.source
    ]


def _check_evidence_unused(ctx: _Context) -> list[ValidationIssue]:
    referenced = {eid for statement in ctx.statements for eid in statement.evidence}
    return [
        ValidationIssue(
            "EVIDENCE_UNUSED",
            "warning",
            f"$.evidence[{i}]",
            f"{item.id} is not referenced by any statement.",
            "Attach the span to a statement, or remove it if no claim uses it.",
        )
        for i, item in enumerate(ctx.evidence)
        if item.id not in referenced
    ]


def _check_unknown_evidence_refs(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "UNKNOWN_EVIDENCE_REF",
            "error",
            f"$.statements[{i}].evidence[{j}]",
            f"{statement.id} cites {eid}, which is not in evidence.",
            "Reference only evidence IDs defined in evidence, or register the span first.",
        )
        for i, statement in enumerate(ctx.statements)
        for j, eid in enumerate(statement.evidence)
        if eid not in ctx.evidence_by_id
    ]


def _check_invalid_claim_types(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "INVALID_CLAIM_TYPE",
            "error",
            f"$.statements[{i}].claim_type",
            f"{statement.id} has claim type {statement.claim_type}, which is not in the taxonomy.",
            f"Use one of: {', '.join(ctx.taxonomy.claim_types)}.",
        )
        for i, statement in enumerate(ctx.statements)
        if statement.claim_type not in ctx.taxonomy.claim_types
    ]


def _check_invalid_modalities(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "INVALID_MODALITY",
            "error",
            f"$.statements[{i}].modality",
            f"{statement.id} has modality {statement.modality}, which is not in the taxonomy.",
            f"Use one of: {', '.join(ctx.taxonomy.modalities)}.",
        )
        for i, statement in enumerate(ctx.statements)
        if statement.modality not in ctx.taxonomy.modalities
    ]


def _check_fixed_modality(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, statement in enumerate(ctx.statements):
        if statement.claim_type not in ctx.taxonomy.claim_types:
            continue
        fixed = ctx.taxonomy.fixed_modality(statement.claim_type)
        if fixed and statement.modality != fixed:
            issues.append(
                ValidationIssue(
                    "FIXED_MODALITY",
                    "error",
                    f"$.statements[{i}].modality",
                    f"{statement.id} is {statement.claim_type}, which always has modality {fixed}.",
                    f"Set modality to {fixed}.",
                )
            )
    return issues


def _check_proposition_kinds(ctx: _Context) -> list[ValidationIssue]:
    kinds = ctx.taxonomy.proposition_kinds
    if not kinds:
        if not ctx.taxonomy.subkinds:
            return []
        return [
            ValidationIssue(
                "PROPOSITION_KIND_NOT_SUPPORTED",
                "error",
                f"$.statements[{i}].proposition_kind",
                f"{statement.id} sets proposition_kind, which this taxonomy does not use.",
                "Remove proposition_kind and put the value in subkinds.",
            )
            for i, statement in enumerate(ctx.statements)
            if statement.proposition_kind is not None
        ]
    return [
        ValidationIssue(
            "INVALID_PROPOSITION_KIND",
            "error",
            f"$.statements[{i}].proposition_kind",
            f"{statement.id} has proposition kind {statement.proposition_kind}, which is not in the taxonomy.",
            f"Use one of: {', '.join(kinds)}.",
        )
        for i, statement in enumerate(ctx.statements)
        if statement.proposition_kind not in kinds
    ]


def _check_fixed_proposition_kind(ctx: _Context) -> list[ValidationIssue]:
    if not ctx.taxonomy.proposition_kinds:
        return []
    issues: list[ValidationIssue] = []
    for i, statement in enumerate(ctx.statements):
        if statement.claim_type not in ctx.taxonomy.claim_types:
            continue
        fixed = ctx.taxonomy.fixed_proposition_kind(statement.claim_type)
        if fixed and statement.proposition_kind != fixed:
            issues.append(
                ValidationIssue(
                    "FIXED_PROPOSITION_KIND",
                    "error",
                    f"$.statements[{i}].proposition_kind",
                    f"{statement.id} is {statement.claim_type}, which always has proposition kind {fixed}.",
                    f"Set proposition_kind to {fixed}.",
                )
            )
    return issues


def _check_subkinds(ctx: _Context) -> list[ValidationIssue]:
    if not ctx.taxonomy.subkinds:
        return [
            ValidationIssue(
                "SUBKINDS_NOT_SUPPORTED",
                "error",
                f"$.statements[{i}].subkinds",
                f"{statement.id} sets subkinds, which this taxonomy does not use.",
                "Remove subkinds.",
            )
            for i, statement in enumerate(ctx.statements)
            if statement.subkinds
        ]
    issues: list[ValidationIssue] = []
    for i, statement in enumerate(ctx.statements):
        if statement.claim_type not in ctx.taxonomy.claim_types:
            continue
        path = f"$.statements[{i}].subkinds"
        spec = ctx.taxonomy.subkind_spec(statement.claim_type)
        allowed = ctx.taxonomy.subkind_values(statement.claim_type)
        invalid = [value for value in statement.subkinds if value not in allowed]
        if invalid:
            hint = f"Use values from: {', '.join(allowed)}." if allowed else "Leave subkinds empty for this type."
            issues.append(
                ValidationIssue(
                    "INVALID_SUBKIND",
                    "error",
                    path,
                    f"{statement.id} is {statement.claim_type} with subkinds {', '.join(invalid)}, "
                    "which its type does not allow.",
                    hint,
                )
            )
        if spec is None:
            continue
        if spec.get("required") and not statement.subkinds:
            issues.append(
                ValidationIssue(
                    "MISSING_SUBKIND",
                    "error",
                    path,
                    f"{statement.id} is {statement.claim_type}, which needs a subkind.",
                    f"Set subkinds from: {', '.join(allowed)}.",
                )
            )
        if not spec.get("multiple") and len(set(statement.subkinds)) > 1:
            issues.append(
                ValidationIssue(
                    "MULTIPLE_SUBKINDS",
                    "error",
                    path,
                    f"{statement.id} is {statement.claim_type}, which takes one subkind, but has "
                    f"{len(statement.subkinds)}.",
                    "Keep the single subkind that best describes the statement.",
                )
            )
    return issues


def _check_cue_in_evidence(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, statement in enumerate(ctx.statements):
        cue = _squash(statement.modality_cue)
        texts = [_squash(ctx.evidence_by_id[eid].text) for eid in statement.evidence if eid in ctx.evidence_by_id]
        if not cue or not any(cue in text for text in texts):
            issues.append(
                ValidationIssue(
                    "CUE_NOT_IN_EVIDENCE",
                    "error",
                    f"$.statements[{i}].modality_cue",
                    f"{statement.id} modality cue is not found in its evidence.",
                    "Copy the modality cue verbatim from one of the statement's evidence spans.",
                )
            )
    return issues


def _check_unknown_statement_refs(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "UNKNOWN_STATEMENT_REF",
            "error",
            ref.path,
            f"{ref.statement_id} does not exist in statements.",
            "Reference only statement IDs defined in statements, or remove the reference.",
        )
        for ref in _iter_refs(ctx)
        if not is_scenario_ref(ref.statement_id)
        and not is_argument_ref(ref.statement_id)
        and ref.statement_id not in ctx.statement_by_id
    ]


def _check_role_scenario_refs(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    scenario_roles = set(ctx.taxonomy.scenario_roles)
    for ref in _iter_refs(ctx):
        if not is_scenario_ref(ref.statement_id):
            continue
        if ref.role not in scenario_roles:
            allowed = ", ".join(ctx.taxonomy.scenario_roles) or "no role in this taxonomy"
            issues.append(
                ValidationIssue(
                    "ROLE_SCENARIO_NOT_ALLOWED",
                    "error",
                    ref.path,
                    f"{ref.statement_id} is a scenario; role {ref.role} holds statements only.",
                    f"Reference scenarios only from: {allowed}.",
                )
            )
        elif ref.statement_id not in ctx.scenario_by_id:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_SCENARIO_REF",
                    "error",
                    ref.path,
                    f"{ref.statement_id} does not exist in scenarios.",
                    "Reference only scenario IDs defined in scenarios, or remove the reference.",
                )
            )
    return issues


def _check_unsupported_roles(ctx: _Context) -> list[ValidationIssue]:
    unsupported = [role for role in ARGUMENT_ROLES if role not in ctx.taxonomy.roles]
    return [
        ValidationIssue(
            "ROLE_NOT_SUPPORTED",
            "error",
            f"$.arguments[{i}].{role}",
            f"{argument.id} uses role {role}, which this taxonomy does not define.",
            f"Move the entries to one of: {', '.join(ctx.taxonomy.argument_roles)}.",
        )
        for i, argument in enumerate(ctx.arguments)
        for role in unsupported
        if getattr(argument, role)
    ]


def _check_core_duplicates(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    owner: dict[str, int] = {}
    core = ctx.taxonomy.core_role
    for i, argument in enumerate(ctx.arguments):
        if argument.conclusion in owner:
            first = ctx.arguments[owner[argument.conclusion]].id
            issues.append(
                ValidationIssue(
                    "CORE_DUPLICATE",
                    "error",
                    f"$.arguments[{i}].{core}",
                    f"{argument.conclusion} is the {core} of both {first} and {argument.id}.",
                    "Give each statement to one argument only; merge the arguments or use a different conclusion.",
                )
            )
        else:
            owner[argument.conclusion] = i
    return issues


def _check_role_types(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for ref in _iter_refs(ctx):
        statement = ctx.statement_by_id.get(ref.statement_id)
        if statement is None or statement.claim_type not in ctx.taxonomy.claim_types:
            continue
        allowed = ctx.taxonomy.roles[ref.role]["allowed_types"]
        if statement.claim_type not in allowed:
            accepts = ", ".join(allowed) if allowed else "scenarios only"
            issues.append(
                ValidationIssue(
                    "ROLE_TYPE_MISMATCH",
                    "error",
                    ref.path,
                    f"{statement.id} is {statement.claim_type}; role {ref.role} allows {accepts}.",
                    "Move the statement to a role that allows its type, or correct its claim type.",
                )
            )
    return issues


def _check_argument_relations(ctx: _Context) -> list[ValidationIssue]:
    # Types marked counts_as_relation: false ground an argument but cannot on their own make a claim an argument.
    non_relation = {name for name, spec in ctx.taxonomy.claim_types.items() if spec.get("counts_as_relation") is False}
    issues: list[ValidationIssue] = []
    for i, argument in enumerate(ctx.arguments):
        refs = [sid for role in ctx.taxonomy.argument_roles for sid in getattr(argument, role)]
        relations = [
            sid
            for sid in refs
            if is_scenario_ref(sid)
            or is_argument_ref(sid)
            or ((statement := ctx.statement_by_id.get(sid)) is not None and statement.claim_type not in non_relation)
        ]
        if not relations:
            issues.append(
                ValidationIssue(
                    "ARGUMENT_WITHOUT_RELATION",
                    "warning" if ctx.taxonomy.bare_argument_severity == "warning" else "error",
                    f"$.arguments[{i}]",
                    f"{argument.id} has no relation other than observations in rationale.",
                    "Add the reason, data point, risk or qualifier the text gives for the core claim, "
                    "or place the core claim in the argument it serves and delete this argument.",
                )
            )
    return issues


def _check_unreferenced_statements(ctx: _Context) -> list[ValidationIssue]:
    referenced = {ref.statement_id for ref in _iter_refs(ctx)}
    if ctx.taxonomy.scenario_roles:
        # Scenarios are referenced from arguments, so their members count as referenced.
        referenced |= {sid for s in ctx.scenarios for name in _SCENARIO_MEMBER_FIELDS for sid in getattr(s, name)}
    return [
        ValidationIssue(
            "STATEMENT_UNREFERENCED",
            "error",
            f"$.statements[{i}]",
            f"{statement.id} is not referenced by any argument.",
            "Place the statement in an argument role, or delete it and list its sentence under exclusions.",
        )
        for i, statement in enumerate(ctx.statements)
        if statement.id not in referenced
    ]


def _check_self_references(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "SELF_REFERENCE",
            "error",
            ref.path,
            f"{ctx.arguments[ref.argument_index].id} lists itself or its own conclusion {ref.statement_id} "
            f"in role {ref.role}.",
            "Remove the self-reference; an argument may not support itself.",
        )
        for ref in _iter_refs(ctx)
        if ref.role not in CORE_ROLES
        and ref.statement_id
        in (ctx.arguments[ref.argument_index].conclusion, ctx.arguments[ref.argument_index].id)
    ]


def _check_duplicate_role_members(ctx: _Context) -> list[ValidationIssue]:
    seen: set[tuple[int, str]] = set()
    issues: list[ValidationIssue] = []
    for ref in _iter_refs(ctx):
        if ref.role in CORE_ROLES:
            continue
        key = (ref.argument_index, ref.statement_id)
        if key in seen:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_ROLE_MEMBER",
                    "error",
                    ref.path,
                    f"{ctx.arguments[ref.argument_index].id} lists {ref.statement_id} more than once.",
                    "Keep the statement in the single role that best describes it and remove the other entries.",
                )
            )
        seen.add(key)
    return issues


def _check_summary_citations(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, argument in enumerate(ctx.arguments):
        members = _members(ctx, argument)
        for cited in dict.fromkeys(_SUMMARY_CITATION.findall(argument.summary)):
            if cited not in members:
                issues.append(
                    ValidationIssue(
                        "SUMMARY_CITES_NON_MEMBER",
                        "error",
                        f"$.arguments[{i}].summary",
                        f"{argument.id} summary cites {cited}, which is not its core claim or a role member.",
                        "Cite only the core claim and the statements listed in this argument's roles.",
                    )
                )
    return issues


def _check_cycles(ctx: _Context) -> list[ValidationIssue]:
    graph: dict[str, list[str]] = {argument.id: [] for argument in ctx.arguments}
    for source, _role, target in ctx.edges:
        graph.setdefault(source, []).append(target)
    index_of = {argument.id: i for i, argument in enumerate(ctx.arguments)}
    issues: list[ValidationIssue] = []
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
    path: list[str] = []

    def _visit(node: str) -> None:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cycle = [*path[path.index(nxt) :], nxt]
                issues.append(
                    ValidationIssue(
                        "ARGUMENT_CYCLE",
                        "error",
                        f"$.arguments[{index_of.get(nxt, 0)}]",
                        "Arguments form a cycle: " + " -> ".join(cycle) + ".",
                        "Remove the role reference that closes the cycle; "
                        "link arguments only where the source states it.",
                    )
                )
            elif state.get(nxt) is None:
                _visit(nxt)
        path.pop()
        state[node] = 2

    for node in graph:
        if state.get(node) is None:
            _visit(node)
    return issues


def _check_exclusions_verbatim(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "EXCLUSION_NOT_VERBATIM",
            "warning",
            f"$.exclusions[{i}].text",
            "An exclusion is not a substring of the source.",
            "Copy the excluded sentence exactly from the document; only whitespace may differ.",
        )
        for i, exclusion in enumerate(ctx.exclusions)
        if not _squash(exclusion.text) or _squash(exclusion.text) not in ctx.source
    ]


def _check_brief_length(ctx: _Context) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "BRIEF_TOO_LONG",
            "warning",
            f"$.statements[{i}].brief",
            f"{statement.id} brief has {len(statement.brief.split())} words; the limit is {MAX_BRIEF_WORDS}.",
            "Shorten the brief to ten words or fewer.",
        )
        for i, statement in enumerate(ctx.statements)
        if len(statement.brief.split()) > MAX_BRIEF_WORDS
    ]


def _check_scenario_values(ctx: _Context) -> list[ValidationIssue]:
    spec = ctx.taxonomy.scenarios
    if not spec:
        return [
            ValidationIssue(
                "SCENARIOS_NOT_SUPPORTED",
                "error",
                f"$.scenarios[{i}]",
                f"{scenario.id} is listed, but this taxonomy does not define scenarios.",
                "Remove the scenarios list; express conditional claims through the conditions role.",
            )
            for i, scenario in enumerate(ctx.scenarios)
        ]
    issues: list[ValidationIssue] = []
    for i, scenario in enumerate(ctx.scenarios):
        for field_name, key in _SCENARIO_VALUE_FIELDS.items():
            value = getattr(scenario, field_name)
            if key not in spec:
                if value is not None:
                    issues.append(
                        ValidationIssue(
                            "INVALID_SCENARIO_VALUE",
                            "error",
                            f"$.scenarios[{i}].{field_name}",
                            f"{scenario.id} sets {field_name}, which this taxonomy does not use.",
                            f"Remove {field_name}.",
                        )
                    )
                continue
            allowed = spec[key]
            if value not in allowed:
                issues.append(
                    ValidationIssue(
                        "INVALID_SCENARIO_VALUE",
                        "error",
                        f"$.scenarios[{i}].{field_name}",
                        f"{scenario.id} has {field_name} {value}, which is not in the taxonomy.",
                        f"Use one of: {', '.join(allowed)}.",
                    )
                )
    return issues


def _check_scenario_refs(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    spec = ctx.taxonomy.scenarios
    for i, scenario in enumerate(ctx.scenarios):
        for j, eid in enumerate(scenario.evidence):
            if eid not in ctx.evidence_by_id:
                issues.append(
                    ValidationIssue(
                        "UNKNOWN_EVIDENCE_REF",
                        "error",
                        f"$.scenarios[{i}].evidence[{j}]",
                        f"{scenario.id} cites {eid}, which is not in evidence.",
                        "Reference only evidence IDs defined in evidence, or register the span first.",
                    )
                )
        for field_name in _SCENARIO_MEMBER_FIELDS:
            for j, sid in enumerate(getattr(scenario, field_name)):
                statement = ctx.statement_by_id.get(sid)
                path = f"$.scenarios[{i}].{field_name}[{j}]"
                if statement is None:
                    issues.append(
                        ValidationIssue(
                            "UNKNOWN_STATEMENT_REF",
                            "error",
                            path,
                            f"{sid} does not exist in statements.",
                            "Reference only statement IDs defined in statements, or remove the reference.",
                        )
                    )
                elif field_name == "recommendations" and statement.claim_type not in spec.get(
                    "recommendation_types", ["RECOMMENDATION"]
                ):
                    allowed = ", ".join(spec.get("recommendation_types", ["RECOMMENDATION"]))
                    issues.append(
                        ValidationIssue(
                            "SCENARIO_RECOMMENDATION_TYPE",
                            "error",
                            path,
                            f"{sid} is {statement.claim_type}, but scenario recommendations must be {allowed}.",
                            "Move the statement to assumptions or implications, or correct its claim type.",
                        )
                    )
                elif (key := _slot_types_key(field_name, spec)) is not None:
                    allowed = spec[key]
                    if statement.claim_type not in allowed:
                        issues.append(
                            ValidationIssue(
                                "SCENARIO_SLOT_TYPE",
                                "error",
                                path,
                                f"{sid} is {statement.claim_type}; scenario {field_name} allow {', '.join(allowed)}.",
                                "Move the statement to the right scenario slot, or correct its claim type.",
                            )
                        )
    return issues


def _slot_types_key(field_name: str, spec: dict) -> str | None:
    return next((key for key in _SCENARIO_SLOT_TYPES.get(field_name, ()) if key in spec), None)


def _check_scenario_unreferenced(ctx: _Context) -> list[ValidationIssue]:
    if not ctx.taxonomy.scenario_roles:
        return []
    referenced = {ref.statement_id for ref in _iter_refs(ctx)}
    return [
        ValidationIssue(
            "SCENARIO_UNREFERENCED",
            "warning",
            f"$.scenarios[{i}]",
            f"{scenario.id} is not referenced by any argument.",
            f"Place {scenario.id} in an argument's {', '.join(ctx.taxonomy.scenario_roles)} role.",
        )
        for i, scenario in enumerate(ctx.scenarios)
        if scenario.id not in referenced
    ]


def _check_must_keep_exclusions(ctx: _Context) -> list[ValidationIssue]:
    patterns = {name: re.compile(p, re.IGNORECASE) for name, p in ctx.taxonomy.must_keep_patterns.items()}
    issues: list[ValidationIssue] = []
    for i, exclusion in enumerate(ctx.exclusions):
        hits = [name for name, pattern in patterns.items() if pattern.search(exclusion.text)]
        if hits:
            issues.append(
                ValidationIssue(
                    "MUST_KEEP_EXCLUDED",
                    "warning",
                    f"$.exclusions[{i}]",
                    f"An excluded sentence looks like a {' or '.join(hits)} claim.",
                    "Represent it as a statement in an argument unless it is not the author's claim.",
                )
            )
    return issues


def _check_scenario_members(ctx: _Context) -> list[ValidationIssue]:
    severity: Severity = "error" if ctx.taxonomy.scenario_empty_severity == "error" else "warning"
    return [
        ValidationIssue(
            "SCENARIO_EMPTY",
            severity,
            f"$.scenarios[{i}]",
            f"{scenario.id} needs at least one assumption and one implication.",
            "Add the SUPPOSITION statements that define the scenario and those that would follow, "
            "or drop the scenario and use the conditions role.",
        )
        for i, scenario in enumerate(ctx.scenarios)
        if not scenario.assumptions or not scenario.implications
    ]


def _check_argument_refs(ctx: _Context) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    allowed_roles = set(ctx.taxonomy.argument_ref_roles)
    for ref in _iter_refs(ctx):
        if not is_argument_ref(ref.statement_id):
            continue
        target = ctx.argument_by_id.get(ref.statement_id)
        if ref.role not in allowed_roles:
            allowed = ", ".join(ctx.taxonomy.argument_ref_roles) or "no role in this taxonomy"
            issues.append(
                ValidationIssue(
                    "ROLE_ARGUMENT_NOT_ALLOWED",
                    "error",
                    ref.path,
                    f"{ref.statement_id} is an argument; role {ref.role} cannot reference arguments.",
                    f"Reference arguments only from: {allowed}; elsewhere use the statement ID.",
                )
            )
        elif target is None:
            issues.append(
                ValidationIssue(
                    "UNKNOWN_ARGUMENT_REF",
                    "error",
                    ref.path,
                    f"{ref.statement_id} does not exist in arguments.",
                    "Reference only argument IDs defined in arguments, or remove the reference.",
                )
            )
        elif ctx.taxonomy.reasoning_roles and not _has_reasoning(ctx, target):
            issues.append(
                ValidationIssue(
                    "SUBARGUMENT_WITHOUT_REASONING",
                    "error",
                    ref.path,
                    f"{target.id} has no {', '.join(ctx.taxonomy.reasoning_roles)} of its own, so it is a statement, "
                    "not an argument to reference.",
                    f"Reference its conclusion {target.conclusion} instead of {target.id}.",
                )
            )
        else:
            conclusion = ctx.statement_by_id.get(target.conclusion)
            allowed_types = ctx.taxonomy.roles[ref.role].get("allowed_types", [])
            if conclusion is not None and allowed_types and conclusion.claim_type not in allowed_types:
                issues.append(
                    ValidationIssue(
                        "ROLE_TYPE_MISMATCH",
                        "error",
                        ref.path,
                        f"{target.id} concludes {conclusion.claim_type}; role {ref.role} allows "
                        f"{', '.join(allowed_types)}.",
                        "Move the reference to a role that allows its conclusion's type.",
                    )
                )
    return issues


def _check_role_cues(ctx: _Context) -> list[ValidationIssue]:
    """Roles with an ``evidence_cue`` need a statement whose evidence contains the cue, e.g. explicit assumptions."""
    issues: list[ValidationIssue] = []
    cues = {role: spec["evidence_cue"] for role, spec in ctx.taxonomy.roles.items() if spec.get("evidence_cue")}
    patterns = {role: re.compile(spec["pattern"]) for role, spec in cues.items()}
    for ref in _iter_refs(ctx):
        statement = ctx.statement_by_id.get(ref.statement_id)
        if ref.role not in cues or statement is None:
            continue
        text = " ".join(ctx.evidence_by_id[e].text for e in statement.evidence if e in ctx.evidence_by_id)
        if not patterns[ref.role].search(text):
            spec = cues[ref.role]
            issues.append(
                ValidationIssue(
                    spec["code"],
                    spec.get("severity", "warning"),
                    ref.path,
                    f"{statement.id} is in {ref.role}, but its evidence has none of the wording that role needs.",
                    spec["action"],
                )
            )
    return issues


def _check_role_wording(ctx: _Context) -> list[ValidationIssue]:
    """Roles with ``wording_overlap`` need statements worded from their evidence, so they are stated, not inferred."""
    issues: list[ValidationIssue] = []
    specs = {role: spec["wording_overlap"] for role, spec in ctx.taxonomy.roles.items() if spec.get("wording_overlap")}
    for ref in _iter_refs(ctx):
        statement = ctx.statement_by_id.get(ref.statement_id)
        if ref.role not in specs or statement is None:
            continue
        words = _content_words(statement.statement)
        evidence = _content_words(
            " ".join(ctx.evidence_by_id[e].text for e in statement.evidence if e in ctx.evidence_by_id)
        )
        share = len(words & evidence) / len(words) if words else 1.0
        spec = specs[ref.role]
        if share < spec["threshold"]:
            issues.append(
                ValidationIssue(
                    spec["code"],
                    spec.get("severity", "error"),
                    ref.path,
                    f"Only {share:.0%} of {statement.id}'s content words appear in its evidence; "
                    f"a {ref.role} statement must be stated by the author.",
                    spec["action"],
                )
            )
    return issues


def _check_required_roles(ctx: _Context) -> list[ValidationIssue]:
    """Roles with ``requires_roles`` are only valid in an argument that also fills one of those roles."""
    issues: list[ValidationIssue] = []
    for role, spec in ctx.taxonomy.roles.items():
        required = spec.get("requires_roles")
        if not required:
            continue
        for i, argument in enumerate(ctx.arguments):
            if getattr(argument, role, None) and not any(getattr(argument, r) for r in required["roles"]):
                issues.append(
                    ValidationIssue(
                        required["code"],
                        required.get("severity", "error"),
                        f"$.arguments[{i}].{role}",
                        f"{argument.id} has {role} but no {', '.join(required['roles'])}.",
                        required["action"],
                    )
                )
    return issues


def _check_conditional_claims(ctx: _Context) -> list[ValidationIssue]:
    if not ctx.taxonomy.conditional_pattern:
        return []
    pattern = re.compile(ctx.taxonomy.conditional_pattern)
    return [
        ValidationIssue(
            "CONDITIONAL_IN_CLAIM",
            "warning",
            f"$.statements[{i}].statement",
            f"{statement.id} is {statement.claim_type} but carries a conditional clause.",
            "Split it into a SUPPOSITION for the premise and a statement for the consequent; if a scenario has that "
            "premise, put the consequent in the scenario's implications.",
        )
        for i, statement in enumerate(ctx.statements)
        if statement.claim_type != "SUPPOSITION" and pattern.search(statement.statement)
    ]


def _check_restated_conclusions(ctx: _Context) -> list[ValidationIssue]:
    threshold = ctx.taxonomy.duplicate_conclusion_threshold
    if threshold is None:
        return []
    conclusions = {
        a.id: ctx.statement_by_id[a.conclusion] for a in ctx.arguments if a.conclusion in ctx.statement_by_id
    }
    words = {aid: _content_words(s.statement) for aid, s in conclusions.items()}
    issues: list[ValidationIssue] = []
    for ref in _iter_refs(ctx):
        statement = ctx.statement_by_id.get(ref.statement_id)
        if ref.role in CORE_ROLES or statement is None:
            continue
        own = ctx.arguments[ref.argument_index].id
        mine = _content_words(statement.statement)
        for aid, other in words.items():
            if aid == own or conclusions[aid].id == statement.id or not mine or not other:
                continue
            overlap = len(mine & other)
            f1 = 2 * overlap / (len(mine) + len(other))
            if f1 >= threshold:
                issues.append(
                    ValidationIssue(
                        "PREMISE_DUPLICATES_CORE",
                        "warning",
                        ref.path,
                        f"{statement.id} restates {conclusions[aid].id}, the conclusion of {aid} "
                        f"(word overlap {f1:.2f}).",
                        f"Reference {aid} (or {conclusions[aid].id}) instead of restating it.",
                    )
                )
                break
    return issues


def _check_must_keep_uncovered(ctx: _Context) -> list[ValidationIssue]:
    if not ctx.taxonomy.coverage_check or not ctx.taxonomy.must_keep_patterns:
        return []
    result = coverage(ctx.map_, ctx.source, ctx.taxonomy.must_keep_patterns)
    return [
        ValidationIssue(
            "MUST_KEEP_UNCOVERED",
            "warning",
            "$.evidence",
            f"A sentence that looks like a claim is neither cited nor excluded: {sentence[:160]!r}.",
            "Cite it as evidence of a statement, or list it under exclusions with a reason.",
        )
        for sentence in result.must_keep_silent
    ]


# Registered checks, run in this order. Add a new check as one function plus one entry here.
CHECKS: list[Callable[[_Context], list[ValidationIssue]]] = [
    _check_duplicate_ids,
    _check_evidence_verbatim,
    _check_evidence_unused,
    _check_unknown_evidence_refs,
    _check_invalid_claim_types,
    _check_invalid_modalities,
    _check_fixed_modality,
    _check_proposition_kinds,
    _check_fixed_proposition_kind,
    _check_subkinds,
    _check_cue_in_evidence,
    _check_unknown_statement_refs,
    _check_role_scenario_refs,
    _check_unsupported_roles,
    _check_core_duplicates,
    _check_role_types,
    _check_argument_relations,
    _check_unreferenced_statements,
    _check_self_references,
    _check_duplicate_role_members,
    _check_summary_citations,
    _check_cycles,
    _check_exclusions_verbatim,
    _check_brief_length,
    _check_scenario_values,
    _check_scenario_refs,
    _check_scenario_members,
    _check_scenario_unreferenced,
    _check_must_keep_exclusions,
    _check_argument_refs,
    _check_role_cues,
    _check_role_wording,
    _check_required_roles,
    _check_conditional_claims,
    _check_restated_conclusions,
    _check_must_keep_uncovered,
]
