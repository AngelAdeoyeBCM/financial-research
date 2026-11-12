"""Financial research claim extraction ontology, draft v0.2.

Requires: pydantic >= 2.  This is an extraction schema, not an entity
registry, metric taxonomy, or graph persistence model.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().casefold()


class ClaimFunction(StrEnum):
    VIEW = 'view'
    FORECAST = 'forecast'
    RECOMMENDATION = 'recommendation'


class ClaimDomain(StrEnum):
    VALUATION = 'valuation'
    POSITIONING = 'positioning'
    MARKET_PRICE = 'market_price'
    MARKET_EXPECTATIONS = 'market_expectations'
    CORPORATE_FUNDAMENTALS = 'corporate_fundamentals'
    MACROECONOMICS = 'macroeconomics'
    POLICY = 'policy'
    CREDIT_RISK = 'credit_risk'


class ClaimModality(StrEnum):
    ASSERTED = 'asserted'
    HEDGED = 'hedged'
    SPECULATIVE = 'speculative'


class Direction(StrEnum):
    INCREASE = 'increase'
    DECREASE = 'decrease'
    STABLE = 'stable'
    POSITIVE = 'positive'  # level/sign, not necessarily change
    NEGATIVE = 'negative'


class EvaluationCode(StrEnum):
    OVERVALUED = 'overvalued'
    UNDERVALUED = 'undervalued'
    FAIR_VALUE = 'fair_value'
    STRETCHED = 'stretched'
    CROWDED = 'crowded'
    ATTRACTIVE = 'attractive'
    UNATTRACTIVE = 'unattractive'
    STRONG = 'strong'
    WEAK = 'weak'


class EvidenceSpan(StrictModel):
    quote: str = Field(min_length=1, description='Verbatim source text')
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def check_offsets(self):
        if (self.start is None) != (self.end is None):
            raise ValueError('Evidence start and end must both be present or both absent')
        if self.start is not None and self.end <= self.start:
            raise ValueError('Evidence end must be after start')
        return self


class EntityLink(StrictModel):
    surface: str = Field(min_length=1, description='Text referring to an entity')
    entity_id: str | None = None  # Only if resolved against existing registry


TemporalRelation = Literal[
    'as_of', 'at', 'by', 'during', 'from', 'to', 'after', 'before', 'until', 'within', 'since'
]


class TemporalReference(StrictModel):
    relation: TemporalRelation
    value: str = Field(
        min_length=1,
        description="Period, date or event as written; e.g. 'FY28', 'next month', 'the FOMC'",
    )
    normalized: str | None = Field(default=None, description='ISO date/interval if verifiable')


class ConditionClause(StrictModel):
    expression: str = Field(min_length=1, description='Affirmative form; negate via required_truth')
    required_truth: bool = True


class ConditionGroup(StrictModel):
    operator: Literal['and', 'or']
    clauses: list[ConditionClause] = Field(min_length=2)


# A single clause has no Boolean operator; multiple clauses use a group.
Condition = ConditionClause | ConditionGroup

QuantityBasis = Literal[
    'analyst_model', 'analyst_forecast', 'reported', 'market_implied', 'unspecified'
]


class Quantification(StrictModel):
    metric: str = Field(min_length=1, description='Metric name from source, not invented')
    metric_id: str | None = Field(default=None, description='Verified metric registry ID')
    unit: str = Field(min_length=1, description='Seed unit taxonomy; e.g. percent, multiple, GBP')
    value: FiniteFloat | None = None
    min_value: FiniteFloat | None = None
    max_value: FiniteFloat | None = None
    approximate: bool = False
    comparator: Literal['eq', 'lt', 'lte', 'gt', 'gte'] | None = None
    benchmark: str | None = None
    basis: QuantityBasis = 'unspecified'
    temporal: TemporalReference | None = None

    @model_validator(mode='after')
    def check_point_or_range(self):
        point = self.value is not None
        lower = self.min_value is not None
        upper = self.max_value is not None
        if point == (lower or upper):
            raise ValueError('Provide a point value OR both range bounds')
        if lower != upper:
            raise ValueError('A range requires both min_value and max_value')
        if lower and self.min_value > self.max_value:
            raise ValueError('min_value must be <= max_value')
        if self.comparator is not None and not point:
            raise ValueError('Comparators are defined only for point quantities in v0.1')
        return self


class PositioningDetail(StrictModel):
    holder: str | None = Field(
        default=None, description='Who holds the position, as written; null for the market'
    )
    measure: Literal['net', 'gross'] | None = None
    side: Literal['long', 'short'] | None = None
    denominator: str | None = Field(
        default=None, description="What the position is measured against, e.g. 'open interest'"
    )

    @model_validator(mode='after')
    def check_not_empty(self):
        if all(v is None for v in (self.holder, self.measure, self.side, self.denominator)):
            raise ValueError('Provide at least one positioning field or omit the block')
        return self


class ValuationDetail(StrictModel):
    method: str | None = Field(
        default=None, description="Model or approach, e.g. 'short-term valuation model', 'DCF'"
    )
    reference_level: Quantification | None = Field(
        default=None, description='Stated level the claim is measured against, e.g. fair value'
    )

    @model_validator(mode='after')
    def check_not_empty(self):
        if self.method is None and self.reference_level is None:
            raise ValueError('Provide at least one valuation field or omit the block')
        return self


class Evaluation(StrictModel):
    phrase: str = Field(
        min_length=1, description="Exact qualitative descriptor, e.g. 'increasingly stretched'"
    )
    code: EvaluationCode | None = None  # Optional normalization, never required
    benchmark: str | None = None


class AnalyticalAttributes(StrictModel):
    evaluation: Evaluation | None = None
    direction: Direction | None = None
    quantities: list[Quantification] = Field(default_factory=list)
    comparison: str | None = None  # Grounded comparison not otherwise captured
    positioning: PositioningDetail | None = None  # Only with domain == positioning
    valuation: ValuationDetail | None = None  # Only with domain == valuation


class RatingRecommendation(StrictModel):
    kind: Literal['rating'] = 'rating'
    action: Literal['initiate', 'assign', 'upgrade', 'downgrade', 'maintain', 'reiterate']
    rating: str = Field(min_length=1, description='Verbatim rating, e.g. Overweight')
    rating_system: str | None = None


LegSide = Literal['buy', 'sell', 'long', 'short', 'pay', 'receive', 'overweight', 'underweight']
TradeAction = Literal[
    'buy', 'sell', 'open', 'add', 'reduce', 'close', 'maintain', 'hedge', 'switch', 'avoid'
]
BUY_SIDES = frozenset({'buy', 'long', 'overweight'})
SELL_SIDES = frozenset({'sell', 'short', 'underweight'})


class TradeLeg(StrictModel):
    instrument: str = Field(min_length=1)
    side: LegSide | None = None
    entry: Quantification | None = None
    target: Quantification | None = None
    stop: Quantification | None = None


class TradeRecommendation(StrictModel):
    kind: Literal['trade'] = 'trade'
    action: TradeAction
    legs: list[TradeLeg] = Field(default_factory=list)
    # Legs may be empty for broad instructions ('Reduce EM equity exposure').
    # The claim's subject still gives the target exposure.

    @model_validator(mode='after')
    def check_action_matches_sides(self):
        sides = {leg.side for leg in self.legs if leg.side is not None}
        if self.action == 'buy' and not sides <= BUY_SIDES:
            raise ValueError(
                "Action 'buy' allows only buy, long or overweight legs; "
                "use 'open' or 'switch' for opposing legs"
            )
        if self.action == 'sell' and not sides <= SELL_SIDES:
            raise ValueError(
                "Action 'sell' allows only sell, short or underweight legs; "
                "use 'open' or 'switch' for opposing legs"
            )
        return self


RecommendationPayload = Annotated[
    RatingRecommendation | TradeRecommendation, Field(discriminator='kind')
]


class RecommendationAttributes(StrictModel):
    recommendation: RecommendationPayload


class ClaimBase(StrictModel):
    id: str = Field(min_length=1)
    proposition: str = Field(min_length=1, description='Standalone source-faithful proposition')
    subject: str = Field(min_length=1, description='Natural-language subject')
    entities: list[EntityLink] = Field(default_factory=list)
    modality: ClaimModality
    modality_cue: str | None = Field(
        default=None,
        description='Verbatim evidence words that justify hedged/speculative; null if asserted',
    )
    temporal: TemporalReference | None = None
    condition: Condition | None = None
    attributed_to: str | None = Field(
        default=None,
        description="Third party named as the speaker, as written; null for the document's voice",
    )
    evidence: list[EvidenceSpan] = Field(min_length=1)
    extraction_confidence: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode='after')
    def check_modality_cue(self):
        if self.modality == ClaimModality.ASSERTED:
            if self.modality_cue is not None:
                raise ValueError('An asserted claim has no modality_cue; leave it null')
            return self
        if self.modality_cue is None or not self.modality_cue.strip():
            raise ValueError(f"Modality '{self.modality.value}' requires a verbatim modality_cue")
        cue = _norm(self.modality_cue)
        if not any(cue in _norm(span.quote) for span in self.evidence):
            raise ValueError('modality_cue must appear verbatim in an evidence quote')
        return self


class AnalyticalClaim(ClaimBase):
    domain: ClaimDomain
    required_truth: bool = Field(
        default=True,
        description='True if the source affirms the proposition, False if it denies it',
    )
    attributes: AnalyticalAttributes = Field(default_factory=AnalyticalAttributes)

    @model_validator(mode='after')
    def check_domain_detail(self):
        if self.attributes.positioning is not None and self.domain != ClaimDomain.POSITIONING:
            raise ValueError("attributes.positioning requires domain 'positioning'")
        if self.attributes.valuation is not None and self.domain != ClaimDomain.VALUATION:
            raise ValueError("attributes.valuation requires domain 'valuation'")
        return self


class ViewClaim(AnalyticalClaim):
    function: Literal['view'] = 'view'


class ForecastClaim(AnalyticalClaim):
    function: Literal['forecast'] = 'forecast'


class RecommendationClaim(ClaimBase):
    function: Literal['recommendation'] = 'recommendation'
    attributes: RecommendationAttributes
    # No domain: recommendation expresses a rating or advocated exposure action.
    # Underlying valuation / positioning rationale is a separate linked claim.


Claim = Annotated[
    ViewClaim | ForecastClaim | RecommendationClaim,
    Field(discriminator='function'),
]


class RelationshipType(StrEnum):
    IS_SUPPORTING = 'is_supporting'


class ClaimRelationship(StrictModel):
    source_id: str  # the supplementary claim
    target_id: str  # the claim it supports
    type: RelationshipType
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class DocumentMetadata(StrictModel):
    document_id: str = Field(min_length=1)
    title: str | None = None
    publisher: str | None = None
    authors: list[str] = Field(default_factory=list)
    received_at: str | None = Field(
        default=None, description='When the document was received, ISO 8601'
    )


class ClaimExtraction(StrictModel):
    document: DocumentMetadata
    claims: list[Claim] = Field(default_factory=list)
    relationships: list[ClaimRelationship] = Field(default_factory=list)
    coverage_confidence: FiniteFloat = Field(
        ge=0.0,
        le=1.0,
        description=(
            'Self-assessed completeness of claims[] against every eligible claim in the text: '
            '1.0 = nothing eligible missed, about 0.5 = roughly half captured or text partly '
            'unreadable, near 0 = most not processed. Not confidence in any single claim.'
        ),
    )

    @model_validator(mode='after')
    def validate_graph_references(self):
        ids = [c.id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate claim IDs')
        known = set(ids)
        for rel in self.relationships:
            if rel.source_id not in known or rel.target_id not in known:
                raise ValueError('Relationship must link two extracted claims')
            if rel.source_id == rel.target_id:
                raise ValueError('Self-relationships are forbidden')
        return self
