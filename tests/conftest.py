"""Shared fixtures for the argumentation tests: the taxonomy, preprocessing config and the three gold maps."""

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from incolor.argumentation.ingest import PreprocessConfig, load_document, normalise
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import Taxonomy, load_taxonomy

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = REPO_ROOT / "tests" / "fixtures" / "gold"
TEXTS_DIR = REPO_ROOT / "tests" / "fixtures" / "texts"
PIPELINE_YAML = REPO_ROOT / "src" / "incolor" / "argumentation" / "pipeline.yaml"
GOLD_FILES = {
    "ms": "ms_d1_sales_argument_map_gold_v06.yaml",
    "ocado": "ocado_phase1_argument_map_gold_v06.yaml",
    "ing": "ing_fx_daily_argument_map_gold_v06.yaml",
}


@dataclass(frozen=True)
class GoldCase:
    """A gold argument map and the normalised source text its evidence must match."""

    name: str
    argument_map: ArgumentMap
    source: str


@pytest.fixture(scope="session")
def taxonomy() -> Taxonomy:
    return load_taxonomy()


@pytest.fixture(scope="session")
def preprocess_config() -> PreprocessConfig:
    data = yaml.safe_load(PIPELINE_YAML.read_text(encoding="utf-8"))
    return PreprocessConfig(
        furniture_patterns=data["preprocessing"]["furniture_patterns"],
        max_input_chars=data["max_input_chars"],
    )


def _source_text(name: str, config: PreprocessConfig) -> str:
    if name == "ms":
        # The MS sample is an email body inside a larger export: slice from the first sentence to the closing line.
        raw = (REPO_ROOT / "tests" / "email_parser_samples_output.txt").read_text(encoding="utf-8")
        start = raw.index("Sentiment across sales")
        end = raw.index("help.", start) + len("help.")
        return normalise(raw[start:end], config.furniture_patterns)
    if name == "ocado":
        return load_document(TEXTS_DIR / "Ocado.txt", config).text
    return load_document(TEXTS_DIR / "ING.txt", config).text


@pytest.fixture(scope="session", params=sorted(GOLD_FILES))
def gold_case(request: pytest.FixtureRequest, preprocess_config: PreprocessConfig) -> GoldCase:
    name: str = request.param
    text = (GOLD_DIR / GOLD_FILES[name]).read_text(encoding="utf-8")
    argument_map = ArgumentMap.model_validate(yaml.safe_load(text))
    return GoldCase(name=name, argument_map=argument_map, source=_source_text(name, preprocess_config))


@pytest.fixture(scope="session")
def ms_gold(preprocess_config: PreprocessConfig) -> GoldCase:
    text = (GOLD_DIR / GOLD_FILES["ms"]).read_text(encoding="utf-8")
    return GoldCase(
        name="ms",
        argument_map=ArgumentMap.model_validate(yaml.safe_load(text)),
        source=_source_text("ms", preprocess_config),
    )
