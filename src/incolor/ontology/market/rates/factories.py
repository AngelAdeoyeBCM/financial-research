"""Rates factories."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...core import BuildContext, BuildFactory, Factory, SeedFactory, Unresolved
from ..fx import Currency
from ..identity import MarketType
from .definitions import PolicyRate, RateIndex
from .templates import IRS, Swaption

_DEFAULTS = {'ois': 'default_ois_id', 'ibor': 'default_ibor_id', None: 'default_swap_id'}
"""Which of a currency's default indices a mention means: "EUR OIS", "EUR IBOR swaps", a bare "EUR swap"."""


class IndexTemplateFactory[T: IRS | Swaption](BuildFactory[T]):
    """Fills what a mention leaves out, from the entities it names.

    A currency alone takes one of its default indices; `family` ('ois' or 'ibor') says which, else the bare-swap
    default. An index alone takes its default fixing:

        {'currency_id': 'USD'}                        -> irs:USD.SOFR.1d
        {'currency_id': 'EUR'}                        -> irs:EUR.EURIBOR.6m
        {'currency_id': 'EUR', 'family': 'ois'}       -> irs:EUR.ESTR.1d
        {'currency_id': 'EUR', 'code': 'EURIBOR'}     -> irs:EUR.EURIBOR.6m
        {'index_id': 'EUR.EURIBOR', 'fixing': '3m'}   -> irs:EUR.EURIBOR.3m
    """

    def canonicalise(self, parts: Mapping[str, Any], ctx: BuildContext) -> dict[str, Any]:
        """Index and fixing, defaults filled from the currency and the index."""
        index_id = parts.get('index_id')
        if index_id is None:
            currency = ctx.manager.get(MarketType.CURRENCY.id_of(parts['currency_id']), Currency)
            family = parts.get('family')
            if code := parts.get('code'):
                index_id = f'{currency.key}.{code}'
            elif family not in _DEFAULTS:
                raise Unresolved(f'index family {family!r}: expected ois or ibor')
            elif (index_id := getattr(currency, _DEFAULTS[family])) is None:
                raise Unresolved(f'{currency.id} has no default {family or "swap"} index; name one')
        index = ctx.manager.get(MarketType.RATE_INDEX.id_of(index_id), RateIndex)
        if isinstance(index, PolicyRate):
            raise Unresolved(f'{index.id} is a policy rate, not swapped; swaps reference the overnight fixing')
        return {'index_id': index.key, 'fixing': parts.get('fixing') or index.default_fixing}


def factories(seeds: Path) -> list[Factory[Any]]:
    """Rates factories, seeds read from `seeds`."""
    return [
        SeedFactory(RateIndex, seeds / 'rate_indices.yaml'),
        SeedFactory(PolicyRate, seeds / 'policy_rates.yaml'),
        IndexTemplateFactory(IRS),
        IndexTemplateFactory(Swaption),
    ]
