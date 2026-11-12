"""Deterministic repairs applied to model output before validation, each reported as a warning.

* Evidence and exclusion spans that are not verbatim are replaced by the source text they match (see
  ``grounding.locate``): curly quotes, broken words, page furniture inside a sentence or small omissions.
* Modality cues not found in their evidence are replaced by the evidence text: the same words up to quote style and
  case, or the longest run of the cue's words when a snapped span split it.
* A role that references the conclusion of an argument with its own reasoning is pointed at that argument's ID.
"""

import difflib

from .grounding import fold, locate, squash
from .schema import ModelOutput
from .taxonomy import Taxonomy
from .validate import ValidationIssue, is_argument_ref, is_scenario_ref

REPAIR_CODES = frozenset({"EVIDENCE_SNAPPED", "EXCLUSION_SNAPPED", "CUE_SNAPPED", "LINK_CANONICALISED"})
MIN_PARTIAL_CUE_SHARE = 0.5
_NO_ACTION = "None; the repair has been applied."


def repair_output(
    output: ModelOutput, source_text: str, taxonomy: Taxonomy
) -> tuple[ModelOutput, list[ValidationIssue]]:
    """Return the repaired output and one warning per repair."""
    source = squash(source_text)
    folded = fold(source)
    issues: list[ValidationIssue] = []

    evidence = []
    for i, item in enumerate(output.evidence):
        match = locate(item.text, source, folded)
        if match is None or match.method == "exact":
            evidence.append(item)
            continue
        evidence.append(item.model_copy(update={"text": source[match.start : match.end]}))
        issues.append(
            ValidationIssue(
                "EVIDENCE_SNAPPED",
                "warning",
                f"$.evidence[{i}].text",
                f"{item.id} matched the source by {match.method} alignment (score {match.score}); "
                "replaced with the source text.",
                _NO_ACTION,
            )
        )

    exclusions = []
    for i, item in enumerate(output.exclusions):
        match = locate(item.text, source, folded)
        if match is None or match.method == "exact":
            exclusions.append(item)
            continue
        exclusions.append(item.model_copy(update={"text": source[match.start : match.end]}))
        issues.append(
            ValidationIssue(
                "EXCLUSION_SNAPPED",
                "warning",
                f"$.exclusions[{i}].text",
                f"Exclusion matched the source by {match.method} alignment (score {match.score}); "
                "replaced with the source text.",
                _NO_ACTION,
            )
        )

    texts = {item.id: squash(item.text) for item in evidence}
    statements = []
    for i, statement in enumerate(output.statements):
        cue = squash(statement.modality_cue)
        own = [texts[e] for e in statement.evidence if e in texts]
        fixed = None if not cue or any(cue in t for t in own) else _match_cue(cue, own)
        if fixed is None:
            statements.append(statement)
            continue
        statements.append(statement.model_copy(update={"modality_cue": fixed}))
        issues.append(
            ValidationIssue(
                "CUE_SNAPPED",
                "warning",
                f"$.statements[{i}].modality_cue",
                f"{statement.id} cue {cue!r} is not verbatim in its evidence; "
                f"replaced with {fixed!r} as written there.",
                _NO_ACTION,
            )
        )

    repaired = output.model_copy(update={"evidence": evidence, "exclusions": exclusions, "statements": statements})
    repaired, link_issues = _canonicalise_links(repaired, taxonomy)
    return repaired, issues + link_issues


def _match_cue(cue: str, texts: list[str]) -> str | None:
    """Return the cue as written in the evidence: up to quotes and case, else its longest shared run of words."""
    target = fold(cue).lower()
    for text in texts:
        index = fold(text).lower().find(target)
        if index >= 0:
            return text[index : index + len(cue)]
    # A span snapped across furniture or an omission can split the cue; keep its longest part in the evidence.
    best = ""
    for text in texts:
        folded = fold(text).lower()
        block = difflib.SequenceMatcher(None, folded, target, autojunk=False).find_longest_match(
            0, len(folded), 0, len(target)
        )
        part = text[block.a : block.a + block.size].strip(" ,;:")
        if len(part) > len(best):
            best = part
    return best if len(best) >= MIN_PARTIAL_CUE_SHARE * len(cue) and " " in best else None


def _canonicalise_links(output: ModelOutput, taxonomy: Taxonomy) -> tuple[ModelOutput, list[ValidationIssue]]:
    """Point role references at the conclusion of a reasoned argument to that argument's ID."""
    roles = set(taxonomy.argument_ref_roles)
    if not roles or not taxonomy.reasoning_roles:
        return output, []
    reasoned = {
        a.conclusion: a.id for a in output.arguments if any(getattr(a, role) for role in taxonomy.reasoning_roles)
    }
    issues: list[ValidationIssue] = []
    arguments = []
    for i, argument in enumerate(output.arguments):
        update = {}
        for role in taxonomy.argument_roles:
            refs = getattr(argument, role)
            new_refs = []
            for j, ref in enumerate(refs):
                target = reasoned.get(ref)
                is_statement = not (is_scenario_ref(ref) or is_argument_ref(ref))
                if role in roles and target and target != argument.id and is_statement:
                    issues.append(
                        ValidationIssue(
                            "LINK_CANONICALISED",
                            "warning",
                            f"$.arguments[{i}].{role}[{j}]",
                            f"{ref} is the conclusion of {target}, which has its own reasoning; "
                            f"referenced as {target}.",
                            _NO_ACTION,
                        )
                    )
                    ref = target
                new_refs.append(ref)
            if new_refs != refs:
                update[role] = list(dict.fromkeys(new_refs))
        arguments.append(argument.model_copy(update=update) if update else argument)
    return output.model_copy(update={"arguments": arguments}), issues
