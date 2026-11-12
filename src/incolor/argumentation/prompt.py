"""Render the system prompt, user prompt and repair prompt from the templates and the taxonomy."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .ingest import SourceDocument
from .schema import ArgumentMap, ModelOutput
from .taxonomy import Taxonomy
from .validate import ARGUMENT_ROLES, ValidationIssue

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_TEMPLATE = PROMPT_DIR / "system_prompt.md"
USER_TEMPLATE = PROMPT_DIR / "user_prompt.md"

# Fields that the model output does not carry; they are dropped from the example map.
_EXAMPLE_EXCLUDED = {"schema_version", "rejected_links", "adjudication_notes"}
# Scenario field -> taxonomy key that enables it.
_SCENARIO_SETTINGS = {"role": "roles", "outcome_orientation": "outcome_orientations", "purpose": "purposes"}
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_REPAIR_INSTRUCTION = (
    "Return the full corrected JSON object. Fix every error; do not change anything that was not flagged."
)


def _fill(template: str, values: dict[str, str]) -> str:
    """Replace ``{{NAME}}`` placeholders in one pass, so substituted text is never re-scanned.

    Raises:
        ValueError: If the template uses a placeholder that has no value.
    """
    unknown = sorted(set(_PLACEHOLDER.findall(template)) - values.keys())
    if unknown:
        raise ValueError(f"Prompt template has unknown placeholders: {', '.join(unknown)}")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _render_claim_types(taxonomy: Taxonomy) -> str:
    blocks = []
    for name, spec in taxonomy.claim_types.items():
        lines = [f"### {name}", "", spec["definition"], "", "Include:"]
        lines += [f"- {item}" for item in spec.get("include", [])]
        lines += ["", "Exclude:"]
        lines += [f"- {item}" for item in spec.get("exclude", [])]
        if spec.get("fixed_modality"):
            lines += ["", f"Fixed modality: `{spec['fixed_modality']}`."]
        if spec.get("fixed_proposition_kind"):
            lines += ["", f"Fixed proposition kind: `{spec['fixed_proposition_kind']}`."]
        if spec.get("subkinds"):
            sub = spec["subkinds"]
            count = "one or more" if sub.get("multiple") else "one"
            need = "required" if sub.get("required") else "optional"
            lines += ["", f"Subkinds: {count} from `{sub['set']}` ({need})."]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_type_decision_order(taxonomy: Taxonomy) -> str:
    return "\n".join(
        f"{index}. **{step['type']}**: {step['test']}" for index, step in enumerate(taxonomy.type_decision_order, 1)
    )


def _render_proposition_kinds(taxonomy: Taxonomy) -> str:
    if not taxonomy.proposition_kinds:
        return ""
    blocks = [
        "# Proposition kinds\n\n"
        "Set `proposition_kind` on every statement to what the proposition is about, independently of its claim type."
    ]
    for name, spec in taxonomy.proposition_kinds.items():
        lines = [f"### `{name}`", "", spec["definition"], "", "Include:"]
        lines += [f"- {item}" for item in spec.get("include", [])]
        lines += ["", "Exclude:"]
        lines += [f"- {item}" for item in spec.get("exclude", [])]
        blocks.append("\n".join(lines))
    order = "\n".join(
        f"{index}. **{step['kind']}**: {step['test']}"
        for index, step in enumerate(taxonomy.proposition_kind_decision_order, 1)
    )
    blocks.append(
        "## Proposition kind decision order\n\nApply these tests in order; the first \"yes\" decides the kind.\n\n"
        + order
    )
    return "\n\n".join(blocks)


def _render_subkinds(taxonomy: Taxonomy) -> str:
    if not taxonomy.subkinds:
        return ""
    blocks = [
        "# Subkinds\n\n"
        "Set `subkinds` on every statement to a list of values from the set its claim type uses."
    ]
    for set_name, spec in taxonomy.subkinds.items():
        users = [name for name, t in taxonomy.claim_types.items() if (t.get("subkinds") or {}).get("set") == set_name]
        lines = [f"## `{set_name}` (used by {', '.join(users)})", "", spec["description"]]
        for value, value_spec in spec["values"].items():
            lines += ["", f"- `{value}`: {value_spec['definition']}"]
            lines += [f"  - Include: {item}" for item in value_spec.get("include", [])]
            lines += [f"  - Exclude: {item}" for item in value_spec.get("exclude", [])]
        if spec.get("decision_order"):
            lines += ["", "Apply these tests in order; the first \"yes\" decides the value.", ""]
            lines += [
                f"{index}. **{step['value']}**: {step['test']}"
                for index, step in enumerate(spec["decision_order"], 1)
            ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_scenarios(taxonomy: Taxonomy) -> str:
    spec = taxonomy.scenarios
    if not spec:
        return ""
    lines = [
        "# Scenarios",
        "",
        spec["definition"],
        "",
        "Record each scenario under `scenarios` with ID `SC001`, `SC002`, …, a `label`, the `evidence` that "
        "introduces it, and the statement IDs in `assumptions`, `implications` and `recommendations`.",
    ]
    constraints = []
    if spec.get("assumption_types"):
        constraints.append(f"- `assumptions` hold only {', '.join(spec['assumption_types'])} statements.")
    implication_types = spec.get("implication_types") or spec.get("outcome_types")
    if implication_types:
        constraints.append(f"- `implications` hold only {', '.join(implication_types)} statements.")
    if spec.get("recommendation_types"):
        constraints.append(f"- `recommendations` hold only {', '.join(spec['recommendation_types'])} statements.")
    if taxonomy.scenario_roles:
        roles = ", ".join(f"`{role}`" for role in taxonomy.scenario_roles)
        constraints.append(f"- Reference a scenario from an argument by placing its ID in one of these roles: {roles}.")
    if constraints:
        lines += ["", *constraints]
    for field_name, key in _SCENARIO_SETTINGS.items():
        if key not in spec:
            continue
        lines += ["", f"`{field_name}`:"]
        lines += [f"- `{value}`: {definition}" for value, definition in spec[key].items()]
    return "\n".join(lines)


def _render_modalities(taxonomy: Taxonomy) -> str:
    blocks = []
    for name, spec in taxonomy.modalities.items():
        lines = [f"- **{name}**: {spec['definition']}"]
        for category, cues in spec.get("cues", {}).items():
            lines.append(f"  - {category}: " + ", ".join(f"`{cue}`" for cue in cues))
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _render_roles(taxonomy: Taxonomy) -> str:
    if taxonomy.argument_ref_roles:
        rows = ["| Role | Definition | Allowed types | Scenarios | Arguments |", "| --- | --- | --- | --- | --- |"]
        for name, spec in taxonomy.roles.items():
            allowed = ", ".join(spec.get("allowed_types", [])) or "none"
            scenarios = "yes" if spec.get("allows_scenarios") else "no"
            arguments = "yes" if spec.get("allows_arguments") else "no"
            rows.append(f"| `{name}` | {spec['definition']} | {allowed} | {scenarios} | {arguments} |")
        return "\n".join(rows)
    if not taxonomy.scenario_roles:
        rows = ["| Role | Definition | Allowed types |", "| --- | --- | --- |"]
        for name, spec in taxonomy.roles.items():
            allowed = ", ".join(spec.get("allowed_types", []))
            rows.append(f"| `{name}` | {spec['definition']} | {allowed} |")
        return "\n".join(rows)
    rows = ["| Role | Definition | Allowed types | Scenarios |", "| --- | --- | --- | --- |"]
    for name, spec in taxonomy.roles.items():
        allowed = ", ".join(spec.get("allowed_types", [])) or "none"
        scenarios = "yes" if spec.get("allows_scenarios") else "no"
        rows.append(f"| `{name}` | {spec['definition']} | {allowed} | {scenarios} |")
    return "\n".join(rows)


def _render_rules(taxonomy: Taxonomy) -> str:
    sections = []
    for section, bullets in taxonomy.rules.items():
        lines = [f"## {section.replace('_', ' ').capitalize()}", ""]
        lines += [f"- {bullet}" for bullet in bullets]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _render_example(example: ArgumentMap | None) -> str:
    if example is None:
        return ""
    body = example.model_dump(mode="json", exclude=_EXAMPLE_EXCLUDED)
    return "# Example\n\n```json\n" + json.dumps(body, indent=2, ensure_ascii=False) + "\n```"


def _drop_properties(definition: dict[str, Any], names: set[str]) -> None:
    for name in names:
        definition["properties"].pop(name, None)
    if "required" in definition:
        definition["required"] = [name for name in definition["required"] if name not in names]


def output_schema(taxonomy: Taxonomy) -> dict[str, Any]:
    """Return the ModelOutput JSON Schema without the fields ``taxonomy`` does not use, keys in its output order."""
    schema = ModelOutput.model_json_schema()
    defs = schema["$defs"]
    _drop_properties(defs["Argument"], set(ARGUMENT_ROLES) - set(taxonomy.argument_roles))
    statement_unused = set()
    if not taxonomy.subkinds:
        statement_unused.add("subkinds")
    elif not taxonomy.proposition_kinds:
        statement_unused.add("proposition_kind")
    _drop_properties(defs["Statement"], statement_unused)
    if taxonomy.scenarios:
        unused = {name for name, key in _SCENARIO_SETTINGS.items() if key not in taxonomy.scenarios}
        _drop_properties(defs["Scenario"], unused)
    if taxonomy.output_order:
        properties = schema["properties"]
        order = [key for key in taxonomy.output_order if key in properties]
        schema["properties"] = {key: properties[key] for key in [*order, *(k for k in properties if k not in order)]}
    return schema


def render_system_prompt(taxonomy: Taxonomy, example: ArgumentMap | None = None) -> str:
    """Render the system prompt with the taxonomy, the output JSON Schema and an optional example map.

    Raises:
        ValueError: If the rendered prompt still contains ``{{``.
    """
    template = (PROMPT_DIR / taxonomy.system_prompt if taxonomy.system_prompt else SYSTEM_TEMPLATE).read_text(
        encoding="utf-8"
    )
    schema = output_schema(taxonomy)
    values = {
        "CLAIM_TYPES": _render_claim_types(taxonomy),
        "TYPE_DECISION_ORDER": _render_type_decision_order(taxonomy),
        "PROPOSITION_KINDS": _render_proposition_kinds(taxonomy),
        "SUBKINDS": _render_subkinds(taxonomy),
        "SCENARIOS": _render_scenarios(taxonomy),
        "MODALITIES": _render_modalities(taxonomy),
        "ROLES": _render_roles(taxonomy),
        "RULES": _render_rules(taxonomy),
        "OUTPUT_ORDER": ", ".join(f"`{key}`" for key in schema["properties"]),
        "OUTPUT_SCHEMA": json.dumps(schema, indent=2),
        "EXAMPLE": _render_example(example),
    }
    # Optional sections render empty; collapse the blank lines they leave behind.
    rendered = re.sub(r"\n{3,}", "\n\n", _fill(template, values))
    if "{{" in rendered:
        raise ValueError("Rendered system prompt still contains a placeholder")
    return rendered


def render_user_prompt(doc: SourceDocument) -> str:
    """Render the user prompt with the document metadata and normalised text."""
    template = USER_TEMPLATE.read_text(encoding="utf-8")
    metadata = yaml.safe_dump(doc.metadata, sort_keys=False, allow_unicode=True).strip()
    return _fill(template, {"DOCUMENT_METADATA": metadata, "DOCUMENT_TEXT": doc.text})


def render_repair_prompt(doc: SourceDocument, previous_json: str, errors: list[ValidationIssue]) -> str:
    """Build the repair prompt: the original user prompt, the previous output, and the issues to fix."""
    error_lines = "\n".join(
        json.dumps(
            {
                "code": issue.code,
                "severity": issue.severity,
                "path": issue.path,
                "message": issue.message,
                "suggested_action": issue.suggested_action,
            },
            ensure_ascii=False,
        )
        for issue in errors
    )
    return (
        f"{render_user_prompt(doc)}\n\n"
        f"<previous_output>\n{previous_json}\n</previous_output>\n\n"
        f"<validation_errors>\n{error_lines}\n</validation_errors>\n\n"
        f"{_REPAIR_INSTRUCTION}"
    )
