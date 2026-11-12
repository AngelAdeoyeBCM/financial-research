import json
from pathlib import Path

import pytest

from incolor.classification import (
    ClaudeClassifier,
    CsvReporter,
    Document,
    EntityReporter,
    HtmlReporter,
    Pipeline,
    Taxonomy,
)

ROOT = Path(__file__).resolve().parents[1]
GOOD = {
    "primary": {"category": "Central bank", "subcategory": "Meeting preview/review"},
    "secondary": [{"category": "Rates", "subcategory": "Local curve and duration"}],
    "countries": ["us"],
    "document_type": "weekly",
    "confidence": 0.9,
    "rationale": "Reviews the FOMC meeting.",
    "runner_up": {
        "category": "Central bank",
        "subcategory": "Policy rate path",
        "reason": "Less rate path.",
        "close_call": False,
    },
    "text_quality": "ok",
    "entities": [{"name": "Federal Reserve", "type": "central_bank"}, {"name": "Fed", "type": "central_bank"}],
}


class FakeBackend:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict) -> str:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return "```json\n" + json.dumps(reply) + "\n```"


@pytest.fixture
def taxonomy() -> Taxonomy:
    return Taxonomy.load(ROOT / "taxonomy.yaml")


@pytest.fixture
def doc_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    header = '---\nTitle: "A"\nDate: 2026-01-02\n---\n\n# Research Text\n\n'
    (folder / "a.txt").write_text(header + "Fed text. " * 50, encoding="utf-8")
    return folder


def test_retries_on_invalid_label(taxonomy: Taxonomy, doc_dir: Path) -> None:
    bad = {**GOOD, "primary": {"category": "Central bank", "subcategory": "Made up"}}
    backend = FakeBackend([bad, GOOD])
    result = ClaudeClassifier(taxonomy, backend).classify(Document.load(doc_dir / "a.txt"))
    assert backend.calls == 2
    assert result.classification.countries == ("US",)
    assert [e.name for e in result.classification.entities] == ["Fed"]
    assert not result.needs_review


def test_pipeline_writes_outputs_and_resumes(taxonomy: Taxonomy, doc_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    backend = FakeBackend([GOOD])

    def build() -> Pipeline:
        return Pipeline(
            ClaudeClassifier(taxonomy, backend),
            [CsvReporter(out / "c.csv"), EntityReporter(out / "e.csv"), HtmlReporter(out / "r.html", taxonomy)],
            out / "cache",
            out / "failures.json",
        )

    assert build().run(doc_dir).cached == 0
    assert build().run(doc_dir).cached == 1
    assert backend.calls == 1
    assert (out / "e.csv").read_text().splitlines()[1] == "a.txt,Fed,central_bank,Central bank"
    assert '"Fed"' in (out / "r.html").read_text(encoding="utf-8")


def test_exhausted_retries_are_logged_not_raised(taxonomy: Taxonomy, doc_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    pipeline = Pipeline(
        ClaudeClassifier(taxonomy, FakeBackend([{**GOOD, "confidence": 5}])), [], out / "cache", out / "failures.json"
    )
    summary = pipeline.run(doc_dir)
    assert list(summary.failures) == ["a.txt"]
    assert "a.txt" in (out / "failures.json").read_text()
