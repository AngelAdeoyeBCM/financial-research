"""Templates: a product written on an underlying, the terms its instances share (QLib instrument definition).

    irs:USD.SOFR.1d      IRS on SOFR, fixing 1d (an OIS)
    irs:EUR.EURIBOR.6m   IRS on 6m Euribor
    bond:us_treasury.USD.nominal   cash US Treasuries

A template is an entity because many instances share it: the 5y and 10y SOFR
swaps both reference irs:USD.SOFR.1d. The template type is the product, so
there is no separate product enum.
"""

from typing import ClassVar

from ..enums import Form
from ..identity import Market, MarketType
from .point import PointType


class Template(Market):
    """Abstract. Subclasses set `form` and `point_type`, what pins an instance (a tenor for an IRS)."""

    entity_type = MarketType.TEMPLATE
    form: ClassVar[Form]
    point_type: ClassVar[PointType]
