"""Markets: the underlyings research prices and trades.

Only underlyings live in the registry. Tenor, form and structure
("10y", "payer spread", "OAT-Bund") are built per mention, see
`instruments`.

Every kind has a fixed Bloomberg yellow key and, where the firm's QLib
library has one, builds its QLib identifier from its own fields
(`qlib_id`). Classifications use QLib's own enums (`qlib_enums`).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from .base import Entity, Lookup, WikidataMap, ref
from .geography import GeoLevel
from .organizations import OrgKind
from .qlib_enums import BondClassification, CommodityType, IndexIdentifier, MarketType, YellowKey
from .vocab import Category


class AssetClass(StrEnum):
    """What an index tracks."""

    FX = 'fx'
    RATES = 'rates'
    CREDIT = 'credit'
    EQUITY = 'equity'
    COMMODITY = 'commodity'

    @property
    def market_type(self) -> MarketType | None:
        """QLib curve market; QLib only separates rates and FX."""
        return {AssetClass.RATES: MarketType.RATES_MARKET, AssetClass.FX: MarketType.FX_MARKET}.get(self)


def qlib_definition_name(qlib_id: str) -> str:
    """File name of a QLib definition: QLib writes qualifiers `key:value`, its files `key=value`.

    ccy[USD] -> ccy[USD]; fx[EUR,cc:USD] -> fx[EUR,cc=USD].
    """
    return qlib_id.replace(':', '=')


class MarketKind(StrEnum):
    CURRENCY = 'currency'
    FX_PAIR = 'fx_pair'
    RATE_INDEX = 'rate_index'
    BOND = 'bond'  # family label carried by both bond kinds below
    SOVEREIGN_BOND = 'sovereign_bond'
    NON_SOVEREIGN_BOND = 'non_sovereign_bond'
    INDEX = 'index'
    COMMODITY = 'commodity'


class BondSegment(StrEnum):
    """Coupon type; inflation-linked and floating map to QLib's Infl and Floater classes."""

    NOMINAL = 'nominal'
    INFLATION_LINKED = 'inflation_linked'
    FLOATING = 'floating'  # FRNs, CCTeu


_SEGMENT_CLASS = {
    BondSegment.INFLATION_LINKED: BondClassification.INFL,
    BondSegment.FLOATING: BondClassification.FLOATER,
}


class IssuerKind(StrEnum):
    """Who issues a non-sovereign bond."""

    AGENCY = 'agency'    # KfW, CADES
    SUPRA = 'supra'      # EU, EIB, World Bank
    SUBSOV = 'subsov'    # German Laender, LGFVs
    CORP = 'corp'


def _issuer_outside_geography(entity: Entity, lookup: Lookup) -> list[str]:
    """When both are set, the issuer must sit in the entity's own geography
    (Fed in the US, UK DMO in the UK)."""
    issuer_id, geography_id = getattr(entity, 'issuer_id'), getattr(entity, 'geography_id')
    if issuer_id is None or geography_id is None:
        return []
    issuer = lookup(issuer_id)
    if issuer is not None and dict(issuer.links).get('geography_id') != geography_id:
        return [f'{entity.entity_id}: issuer {issuer_id!r} is not in {geography_id!r}']
    return []


def _code(lookup: Lookup, entity_id: str | None) -> str | None:
    """`code` of a referenced currency or geography, if it has one."""
    target = lookup(entity_id) if entity_id else None
    return getattr(target, 'code', None)


@dataclass(frozen=True, kw_only=True)
class Market(Entity):
    """Abstract. Each concrete kind fixes its `yellow_key` and builds its own `qlib_id`."""

    category = Category.MARKET
    entity_kind: ClassVar[MarketKind]
    yellow_key: ClassVar[YellowKey]  # Bloomberg market sector, one per kind: Govt for UST, Index for SOFR

    def qlib_id(self, lookup: Lookup) -> str | None:
        """QLib identifier from this market's fields and the codes of what it refers to.

        None where QLib has no equivalent. See `qlib_definition_name` for the file name.
        """
        return None

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.entity_kind, self.yellow_key)


