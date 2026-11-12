"""Forms and products: what contract an instrument leg is.

`Form` is the contract family (cash, forward, swap, future, option, repo).
`Product` is the specific contract, limited to what Rates/FX research trades
and talks about; each carries its QLib instrument keyword where QLib has one,
so a leg can be matched to the firm's library. Add a product here (from QLib's
keyword list) only when research starts using it.

An underlying and a form usually imply the product (rate index + swap -> IRS,
bond + future -> bond future); a leg names its product only when they don't
(a meeting-dated OIS rather than a vanilla one).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .qlib_enums import AssetType, InstrumentCategory


class Form(StrEnum):
    """Contract family."""

    CASH = 'cash'        # bonds, FX spot, rate fixings, index and commodity levels
    FORWARD = 'forward'  # FRAs, FX outrights and NDFs
    SWAP = 'swap'        # IRS/OIS, meeting-dated OIS, inflation swaps, FX swaps
    FUTURE = 'future'
    OPTION = 'option'    # swaptions, FX options, options on futures
    REPO = 'repo'


class Underlying(StrEnum):
    """What a leg is written on."""

    RATE_INDEX = 'rate_index'
    BOND = 'bond'
    FX = 'fx'                # an FX pair or a currency
    INFLATION = 'inflation'  # an inflation indicator (CPI, HICPx)
    INDEX = 'index'          # DXY, MOVE, SPX, iTraxx
    COMMODITY = 'commodity'
    CURVE = 'curve'          # a curve spread, for CMS spread options


class Product(StrEnum):
    """Specific contract; `spec` gives its form, underlyings and QLib keyword."""

    # rates
    DEPOSIT = 'deposit'                        # the cash rate or fixing
    FRA = 'fra'
    IRS = 'irs'                                # incl. OIS
    MEETING_SWAP = 'meeting_swap'              # OIS dated to a central-bank meeting
    RATE_FUTURE = 'rate_future'                # STIR futures
    RATE_FUTURE_OPTION = 'rate_future_option'
    SWAPTION = 'swaption'
    CMS_SPREAD_OPTION = 'cms_spread_option'    # option on a curve spread
    # bonds
    CASH_BOND = 'cash_bond'
    BOND_FUTURE = 'bond_future'
    BOND_FUTURE_OPTION = 'bond_future_option'
    REPO = 'repo'
    # FX
    FX_SPOT = 'fx_spot'
    FX_FORWARD = 'fx_forward'                  # incl. NDFs
    FX_SWAP = 'fx_swap'
    FX_OPTION = 'fx_option'
    # inflation
    INFLATION_SWAP = 'inflation_swap'
    # levels of other subjects research cites
    INDEX_LEVEL = 'index_level'
    COMMODITY_SPOT = 'commodity_spot'

    @property
    def spec(self) -> 'ProductSpec':
        """Form, underlyings and QLib keyword of this product."""
        return PRODUCTS[self]

    @property
    def form(self) -> Form:
        """Contract family this product belongs to."""
        return PRODUCTS[self].form

    @classmethod
    def default(cls, underlying: Underlying, form: Form, *, on_future: bool = False) -> 'Product | None':
        """Product implied by an underlying and form; options with a futures contract are options on that future."""
        if form is Form.OPTION and on_future:
            return _FUTURE_OPTIONS.get(underlying)
        return _DEFAULTS.get((underlying, form))


@dataclass(frozen=True)
class ProductSpec:
    """What a product is, in QLib's terms.

    `qlib` is the QLib instrument keyword; `asset_type` QLib's AssetType where it has one;
    `category` how QLib quotes a rate index curve point in this product; `listed` products
    take an exchange contract code (TYM4).
    """

    form: Form
    underlyings: frozenset[Underlying]
    qlib: str | None
    asset_type: AssetType | None = None
    category: InstrumentCategory | None = None
    listed: bool = False


_U = Underlying
_A = AssetType


def _spec(form: Form, *on: Underlying, qlib: str | None, **kwargs: object) -> ProductSpec:
    return ProductSpec(form, frozenset(on), qlib, **kwargs)  # type: ignore[arg-type]


PRODUCTS: Mapping[Product, ProductSpec] = MappingProxyType({
    Product.DEPOSIT: _spec(Form.CASH, _U.RATE_INDEX, qlib='csh', category=InstrumentCategory.CASH),
    Product.FRA: _spec(Form.FORWARD, _U.RATE_INDEX, qlib='fra'),
    Product.IRS: _spec(
        Form.SWAP, _U.RATE_INDEX, qlib='irs', asset_type=_A.INTEREST_RATE_SWAP, category=InstrumentCategory.SWAP
    ),
    Product.MEETING_SWAP: _spec(Form.SWAP, _U.RATE_INDEX, qlib='cbs'),
    Product.RATE_FUTURE: _spec(
        Form.FUTURE, _U.RATE_INDEX, qlib='rf', asset_type=_A.INTEREST_RATE_FUTURE,
        category=InstrumentCategory.IR_FUTURE, listed=True,
    ),
    Product.RATE_FUTURE_OPTION: _spec(Form.OPTION, _U.RATE_INDEX, qlib='irfo', listed=True),
    Product.SWAPTION: _spec(Form.OPTION, _U.RATE_INDEX, qlib='swpo'),
    Product.CMS_SPREAD_OPTION: _spec(Form.OPTION, _U.CURVE, qlib='cmsspo'),
    Product.CASH_BOND: _spec(Form.CASH, _U.BOND, qlib='bond', asset_type=_A.BOND),
    Product.BOND_FUTURE: _spec(Form.FUTURE, _U.BOND, qlib='bf', asset_type=_A.BOND_FUTURE, listed=True),
    Product.BOND_FUTURE_OPTION: _spec(Form.OPTION, _U.BOND, qlib='bfo', listed=True),
    Product.REPO: _spec(Form.REPO, _U.BOND, qlib='repo'),
    Product.FX_SPOT: _spec(Form.CASH, _U.FX, qlib='fx'),
    Product.FX_FORWARD: _spec(Form.FORWARD, _U.FX, qlib='fxf', asset_type=_A.FX_FWD),
    Product.FX_SWAP: _spec(Form.SWAP, _U.FX, qlib='fxswp'),
    Product.FX_OPTION: _spec(Form.OPTION, _U.FX, qlib='fxo'),
    Product.INFLATION_SWAP: _spec(Form.SWAP, _U.INFLATION, qlib='ins', asset_type=_A.INFLATION_SWAP),
    Product.INDEX_LEVEL: _spec(Form.CASH, _U.INDEX, qlib=None),
    Product.COMMODITY_SPOT: _spec(Form.CASH, _U.COMMODITY, qlib=None),
})

# (underlying, form) -> the product a bare mention means. Absent: name the product, or it isn't covered.
_DEFAULTS: Mapping[tuple[Underlying, Form], Product] = MappingProxyType({
    (_U.RATE_INDEX, Form.CASH): Product.DEPOSIT,
    (_U.RATE_INDEX, Form.FORWARD): Product.FRA,
    (_U.RATE_INDEX, Form.SWAP): Product.IRS,
    (_U.RATE_INDEX, Form.FUTURE): Product.RATE_FUTURE,
    (_U.RATE_INDEX, Form.OPTION): Product.SWAPTION,
    (_U.BOND, Form.CASH): Product.CASH_BOND,
    (_U.BOND, Form.FUTURE): Product.BOND_FUTURE,
    (_U.BOND, Form.REPO): Product.REPO,
    (_U.FX, Form.CASH): Product.FX_SPOT,
    (_U.FX, Form.FORWARD): Product.FX_FORWARD,
    (_U.FX, Form.SWAP): Product.FX_SWAP,
    (_U.FX, Form.OPTION): Product.FX_OPTION,
    (_U.INFLATION, Form.SWAP): Product.INFLATION_SWAP,
    (_U.INDEX, Form.CASH): Product.INDEX_LEVEL,
    (_U.COMMODITY, Form.CASH): Product.COMMODITY_SPOT,
    (_U.CURVE, Form.OPTION): Product.CMS_SPREAD_OPTION,
})

# Options written on a futures contract (SFRZ6 calls, TYM4 puts), by underlying.
_FUTURE_OPTIONS: Mapping[Underlying, Product] = MappingProxyType({
    _U.RATE_INDEX: Product.RATE_FUTURE_OPTION,
    _U.BOND: Product.BOND_FUTURE_OPTION,
})
