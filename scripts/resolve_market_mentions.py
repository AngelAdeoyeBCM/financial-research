"""Resolve ledger asset-ticker mentions, and instrument keywords, against the rebuilt market ontology.

    data/corpus/ledger_asset_ticker.csv -> ledger_asset_ticker_markets.csv   one row per mention
    data/corpus/ledger_keywords.csv     -> ledger_keywords_instruments.csv   only keywords naming an instrument
                                        -> market_mentions_summary.csv       counts by source, status and kind

A mention is parsed into parts (underlyings, product, structure, tenors) and built through
`ontology_manager()`, so it gets the same canonical id as every other phrasing of it. Status:

    resolved      built: an underlying, template, instance or structure id
    seed_gap      the kind is modelled but an underlying is not seeded (FX pair of an unseeded currency)
    kind_gap      recognised, but the kind is not modelled yet; `qlib_kind` names the QLib type it would be
    generic       a product or structure with no underlying ("swap spreads", "FX options", "steepener")
    asset_class   an asset class, not an instrument ("EM FX", "rates", "oil")
    partial       underlyings found, but other words left unparsed ("JGB issuance")
    unrecognised

Keywords are kept when resolved, seed_gap, kind_gap or generic.

    .venv/Scripts/python.exe scripts/resolve_market_mentions.py [--skip-keywords]
"""

import argparse
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pycountry
import yaml

from incolor.ontology.core import DefinitionManager, Entity, Unresolved
from incolor.ontology.market import (
    IRS,
    BondProgramme,
    BondSegment,
    CashBond,
    Commodity,
    CouponType,
    Currency,
    EquityIndex,
    FXForward,
    FXPair,
    Instance,
    MarketType,
    OptionPoint,
    PolicyRate,
    RateIndex,
    SegmentBond,
    Structure,
    Swaption,
    Template,
    shape,
)
from incolor.ontology.market.external import qlib_id
from incolor.ontology.organization import CentralBank, Issuer, Organization, OrganizationType, SovereignIssuer
from incolor.ontology.registry import SEEDS, ontology_manager

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'data' / 'corpus'
AS_OF = date(2026, 11, 10)  # tenors are relative; no resolution here depends on the document date
INSTRUMENT_STATUSES = ('resolved', 'seed_gap', 'kind_gap', 'generic')


@dataclass
class Result:
    """One mention's resolution: built entities, or the refs and QLib kind of a gap."""

    status: str
    kind: str = ''
    entities: tuple[Entity, ...] = ()
    refs: tuple[str, ...] = ()
    qlib_kind: str = ''
    note: str = ''

    def row(self, manager: DefinitionManager) -> dict[str, str]:
        """Output columns."""
        structure = next((e for e in self.entities if isinstance(e, Structure)), None)
        return {
            'status': self.status,
            'kind': self.kind,
            'entity_id': '; '.join(e.id for e in self.entities),
            'name': '; '.join(e.name for e in self.entities if e.name != e.key),
            'refs': '; '.join(dict.fromkeys(self.refs)),
            'qlib_id': '; '.join(q for e in self.entities if (q := qlib_id(e, manager))),
            'qlib_kind': self.qlib_kind,
            'shape': str(shape(structure, manager) or '') if structure else '',
            'note': self.note,
        }


# -----------------------------------------------------------------------------------------------------
# normalise
# -----------------------------------------------------------------------------------------------------
_YELLOW = re.compile(r'\s+(index|curncy|comdty|govt|corp|equity|mtge)$', re.I)
_TENOR_WORDS = [
    (re.compile(r'\b(\d+)\s*-?\s*(?:years?|yrs?|yr)\b'), r'\1y'),
    (re.compile(r'\b(\d+)\s*-?\s*(?:months?|mths?|mo)\b'), r'\1m'),
    (re.compile(r'\b(\d+)\s*-?\s*(?:weeks?|wks?)\b'), r'\1w'),
    (re.compile(r'\b(\d+)\s+([dwmy])\b'), r'\1\2'),
    (re.compile(r'\b(\d+[dwmy])\s*x\s*(\d+[dwmy])\b'), r'\1x\2'),  # 1Y x 10Y -> 1yx10y
    (re.compile(r'\b([a-z]{2,6})(\d+[ym])\b'), r'\1 \2'),            # ust10y, us10y -> ust 10y
    (re.compile(r'\b(\d+)/(\d+)/(\d+)s?y?\b'), r'\1s\2s\3s'),       # 5/10/30s -> 5s10s30s
    (re.compile(r'\b(\d+)\s*/\s*(\d+)(?:y|s)\b'), r'\1s\2s'),       # 2/10y, 2/10s -> 2s10s
    (re.compile(r'\brmb\b'), 'cny'),
]


def normalise(raw: str) -> str:
    """Casefolded, yellow key stripped, tenors written 10y / 1yx10y / 2s10s."""
    s = unicodedata.normalize('NFKC', raw)
    s = re.sub(r'[‐-―−]', '-', s).replace('’', "'")
    s = ' '.join(s.split()).strip(' "\'`.,;:*()')
    s = _YELLOW.sub('', s).casefold()
    for pattern, repl in _TENOR_WORDS:
        s = pattern.sub(repl, s)
    return ' '.join(s.split())


def split_mentions(cell: str) -> list[str]:
    """'BTP, Bund; OAT' -> ['BTP', 'Bund', 'OAT']."""
    return [p.strip() for p in re.split(r'\s*[;,\n]\s*', cell or '') if p.strip()]


