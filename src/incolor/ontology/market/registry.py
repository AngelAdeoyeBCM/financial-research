"""Every market factory: the single list of what the market branch can make."""

from pathlib import Path
from typing import Any

from ..core import Factory
from .bonds import factories as bonds
from .commodity import factories as commodity
from .equity import factories as equity
from .fx import factories as fx
from .instrument import InstanceFactory, StructureFactory
from .rates import factories as rates


def factories(seeds: Path) -> list[Factory[Any]]:
    """Market factories, seeds read from the asset folders under `seeds` (config/registries/market)."""
    return [
        *fx.factories(seeds / 'fx'),
        *rates.factories(seeds / 'rates'),
        *bonds.factories(seeds / 'bonds'),
        *equity.factories(seeds / 'equity'),
        *commodity.factories(seeds / 'commodity'),
        InstanceFactory(),
        StructureFactory(),
    ]
