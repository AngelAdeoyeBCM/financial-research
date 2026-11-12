"""Bond templates."""

from ...core.refs import BondProgrammeKey, BondSegmentKey
from ...dates import Tenor
from ..enums import Form
from ..identity import MarketType
from ..instrument import Template


class CashBond(Template):
    """Cash bonds of a programme; an instance is pinned by its benchmark tenor: 10y UST."""

    entity_type = MarketType.CASH_BOND
    form = Form.CASH
    point_type = Tenor

    programme_id: BondProgrammeKey


class SegmentBond(Template):
    """Cash bonds of a segment, its yield curve; an instance is a tenor on it: 10y AAA MMD, 5y EUR covered."""

    entity_type = MarketType.SEGMENT_BOND
    form = Form.CASH
    point_type = Tenor

    segment_id: BondSegmentKey
