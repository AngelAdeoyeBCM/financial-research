"""QLib identifiers of market definitions.

QLib's quirks stay here, not on the definitions: its reference-index codes
differ from ours in places (TONA is TONAROIS, fed funds is OIS), it prices
precious metals as currencies (ccy[XAU]) and other commodities as indices in
a currency (idx[USD,WTI]), and keys a bond curve by the issuer's country and
class (bndcnv[DE,Govt,EUR], the EU as bndcnv[EU,Govt,EUR]). Only id forms
confirmed against the QLib definitions bundle are emitted; anything else is
None. Templates and instances have none: QLib builds those per pricing request.
"""

from ...core import DefinitionManager, Entity
from ...organization import CentralBank, Issuer, SovereignIssuer, Supranational
from ..bonds import BondProgramme
from ..commodity import Commodity
from ..enums import CouponType
from ..equity import EquityIndex
from ..fx import Currency, FXPair
from ..rates import RateIndex

_REFERENCE_INDEX = {
    'USD.SOFR': 'SOFR', 'USD.FEDFUNDS': 'OIS', 'EUR.ESTR': 'ESTR', 'EUR.EURIBOR': 'EURIBOR', 'GBP.SONIA': 'SONIA',
    'JPY.TONA': 'TONAROIS', 'CHF.SARON': 'SARON', 'CAD.CORRA': 'OIS', 'AUD.AONIA': 'OIS', 'AUD.BBSW': 'BBSW',
    'NZD.BKBM': 'BANKBILL', 'SEK.SWESTR': 'SWESTR', 'SEK.STIBOR': 'STIBOR', 'NOK.NOWA': 'NOWA', 'NOK.NIBOR': 'NIBOR',
    'CNY.FR007': 'REPO', 'CNY.SHIBOR': 'SHIBOR', 'CNH.HIBOR': 'HIBOR', 'HKD.HIBOR': 'HIBOR', 'HKD.HONIA': 'HONIA',
    'KRW.CD91': 'CD', 'TWD.TAIBOR': 'TAIBOR', 'INR.MIBOR': 'OIS', 'IDR.JIBOR': 'JIBOR', 'MYR.KLIBOR': 'KLIBOR',
    'SGD.SORA': 'SORA', 'THB.THOR': 'THORON', 'BRL.CDI': 'CDI', 'MXN.TIIE': 'TIIE', 'MXN.TIIEFONDEO': 'MXIBTIEF',
    'CLP.CAMARA': 'CAMARA', 'COP.IBR': 'OIS', 'ZAR.JIBAR': 'JIBR', 'ZAR.ZARONIA': 'ZARONIA', 'TRY.TLREF': 'TLREF',
    'PLN.WIBOR': 'WIBOR', 'HUF.BUBOR': 'BUBOR', 'CZK.PRIBOR': 'PRIBOR', 'ILS.TELBOR': 'TELBOR', 'ILS.SHIR': 'SHIRON',
    # policy rates QLib defines; ECBR floats off €STR, so it is taken to be the deposit rate (the floor)
    'USD.FDTR': 'FDTR', 'USD.IORB': 'IOER', 'EUR.DFR': 'ECBR', 'GBP.BANKRATE': 'BASE', 'CAD.BOCR': 'BOCR',
    'AUD.CASHRATE': 'CASH', 'NZD.OCR': 'CASH', 'BRL.SELIC': 'SELIC', 'CLP.TPM': 'TPM',
}
"""Our rate index key -> QLib ReferenceIndex code (the old registry's confirmed `ref_code`s). Absent: no QLib index."""

_CENTRAL_BANK_CODE = {
    'CB.US': 'FED', 'CB.EZ': 'ECB', 'CB.GB': 'BOE', 'CB.JP': 'BOJ', 'CB.CH': 'SNB', 'CB.CA': 'BOC', 'CB.AU': 'RBA',
    'CB.NZ': 'RBZ', 'CB.SE': 'SRB', 'CB.NO': 'CBN', 'CB.KR': 'BOK', 'CB.IN': 'CBI', 'CB.MY': 'BNM', 'CB.TH': 'BOT',
    'CB.BR': 'CBB', 'CB.MX': 'BDM', 'CB.CL': 'BCC', 'CB.CO': 'BRC', 'CB.ZA': 'SAB', 'CB.TR': 'CBT', 'CB.PL': 'NBP',
    'CB.HU': 'NBH', 'CB.CZ': 'CNB', 'CB.IL': 'BOI', 'CB.KZ': 'NBK', 'CB.PE': 'BCP', 'CB.RO': 'BNR', 'CB.RU': 'BOR',
}
"""Our central bank key -> QLib CentralBankCode (ccy[XXX] definitions, meeting PeriodTypes FEDM/FED). Absent: none."""

