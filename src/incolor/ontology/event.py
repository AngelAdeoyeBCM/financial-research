"""Events."""

from .core import Entity, EntityType


class Event(Entity):
    """Recurring series (FOMC meeting) or named one-off events.

    A dated occurrence is the series plus a date from the mention. Data
    releases are indicators, not events.
    """

    entity_type = EntityType.EVENT
