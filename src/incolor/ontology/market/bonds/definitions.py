"""Bond underlyings: one issuer's programmes, many issuers' segments, and the indices that track them."""

from pydantic import Field

from ...core.refs import BondSegmentKey, CurrencyKey, IssuerKey
from ..enums import BondSector, CouponType, IndexProvider, Rank, RatingBand
from ..identity import Market, MarketType


class BondProgramme(Market):
    """One issuer's bonds in one currency, coupon type and rank: US Treasuries, TIPS, Bunds, KfW EUR.

    Key: bnd:us_treasury.USD.nominal; a non-senior rank is appended (bnd:<bank>.EUR.nominal.t2). The obligor is
    an `Issuer` organization: for a sovereign its debt office or treasury, never the central bank. Whether the
    programme is sovereign, and its country, come from the issuer. Single bond lines (ISIN) are deferred.
    """

    entity_type = MarketType.BOND_PROGRAMME

    obligor_id: IssuerKey
    currency_id: CurrencyKey
    coupon: CouponType = CouponType.NOMINAL
    rank: Rank | None = None


class BondSegment(Market):
    """Many issuers' bonds of one sector in one currency, optionally one rating band: seg:USD.corp.ig, seg:USD.muni.

    What research means by "USD IG corporates", "munis", "EUR covered bonds" or "EGBs": no single obligor.
    """

    entity_type = MarketType.BOND_SEGMENT

    currency_id: CurrencyKey
    sector: BondSector
    rating: RatingBand | None = None


class BondIndex(Market):
    """A provider's bond index, tracking a segment where it tracks one: iBoxx EUR Covered, Bloomberg Municipal.

    Broad indices (Global Agg, WGBI, GBI-EM) span segments and set no `segment_id`.
    """

    entity_type = MarketType.BOND_INDEX

    key: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    provider: IndexProvider
    segment_id: BondSegmentKey | None = None
