"""Pydantic models for argument maps (gold files and pipeline output)."""

import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

EvidenceId = Annotated[str, StringConstraints(pattern=r"^E\d{3}$")]
StatementId = Annotated[str, StringConstraints(pattern=r"^S\d{3}$")]
ArgumentId = Annotated[str, StringConstraints(pattern=r"^A\d{3}$")]
ScenarioId = Annotated[str, StringConstraints(pattern=r"^SC\d{3}$")]
# Argument roles hold statement IDs and, where the taxonomy allows it, scenario or argument IDs.
RoleRef = Annotated[str, StringConstraints(pattern=r"^(?:S|SC|A)\d{3}$")]
ExclusionCode = Literal[
    "TANGENTIAL", "NOT_LOAD_BEARING", "REDUNDANT", "VAGUE", "TRANSIENT", "UNFAITHFUL", "META", "NON_CLAIM"
]


def _as_text(value: Any) -> Any:
    """Keep YAML timestamps written without quotes as ISO-8601 strings."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


OptionalText = Annotated[str | None, BeforeValidator(_as_text)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentMeta(_Strict):
    """Document-level metadata, in the key order used by the gold files."""

    title: str | None = None
    publisher: str | None = None
    authors: list[str] = Field(default_factory=list)
    desk: str | None = None
    asset_classes: list[str] = Field(default_factory=list)
    source_email_sent_at: OptionalText = None
    publication_date: OptionalText = None
    source_preprocessing: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)


class Evidence(_Strict):
    """A verbatim source span registered under an ID."""

    id: EvidenceId
    text: str


class Statement(_Strict):
    """A typed, modality-tagged proposition grounded in evidence.

    ``proposition_kind`` (v0.9) and ``subkinds`` (v0.10) are used by taxonomies that define them; ``attribution``
    is None for the author's own claims.
    """

    id: StatementId
    brief: str
    statement: str
    claim_type: str
    proposition_kind: str | None = None
    subkinds: list[str] = Field(default_factory=list)
    modality: str
    modality_cue: str = Field(min_length=1)
    attribution: str | None = None
    evidence: list[EvidenceId] = Field(min_length=1)


class Argument(_Strict):
    """A conclusion with the statements, scenarios and arguments that support, qualify or extend it.

    The role fields cover the roles of every taxonomy; a taxonomy's ``argument_roles`` must be a subset, and a unit
    test enforces this. Roles hold scenario or argument IDs only where the taxonomy allows it. ``conclusion`` was
    ``core_claim`` before v0.12; maps that use the old key still load.
    """

    id: ArgumentId
    summary: str
    conclusion: StatementId = Field(validation_alias=AliasChoices("conclusion", "core_claim"))
    premises: list[RoleRef] = Field(default_factory=list)
    assumptions: list[RoleRef] = Field(default_factory=list)
    warrants: list[RoleRef] = Field(default_factory=list)
    supporting: list[RoleRef] = Field(default_factory=list)
    rationale: list[RoleRef] = Field(default_factory=list)
    risks: list[RoleRef] = Field(default_factory=list)
    conditions: list[RoleRef] = Field(default_factory=list)
    catalysts: list[RoleRef] = Field(default_factory=list)
    qualifiers: list[RoleRef] = Field(default_factory=list)
    concessions: list[RoleRef] = Field(default_factory=list)
    implications: list[RoleRef] = Field(default_factory=list)
    alternatives: list[RoleRef] = Field(default_factory=list)


class Scenario(_Strict):
    """A hypothetical context grouping assumptions with the implications and recommendations that would follow.

    ``role``, ``outcome_orientation`` and ``purpose`` are set only under taxonomies that define them (v0.9).
    ``implications`` was ``outcomes`` before v0.12; maps that use the old key still load.
    """

    id: ScenarioId
    label: str
    role: str | None = None
    outcome_orientation: str | None = None
    purpose: str | None = None
    evidence: list[EvidenceId] = Field(min_length=1)
    assumptions: list[StatementId] = Field(default_factory=list)
    implications: list[StatementId] = Field(
        default_factory=list, validation_alias=AliasChoices("implications", "outcomes")
    )
    recommendations: list[StatementId] = Field(default_factory=list)


class Exclusion(_Strict):
    """A source sentence intentionally not represented, with a reason code and a short reason."""

    text: str
    code: ExclusionCode | None = None
    reason: str


class ArgumentMap(_Strict):
    """A complete argument map, as stored in the gold files and written by the pipeline."""

    schema_version: str
    document: DocumentMeta
    evidence: list[Evidence]
    statements: list[Statement]
    arguments: list[Argument]
    scenarios: list[Scenario] = Field(default_factory=list)
    rejected_links: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    adjudication_notes: list[str] = Field(default_factory=list)


class ModelOutput(_Strict):
    """The JSON object the model must return; it has no schema_version or gold-only keys."""

    document: DocumentMeta
    evidence: list[Evidence]
    statements: list[Statement]
    arguments: list[Argument]
    scenarios: list[Scenario] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
