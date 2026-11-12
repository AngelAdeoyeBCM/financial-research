"""Run one document through prompt, backend, parse, validate and repair, and return the result."""

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .backends import ModelBackend, get_backend
from .ingest import PreprocessConfig, load_document
from .prompt import render_repair_prompt, render_system_prompt, render_user_prompt
from .repair import REPAIR_CODES, repair_output
from .schema import ArgumentMap, ModelOutput
from .taxonomy import DEFAULT_TAXONOMY_PATH, REPO_ROOT, load_taxonomy
from .validate import ValidationIssue, has_errors, validate

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "pipeline.yaml"
BACKEND_NAMES = ("claude", "local")
_JSON_REPAIR_ACTION = "Return one JSON object that validates against the schema, with no prose or code fences."


@dataclass(frozen=True)
class ClaudeSettings:
    """Settings for the Claude Agent SDK backend. ``model`` None means the SDK default."""

    model: str | None = None


@dataclass(frozen=True)
class LocalSettings:
    """Settings for the Ollama backend."""

    provider: str
    model: str
    host: str
    num_ctx: int


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline settings loaded from ``pipeline.yaml`` and optionally overridden on the command line."""

    backend: str
    temperature: float
    max_repairs: int
    max_input_chars: int
    few_shot_example: Path | None
    schema_version: str
    claude: ClaudeSettings
    local: LocalSettings
    furniture_patterns: list[str] = field(default_factory=list)
    taxonomy: Path = DEFAULT_TAXONOMY_PATH


@dataclass
class PipelineResult:
    """Outcome of one pipeline run.

    ``map`` is the last parsed map, including any with remaining errors, and is None if the last response was not
    valid JSON. ``issues`` are the issues from the final attempt.
    """

    map: ArgumentMap | None
    issues: list[ValidationIssue]
    attempts: int
    raw_outputs: list[str]

    @property
    def ok(self) -> bool:
        """Return True if a map was produced and has no error-severity issues."""
        return self.map is not None and not has_errors(self.issues)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> PipelineConfig:
    """Load and check the pipeline configuration file.

    Raises:
        ValueError: If a required key is missing or the backend is unknown.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    try:
        backend = data["backend"]
        if backend not in BACKEND_NAMES:
            raise ValueError(f"{path}: backend must be one of {', '.join(BACKEND_NAMES)}, got {backend!r}")
        example = data.get("few_shot_example")
        taxonomy = data.get("taxonomy")
        local = data["local"]
        return PipelineConfig(
            backend=backend,
            temperature=float(data["temperature"]),
            max_repairs=int(data["max_repairs"]),
            max_input_chars=int(data["max_input_chars"]),
            few_shot_example=None if example is None else REPO_ROOT / example,
            schema_version=str(data["schema_version"]),
            claude=ClaudeSettings(model=(data.get("claude") or {}).get("model")),
            local=LocalSettings(
                provider=local["provider"],
                model=local["model"],
                host=local["host"],
                num_ctx=int(local["num_ctx"]),
            ),
            furniture_patterns=list(data["preprocessing"]["furniture_patterns"]),
            taxonomy=DEFAULT_TAXONOMY_PATH if taxonomy is None else REPO_ROOT / taxonomy,
        )
    except KeyError as exc:
        raise ValueError(f"{path}: missing key {exc}") from exc


def apply_overrides(
    config: PipelineConfig,
    backend: str | None = None,
    model: str | None = None,
    no_example: bool = False,
    taxonomy: Path | None = None,
) -> PipelineConfig:
    """Return a copy of ``config`` with CLI overrides applied. ``model`` replaces the selected backend's model."""
    changes: dict[str, Any] = {}
    if backend:
        changes["backend"] = backend
    if model:
        target = backend or config.backend
        if target == "claude":
            changes["claude"] = dataclasses.replace(config.claude, model=model)
        else:
            changes["local"] = dataclasses.replace(config.local, model=model)
    if no_example:
        changes["few_shot_example"] = None
    if taxonomy is not None:
        changes["taxonomy"] = Path(taxonomy)
    return dataclasses.replace(config, **changes)


def _load_example(path: Path | None) -> ArgumentMap | None:
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return ArgumentMap.model_validate(yaml.safe_load(f))


def _extract_json(raw: str) -> str:
    """Return the substring from the first ``{`` to the last ``}``, so stray code fences are tolerated.

    Raises:
        ValueError: If no JSON object delimiters are found.
    """
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found in the model response")
    return raw[start : end + 1]


def _preprocessing_notes(config: PipelineConfig) -> list[str]:
    notes = ["Whitespace collapsed to single spaces."]
    if config.furniture_patterns:
        notes.append("Page furniture removed.")
    return notes


def _to_argument_map(output: ModelOutput, config: PipelineConfig) -> ArgumentMap:
    document = output.document.model_copy(update={"source_preprocessing": _preprocessing_notes(config)})
    return ArgumentMap(
        schema_version=config.schema_version,
        document=document,
        evidence=output.evidence,
        statements=output.statements,
        arguments=output.arguments,
        scenarios=output.scenarios,
        exclusions=output.exclusions,
    )


def run_pipeline(input_path: Path, config: PipelineConfig, backend: ModelBackend | None = None) -> PipelineResult:
    """Extract an argument map from one document, repairing it up to ``config.max_repairs`` times.

    Raises:
        InputError: If the input file cannot be used.
        BackendUnavailableError: If no backend can be created.
    """
    taxonomy = load_taxonomy(config.taxonomy)
    doc = load_document(Path(input_path), PreprocessConfig(list(config.furniture_patterns), config.max_input_chars))
    system_prompt = render_system_prompt(taxonomy, _load_example(config.few_shot_example))
    model = backend if backend is not None else get_backend(config)
    schema = ModelOutput.model_json_schema()

    prompt = render_user_prompt(doc)
    raw_outputs: list[str] = []
    last_map: ArgumentMap | None = None
    issues: list[ValidationIssue] = []
    attempt = 0
    for attempt in range(1, config.max_repairs + 2):
        raw = model.generate(system_prompt, prompt, schema)
        raw_outputs.append(raw)
        previous = raw
        try:
            output = ModelOutput.model_validate(json.loads(_extract_json(raw)))
        except ValueError as exc:
            last_map = None
            issues = [ValidationIssue("INVALID_JSON", "error", "$", str(exc)[:500], _JSON_REPAIR_ACTION)]
        else:
            output, repairs = repair_output(output, doc.text, taxonomy)
            previous = output.model_dump_json()
            last_map = _to_argument_map(output, config)
            issues = repairs + validate(output, doc.text, taxonomy)
            if not has_errors(issues):
                break
        if attempt <= config.max_repairs:
            # The repaired output is sent back, so the model does not redo the deterministic fixes.
            prompt = render_repair_prompt(doc, previous, [i for i in issues if i.code not in REPAIR_CODES])
    return PipelineResult(map=last_map, issues=issues, attempts=attempt, raw_outputs=raw_outputs)