_EQUITY_INDICES = frozenset({'SPX', 'NDX', 'NKY', 'TPX', 'SX5E'})
"""QLib IndexIdentifier equity indices."""

_METALS = {'GOLD': 'XAU', 'SILVER': 'XAG'}
"""Commodities QLib prices as currencies."""

_COMMODITY_INDICES = {'WTI': 'WTI', 'BRENT': 'BRENT', 'NATGAS': 'NG', 'TTF': 'TTF', 'GASOIL': 'GASOIL'}
"""Our commodity key -> QLib ReferenceIndex code."""


_CONVENTION_PAIRS = (
    'AT,EUR AU,AUD BE,EUR CA,CAD CA,USD CH,CHF CL,CLP CN,CNY CO,COP CZ,CZK DE,EUR ES,EUR EU,EUR FI,EUR FR,EUR '
    'GB,GBP GR,EUR HU,HUF IE,EUR IL,ILS IT,EUR JP,JPY KR,KRW MX,MXN NL,EUR NO,NOK NZ,NZD PE,PEN PL,PLN PT,EUR '
    'SE,SEK TR,TRY UA,UAH US,USD ZA,ZAR'
)
_BOND_CONVENTIONS = frozenset(tuple(pair.split(',')) for pair in _CONVENTION_PAIRS.split())
"""(country, currency) of the Govt bond conventions in the bundle (bndcnv[<country>,Govt,<currency>])."""


def qlib_id(entity: Entity, manager: DefinitionManager | None = None) -> str | None:
    """The QLib id of a definition, or None where QLib has no equivalent.

    A bond programme's id depends on its issuer, so it needs `manager` to look the issuer up.
    """
    match entity:
        case BondProgramme() if manager is not None:
            return _bond_convention(entity, manager)
        case Currency():
            return f'ccy[{entity.key}]'
        case FXPair():
            return f'fx[{entity.base_id},cc:{entity.quote_id}]'
        case RateIndex() if entity.key in _REFERENCE_INDEX:
            return f'idx[{entity.currency_id},{_REFERENCE_INDEX[entity.key]}]'
        case EquityIndex() if entity.key in _EQUITY_INDICES:
            return f'eqidx[{entity.key}]'
        case Commodity() if entity.key in _METALS:
            return f'ccy[{_METALS[entity.key]}]'
        case Commodity() if entity.currency_id and entity.key in _COMMODITY_INDICES:
            return f'idx[{entity.currency_id},{_COMMODITY_INDICES[entity.key]}]'
    return None


def central_bank_code(bank: CentralBank) -> str | None:
    """QLib's CentralBankCode for a bank (CB.US -> FED). Not an id: QLib has no central-bank identity type."""
    return _CENTRAL_BANK_CODE.get(bank.key)


def _bond_convention(programme: BondProgramme, manager: DefinitionManager) -> str | None:
    """bndcnv[DE,Govt,EUR]: nominal sovereign curves by country, the EU (a supranational) as country EU."""
    issuer = manager.ref(programme, 'obligor_id', Issuer)
    if programme.coupon is not CouponType.NOMINAL:
        return None
    if isinstance(issuer, SovereignIssuer):
        country = issuer.country_id
    elif isinstance(issuer, Supranational) and issuer.key == 'european_commission':
        country = 'EU'
    else:
        return None
    return f'bndcnv[{country},Govt,{programme.currency_id}]' if (country, programme.currency_id) in _BOND_CONVENTIONS \
        else None


def definition_file(qlib_id: str) -> str:
    """QLib definition file name: QLib writes qualifiers `key:value`, its files `key=value`."""
    return qlib_id.replace(':', '=')
