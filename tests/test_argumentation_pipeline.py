"""Tests for the pipeline loop, config handling, writer round trip and the CLI, using a deterministic FakeBackend."""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from incolor.argumentation import pipeline
from incolor.argumentation.cli import main
from incolor.argumentation.pipeline import apply_overrides, load_config, run_pipeline
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import REPO_ROOT
from incolor.argumentation.writer import load_argument_map, write_argument_map

ING_GOLD = REPO_ROOT / "tests" / "fixtures" / "gold" / "ing_fx_daily_argument_map_gold_v06.yaml"
ING_SOURCE = REPO_ROOT / "tests" / "fixtures" / "texts" / "ING.txt"


class FakeBackend:
    """Return canned responses in order and record every user prompt it receives."""

    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.user_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        assert "{{" not in system_prompt
        self.user_prompts.append(user_prompt)
        if not self._responses:
            raise AssertionError("FakeBackend has no responses left")
        return self._responses.pop(0)


def _gold() -> ArgumentMap:
    return ArgumentMap.model_validate(_load_yaml(ING_GOLD))


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _model_json(map_: ArgumentMap) -> str:
    """Serialise a gold map in the shape the model must return (no gold-only keys)."""
    data = map_.model_dump(mode="json", exclude={"schema_version", "rejected_links", "adjudication_notes"})
    return json.dumps(data)


def _config(**changes: Any) -> pipeline.PipelineConfig:
    return dataclasses.replace(load_config(), few_shot_example=None, **changes)


def test_gold_response_passes_on_first_attempt() -> None:
    backend = FakeBackend([_model_json(_gold())])
    result = run_pipeline(ING_SOURCE, _config(), backend=backend)
    assert result.ok
    assert result.attempts == 1
    assert result.issues == []


def test_broken_json_is_repaired_on_second_attempt() -> None:
    backend = FakeBackend(["{not json", _model_json(_gold())])
    result = run_pipeline(ING_SOURCE, _config(), backend=backend)
    assert result.ok
    assert result.attempts == 2
    assert "<previous_output>" in backend.user_prompts[1]
    assert "INVALID_JSON" in backend.user_prompts[1]


def test_semantic_error_is_repaired_on_second_attempt() -> None:
    broken = _gold().model_copy(deep=True)
    broken.evidence[0].text = "This sentence does not occur in the source."
    backend = FakeBackend([_model_json(broken), _model_json(_gold())])
    result = run_pipeline(ING_SOURCE, _config(), backend=backend)
    assert result.ok
    assert result.attempts == 2
    assert "EVIDENCE_NOT_VERBATIM" in backend.user_prompts[1]


def test_persistent_invalid_json_gives_invalid_json_issue_and_no_map() -> None:
    backend = FakeBackend(["not json"] * 3)
    result = run_pipeline(ING_SOURCE, _config(max_repairs=2), backend=backend)
    assert not result.ok
    assert result.map is None
    assert result.attempts == 3
    assert [issue.code for issue in result.issues] == ["INVALID_JSON"]
    assert len(result.raw_outputs) == 3


def test_writer_round_trip_keeps_statements_and_arguments(tmp_path: Path) -> None:
    result = run_pipeline(ING_SOURCE, _config(), backend=FakeBackend([_model_json(_gold())]))
    assert result.map is not None
    target = tmp_path / "out" / "map.yaml"
    write_argument_map(result.map, target)
    reloaded = load_argument_map(target)
    assert reloaded.statements == result.map.statements
    assert reloaded.arguments == result.map.arguments
    assert list(_load_yaml(target))[:5] == ["schema_version", "document", "evidence", "statements", "arguments"]


def test_load_config_reads_default_file() -> None:
    config = load_config()
    assert config.backend in {"claude", "local"}
    assert config.max_repairs >= 0
    assert config.furniture_patterns


def test_apply_overrides_sets_backend_and_model() -> None:
    config = apply_overrides(_config(), backend="local", model="phi4", no_example=True)
    assert config.backend == "local"
    assert config.local.model == "phi4"
    assert config.few_shot_example is None


def test_cli_writes_yaml_and_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "get_backend", lambda config: FakeBackend([_model_json(_gold())]))
    output = tmp_path / "ing.yaml"
    code = main([str(ING_SOURCE), "-o", str(output), "--no-example"])
    assert code == 0
    assert output.exists()
    assert load_argument_map(output).statements == _gold().statements


def test_cli_returns_two_and_writes_issues_when_output_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "get_backend", lambda config: FakeBackend(["not json"] * 3))
    output = tmp_path / "ing.yaml"
    code = main([str(ING_SOURCE), "-o", str(output), "--no-example"])
    assert code == 2
    assert not output.exists()
    issues_file = tmp_path / "ing.issues.json"
    assert issues_file.exists()
    assert json.loads(issues_file.read_text(encoding="utf-8"))[0]["code"] == "INVALID_JSON"


def test_cli_returns_one_for_missing_input(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.txt"), "--no-example"]) == 1
