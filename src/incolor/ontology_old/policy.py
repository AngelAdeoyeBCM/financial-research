"""Policy tools: levers an authority sets (PEPP, TPI, QT, VAT, gilt remit).

A tool's setting or status (expanded, cut, ended) is a state, not part of
the entity. Policy rates are indicators; the meetings and budgets that
decide tools are events.
"""

from dataclasses import dataclass
from enum import StrEnum

from .base import Entity, ref
from .vocab import Category


class PolicyDomain(StrEnum):
    MONETARY = 'monetary'
    MACROPRUDENTIAL = 'macroprudential'
    FISCAL = 'fiscal'


class PolicyKind(StrEnum):
    ASSET_PURCHASE = 'asset_purchase'              # APP, PEPP, QE
    BALANCE_SHEET_RUNOFF = 'balance_sheet_runoff'  # QT, active gilt sales
    LENDING_FACILITY = 'lending_facility'          # LTRO, MLF, relending
    BACKSTOP = 'backstop'                          # TPI, OMT
    LIQUIDITY_OPERATION = 'liquidity_operation'    # OMOs, repo, RRP
    RESERVE_REQUIREMENT = 'reserve_requirement'    # RRR
    FX_INTERVENTION = 'fx_intervention'
    YIELD_CURVE_CONTROL = 'yield_curve_control'
    MACROPRUDENTIAL = 'macroprudential'            # eSLR, LTV caps
    TAX = 'tax'
    TRANSFER = 'transfer'                          # subsidies, Warm Homes Discount
    PRICE_CONTROL = 'price_control'                # Ofgem cap
    DEBT_MANAGEMENT = 'debt_management'            # buybacks, gilt remit, LGB quotas

    @property
    def domain(self) -> PolicyDomain:
        if self is PolicyKind.MACROPRUDENTIAL:
            return PolicyDomain.MACROPRUDENTIAL
        if self in _FISCAL:
            return PolicyDomain.FISCAL
        return PolicyDomain.MONETARY


_FISCAL = frozenset({PolicyKind.TAX, PolicyKind.TRANSFER, PolicyKind.PRICE_CONTROL, PolicyKind.DEBT_MANAGEMENT})


@dataclass(frozen=True, kw_only=True)
class PolicyTool(Entity):
    """A lever set by an authority."""

    category = Category.POLICY
    entity_kind = Category.POLICY

    kind: PolicyKind
    authority_id: str = ref(Category.ORGANIZATION)

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.kind, self.kind.domain)
