"""Bond factories."""

from pathlib import Path
from typing import Any

from ...core import BuildFactory, Factory, SeedFactory
from .definitions import BondIndex, BondProgramme, BondSegment
from .templates import CashBond, SegmentBond


def factories(seeds: Path) -> list[Factory[Any]]:
    """Bond factories, seeds read from `seeds`."""
    return [
        SeedFactory(BondProgramme, seeds / 'bond_programmes.yaml'),
        SeedFactory(BondSegment, seeds / 'bond_segments.yaml'),
        SeedFactory(BondIndex, seeds / 'bond_indices.yaml'),
        BuildFactory(CashBond),
        BuildFactory(SegmentBond),
    ]
