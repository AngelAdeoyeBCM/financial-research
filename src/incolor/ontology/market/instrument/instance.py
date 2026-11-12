"""Instances: a template pinned by a point, the thing a mention resolves to (QLib instrument instance).

    "10y SOFR swap" -> {template_id: irs:USD.SOFR.1d, point: 10y} -> ins:irs:USD.SOFR.1d@10y

Instances are stored on first mention, not seeded. Mentions that resolve to
the same parts get the same id; mentions of one template at different points
share `template_id`.
"""

from collections.abc import Mapping
from typing import Any

from ...core import BuildContext, BuildFactory
from ...core.refs import EntityId
from ..identity import Market, MarketType
from .point import Point
from .template import Template


class Instance(Market):
    """One point on a template: the 10y SOFR swap, a 2yx30y EUR swaption."""

    entity_type = MarketType.INSTANCE

    template_id: EntityId
    point: Point


class InstanceFactory(BuildFactory[Instance]):
    """Reads the point as the template's point type: '120m' on an IRS is 10y; a tenor on a swaption is unresolved."""

    def __init__(self) -> None:
        super().__init__(Instance)

    def canonicalise(self, parts: Mapping[str, Any], ctx: BuildContext) -> dict[str, Any]:
        """The stored template's id and the point read as its point type."""
        template = ctx.manager.get(parts['template_id'], Template)
        return {'template_id': template.id, 'point': template.point_type.model_validate(parts['point'])}
