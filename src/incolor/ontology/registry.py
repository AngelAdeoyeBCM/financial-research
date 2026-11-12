"""One DefinitionManager over every branch with factories: organizations, dates, then markets (which reference them)."""

from pathlib import Path

from . import geography, organization  # noqa: F401  geography: its types are referenced (country_id) but not seeded
from .core import DefinitionManager, Store
from .dates import meetings
from .market import registry as market

SEEDS = Path(__file__).resolve().parents[3] / 'config' / 'registries'


def ontology_manager(seeds: Path = SEEDS, store: Store | None = None) -> DefinitionManager:
    """A manager with every kind registered and the seed files under `seeds` loaded."""
    manager = DefinitionManager(store)
    for factory in (
        *organization.factories(seeds / 'organization'),
        *meetings.factories(seeds / 'dates'),
        *market.factories(seeds / 'market'),
    ):
        manager.register(factory)
    return manager