# -----------------------------------------------------------------------------------------------------
# vocabulary
# -----------------------------------------------------------------------------------------------------
# Words that qualify a mention without naming anything: quote, side and curve-segment words.
NOISE = set(
    'the a an of on in at for and to yield yields rate rates price prices level levels spot outright long short '  # noqa: SIM905
    'pay paid receive received bond bonds govt govts govies gov cash notes note bills paper benchmark generic '
    'market markets nominal implied atm atmf otm itm front end belly back sector trade trades position positions '
    'exposure leg legs weekly daily index contract contracts bp bps yield-curve comex lme shfe nymex ice cme cbot '
    'eurex sgx dated physical'.split()
)
BOND_WORDS = set('yield yields bond bonds govt govts govies gov notes bills paper'.split())  # noqa: SIM905
_MONTH_YEAR = re.compile(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*['\-]?(\d{2})"
                         r"(?:/(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*['\-]?\d{2})?")
"""A dated contract or bond month in a mention: Jun26, Sep'26, Sep25/Sep27."""

PHRASES: dict[str, tuple[str, str]] = {}
"""phrase -> (role, value). Roles: product, structure, asset_class, gap ('qlib kind|label')."""


def _phrases(role: str, value: str, *forms: str) -> None:
    PHRASES.update(dict.fromkeys(forms, (role, value)))


_phrases('product', 'irs', 'swap', 'swaps', 'irs', 'nds', 'ndirs', 'swap rate', 'swap rates', 'swap curve')
_phrases('product', 'ois', 'ois', 'ndois', 'ois curve', 'ois swaps', 'ois swap', 'ois rates')  # the OIS default index
SWAPS = ('irs', 'ois')
_phrases('product', 'swaption', 'swaption', 'swaptions', 'payer', 'payers', 'receiver', 'receivers', 'swaption vol',
         'swaption volatility', 'swaption straddle', 'swaption straddles', 'payer spread', 'receiver spread')
_phrases('product', 'option', 'option', 'options', 'vol', 'vols', 'volatility', 'implied vol', 'call', 'calls', 'put',
         'puts', 'straddle', 'straddles', 'strangle', 'strangles', 'risk reversal', 'risk reversals', 'rr', 'skew',
         'call spread', 'put spread', 'call spreads', 'put spreads', 'digital', 'digitals', 'call fly', 'put fly')
_phrases('product', 'future', 'future', 'futures', 'fut', 'futs')
_phrases('product', 'forward', 'forward', 'forwards', 'fwd', 'fwds', 'ndf', 'ndfs', 'outright forward')
_phrases('product', 'fra', 'fra', 'fras')
_phrases('product', 'fxswap', 'fx swap', 'fx swaps', 'forward points', 'swap points')
_phrases('product', 'xccy', 'xccy', 'xccy basis', 'cross-currency basis', 'cross currency basis', 'cross-currency',
         'cross-currency swap', 'cross-currency swaps', 'ccs', 'xcs', 'cross-currency basis swaps')
_phrases('product', 'basis', 'basis swap', 'basis swaps', 'tenor basis')
_phrases('product', 'breakeven', 'breakeven', 'breakevens', 'break-even', 'break-evens', 'bei', 'beis',
         'breakeven inflation', 'inflation breakevens', 'inflation swap', 'inflation swaps', 'zc inflation swaps',
         'inflation-linked swaps', 'cpi swaps', 'hicp swaps', 'rpi swaps', 'cpi fixings', 'hicpx swaps')
_phrases('product', 'linker', 'linker', 'linkers', 'inflation-linked bonds', 'inflation linked bonds', 'real yields',
         'real yield', 'real rates', 'ilbs')
_phrases('product', 'cds', 'cds', 'credit default swap', 'credit default swaps', 'sovereign cds')
_phrases('product', 'repo', 'repo', 'repos', 'repo rate', 'repo rates', 'reverse repo', 'gc repo')
_phrases('product', 'cap', 'cap', 'caps', 'floor', 'floors', 'caps/floors', 'cap/floor')
_phrases('product', 'etf', 'etf', 'etfs')
_phrases('product', 'meeting_ois', 'mpc ois', 'fomc ois', 'ecb ois', 'boj ois', 'rba ois', 'boc ois', 'meeting ois',
         'meeting-dated ois', 'meeting swaps', 'meeting-dated swaps', 'mpc-dated ois', 'fomc-dated ois', 'mpc swaps')
_phrases('product', 'efp', 'efp', 'efps', 'futures basis', 'net basis')
_phrases('gap', '|mbs', 'fn 30', 'fn 15', 'g2 30', 'g2sf', 'g2/fn', 'tba', 'tbas', 'fnma', 'gnma', 'fnci', 'fncl')
_phrases('gap', 'ccy|fx_index', 'twi', 'neer', 's$neer', 'reer', 'trade-weighted', 'trade weighted')
_phrases('seed', 'bond_programme', 'ifc', 'sfil', 'cdc', 'kbn', 'kommuninvest', 'oekb')  # issuers not yet seeded
# Bond segments: value is 'sector|rating'; a rating alone (IG, HY) means corporates. See Resolver._segment.
_phrases('sector', 'govt|', 'egbs', 'egb', 'euro govies', 'eurozone govies', 'european government bonds')
_phrases('sector', 'ssa|', 'ssa', 'ssas', 'supras', 'agencies', 'sub-sovereigns', 'lander', 'länder',
         'sovereign-related')
_phrases('sector', 'covered|', 'covered bonds', 'covered bond', 'covereds', 'covered')
_phrases('sector', 'corp|', 'corporate bonds', 'corporate bond', 'corporates', 'corporate credit', 'corp bonds')
_phrases('sector', '|ig', 'ig', '$ig', '€ig', 'investment grade', 'investment-grade', 'ig credit', 'ig bonds',
         'ig corporates', 'ig corporate bonds', 'investment grade bonds', 'investment-grade bonds')
_phrases('sector', '|hy', 'hy', '$hy', '€hy', 'high yield', 'high-yield', 'hy credit', 'hy bonds', 'high yield bonds',
         'high-yield bonds', 'junk bonds')
_phrases('sector', 'muni|', 'munis', 'muni', 'muni bonds', 'municipal bonds', 'municipals', 'municipal', 'tax-exempt',
         'tax-exempts', 'tax-exempt munis')
_phrases('sector', '|aaa', 'aaa')
_phrases('sector', 'mbs|', 'mbs', 'agency mbs', 'umbs', 'agency mortgages')
_phrases('region', 'EUR', 'european', 'europe', 'euro', 'euro area', 'euro-area', 'eurozone', 'eu')
_phrases('rank', 'bond_rank', 'at1', 'at1s', 'coco', 'cocos', 'tier 2', 't2', 'tier 2s', 'senior non-preferred', 'snp',
         'senior preferred', 'subordinated', 'sub debt')
_phrases('seed', 'equity_index', 'msci', 'ftse', 'stoxx', 'russell', 's&p', 'nikkei', 'hang seng', 'csi', 'mib', 'omx')
_phrases('gap', '|bond_index', 'iboxx', 'markit iboxx', 'ice bofa')
_phrases('structure', 'spread', 'oas', 'z-spread', 'z-spreads', 'i-spread', 'g-spread')
_phrases('structure', 'swap_spread', 'swap spread', 'swap spreads', 'swap sprd', 'swapspread', 'swap spread curve')
_phrases('structure', 'asset_swap', 'asw', 'asset swap', 'asset swaps', 'asset swap spread', 'asset swap spreads',
         'asset-swap', 'asset-swap spreads')
_phrases('structure', 'spread', 'spread', 'spreads', 'sprd', 'differential', 'differentials')
_phrases('structure', 'curve', 'curve', 'steepener', 'steepeners', 'flattener', 'flatteners', 'slope',
         'bear steepener', 'bull steepener', 'bear flattener', 'bull flattener', 'curve steepener', 'curve flattener',
         'curve steepeners', 'curve flatteners')
_phrases('structure', 'fly', 'fly', 'flies', 'butterfly', 'butterflies')
_phrases('structure', 'box', 'box', 'boxes')
_phrases('asset_class', 'fx', 'fx', 'em fx', 'g10 fx', 'asia fx', 'latam fx', 'cee fx', 'ceemea fx', 'currencies',
         'currency', 'emfx')
_phrases('asset_class', 'rates', 'rates', 'em rates', 'g10 rates', 'local rates', 'duration', 'fixed income')
_phrases('asset_class', 'credit', 'credit', 'em credit', 'em sovereign credit', 'sovereigns')
_phrases('asset_class', 'equities', 'equities', 'equity', 'stocks', 'em equities', 'us equities', 'shares')
_phrases('asset_class', 'commodities', 'commodities', 'oil', 'crude', 'crude oil', 'oil prices', 'metals',
         'base metals', 'precious metals', 'energy', 'gas', 'natural gas', 'lng', 'agriculture', 'grains')
_phrases('gap', 'ccy[DXY]|fx_index', 'dxy', 'bbdxy', 'dollar index', 'us dollar index', 'usdx', 'adxy')
_phrases('gap', '|vol_index', 'move index', 'ice bofa move', 'ovx', 'v2x', 'vstoxx', 'cvix')
_phrases('gap', 'cdsidx|credit_index', 'cdx ig', 'cdx hy', 'cdx.ig', 'cdx.hy', 'cdx.na.ig', 'cdx.na.hy', 'cdx em',
         'cdx', 'itraxx', 'itraxx main', 'itraxx xover', 'itraxx crossover', 'itraxx europe', 'xover',
         'itraxx senior financials', 'itraxx sub financials', 'itraxx asia', 'cdx na ig', 'cdx na hy',
         'itraxx senfin', 'itraxx subfin', 'itraxx finsen', 'itraxx finsub')
_phrases('gap', '|emissions', 'eua', 'euas', 'carbon', 'eu carbon', 'eu ets')
_phrases('gap', '|crypto', 'bitcoin', 'btc', 'ethereum', 'eth', 'crypto')
# A policy rate named generically: the headline rate of the central bank or currency named with it (BoJ policy
# rate, Brazil policy rate). Named rates (Bank Rate, ECB deposit rate, IORB, cash rate) are aliases of their index.
_phrases('policy', 'policy_rate', 'policy rate', 'policy rates', 'base rate', 'key rate', 'key policy rate',
         'benchmark rate', 'deposit rate', 'depo rate', 'policy interest rate', 'official rate')
_phrases('gap', 'inf|inflation_index', 'hicpx', 'hicp ex-tobacco', 'cpurnsa', 'uk rpi', 'ukrpi', 'frcpi', 'cpxtemu',
         'us cpi nsa', 'cpi-u nsa')
_phrases('gap', '|custom_index', 's&p gsci', 'bcom', 'bloomberg commodity index')
# Central banks and their policy committees; the value is the bank's key (config/registries/organization).
CENTRAL_BANK_WORDS = {
    'CB.US': ['fed', 'fomc', 'federal reserve', 'the fed'], 'CB.EZ': ['ecb', 'governing council'],
    'CB.GB': ['boe', 'mpc', 'bank of england'], 'CB.JP': ['boj', 'bank of japan'], 'CB.CH': ['snb'],
    'CB.CA': ['boc', 'bank of canada'], 'CB.AU': ['rba'], 'CB.NZ': ['rbnz'], 'CB.SE': ['riksbank'],
    'CB.NO': ['norges bank', 'norges'], 'CB.CN': ['pboc'], 'CB.KR': ['bok', 'bank of korea'], 'CB.IN': ['rbi'],
    'CB.MY': ['bnm'], 'CB.PH': ['bsp'], 'CB.HK': ['hkma'], 'CB.TW': ['cbc'], 'CB.BR': ['bcb', 'copom'],
    'CB.MX': ['banxico'], 'CB.CL': ['bcch'], 'CB.CO': ['banrep'], 'CB.ZA': ['sarb'], 'CB.TR': ['cbrt'],
    'CB.PL': ['nbp'], 'CB.HU': ['mnb'], 'CB.CZ': ['cnb'], 'CB.IL': ['bank of israel'],
}
for _bank, _forms in CENTRAL_BANK_WORDS.items():
    _phrases('meeting', _bank, *_forms)

# Futures roots (Bloomberg) -> underlying. Bare roots only for those research quotes alone.
FUT_ROOTS = {
    # bond futures: the country, whose sovereign programme is found through its issuer
    'TU': 'US', 'FV': 'US', 'TY': 'US', 'UXY': 'US', 'US': 'US', 'WN': 'US', 'DU': 'DE', 'OE': 'DE', 'RX': 'DE',
    'UB': 'DE', 'IK': 'IT', 'BTS': 'IT', 'OAT': 'FR', 'G': 'GB', 'JB': 'JP', 'XM': 'AU', 'YM': 'AU', 'CN': 'CA',
    'SFR': 'idx:USD.SOFR', 'SR3': 'idx:USD.SOFR', 'SR1': 'idx:USD.SOFR', 'FF': 'idx:USD.FEDFUNDS',
    'ER': 'idx:EUR.EURIBOR', 'SFI': 'idx:GBP.SONIA', 'SO3': 'idx:GBP.SONIA', 'IR': 'idx:AUD.BBSW',
    'CRA': 'idx:CAD.CORRA', 'OD': 'idx:BRL.CDI', 'CL': 'cmdty:WTI', 'CO': 'cmdty:BRENT', 'NG': 'cmdty:NATGAS',
    'GC': 'cmdty:GOLD', 'SI': 'cmdty:SILVER', 'HG': 'cmdty:COPPER', 'QS': 'cmdty:GASOIL', 'PL': 'cmdty:PLATINUM',
    'PA': 'cmdty:PALLADIUM', 'TZT': 'cmdty:TTF', 'ES': 'eqidx:SPX', 'NQ': 'eqidx:NDX', 'UX': 'eqidx:VIX',
    'VX': 'eqidx:VIX', 'VG': 'eqidx:SX5E', 'GX': 'eqidx:DAX', 'NK': 'eqidx:NKY', 'Z': 'eqidx:UKX', 'RTY': 'eqidx:RTY',
}
BARE_ROOTS = {'TY', 'TU', 'FV', 'WN', 'UXY', 'RX', 'OE', 'DU', 'IK', 'JB', 'SFR', 'SR3', 'ER', 'CL', 'NG', 'GC', 'HG',
              'ES', 'NQ', 'VX', 'UB'}
FUTURE_KIND = {'bond_programme': 'bf', 'rate_index': 'rf', 'commodity': 'cf', 'equity_index': 'eif'}
OPTION_KIND = {'fx_pair': 'fxo', 'currency': 'fxo', 'equity_index': 'eio', 'commodity': 'cfo', 'bond_programme': 'bfo'}
SECTOR_CURRENCY = {'govt': 'EUR', 'muni': 'USD', 'mbs': 'USD'}
"""Currency a segment means when a mention names none: EGBs are EUR, munis and agency MBS USD."""
GAP_PRODUCTS = {'future': '', 'option': '', 'fra': 'fra', 'fxswap': 'fxswp', 'cds': 'cds', 'repo': 'repo',
                'cap': 'cap', 'etf': 'eq', 'xccy': 'xcs', 'meeting_ois': 'cbs', 'efp': 'fb'}
ETFS = set('SPY QQQ IWM EEM EFA GLD SLV TLT IEF SHY LQD HYG JNK EMB FXI KWEB EWZ EWW EWJ EWY EWT EWG EWU FEZ VGK '  # noqa: SIM905
           'XLE XLF XLK XLI XLP XLU XLV XLY XLB XLC XLRE XRT XHB XME XOP SMH SOXX IGV KRE KBE GDX GDXJ JETS DIA ARKK '
           'MCHI ASHR INDA VWO VEA AGG BND TIP SCHD USO UNG IBIT'.split())
BBG_GOVT = {'t': 'US', 'ust': 'US', 'dbr': 'DE', 'bund': 'DE', 'obl': 'DE', 'bko': 'DE', 'frtr': 'FR', 'oat': 'FR',
            'btps': 'IT', 'btp': 'IT', 'spgb': 'ES', 'ukt': 'GB', 'gilt': 'GB', 'jgb': 'JP', 'acgb': 'AU', 'can': 'CA'}
FUT_NAMES = {'buxl': 'UB', 'buxls': 'UB', 'ultra bond': 'WN', 'ultra 10y': 'UXY'}
"""Futures quoted by contract name alone."""

_NAMED_CONTRACT = re.compile(r'(.+?)\s+(?:futures?\s+)?([fghjkmnquvxz]\d{1,2}(?:\s*/\s*[fghjkmnquvxz]\d{1,2}){0,2})')
_MONTH = r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*'
_BOND_LINE = re.compile(
    r'(?P<issuer>[a-z][a-z&.\' ]{0,20}?)\s+(?:(?P<cpn>\d{1,2}(?:\.\d+)?)\s*%?\s+)?'
    r'(?P<mat>\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{2,4}|' + _MONTH + r"[\s'-]?\d{2,4}|'?\d{2}s|20\d{2})"
)
_EQUITY_TICKER = re.compile(r'[A-Z0-9]{1,6}(?:/[A-Z]?)?\s+(?:LN|US|UN|UW|UQ|JP|JT|HK|GR|GY|FP|IM|SM|NA|SW|SE|CN|CT|AU|'
                            r'KS|KQ|TT|SS|SZ|CH|SP|BZ|MM|SJ|PL|DC|NO|FH|ID|BB|AV|PW|TB|IJ|MK|PM|IN|NZ)|'
                            r'[A-Z0-9]{1,6}\.(?:[A-Z]{1,2}|ST|DE|PA|AS|MI|SW|HK|TO|AX|KS|T)')
_PAIR = re.compile(r'([a-z]{3})\s*[/\-]?\s*([a-z]{3})(?:\s+(.*))?')
_MULTI_TENOR = re.compile(r'\b\d+s(?:\s*[/-]?\s*\d+s){1,2}\b|\b\d+[dwmy](?:\s*[/-]\s*\d+[dwmy]){1,2}\b')
_TENOR = re.compile(r'(\d+[dwmy])(?:(x)?(\d+[dwmy]))?')
_FWD = re.compile(r'\b(\d+[dwmy])\s*(?:fwd|forward)\b')
_VS = re.compile(r'\s+(?:vs\.?|versus|over|against|v)\s+')
_NUMBER = re.compile(r'[+-]?\d+(?:\.\d+)?(?:%|bps?)?')
_FIXING_TENORS = {'1m', '3m', '6m', '12m', '1y'}

DEMONYMS = {
    'german': 'DE', 'germany': 'DE', 'ger': 'DE', 'deu': 'DE', 'de': 'DE', 'french': 'FR', 'france': 'FR', 'fr': 'FR',
    'italian': 'IT', 'italy': 'IT', 'ita': 'IT', 'spanish': 'ES', 'spain': 'ES', 'spa': 'ES', 'esp': 'ES',
    'dutch': 'NL', 'belgian': 'BE', 'austrian': 'AT', 'portuguese': 'PT', 'finnish': 'FI', 'irish': 'IE',
    'greek': 'GR', 'japanese': 'JP', 'japan': 'JP', 'jpn': 'JP', 'jp': 'JP', 'british': 'GB', 'uk': 'GB', 'gb': 'GB',
    'swiss': 'CH', 'canadian': 'CA', 'australian': 'AU', 'aus': 'AU', 'au': 'AU', 'swedish': 'SE', 'norwegian': 'NO',
    'chinese': 'CN', 'china': 'CN', 'cn': 'CN', 'korean': 'KR', 'korea': 'KR', 'south korea': 'KR', 'kr': 'KR',
    'indian': 'IN', 'india': 'IN', 'indonesian': 'ID', 'malaysian': 'MY', 'thai': 'TH', 'brazilian': 'BR',
    'brazil': 'BR', 'mexican': 'MX', 'mexico': 'MX', 'chilean': 'CL', 'colombian': 'CO', 'south african': 'ZA',
    'south africa': 'ZA', 'turkish': 'TR', 'polish': 'PL', 'poland': 'PL', 'hungarian': 'HU', 'hungary': 'HU',
    'czech': 'CZ', 'israeli': 'IL', 'us': 'US', 'usa': 'US', 'u.s.': 'US', 'united states': 'US', 'american': 'US',
    'new zealand': 'NZ', 'nz': 'NZ', 'ca': 'CA',
}
GENERIC_ALIASES = {'real', 'won', 'dollar', 'euro', 'pound', 'lira', 'rand', 'kiwi', 'peso', 'rupee', 'yuan', 'eu'}
"""Aliases that mean something else inside a longer mention ("EU-US trade" is not EU bonds)."""
_TERM_WORDS = {k for k, (role, _) in PHRASES.items() if role in ('product', 'structure') and ' ' not in k}
_DASH_COUNTRIES = {'fra': 'france', 'ger': 'germany', 'ita': 'italy', 'spa': 'spain', 'esp': 'spain', 'bel': 'belgium',
                   'aut': 'austria', 'nld': 'netherlands', 'net': 'netherlands', 'por': 'portugal', 'fin': 'finland',
                   'irl': 'ireland', 'grc': 'greece', 'uk': 'uk', 'us': 'us', 'jpn': 'japan'}
"""Country abbreviations read as countries only inside a dashed list (ITA-FRA-GER): FRA alone is a FRA."""


def _contract_root(code: str) -> str | None:
    """Futures root of a contract code: TYH6 -> TY, SFR Z5 -> SFR, NQ1 -> NQ; None when the root is unknown."""
    m = re.fullmatch(r'([A-Z0-9]{1,4}?)\s?([FGHJKMNQUVXZ])(\d{1,2})', code)
    if m and m[1] in FUT_ROOTS:
        return m[1]
    m = re.fullmatch(r'([A-Z]{2,4})(\d)', code)  # generic CL1, NQ1; not G7, Z3
    return m[1] if m and m[1] in FUT_ROOTS else None


def _check_digit(body: str) -> int:
    """CUSIP / FIGI check digit."""
    total = 0
    for i, c in enumerate(body):
        v = int(c) if c.isdigit() else ord(c) - 55
        v *= 2 if i % 2 else 1
        total += v // 10 + v % 10
    return (10 - total % 10) % 10


def _isin_ok(s: str) -> bool:
    if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', s):
        return False
    digits = ''.join(str(int(c) if c.isdigit() else ord(c) - 55) for c in s[:-1])
    total = sum(d - 9 if (d := int(ch) * (2 if i % 2 == 0 else 1)) > 9 else d for i, ch in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == int(s[-1])


def _cusip_ok(s: str) -> bool:
    return bool(re.fullmatch(r'[0-9A-Z]{8}\d', s)) and any(c.isdigit() for c in s[:8]) and _check_digit(s[:8]) == int(
        s[8])


# -----------------------------------------------------------------------------------------------------
# resolver
# -----------------------------------------------------------------------------------------------------
def _kind(e: Entity) -> str:
    """The kind the grammar dispatches on: a policy rate counts as a rate index (Fed funds futures, BoE meeting OIS)."""
    return MarketType.RATE_INDEX.value if isinstance(e, RateIndex) else e.entity_type.value


@dataclass
class Leg:
    """An underlying named in a mention, with the tenors written next to it."""

    entity: Entity
    tenors: list[str] = field(default_factory=list)
    via_country: bool = False  # "Germany" stands for Bunds only in a rates or bond context


@dataclass
class Parse:
    """What the grammar found in a mention."""

    legs: list[Leg] = field(default_factory=list)
    words: list[tuple[str, str]] = field(default_factory=list)
    tenors: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    leftover: list[str] = field(default_factory=list)
    bond_words: bool = False  # yields, bonds, govts ...

    def role(self, role: str) -> list[str]:
        """Values of the phrases found with this role."""
        return [value for r, value in self.words if r == role]


class Resolver:
    """Mention text -> parts -> the canonical market entity, built through the manager's factories."""

    def __init__(self, manager: DefinitionManager) -> None:
        self.m = manager
        self.entities = {e.id: e for e in manager.store}
        self._countries()
        self._lexicon()
        self.first_words = {k.split()[0] for k in (*self.lex, *PHRASES, *self.countries)}
        self.cache: dict[str, Result] = {}

    def _lexicon(self) -> None:
        """Surface form -> entity id. Names and aliases first; codes and plural variants only where free."""
        strong: dict[str, set[str]] = {}
        weak: dict[str, set[str]] = {}

        def add(table: dict[str, set[str]], form: str, entity_id: str) -> None:
            key = normalise(form)
            blocked = key in PHRASES and PHRASES[key][0] != 'seed'  # a named index beats "unseeded family"
            if key and not blocked and key not in NOISE and key not in GENERIC_ALIASES:
                table.setdefault(key, set()).add(entity_id)

        aliases = {**yaml.safe_load((SEEDS / 'market' / 'aliases.yaml').read_text(encoding='utf-8')),
                   **yaml.safe_load((SEEDS / 'organization' / 'aliases.yaml').read_text(encoding='utf-8'))}
        for e in self.entities.values():
            if isinstance(e, Organization):
                continue
            add(strong, e.name, e.id)
            if isinstance(e, Currency | EquityIndex | Commodity | FXPair):
                add(strong, e.key, e.id)
            if isinstance(e, RateIndex) and not isinstance(e, PolicyRate):
                add(weak, e.code, e.id)  # policy codes are words (TARGET, DISCOUNT, REPO): names and aliases only
            for form in aliases.get(e.id, []):
                # "TIPS breakevens", "SOFR futures": the grammar builds these, not the alias
                if not set(normalise(form).split()) & _TERM_WORDS:
                    add(strong, form, e.id)
        # An issuer's name names its bonds when it has one nominal programme: KfW, EIB, NRW, Ontario.
        # Sovereign issuers are left out: "US Treasury" is already a programme alias, "DMO" is not a market.
        for issuer, programmes in self.programmes_by_issuer.items():
            if len(programmes) == 1 and not isinstance(issuer, SovereignIssuer):
                for form in (issuer.name, *aliases.get(issuer.id, [])):
                    add(strong, form, programmes[0].id)
        for key, ids in list(strong.items()):
            variant = key[:-1] if key.endswith('s') and len(key) > 3 else key + 's'
            for entity_id in ids:
                add(weak, variant, entity_id)
        self.lex = {k: next(iter(v)) for k, v in strong.items() if len(v) == 1}
        self.lex.update({k: next(iter(v)) for k, v in weak.items()
                         if len(v) == 1 and k not in strong and k not in self.countries})  # Canadas -/-> canada

    def _countries(self) -> None:
        """Country words -> the country's nominal sovereign programme, found through its sovereign issuer."""
        self.programmes_by_issuer: dict[Issuer, list[BondProgramme]] = {}
        self.programme_by_country: dict[str, BondProgramme] = {}
        for e in self.entities.values():
            if isinstance(e, BondProgramme) and e.coupon is CouponType.NOMINAL:
                issuer = self.m.ref(e, 'obligor_id', Issuer)
                self.programmes_by_issuer.setdefault(issuer, []).append(e)
                if isinstance(issuer, SovereignIssuer):  # home-currency curve over a USD line
                    current = self.programme_by_country.get(issuer.country_id)
                    if current is None or current.currency_id == 'USD':
                        self.programme_by_country[issuer.country_id] = e
        self.countries = {k: v for k, v in DEMONYMS.items() if v in self.programme_by_country}
        for c in pycountry.countries:
            if c.alpha_2 in self.programme_by_country:
                for name in {c.name, getattr(c, 'common_name', c.name)}:
                    self.countries.setdefault(normalise(name), c.alpha_2)

    # -- lookups ---------------------------------------------------------------------------------------
    def entity(self, entity_id: str) -> Entity | None:
        """A stored entity by id."""
        return self.entities.get(entity_id) or self.m.store.get(entity_id)

    def root_underlying(self, root: str) -> Entity | None:
        """Underlying of a futures root: a country's sovereign programme for bond futures, else the entity."""
        target = FUT_ROOTS[root]
        return self.programme_by_country.get(target) if len(target) == 2 else self.entity(target)

    def named[E: Entity](self, text: str, kind: type[E]) -> E | None:
        """The `kind` a surface form names, if any."""
        found = self.entity(self.lex.get(text, ''))
        return found if isinstance(found, kind) else None

    def currency(self, code: str | None) -> Currency | None:
        """A seeded currency by ISO code."""
        found = self.m.store.get(MarketType.CURRENCY.id_of(code)) if code else None
        return found if isinstance(found, Currency) else None

    @staticmethod
    def currency_of(e: Entity) -> str | None:
        """Currency key of a currency, or of anything with a `currency_id`."""
        return e.key if isinstance(e, Currency) else getattr(e, 'currency_id', None)

    def benchmark_bond(self, currency: str | None) -> BondProgramme | None:
        """The sovereign curve a currency's swap spreads are quoted against (Bunds for EUR)."""
        if currency == 'EUR':
            return self.programme_by_country.get('DE')
        found = [p for p in self.programme_by_country.values() if p.currency_id == currency]
        return found[0] if len(found) == 1 else None

    def programme(self, obligor: str, currency: str, coupon: str) -> BondProgramme | None:
        """A seeded bond programme by its key parts."""
        found = self.m.store.get(MarketType.BOND_PROGRAMME.id_of(f'{obligor}.{currency}.{coupon}'))
        return found if isinstance(found, BondProgramme) else None

    # -- entry -----------------------------------------------------------------------------------------
    def resolve(self, raw: str) -> Result:
        """Cached by the raw mention: ticker and identifier patterns are case-sensitive."""
        raw = raw.strip()
        if raw not in self.cache:
            try:
                self.cache[raw] = self._resolve(raw, normalise(raw))
            except Unresolved as error:
                self.cache[raw] = Result('seed_gap', note=str(error)[:200])
        return self.cache[raw]

    def _resolve(self, raw: str, text: str) -> Result:
        if not text:
            return Result('unrecognised')
        for parser in (self._identifier, self._future, self._equity_ticker, self._fx, self._linker, self._bond_line):
            if (result := parser(raw, text)) is not None:
                return result
        return self._grammar(text)

    # -- whole-string patterns ---------------------------------------------------------------------------
    def _identifier(self, raw: str, text: str) -> Result | None:
        s = raw.strip().upper()
        if ' ' not in s and (_isin_ok(s) or _cusip_ok(s)):
            return Result('kind_gap', 'security', qlib_kind='bond[isin]|eq[isin]', note=f'single security {s}')
        return None

    def _future(self, raw: str, text: str) -> Result | None:
        """TYH6, SFRZ5/SFRZ6, CL1, bare TY; and named contracts: SOFR Z6, Euribor H6/M6."""
        if (root := FUT_NAMES.get(text.removesuffix(' futures'))) is not None:
            under = self.root_underlying(root)
            assert under is not None
            return Result('kind_gap', 'future', refs=(under.id,), qlib_kind='bf', note=root)
        codes = [c.strip() for c in raw.upper().removesuffix(' COMDTY').removesuffix(' INDEX').split('/')]
        roots: list[str] = []
        for n, code in enumerate(codes):
            if n and roots and re.fullmatch(r'[FGHJKMNQUVXZ]\d{1,2}', code):
                root: str | None = roots[0]  # SFI Z5/Z6: later legs give only the month
            else:
                root = _contract_root(code)
            if root is None and code in BARE_ROOTS:
                root = code  # TY, or RX/UB
            if root is None:
                roots = []
                break
            roots.append(root)
        unders = [u for root in dict.fromkeys(roots) if (u := self.root_underlying(root)) is not None]
        if roots and len(unders) == len(set(roots)):
            note = 'calendar/strip' if len(codes) > 1 else 'front contract' if codes[0] in BARE_ROOTS else ''
            return Result('kind_gap', 'future', refs=tuple(u.id for u in unders),
                          qlib_kind=FUTURE_KIND[unders[0].entity_type.value], note=f'{"/".join(codes)} {note}'.strip())
        m = _NAMED_CONTRACT.fullmatch(text)
        under = self.entity(self.lex.get(m[1], '')) if m else None
        if m and under is not None and under.entity_type.value in FUTURE_KIND:
            return Result('kind_gap', 'future', refs=(under.id,), qlib_kind=FUTURE_KIND[under.entity_type.value],
                          note=m[2].upper())
        return None

    def _equity_ticker(self, raw: str, text: str) -> Result | None:
        s = raw.strip()
        if _EQUITY_TICKER.fullmatch(s) or (s.isupper() and s in ETFS):
            return Result('kind_gap', 'equity', qlib_kind='eq', note='ETF' if s in ETFS else 'single stock')
        if s in ('MOVE', 'MOVE Index'):  # the ICE BofA rates vol index; "implied move" is not
            return Result('kind_gap', 'vol_index', note='ICE BofA MOVE')
        if re.fullmatch(r'SX\d?[A-Z0-9]{1,2}[EP]', s) and text not in self.lex:  # SX7E, SX86P: Stoxx sectors
            return Result('seed_gap', 'equity_index', note='Stoxx sector index not seeded')
        if re.fullmatch(r'(?:GS|BNP|MS|JPM|BAML|CIT|UBS|DB|BARC)[A-Z0-9]{4,}(?: INDEX)?', s.upper()) and s.isupper():
            return Result('kind_gap', 'custom_index', note='bank custom basket or strategy index')
        if re.fullmatch(r'J[BLNSUX]\d{1,3}', s):  # JX87, JN476, JL173: JGB issue numbers
            return Result('kind_gap', 'bond_line', refs=(self.programme_by_country['JP'].id,), qlib_kind='bnd-ins',
                          note=s)
        return None

    def _fx(self, raw: str, text: str) -> Result | None:
        m = _PAIR.fullmatch(re.sub(r'^rmb|(?<=^[a-z]{3})rmb', 'cny', text))
        if not m or m[1] == m[2]:
            return None
        a, b, rest = m[1].upper(), m[2].upper(), (m[3] or '').strip()
        metal = self.named(a.casefold(), Commodity) if a in ('XAU', 'XAG', 'XPT', 'XPD') else None
        if metal is not None and self.currency(b) and not rest:
            return Result('resolved', 'commodity', (metal,), note=f'quoted in {b}')
        if not (self.currency(a) and self.currency(b)):
            return None
        if rest and self.currency(rest.split()[0].upper()):
            return None  # "NOK THB BRL": a list of currencies, not a pair
        if re.search(r'\b(?:swap spreads?|basis|xccy|cross-currency|spreads?)\b', rest):
            return None  # "MXN-USD 5y swap spread": two rates markets, not the pair
        try:
            pair = self.m.build(FXPair, {'base_id': a, 'quote_id': b}, AS_OF)
        except Unresolved:
            return Result('seed_gap', 'fx_pair', note=f'{a}{b}: pair not seeded')
        if not rest:
            return Result('resolved', 'fx_pair', (pair,))
        p = self._scan_terms(rest)
        products = p.role('product')
        if p.leftover:
            return Result('partial', 'fx_pair', (pair,), note=f'unparsed: {" ".join(p.leftover)}')
        for product, (kind, qlib) in {'option': ('fx_option', 'fxo'), 'swaption': ('fx_option', 'fxo'),
                                      'fxswap': ('fx_swap', 'fxswp'), 'future': ('fx_future', 'fxfut')}.items():
            if product in products:
                return Result('kind_gap', kind, refs=(pair.id,), qlib_kind=qlib, note=' '.join(p.tenors))
        if 'forward' in products or p.tenors:
            template = self.m.build(FXForward, {'pair_id': pair.key}, AS_OF)
            if p.tenors:
                return Result('resolved', 'instance', (self._instance(template, p.tenors[0]),))
            return Result('resolved', 'fx_forward', (template,))
        return Result('resolved', 'fx_pair', (pair,), note=f'ignored: {rest}')

    def _linker(self, raw: str, text: str) -> Result | None:
        """Bloomberg linker tickers: OATei, BTPei, DBRei, UKTi, ACGBi -> the sovereign's linker programme."""
        m = re.fullmatch(r'([a-z]{2,6}?)(€i|ei|i)', text.split()[0]) if text else None
        if not m:
            return None
        base = self.programme_by_country.get(BBG_GOVT.get(m[1], '')) or self.named(m[1], BondProgramme)
        if base is None and (ccy := self.currency(m[1].upper())) is not None:
            base = self.benchmark_bond(ccy.key)  # EURi: EUR linkers
        if base is None:
            return None
        linker = self.programme(base.obligor_id, base.currency_id, 'linker')
        if linker is None:
            return Result('seed_gap', 'bond_programme', refs=(base.id,), note=f'no linker programme for {base.id}')
        rest = text.split()[1:]
        if not rest:
            return Result('resolved', 'bond_programme', (linker,))
        return self._grammar(' '.join([linker.name.casefold(), *rest]))

    def _bond_line(self, raw: str, text: str) -> Result | None:
        """T 4.25 11/34, DBR 2.5 08/54, Bund Aug54: one bond line of a programme."""
        m = _BOND_LINE.fullmatch(text)
        if not m or not (m['cpn'] or re.match(_MONTH, m['mat'])):
            return None
        issuer = m['issuer'].strip()
        programme = self.programme_by_country.get(BBG_GOVT.get(issuer, '')) or self.named(issuer, BondProgramme)
        if programme is None:
            return None
        return Result('kind_gap', 'bond_line', refs=(programme.id,), qlib_kind='bnd-ins',
                      note=f'single bond line {raw!r} (ISIN lines deferred)')

    # -- grammar -------------------------------------------------------------------------------------------
    def _scan_terms(self, text: str) -> Parse:
        """Phrases, tenors and leftover words of a term string that names no underlying."""
        p = Parse()
        self._scan(text, p, underlyings=False)
        return p

    def _scan(self, part: str, p: Parse, underlyings: bool = True) -> None:
        """Longest-first phrase matching. Tenors in a part attach to the part's single underlying."""
        toks = part.split()
        found: list[Leg] = []
        tenors: list[str] = []
        i = 0
        while i < len(toks):
            for n in range(min(7, len(toks) - i), 0, -1):  # J.P. Morgan High Yield Bond Index
                phrase = ' '.join(toks[i : i + n])
                pair = _PAIR.fullmatch(phrase) if n == 1 and underlyings else None
                if pair and pair[1] != pair[2] and not pair[3] and self.currency(pair[1].upper()) \
                        and self.currency(pair[2].upper()) and phrase not in self.lex:
                    try:  # short USD/EGP, long 6M USD/CNH put
                        found.append(Leg(self.m.build(FXPair, {'base_id': pair[1].upper(),
                                                               'quote_id': pair[2].upper()}, AS_OF)))
                    except Unresolved:
                        p.words.append(('seed', 'fx_pair'))
                elif underlyings and phrase in self.lex and (e := self.entity(self.lex[phrase])) is not None:
                    found.append(Leg(e))
                elif underlyings and phrase in self.countries:
                    found.append(Leg(self.programme_by_country[self.countries[phrase]], via_country=True))
                elif phrase in PHRASES:
                    p.words.append(PHRASES[phrase])
                else:
                    continue
                i += n
                break
            else:
                tok = toks[i]
                if _TENOR.fullmatch(tok):
                    tenors.append(tok)
                elif _MONTH_YEAR.fullmatch(tok) or re.fullmatch(r"#\d+|\d{1,2}/\d{2}|'\d{2}s?", tok):
                    p.dates.append(tok)  # a contract month (Jun26 Euribor) or a bond line (BTPS 4/45, JGB #161)
                elif tok in BOND_WORDS:
                    p.bond_words = True
                elif tok not in NOISE and not _NUMBER.fullmatch(tok):
                    p.leftover.append(tok)
                i += 1
        p.tenors.extend(tenors)
        if len(found) == 1:
            found[0].tenors = tenors
        p.legs.extend(found)

    def _split_legs(self, text: str) -> list[str]:
        """'oat-bund 10y' -> ['oat', 'bund 10y']: a dashed token splits when two or more pieces name markets."""
        parts: list[str] = []
        for chunk in _VS.split(text):
            buf: list[str] = []
            for tok in chunk.split():
                pieces = [p for p in re.split(r'[-/]', tok) if p]
                if len(pieces) == 2 and all(len(p) == 3 and self.currency(p.upper()) for p in pieces):
                    buf.append(tok)  # USD/EGP: an FX pair, not two legs
                    continue
                if len(pieces) > 1:
                    pieces = [_DASH_COUNTRIES.get(p, p) for p in pieces]
                named = sum(1 for p in pieces if p in self.lex or p in self.countries)
                if len(pieces) > 1 and tok not in self.lex and tok not in PHRASES and named >= 2:
                    parts.append(' '.join([*buf, pieces[0]]))
                    parts.extend(pieces[1:-1])
                    buf = [pieces[-1]]
                else:
                    buf.append(tok)
            if buf:
                parts.append(' '.join(buf))
        return parts

    def _grammar(self, text: str) -> Result:
        words = set(text.split()) | {w for w in re.split(r'[\s/-]+', text) if w}
        if not words & self.first_words and not re.search(r'\d+[dwmy]\b|\d+s\b', text):
            return Result('unrecognised')
        fwd = None
        if m := _FWD.search(text):
            fwd, text = m[1], f'{text[: m.start()]} {text[m.end() :]}'.strip()
        multi: list[str] = []
        if m := _MULTI_TENOR.search(text):
            multi = [t if t[-1] in 'dwmy' else t[:-1] + 'y' for t in re.findall(r'\d+[sdwmy]', m[0])]
            text = f'{text[: m.start()]} {text[m.end() :]}'.strip()
        p = Parse()
        for part in self._split_legs(text):
            self._scan(part, p)
        if fwd and p.tenors:
            p.tenors[0] = f'{fwd}{p.tenors[0]}'
            for leg in p.legs:
                leg.tenors = [f'{fwd}{t}' for t in leg.tenors]
        merged: dict[str, Leg] = {}
        for leg in p.legs:  # "UK Gilt 10s30s": two words, one market
            kept = merged.setdefault(leg.entity.id, Leg(leg.entity, via_country=leg.via_country))
            kept.tenors.extend(t for t in leg.tenors if t not in kept.tenors)
            kept.via_country = kept.via_country and leg.via_country
        p.legs = list(merged.values())
        if len(p.legs) == 1 and not multi and len(p.legs[0].tenors) in (2, 3):
            multi = p.legs[0].tenors  # 2Y UST vs 10Y UST: one market at two points is a curve
        refs = tuple(leg.entity.id for leg in p.legs)
        if p.leftover:
            if p.legs:
                return Result('partial', refs=refs, note=f'unparsed: {" ".join(p.leftover)}')
            return Result('unrecognised', note=f'unparsed: {" ".join(p.leftover)}')
        products, structures, gaps = p.role('product'), p.role('structure'), p.role('gap')
        if seeds := p.role('seed'):  # MSCI Japan: the country names the index, not a bond market
            return Result('seed_gap', seeds[0], note=f'{seeds[0]} not seeded')
        if gaps:
            qlib, _, label = gaps[0].partition('|')
            return Result('kind_gap', label, refs=refs, qlib_kind=qlib)
        if p.role('sector'):
            return self._segment(p, products, structures, multi)
        if p.role('policy'):
            return self._policy_rate(p)
        rates_only = {_kind(leg.entity) for leg in p.legs} <= {'rate_index', 'currency'}
        if p.role('meeting') and p.legs and rates_only:  # Jul25 ECB €STR: a meeting-dated OIS
            return Result('kind_gap', 'meeting_ois', refs=refs, qlib_kind='cbs', note=' '.join(p.dates))
        if not p.legs:
            if set(p.role('asset_class')) & {'credit', 'equities'}:  # credit spreads
                return Result('asset_class', p.role('asset_class')[0])
            if products or structures or multi or p.role('rank'):
                kind = products[0] if products else structures[0] if structures else 'curve' if multi else 'bond_rank'
                return Result('generic', kind)
            if p.tenors:
                return Result('generic', 'point', note=f'{" ".join(p.tenors)} with no underlying')
            if classes := p.role('asset_class'):
                return Result('asset_class', classes[0])
            return Result('unrecognised')
        return self._build(p, products[0] if products else None, structures[0] if structures else None, multi)

    def _policy_rate(self, p: Parse) -> Result:
        """BoJ policy rate, Brazil policy rate, EUR deposit rate: the headline rate of the bank named or implied."""
        refs = tuple(leg.entity.id for leg in p.legs)
        banks = set(p.role('meeting'))
        for leg in p.legs:
            currency = self.currency(self.currency_of(leg.entity))
            if currency is not None and currency.central_bank_id:
                banks.add(currency.central_bank_id)
        if len(banks) != 1:
            note = f'several central banks: {sorted(banks)}' if banks else 'no central bank named'
            return Result('generic', 'policy_rate', refs=refs, note=note)
        bank = self.m.get(OrganizationType.CENTRAL_BANK.id_of(banks.pop()), CentralBank)
        if bank.policy_rate_id is None:
            return Result('seed_gap', 'policy_rate', refs=(bank.id,), note=f'{bank.id} has no policy rate seeded')
        return Result('resolved', 'policy_rate', (self.m.ref(bank, 'policy_rate_id', PolicyRate),), refs=(bank.id,))

    def _segment(self, p: Parse, products: list[str], structures: list[str], multi: list[str]) -> Result:
        """USD IG corporates, EUR HY, munis, EGBs, 10y EUR covered: a segment, its currency named or implied."""
        values = [v.split('|') for v in p.role('sector')]
        sector = next((s for s, _ in values if s), 'corp')  # IG, HY alone: corporates
        rating = next((r for _, r in values if r), None)
        refs = tuple(leg.entity.id for leg in p.legs)
        if any(not (leg.via_country or isinstance(leg.entity, Currency)) for leg in p.legs):
            return Result('partial', refs=refs, note='bond segment with other markets named')
        currencies = {c for leg in p.legs if (c := self.currency_of(leg.entity))} | set(p.role('region'))
        if len(currencies) > 1:
            return Result('partial', refs=refs, note=f'bond segment in several currencies: {sorted(currencies)}')
        ccy = next(iter(currencies), None) or SECTOR_CURRENCY.get(sector)
        if ccy is None:
            return Result('generic', 'bond_segment', note=f'{sector} {rating or ""} with no currency'.strip())
        segment = self.m.build(BondSegment, {'currency_id': ccy, 'sector': sector, 'rating': rating}, AS_OF)
        p.legs = [Leg(segment, tenors=list(p.tenors))]
        return self._build(p, products[0] if products else None, structures[0] if structures else None, multi)

    # -- build ---------------------------------------------------------------------------------------------
    def _template(self, e: Entity, product: str | None) -> Template | None:
        """The template a leg trades: a swap on an index or currency, cash bonds of a programme or segment."""
        if isinstance(e, RateIndex | Currency):
            parts: dict[str, object] = {'index_id': e.key} if isinstance(e, RateIndex) else {'currency_id': e.key}
            if isinstance(e, Currency) and product == 'ois':  # EUR OIS: the OIS default, not the bare-swap one
                parts['family'] = 'ois'
            return self.m.build(Swaption if product == 'swaption' else IRS, parts, AS_OF)
        if isinstance(e, BondProgramme):
            return self.m.build(CashBond, {'programme_id': e.key}, AS_OF)
        if isinstance(e, BondSegment):
            return self.m.build(SegmentBond, {'segment_id': e.key}, AS_OF)
        return None

    def _instance(self, template: Template, tenor: str) -> Instance:
        if template.point_type is OptionPoint:
            m = _TENOR.fullmatch(tenor)
            if not m or not m[3]:
                raise Unresolved(f'swaption needs expiry x tenor, got {tenor}')
            point: object = {'expiry': m[1], 'tenor': m[3]}
        else:
            point = tenor.replace('x', '')
        return self.m.build(Instance, {'template_id': template.id, 'point': point}, AS_OF)

    def _structure(self, weighted: Sequence[tuple[Instance, float]]) -> Structure:
        return self.m.build(Structure, {'legs': [{'instance_id': i.id, 'weight': w} for i, w in weighted]}, AS_OF)

    def _outright(self, template: Template, tenor: str | None, multi: list[str]) -> Result:
        try:
            if len(multi) in (2, 3):
                weights = [-1, 1] if len(multi) == 2 else [-1, 2, -1]
                legs = [(self._instance(template, t), w) for t, w in zip(multi, weights, strict=True)]
                return Result('resolved', 'curve' if len(multi) == 2 else 'fly', (self._structure(legs),))
            if tenor:
                return Result('resolved', 'instance', (self._instance(template, tenor),))
        except Unresolved as error:
            return Result('resolved', template.entity_type.value, (template,), note=str(error))
        return Result('resolved', template.entity_type.value, (template,))

    def _build(self, p: Parse, product: str | None, structure: str | None, multi: list[str]) -> Result:
        classes = p.role('asset_class')
        refs = tuple(leg.entity.id for leg in p.legs)
        if set(classes) & {'credit', 'equities', 'ssa'}:  # EUR IG, US credit: an asset class, not the currency
            return Result('asset_class', classes[0], refs=refs)
        if 'commodities' in classes and all(leg.via_country for leg in p.legs):  # UK natural gas: a location
            return Result('asset_class', 'commodities', note=' '.join(product or '' for _ in [0]).strip())
        context = bool(p.tenors or multi or product or structure or p.bond_words or p.dates or 'rates' in classes)
        names_only = all(leg.via_country or isinstance(leg.entity, Currency) for leg in p.legs)
        if not context and names_only and (len(p.legs) > 1 or p.legs[0].via_country):
            return Result('unrecognised', refs=refs, note='names only: countries or currencies, no market context')
        if 'rates' in classes and not p.bond_words:  # JPY rates, US rates vol: the swap curve
            for leg in p.legs:
                if leg.via_country and (ccy := self.currency(self.currency_of(leg.entity))) is not None:
                    leg.entity, leg.via_country = ccy, False
            product = product or 'irs'
        entities = [leg.entity for leg in p.legs]
        refs = tuple(e.id for e in entities)
        kinds = {_kind(e) for e in entities}
        first = _kind(entities[0])
        tenor = p.tenors[0] if p.tenors else None
        terms = ' '.join(p.tenors + multi)

        if product == 'option' and kinds <= {'rate_index', 'currency'}:
            product = 'swaption'
        if p.dates and product in (None, *SWAPS, 'future') and len(entities) == 1:
            # Jun26 Euribor, Mar26 Bund: a futures contract; Bund Aug54, BTPS 4/45, JGB #161: a bond line
            m = _MONTH_YEAR.fullmatch(p.dates[0])
            near = bool(m) and AS_OF.year - 2 <= 2000 + int(m[1]) <= AS_OF.year + 3
            if first == 'bond_programme' and not (near and product not in SWAPS):
                return Result('kind_gap', 'bond_line', refs=refs, qlib_kind='bnd-ins', note=' '.join(p.dates))
            if first in FUTURE_KIND:
                return Result('kind_gap', 'future', refs=refs, qlib_kind=FUTURE_KIND[first], note=' '.join(p.dates))
        if product == 'fra' and len(entities) > 1 and kinds == {'bond_programme'}:
            product = None  # ITA-FRA-GER: France, not a forward rate agreement
        if product in GAP_PRODUCTS:
            table = FUTURE_KIND if product == 'future' else OPTION_KIND if product == 'option' else {}
            return Result('kind_gap', product, refs=refs, qlib_kind=GAP_PRODUCTS[product] or table.get(first, product),
                          note=terms)
        if product == 'basis' or (len(entities) == 2 and kinds == {'rate_index'}):
            same_ccy = len({self.currency_of(e) for e in entities}) == 1
            return Result('kind_gap', 'basis_swap', refs=refs, qlib_kind='bsw' if same_ccy else 'xcs', note=terms)
        if product == 'forward' and kinds <= {'currency'}:
            ccy = entities[0]
            if len(entities) == 1 and isinstance(ccy, Currency) and ccy.non_deliverable:  # KRW NDF: the USD NDF
                template = self.m.build(FXForward, {'base_id': 'USD', 'quote_id': ccy.key}, AS_OF)
                return self._outright(template, tenor, multi)
            return Result('seed_gap', 'fx_forward', refs=refs, note='forward on a currency, pair not named')
        if product in ('breakeven', 'linker'):
            return self._inflation(entities, product, tenor, multi)
        if len(entities) == 1 and isinstance(entities[0], BondProgramme) and product in SWAPS and not structure:
            structure = 'asset_swap'  # JGB OIS, Bund swaps: the bond against the swap curve
        if structure in ('swap_spread', 'asset_swap') and len(entities) == 1:
            return self._swap_spread(entities[0], structure, tenor, product if product in SWAPS else 'irs')

        rates_context = bool(product in (*SWAPS, 'swaption') or p.tenors or multi or structure in ('curve', 'fly'))
        if len(entities) == 1:
            e = entities[0]
            if isinstance(e, Currency) and not rates_context:
                return Result('resolved', 'currency', (e,))
            if isinstance(e, PolicyRate) and product not in GAP_PRODUCTS:
                return Result('resolved', 'policy_rate', (e,), note=terms)  # Bank Rate: set, not swapped
            if isinstance(e, RateIndex) and not e.is_ois and not product and not multi \
                    and tenor in _FIXING_TENORS:
                return Result('resolved', 'rate_index', (e,), note=f'{tenor} fixing')
            if isinstance(e, RateIndex | Currency | BondProgramme | BondSegment):
                if not (p.tenors or multi or product) and not isinstance(e, Currency):
                    return Result('resolved', e.entity_type.value, (e,))
                template = self._template(e, product)
                assert template is not None
                return self._outright(template, tenor, multi)
            if p.tenors or multi or product:
                qlib = {'commodity': 'cmdtyfwd', 'equity_index': 'eif'}.get(first, '')
                return Result('kind_gap', first, refs=refs, qlib_kind=qlib, note=f'terms: {terms} {product or ""}')
            return Result('resolved', first, (e,))
        if kinds <= {'rate_index', 'currency', 'bond_programme', 'bond_segment'}:
            return self._cross_market(p, product, structure, multi)
        qlib = 'cmdtysprd' if kinds == {'commodity'} else 'struct'
        return Result('kind_gap', 'spread', refs=refs, qlib_kind=qlib, note='spread of underlyings with no template')

    def _inflation(self, entities: list[Entity], product: str, tenor: str | None, multi: list[str]) -> Result:
        """Breakevens and linkers: a sovereign's nominal and inflation-linked programmes."""
        refs = tuple(e.id for e in entities)
        e = entities[0]
        base = e if isinstance(e, BondProgramme) else self.benchmark_bond(self.currency_of(e))
        if len(entities) != 1 or base is None:
            return Result('kind_gap', 'inflation', refs=refs, qlib_kind='ins', note='inflation swap / index')
        nominal = self.programme(base.obligor_id, base.currency_id, 'nominal')
        linker = self.programme(base.obligor_id, base.currency_id, 'linker')
        if nominal is None or linker is None:
            return Result('kind_gap', 'inflation', refs=refs, qlib_kind='ins|inb',
                          note=f'no linker programme: {base.id}')
        if product == 'linker':
            return self._outright(self.m.build(CashBond, {'programme_id': linker.key}, AS_OF), tenor, multi)
        if not tenor:
            return Result('resolved', 'breakeven', (nominal, linker), note='no tenor: programmes only')
        a = self._instance(self.m.build(CashBond, {'programme_id': nominal.key}, AS_OF), tenor)
        b = self._instance(self.m.build(CashBond, {'programme_id': linker.key}, AS_OF), tenor)
        return Result('resolved', 'breakeven', (self._structure([(a, 1), (b, -1)]),))

    def _swap_spread(self, e: Entity, structure: str, tenor: str | None, swap: str = 'irs') -> Result:
        """Swap vs the currency's benchmark bond (swap spread), or bond vs swap (asset swap)."""
        ccy = self.currency_of(e)
        bond = e if isinstance(e, BondProgramme) else self.benchmark_bond(ccy)
        swap_on = e if isinstance(e, RateIndex | Currency) else self.currency(ccy)
        if bond is None or swap_on is None:
            return Result('seed_gap', structure, refs=(e.id,), note=f'no benchmark bond or currency for {ccy}')
        swap_t, bond_t = self._template(swap_on, swap), self._template(bond, None)
        assert swap_t is not None
        assert bond_t is not None
        if not tenor:
            return Result('resolved', structure, (swap_t, bond_t), note='no tenor: templates only')
        s, b = self._instance(swap_t, tenor), self._instance(bond_t, tenor)
        legs = [(s, 1.0), (b, -1.0)] if structure == 'swap_spread' else [(b, 1.0), (s, -1.0)]
        return Result('resolved', structure, (self._structure(legs),))

    def _cross_market(self, p: Parse, product: str | None, structure: str | None, multi: list[str]) -> Result:
        """Two or three rates legs: OAT-Bund 10y, AUD vs USD 2y, OAT-Bund 5s30s (box), ITA-FRA-GER 10y."""
        templates = [self._template(leg.entity, product) for leg in p.legs]
        assert all(templates)
        if multi and len(templates) == 2:
            a, b = templates
            assert a is not None
            assert b is not None
            legs = [(self._instance(a, multi[0]), -1.0), (self._instance(a, multi[1]), 1.0),
                    (self._instance(b, multi[0]), 1.0), (self._instance(b, multi[1]), -1.0)]
            return Result('resolved', 'box', (self._structure(legs),))
        point = p.tenors[0] if p.tenors else None
        if point is None:
            return Result('resolved', structure or 'spread', tuple(t for t in templates if t),
                          note='no tenor: templates only')
        instances = []
        for leg, template in zip(p.legs, templates, strict=True):
            assert template is not None
            instances.append(self._instance(template, leg.tenors[0] if leg.tenors else point))
        if len({i.id for i in instances}) == 1:
            return Result('resolved', 'instance', (instances[0],))
        if len(instances) == 2:
            spread = self._structure([(instances[0], 1), (instances[1], -1)])
            return Result('resolved', structure or 'spread', (spread,))
        if len(instances) == 3:
            return Result('resolved', 'cross_fly',
                          (self._structure([(instances[0], -1), (instances[1], 2), (instances[2], -1)]),))
        return Result('partial', refs=tuple(i.id for i in instances), note='more than three legs')


# -----------------------------------------------------------------------------------------------------
# run
# -----------------------------------------------------------------------------------------------------
_PROBABLE_TICKER = re.compile(r'[A-Z]{1,5}')


def resolve_tickers(resolver: Resolver, manager: DefinitionManager) -> pd.DataFrame:
    """One row per mention in each AssetTicker cell, with its resolution."""
    df = pd.read_csv(CORPUS / 'ledger_asset_ticker.csv', dtype=str, keep_default_na=False)
    rows = []
    for rec in df.to_dict('records'):
        for n, mention in enumerate(split_mentions(str(rec['AssetTicker']))):
            row = resolver.resolve(mention).row(manager)
            if row['status'] == 'unrecognised' and _PROBABLE_TICKER.fullmatch(mention):
                row.update(status='kind_gap', kind='equity', qlib_kind='eq', note='probable single-stock ticker')
            rows.append({'corpus_filepath': rec['corpus_filepath'],
                         'is_redundant_duplicate': rec['is_redundant_duplicate'],
                         'AssetTicker': rec['AssetTicker'], 'mention_no': n, 'mention': mention, **row})
    return pd.DataFrame(rows)


def resolve_keywords(resolver: Resolver, manager: DefinitionManager) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keyword rows that name an instrument, with resolutions; and every distinct keyword's status and count."""
    con = duckdb.connect()
    source = f"read_csv_auto('{(CORPUS / 'ledger_keywords.csv').as_posix()}', all_varchar=true, sample_size=-1)"
    counts = con.execute(f"select Keywords, count(*) n from {source} where is_redundant_duplicate = 'false' "
                         'and Keywords is not null group by 1').df()
    status = pd.DataFrame([{'Keywords': k, **resolver.resolve(k).row(manager)} for k in counts['Keywords']])
    status = status.merge(counts, on='Keywords')
    keep = status[status['status'].isin(INSTRUMENT_STATUSES)].drop(columns='n')
    rows = con.execute(f'select * from {source}').df()
    return rows.merge(keep, on='Keywords'), status


def summarise(tickers: pd.DataFrame, keyword_status: pd.DataFrame) -> pd.DataFrame:
    """Mentions by source, status, kind and QLib kind, with the most frequent examples."""
    frames = {
        'asset_ticker': (tickers[tickers['is_redundant_duplicate'].str.lower() == 'false'].assign(_n=1), 'mention'),
        'keywords': (keyword_status.assign(_n=keyword_status['n'].astype(int)), 'Keywords'),
    }
    parts = []
    for source, (frame, text) in frames.items():
        for (status, kind, qlib), g in frame.groupby(['status', 'kind', 'qlib_kind'], dropna=False):
            top: Counter[str] = Counter()
            for value, n in zip(g[text], g['_n'], strict=True):
                top[str(value)] += int(n)
            parts.append({'source': source, 'status': status, 'kind': kind, 'qlib_kind': qlib,
                          'mentions': top.total(), 'distinct': len(top),
                          'examples': ' | '.join(v for v, _ in top.most_common(8))})
    return pd.DataFrame(parts).sort_values(['source', 'mentions'], ascending=[True, False])


def main() -> None:
    """Resolve both ledgers and write the three outputs."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-keywords', action='store_true', help='resolve asset tickers only')
    args = parser.parse_args()
    manager = ontology_manager()
    resolver = Resolver(manager)
    tickers = resolve_tickers(resolver, manager)
    tickers.to_csv(CORPUS / 'ledger_asset_ticker_markets.csv', index=False)
    keyword_status = pd.DataFrame(columns=['Keywords', 'status', 'kind', 'qlib_kind', 'n'])
    if not args.skip_keywords:
        keywords, keyword_status = resolve_keywords(resolver, manager)
        keywords.to_csv(CORPUS / 'ledger_keywords_instruments.csv', index=False)
    summarise(tickers, keyword_status).to_csv(CORPUS / 'market_mentions_summary.csv', index=False)
    t = tickers[tickers['is_redundant_duplicate'].str.lower() == 'false']
    print('asset_ticker mentions by status:', Counter(t['status']).most_common())
    if not args.skip_keywords:
        by_status: Counter[str] = Counter()
        for status, n in zip(keyword_status['status'], keyword_status['n'], strict=True):
            by_status[str(status)] += int(n)
        print('keyword mentions by status:', by_status.most_common())
    built = Counter(e.entity_type.value for e in manager.store if isinstance(e, Template | Instance | Structure))
    print('built:', dict(built))


if __name__ == '__main__':
    main()