@dataclass(frozen=True, kw_only=True)
class Currency(Market):
    """`geography_id` is the issuing jurisdiction (euro -> euro area), not
    every place the currency is used (Ecuador uses USD)."""

    entity_kind = MarketKind.CURRENCY
    yellow_key = YellowKey.CURNCY

    code: str  # ISO 4217
    geography_id: str = ref(
        Category.GEOGRAPHY, wikidata=WikidataMap('P1001', fallback='P562/P1001')
    )
    issuer_id: str = ref(Category.ORGANIZATION, wikidata=WikidataMap('P562'))  # central bank

    def qlib_id(self, lookup: Lookup) -> str | None:
        """ccy[USD]."""
        return f'ccy[{self.code}]'

    @property
    def surface_forms(self) -> tuple[str, ...]:
        return super().surface_forms + (self.code,)

    def integrity_errors(self, lookup: Lookup) -> list[str]:
        return super().integrity_errors(lookup) + _issuer_outside_geography(self, lookup)


@dataclass(frozen=True, kw_only=True)
class FXPair(Market):
    """Named in market convention (EURUSD, USDJPY)."""

    entity_kind = MarketKind.FX_PAIR
    yellow_key = YellowKey.CURNCY

    base_id: str = ref(MarketKind.CURRENCY)
    quote_id: str = ref(MarketKind.CURRENCY)

    def _validate(self) -> None:
        if self.base_id == self.quote_id:
            raise ValueError(f'{self.entity_id}: base and quote must differ')

    def qlib_id(self, lookup: Lookup) -> str | None:
        """fx[EUR,cc:USD]: base, then quote currency code."""
        base, quote = _code(lookup, self.base_id), _code(lookup, self.quote_id)
        return f'fx[{base},cc:{quote}]' if base and quote else None

    @property
    def surface_forms(self) -> tuple[str, ...]:
        forms = super().surface_forms
        if len(self.name) == 6:
            forms += (f'{self.name[:3]}/{self.name[3:]}',)
        return forms


@dataclass(frozen=True, kw_only=True)
class _CurrencyMarket(Market):
    """Rates markets must name their currency."""

    currency_id: str = ref(MarketKind.CURRENCY)


@dataclass(frozen=True, kw_only=True)
class RateIndex(_CurrencyMarket):
    """Reference rate and the swap/OIS curve priced off it (SOFR, €STR, CDI).

    `ref_code` is QLib's reference index within the currency, so the QLib id is
    idx[<currency code>,<ref_code>]. QLib codes are per currency and not always
    the market name: CORRA is idx[CAD,OIS], FR007 is idx[CNY,REPO]. None where
    QLib has no index (DR001, LPR).
    """

    entity_kind = MarketKind.RATE_INDEX
    yellow_key = YellowKey.INDEX

    ref_code: str | None = None

    def qlib_id(self, lookup: Lookup) -> str | None:
        """idx[USD,SOFR]."""
        ccy = _code(lookup, self.currency_id)
        return f'idx[{ccy},{self.ref_code}]' if ccy and self.ref_code else None


@dataclass(frozen=True, kw_only=True)
class Bond(_CurrencyMarket):
    """Abstract: one obligor's bond curve (Bunds, TIPS, KfW, EU bonds), not a single line."""

    segment: BondSegment = BondSegment.NOMINAL

    def qlib_id(self, lookup: Lookup) -> str | None:
        """bndcnv[US,Infl,USD]: country code of `geography_id`, `bond_class`, currency code."""
        country = _code(lookup, getattr(self, 'geography_id', None))
        ccy = _code(lookup, self.currency_id)
        return f'bndcnv[{country},{self.bond_class},{ccy}]' if country and ccy else None

    @property
    def obligor_id(self) -> str:
        """Whose credit the bond is: the sovereign geography or the issuing organization."""
        raise NotImplementedError

    def _issuer_class(self) -> BondClassification:
        """QLib class of the issuer's nominal bonds."""
        raise NotImplementedError

    @property
    def bond_class(self) -> BondClassification:
        """QLib class in bndcnv[country,class,ccy]: Infl/Floater by segment, else the issuer's class."""
        return _SEGMENT_CLASS.get(self.segment) or self._issuer_class()

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (MarketKind.BOND, self.segment, self.bond_class)


