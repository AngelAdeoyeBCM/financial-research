"""Closed classifications used by market fields. Only what a field needs; QLib's codes where it has one."""

from enum import StrEnum


class MarketClass(StrEnum):
    """Development class of a currency; a country takes its currency's."""

    DM = 'dm'
    EM = 'em'
    FRONTIER = 'frontier'


class Corridor(StrEnum):
    """Where a policy rate bounds overnight market rates: ECB DFR floor, MLF ceiling; Fed ON RRP floor."""

    FLOOR = 'floor'
    CEILING = 'ceiling'


class CouponType(StrEnum):
    """Coupon of a bond programme; QLib BondClassification Infl and Floater for the last two."""

    NOMINAL = 'nominal'
    LINKER = 'linker'
    FLOATER = 'floater'


class Rank(StrEnum):
    """Seniority of a bond programme when it is not plain senior unsecured (QLib Seniority). Unset for sovereigns."""

    SECURED = 'secured'
    COVERED = 'covered'
    SENIOR_PREFERRED = 'sp'
    SENIOR_NON_PREFERRED = 'snp'
    TIER2 = 't2'
    AT1 = 'at1'
    SUBORDINATED = 'sub'


class BondSector(StrEnum):
    """What a bond segment holds: many issuers' bonds of one kind (QLib BondClassification Govt, Corp, Muni, Mtge)."""

    GOVT = 'govt'        # several sovereigns in one currency: EGBs
    SSA = 'ssa'          # sovereign-related: supranationals, sub-sovereigns, agencies
    COVERED = 'covered'
    CORP = 'corp'
    MUNI = 'muni'
    MBS = 'mbs'


class RatingBand(StrEnum):
    """Credit quality band of a segment."""

    AAA = 'aaa'
    IG = 'ig'
    HY = 'hy'


class IndexProvider(StrEnum):
    """Publisher of a bond index."""

    BLOOMBERG = 'bloomberg'
    ICE = 'ice'
    IBOXX = 'iboxx'
    JPM = 'jpm'
    FTSE = 'ftse'


class CommodityType(StrEnum):
    """QLib CommodityType."""

    CRUDE = 'crude'
    NATGAS = 'natgas'
    METAL = 'metal'
    POWER = 'power'
    AGRI = 'agri'


class CallPut(StrEnum):
    """Option side. A payer swaption is a call on the rate."""

    CALL = 'call'
    PUT = 'put'


class Form(StrEnum):
    """Contract family of a template."""

    CASH = 'cash'
    FORWARD = 'forward'
    SWAP = 'swap'
    FUTURE = 'future'
    OPTION = 'option'
    REPO = 'repo'


class Shape(StrEnum):
    """How a structure's legs relate; derived from the legs, never declared."""

    CURVE = 'curve'          # one template, two tenors: UST 2s10s
    CALENDAR = 'calendar'    # one template, two contract months
    FLY = 'fly'              # one template, three points: 2s5s10s
    SPREAD = 'spread'        # two templates, one point: 10y swap spread, OAT-Bund 10y
    BOX = 'box'              # two templates, the same two points: SPGB-Bund 5s30s
