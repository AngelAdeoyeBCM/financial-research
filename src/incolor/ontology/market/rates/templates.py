"""Rates templates: products on a rate index at a fixing tenor.

The index and the fixing tenor both distinguish templates: irs:EUR.ESTR.1d
(an OIS), irs:EUR.EURIBOR.3m and irs:EUR.EURIBOR.6m are three templates.
Overnight vs term needs no key part of its own; it is the index's `is_ois`.
"""

from ...core.refs import RateIndexKey
from ...dates import Tenor
from ..enums import Form
from ..identity import MarketType
from ..instrument import OptionPoint, Template


class IRS(Template):
    """Fixed against floating on an index; an instance is pinned by its tenor: 10y SOFR swap."""

    entity_type = MarketType.IRS
    form = Form.SWAP
    point_type = Tenor

    index_id: RateIndexKey
    fixing: Tenor


class Swaption(Template):
    """Option on an IRS; an instance is pinned by expiry x tenor: 2yx30y."""

    entity_type = MarketType.SWAPTION
    form = Form.OPTION
    point_type = OptionPoint

    index_id: RateIndexKey
    fixing: Tenor
