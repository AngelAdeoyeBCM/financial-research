"""Ontology definitions for financial research claims."""

from dataclasses import dataclass, field
from enum import StrEnum

from incolor.utils import require_nonempty


class ClaimType(StrEnum):
    VIEW = 'view'
    FORECAST = 'forecast'
    TRADE_IDEA = 'trade_idea'
    POSITIONING = 'positioning'
    DATA_POINT = 'data_point'


@dataclass(frozen=True, slots=True)
class Claim:
    """Canonical financial research claim."""

    claim_id: str
    text: str
    type: ClaimType

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'claim_id',
            require_nonempty(self.claim_id, 'claim_id'),
        )
        object.__setattr__(
            self,
            'text',
            require_nonempty(self.text, 'text'),
        )
        object.__setattr__(
            self,
            'type',
            ClaimType(self.type),
        )


@dataclass(frozen=True, slots=True)
class View(Claim):
    """Qualitative analyst view or opinion."""

    type: ClaimType = field(
        default=ClaimType.VIEW,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class Forecast(Claim):
    """Forward-looking quantitative or qualitative forecast."""

    type: ClaimType = field(
        default=ClaimType.FORECAST,
        init=False,
    )

    metric: str | None = None
    value: str | None = None
    horizon: str | None = None
    previous_value: str | None = None
    consensus_value: str | None = None
    revision_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TradeIdea(Claim):
    """Explicit investment or trading recommendation."""

    type: ClaimType = field(
        default=ClaimType.TRADE_IDEA,
        init=False,
    )

    direction: str | None = None
    instrument_ids: tuple[str, ...] = ()
    entry: str | None = None
    target: str | None = None
    stop: str | None = None
    timeframe: str | None = None
    rationale: str | None = None
    risks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Positioning(Claim):
    """Analyst's view on market or portfolio positioning."""

    type: ClaimType = field(
        default=ClaimType.POSITIONING,
        init=False,
    )

    direction: str | None = None
    instrument_ids: tuple[str, ...] = ()
    rationale: str | None = None
    risks: tuple[str, ...] = ()
    investor_type: str | None = None
    instrument_or_market: str | None = None
    position: str | None = None
    size: str | None = None
    recent_change: str | None = None
    flow_data: str | None = None
    implication: str | None = None


@dataclass(frozen=True, slots=True)
class DataPoint(Claim):
    """Specific data point referenced in research."""

    type: ClaimType = field(
        default=ClaimType.DATA_POINT,
        init=False,
    )

    metric: str | None = None
    value: str | None = None
    source: str | None = None
    comparison: str | None = None
    reference_period: str | None = None
    implication: str | None = None
