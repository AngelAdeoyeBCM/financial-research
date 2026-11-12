"""Markets: underlyings, the templates written on them, their instances and structures.

    Market
    ├── underlyings   Currency, FXPair, RateIndex (PolicyRate), BondProgramme, BondSegment, BondIndex,
    │                 EquityIndex, Commodity                                                seeded (YAML)
    ├── templates     IRS, Swaption, CashBond, SegmentBond, FXForward                       built on mention
    ├── Instance      template + point: ins:irs:USD.SOFR.1d@10y                            built on mention
    └── Structure     weighted instances: UST 2s10s                                        built on mention

Each kind is an identity type (`identity.py`), a definition (`<asset>/definitions.py`,
`<asset>/templates.py`) and a factory (`<asset>/factories.py`); `registry.market_manager()`
wires them all.
"""

from .bonds import BondIndex, BondProgramme, BondSegment, CashBond, SegmentBond
from .commodity import Commodity
from .enums import (
    BondSector,
    CallPut,
    CommodityType,
    Corridor,
    CouponType,
    Form,
    IndexProvider,
    MarketClass,
    Rank,
    RatingBand,
    Shape,
)
from .equity import EquityIndex
from .fx import Currency, FXForward, FXPair
from .identity import Market, MarketType
from .instrument import Instance, Leg, OptionPoint, Point, Structure, Template, shape
from .rates import IRS, PolicyRate, RateIndex, Swaption

__all__ = [
    'IRS',
    'BondIndex',
    'BondProgramme',
    'BondSector',
    'BondSegment',
    'CallPut',
    'CashBond',
    'Commodity',
    'CommodityType',
    'Corridor',
    'CouponType',
    'Currency',
    'EquityIndex',
    'FXForward',
    'FXPair',
    'Form',
    'IndexProvider',
    'Instance',
    'Leg',
    'Market',
    'MarketClass',
    'MarketType',
    'OptionPoint',
    'Point',
    'PolicyRate',
    'Rank',
    'RateIndex',
    'RatingBand',
    'SegmentBond',
    'Shape',
    'Structure',
    'Swaption',
    'Template',
    'shape',
]
