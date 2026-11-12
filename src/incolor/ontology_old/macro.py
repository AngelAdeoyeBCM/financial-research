"""Economy: measures (concepts) and indicators (concrete series).

An indicator is identified by measure x geography x basket, plus a source
when a non-official provider publishes the same series (ADP vs BLS payrolls).
Data releases are indicators, not events. Transforms (YoY, SA, 3m ann.) are
mention-level qualifiers.
"""

from dataclasses import dataclass
from enum import StrEnum

from .base import Entity, Lookup, ref
from .vocab import Category, Frequency

HEADLINE = 'headline'


class MeasureKind(StrEnum):
    ACTIVITY = 'activity'    # GDP, PMIs, surveys, retail sales, housing
    PRICES = 'prices'        # CPI, PCE, PPI, inflation expectations
    LABOUR = 'labour'        # payrolls, unemployment, claims, wages
    MONETARY = 'monetary'    # policy rate, r*, credit, money
    EXTERNAL = 'external'    # trade, current account, reserves, flows
    FISCAL = 'fiscal'        # deficit, debt, borrowing requirement
    FINANCIAL = 'financial'  # term premium, financial conditions


@dataclass(frozen=True, kw_only=True)
class Measure(Entity):
    """The concept (CPI, GDP, policy rate), independent of country."""

    category = Category.MEASURE
    entity_kind = Category.MEASURE

    kind: MeasureKind
    baskets: frozenset[str] = frozenset({HEADLINE})  # variants an indicator may take
    # where the measure exists in one place only: PCE -> US
    default_geography_id: str | None = ref(Category.GEOGRAPHY, required=False)

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.kind,)


@dataclass(frozen=True, kw_only=True)
class Indicator(Entity):
    """A concrete series: measure x geography x basket [x source]."""

    category = Category.INDICATOR
    entity_kind = Category.INDICATOR

    measure_id: str = ref(Category.MEASURE)
    geography_id: str = ref(Category.GEOGRAPHY)
    basket: str = HEADLINE
    source: str | None = ref(Category.ORGANIZATION, required=False)  # only for non-official providers
    frequency: Frequency | None = None

    @property
    def key(self) -> str:
        """Identity from parts, e.g. IND[meas:pce|geo:us|core]."""
        parts = [self.measure_id, self.geography_id, self.basket, *([self.source] if self.source else [])]
        return f'IND[{"|".join(parts)}]'

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + ((self.frequency,) if self.frequency else ())

    def integrity_errors(self, lookup: Lookup) -> list[str]:
        errors = super().integrity_errors(lookup)
        measure = lookup(self.measure_id)
        if isinstance(measure, Measure) and self.basket not in measure.baskets:
            errors.append(
                f'{self.entity_id}: basket {self.basket!r} not in '
                f'{self.measure_id} baskets {sorted(measure.baskets)}'
            )
        return errors
