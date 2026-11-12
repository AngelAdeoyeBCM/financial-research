"""Draft Currency definition, designed in stages from QLib's `CurrencyDefinition`.

Source: BlueCrest.QR.QLib.Core.Src/Market/Instrument/CurrencyDefinition.cs (archivers :35-77,
`ReadFromArchive` :284-339) and the QCL bundle's 109 `ccy[*]` files (5.4.528). Field names are
QLib's in snake_case; values keep QLib's spelling. Standalone for now: not wired into the
registry and not a subclass of `Entity`.

Stage 1: identity and market structure, plus the central bank link. The other central-bank
properties (meeting currency, meeting count, implementation and roll days) belong on the
central-bank organization.
"""

from dataclasses import dataclass

from .base import ref
from .geography import GeoLevel
from .markets import MarketKind
from .organizations import OrgKind


@dataclass(frozen=True, kw_only=True)
class Currency:
    """One `ccy[CODE]` definition."""

    # QLib CurrencyCode (required, set in 109/109 files). ISO 4217 code, or a QLib pseudo-code
    # for metals (XAU), crypto (XBT), units of account (CLF, UDI) and indices (DXY).
    currency_code: str

    # Ref to the central-bank organization ('org:fed'). Replaces QLib's CentralBankCode string
    # (FED, ECB, CBN; 28/109 files).
    central_bank_id: str | None = ref(OrgKind.CENTRAL_BANK, required=False)

    # Ref to the issuing country or bloc ('geo:us'; EUR -> euro area). From QLib DefaultCountryCode
    # (10/109; metals and crypto -> ZZ = none, UDI -> MX); where unset, QLib derives the first two
    # letters of currency_code. QLib's code is then the geography's own `code`.
    default_country_id: str | None = ref(GeoLevel.COUNTRY, GeoLevel.BLOC, required=False)

    # QLib NonDeliverable (18/109: AOA, ARS, BRL, CLP, CNY, COP, EGP, IDR, INR, KRW, KZT, LKR,
    # MWK, MYR, PEN, PHP, TWD, UAH). Settles as an NDF.
    non_deliverable: bool = False

    # Ref to the onshore twin ('ccy:cny'), set on an offshore currency. From QLib OnShoreCcyCode
    # (1/109: CNH -> CNY). Replaces QLib's IsOnShore flag, which no bundle file sets.
    onshore_ccy_id: str | None = ref(MarketKind.CURRENCY, required=False)

    @property
    def is_offshore(self) -> bool:
        """True for an offshore currency (CNH), i.e. one that names its onshore twin."""
        return self.onshore_ccy_id is not None


@dataclass(frozen=True, kw_only=True)
class RateIndex():
    """Reference rate and the swap/OIS curve priced off it (SOFR, €STR, CDI).

    `ref_code` is QLib's reference index within the currency, so the QLib id is
    idx[<currency code>,<ref_code>]. QLib codes are per currency and not always
    the market name: CORRA is idx[CAD,OIS], FR007 is idx[CNY,REPO]. None where
    QLib has no index (DR001, LPR).
    """
    ref_code: str | None = None

    def qlib_id(self, lookup: Lookup) -> str | None:
        """idx[USD,SOFR]."""
        ccy = _code(lookup, self.currency_id)
        return f'idx[{ccy},{self.ref_code}]' if ccy and self.ref_code else None
