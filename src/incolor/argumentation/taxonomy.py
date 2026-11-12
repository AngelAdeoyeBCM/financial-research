"""Load the argument-map taxonomy that drives prompt rendering and validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAXONOMY_PATH = PACKAGE_DIR / "prompts" / "taxonomy.yaml"
CORE_ROLE = "core_claim"
# v0.12 renamed the core role; a taxonomy defines one of the two.
CONCLUSION_ROLE = "conclusion"
CORE_ROLES = (CONCLUSION_ROLE, CORE_ROLE)


@dataclass(frozen=True)
class Taxonomy:
    """Claim types, modalities, roles and rules loaded from a taxonomy YAML file.

    ``proposition_kinds``, ``proposition_kind_decision_order`` and ``scenarios`` are optional; when
    ``proposition_kinds`` is empty, statements carry no proposition kind and scenarios are not described.
    ``subkinds`` (v0.10) maps a set name to its values; a claim type opts in with ``subkinds: {set, multiple,
    required}``. ``system_prompt`` names an alternative template in the prompts folder, ``output_order`` the order of
    the top-level keys in the output schema, and ``must_keep_patterns`` regexes for content that must not be excluded.
    ``bare_argument_severity`` is the severity for an argument with nothing but its core claim (v0.11: warning).
    v0.12 settings: ``reasoning_roles`` are the roles that give an argument its own reasoning, so it may be referenced
    by ID from another argument; ``scenario_empty_severity`` for a scenario without assumptions or implications;
    ``conditional_pattern`` flags conditional clauses inside non-supposition statements; ``coverage_check`` warns
    about must-keep sentences that are neither cited nor excluded; ``duplicate_conclusion_threshold`` is the token F1
    above which a role member restating another argument's conclusion is flagged.
    """

    version: str
    claim_types: dict[str, dict[str, Any]]
    type_decision_order: list[dict[str, str]]
    modalities: dict[str, dict[str, Any]]
    roles: dict[str, dict[str, Any]]
    rules: dict[str, list[str]]
    proposition_kinds: dict[str, dict[str, Any]] = field(default_factory=dict)
    proposition_kind_decision_order: list[dict[str, str]] = field(default_factory=list)
    scenarios: dict[str, Any] = field(default_factory=dict)
    subkinds: dict[str, dict[str, Any]] = field(default_factory=dict)
    system_prompt: str | None = None
    output_order: list[str] = field(default_factory=list)
    must_keep_patterns: dict[str, str] = field(default_factory=dict)
    bare_argument_severity: str = "error"
    reasoning_roles: list[str] = field(default_factory=list)
    scenario_empty_severity: str = "warning"
    conditional_pattern: str | None = None
    coverage_check: bool = False
    duplicate_conclusion_threshold: float | None = None

    @property
    def core_role(self) -> str:
        """Return the name of the role that holds the argument's conclusion in this taxonomy."""
        return CONCLUSION_ROLE if CONCLUSION_ROLE in self.roles else CORE_ROLE

    @property
    def argument_roles(self) -> list[str]:
        """Return the roles that hold statements other than the core claim, in file order."""
        return [name for name in self.roles if name not in CORE_ROLES]

    @property
    def scenario_roles(self) -> list[str]:
        """Return the argument roles that may reference scenarios."""
        return [name for name in self.argument_roles if self.roles[name].get("allows_scenarios")]

    @property
    def argument_ref_roles(self) -> list[str]:
        """Return the argument roles that may reference other arguments by ID."""
        return [name for name in self.argument_roles if self.roles[name].get("allows_arguments")]

    def fixed_modality(self, claim_type: str) -> str | None:
        """Return the modality forced by ``claim_type``, or ``None`` if the type is free."""
        return self.claim_types[claim_type].get("fixed_modality")

    def fixed_proposition_kind(self, claim_type: str) -> str | None:
        """Return the proposition kind forced by ``claim_type``, or ``None`` if the kind is free."""
        return self.claim_types[claim_type].get("fixed_proposition_kind")

    def subkind_spec(self, claim_type: str) -> dict[str, Any] | None:
        """Return ``{set, multiple, required}`` for ``claim_type``, or ``None`` if the type takes no subkinds."""
        return self.claim_types[claim_type].get("subkinds")

    def subkind_values(self, claim_type: str) -> list[str]:
        """Return the subkinds allowed for ``claim_type``; empty if the type takes none."""
        spec = self.subkind_spec(claim_type)
        return list(self.subkinds[spec["set"]]["values"]) if spec else []


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> Taxonomy:
    """Load and sanity-check the taxonomy file.

    Raises:
        ValueError: If a required section is missing, the core role is not defined, or a claim type refers to an
            undefined subkind set.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    required = ("version", "claim_types", "type_decision_order", "modalities", "roles", "rules")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"{path}: missing taxonomy sections: {', '.join(missing)}")
    if not any(role in data["roles"] for role in CORE_ROLES):
        raise ValueError(f"{path}: the role '{CONCLUSION_ROLE}' or '{CORE_ROLE}' must be defined")
    subkinds = data.get("subkinds") or {}
    for name, spec in data["claim_types"].items():
        set_name = (spec.get("subkinds") or {}).get("set")
        if set_name is not None and set_name not in subkinds:
            raise ValueError(f"{path}: claim type {name} uses undefined subkind set '{set_name}'")
    return Taxonomy(
        version=str(data["version"]),
        claim_types=data["claim_types"],
        type_decision_order=data["type_decision_order"],
        modalities=data["modalities"],
        roles=data["roles"],
        rules=data["rules"],
        proposition_kinds=data.get("proposition_kinds") or {},
        proposition_kind_decision_order=data.get("proposition_kind_decision_order") or [],
        scenarios=data.get("scenarios") or {},
        subkinds=subkinds,
        system_prompt=data.get("system_prompt"),
        output_order=data.get("output_order") or [],
        must_keep_patterns=data.get("must_keep_patterns") or {},
        bare_argument_severity=data.get("bare_argument_severity", "error"),
        reasoning_roles=data.get("reasoning_roles") or [],
        scenario_empty_severity=data.get("scenario_empty_severity", "warning"),
        conditional_pattern=data.get("conditional_pattern"),
        coverage_check=bool(data.get("coverage_check", False)),
        duplicate_conclusion_threshold=data.get("duplicate_conclusion_threshold"),
    )
