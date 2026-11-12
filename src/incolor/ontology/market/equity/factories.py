"""Equity factories."""

from pathlib import Path
from typing import Any

from ...core import Factory, SeedFactory
from .definitions import EquityIndex


def factories(seeds: Path) -> list[Factory[Any]]:
    """Equity factories, seeds read from `seeds`."""
    return [SeedFactory(EquityIndex, seeds / 'equity_indices.yaml')]
