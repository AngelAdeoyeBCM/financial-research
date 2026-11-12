"""Structures: weighted instances traded as one (UST 2s10s, OAT-Bund 10y, 10y SOFR swap spread).

One class for every shape. The shape (curve, fly, spread, ...) is derived from
how the legs' templates and points relate, never declared:

    +1 × ins:bond:us_treasury.USD.nominal@10y      one template, two tenors -> CURVE
    -1 × ins:bond:us_treasury.USD.nominal@2y

Legs are kept in canonical (id) order, so the key does not depend on the order
a mention names them in. Weights carry the direction.
"""

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...core import BuildContext, BuildFactory, DefinitionManager, Unresolved
from ...core.refs import EntityId
from ...dates import ContractMonth
from ..enums import Shape
from ..identity import Market, MarketType
from .instance import Instance


class Leg(BaseModel):
    """An instance and its weight: +1 long, -1 short, +2 a fly's belly."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    instance_id: EntityId
    weight: float

    def __str__(self) -> str:
        return f'{self.weight:+g}*{self.instance_id}'


class Structure(Market):
    """Two or more weighted instances."""

    entity_type = MarketType.STRUCTURE

    legs: tuple[Leg, ...] = Field(min_length=2)


class StructureFactory(BuildFactory[Structure]):
    """Orders legs canonically and checks each names a stored instance, once."""

    def __init__(self) -> None:
        super().__init__(Structure)

    def canonicalise(self, parts: Mapping[str, Any], ctx: BuildContext) -> dict[str, Any]:
        """Legs in id order, each a stored instance."""
        legs = sorted((Leg.model_validate(leg) for leg in parts['legs']), key=lambda leg: leg.instance_id)
        ids = [leg.instance_id for leg in legs]
        if len(set(ids)) != len(ids):
            raise Unresolved(f'a structure names each instance once: {ids}')
        for instance_id in ids:
            ctx.manager.get(instance_id, Instance)
        return {'legs': tuple(legs)}


def shape(structure: Structure, manager: DefinitionManager) -> Shape | None:
    """How the legs relate; None for a combination with no name."""
    instances = [manager.get(leg.instance_id, Instance) for leg in structure.legs]
    points: dict[str, set[str]] = defaultdict(set)
    for instance in instances:
        points[instance.template_id].add(str(instance.point))
    if len(points) == 1:
        if len(instances) == 3:
            return Shape.FLY
        if len(instances) == 2:
            return Shape.CALENDAR if all(isinstance(i.point, ContractMonth) for i in instances) else Shape.CURVE
    if len(points) == 2:
        first, second = points.values()
        if first == second and len(first) == 1:
            return Shape.SPREAD
        if first == second and len(first) == 2:
            return Shape.BOX
    return None