@dataclass(frozen=True, kw_only=True)
class SovereignBond(Bond):
    """A government's own curve; the obligor is the country or bloc itself.

    `issuer_id` optionally names the debt office (US Treasury, UK DMO) and must
    be a government body of that geography.
    """

    entity_kind = MarketKind.SOVEREIGN_BOND
    yellow_key = YellowKey.GOVT

    geography_id: str = ref(GeoLevel.COUNTRY, GeoLevel.BLOC)
    issuer_id: str | None = ref(OrgKind.GOVERNMENT, required=False)

    @property
    def obligor_id(self) -> str:
        return self.geography_id

    def _issuer_class(self) -> BondClassification:
        return BondClassification.GOVT

    def integrity_errors(self, lookup: Lookup) -> list[str]:
        return super().integrity_errors(lookup) + _issuer_outside_geography(self, lookup)


@dataclass(frozen=True, kw_only=True)
class NonSovereignBond(Bond):
    """Agencies, supras, sub-sovereigns and corporates: the obligor is an organization.

    Bloomberg lists these under Corp. QLib classes supras with sovereigns
    (bndcnv[EU,Govt,EUR]), so their `bond_class` is Govt.
    """

    entity_kind = MarketKind.NON_SOVEREIGN_BOND
    yellow_key = YellowKey.CORP

    issuer_id: str = ref(Category.ORGANIZATION)
    issuer_kind: IssuerKind
    geography_id: str | None = ref(Category.GEOGRAPHY, required=False)  # home market, for filtering

    @property
    def obligor_id(self) -> str:
        return self.issuer_id

    def _issuer_class(self) -> BondClassification:
        return BondClassification.GOVT if self.issuer_kind is IssuerKind.SUPRA else BondClassification.CORP

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.issuer_kind,)

    def integrity_errors(self, lookup: Lookup) -> list[str]:
        return super().integrity_errors(lookup) + _issuer_outside_geography(self, lookup)


@dataclass(frozen=True, kw_only=True)
class Index(Market):
    """`code` is the Bloomberg ticker root (SPX, DXY, MXWO) or, for credit,
    QLib's CdsIndexName (CDX.NA.IG, iTraxx Europe)."""

    entity_kind = MarketKind.INDEX
    yellow_key = YellowKey.INDEX

    asset_class: AssetClass
    code: str | None = None

    def qlib_id(self, lookup: Lookup) -> str | None:
        """eqidx[SPX] for equity indices QLib defines; ccy[DXY] for FX (QLib prices DXY as a currency).

        Credit needs the series, known only per mention, so it has no market-level id.
        """
        if self.code and self.asset_class is AssetClass.EQUITY and self.code in IndexIdentifier:
            return f'eqidx[{self.code}]'
        if self.code and self.asset_class is AssetClass.FX:
            return f'ccy[{self.code}]'
        return None

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.asset_class,)

    @property
    def surface_forms(self) -> tuple[str, ...]:
        return super().surface_forms + ((self.code,) if self.code else ())


@dataclass(frozen=True, kw_only=True)
class Commodity(Market):
    """QLib prices most commodities as a reference index in a currency
    (idx[USD,WTI]: set `currency_id` and `ref_code`) and precious metals as
    currencies (ccy[XAU]: set the ISO 4217 `code`). Umbrella terms ('crude
    oil') name no single benchmark and set neither."""

    entity_kind = MarketKind.COMMODITY
    yellow_key = YellowKey.COMDTY

    commodity_type: CommodityType
    code: str | None = None
    currency_id: str | None = ref(MarketKind.CURRENCY, required=False)
    ref_code: str | None = None

    def _validate(self) -> None:
        if (self.currency_id is None) != (self.ref_code is None):
            raise ValueError(f'{self.entity_id}: currency_id and ref_code go together')
        if self.code is not None and self.ref_code is not None:
            raise ValueError(f'{self.entity_id}: a commodity is a currency code or a reference index, not both')

    def qlib_id(self, lookup: Lookup) -> str | None:
        """idx[USD,WTI], or ccy[XAU] for a precious metal."""
        if self.code:
            return f'ccy[{self.code}]'
        ccy = _code(lookup, self.currency_id)
        return f'idx[{ccy},{self.ref_code}]' if ccy and self.ref_code else None

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.commodity_type,)

    @property
    def surface_forms(self) -> tuple[str, ...]:
        return super().surface_forms + ((self.code,) if self.code else ())
