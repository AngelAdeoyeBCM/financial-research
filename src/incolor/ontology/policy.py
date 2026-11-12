"""Policy tools."""

from .core import Entity, EntityType


class Policy(Entity):
    """A lever set by an authority (ECB APP, Fed QT). Its status is not a field."""

    entity_type = EntityType.POLICY
