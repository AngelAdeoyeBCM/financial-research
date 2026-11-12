"""FX templates."""

from ...core.refs import FXPairKey
from ...dates import Tenor
from ..enums import Form
from ..identity import MarketType
from ..instrument import Template


class FXForward(Template):
    """Outright forward (or NDF) on a pair; an instance is pinned by its tenor: EURUSD 3m."""

    entity_type = MarketType.FX_FORWARD
    form = Form.FORWARD
    point_type = Tenor

    pair_id: FXPairKey
