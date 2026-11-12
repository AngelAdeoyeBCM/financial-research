"""Commodity factories."""

from pathlib import Path
from typing import Any

from ...core import Factory, SeedFactory
from .definitions import Commodity


def factories(seeds: Path) -> list[Factory[Any]]:
    """Commodity factories, seeds read from `seeds`."""
    return [SeedFactory(Commodity, seeds / 'commodities.yaml')]
