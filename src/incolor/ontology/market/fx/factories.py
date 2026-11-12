"""FX factories."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...core import BuildContext, BuildFactory, Factory, SeedFactory, Unresolved
from .definitions import Currency, FXPair
from .templates import FXForward


class FXPairFactory(SeedFactory[FXPair]):
    """Resolves a pair named in either order to its market-convention pair: USD/EUR -> fx:EURUSD."""

    def build(self, parts: Mapping[str, Any], ctx: BuildContext) -> FXPair:
        """The seeded pair, trying the parts' order first."""
        try:
            return super().build(parts, ctx)
        except Unresolved:
            if not {'base_id', 'quote_id'} <= parts.keys():
                raise
            return super().build({'base_id': parts['quote_id'], 'quote_id': parts['base_id']}, ctx)


class FXForwardFactory(BuildFactory[FXForward]):
    """Takes the pair as `pair_id` ('USDEUR') or `base_id` + `quote_id`, in either order."""

    def canonicalise(self, parts: Mapping[str, Any], ctx: BuildContext) -> dict[str, Any]:
        """The market-convention pair."""
        if pair_id := parts.get('pair_id'):
            parts = {'base_id': pair_id[:3], 'quote_id': pair_id[3:]}
        pair = ctx.manager.build(FXPair, parts, ctx.as_of)
        return {'pair_id': pair.key}


def factories(seeds: Path) -> list[Factory[Any]]:
    """FX factories, seeds read from `seeds`."""
    return [
        SeedFactory(Currency, seeds / 'currencies.yaml'),
        FXPairFactory(FXPair, seeds / 'fx_pairs.yaml'),
        FXForwardFactory(FXForward),
    ]
