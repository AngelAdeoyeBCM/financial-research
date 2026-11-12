"""People."""

from .core import Entity, EntityType


class Person(Entity):
    """A named individual: central bankers, politicians, analysts."""

    entity_type = EntityType.PERSON
