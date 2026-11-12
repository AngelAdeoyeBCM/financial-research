"""Resolve ledger AssetTicker mentions to ontology markets and instruments.

A seven-stage cascade, cheapest first:

1. normalise        casefold, expand tenors (10-year -> 10y), strip yellow keys and noise
2. alias cache      exact hit on the normalised string: registry surface forms + write-backs
3. pattern parse    ISIN / FIGI / CUSIP (checksummed), Bloomberg bond lines, futures contracts,
                    FX pairs, equity tickers, and a rates grammar for tenors and structures
                    (10y OAT-Bund, UST 2s10s, 10y SOFR swap spread, TIPS breakeven, ...)
4. candidate search character-trigram index + MiniLM embeddings over registry markets
5. score & decide   weighted lexical / semantic / attribute (ccy, geography, kind, tenor) match
6. fallback         low or ambiguous scores go to a review queue with their top candidates
                    (no LLM is called; `review` rows are that queue)
7. write back       accepted aliases go to an xref table and into the in-run cache;
                    --seed-xref loads a previous run's table into the cache

Reads data/corpus/ledger_asset_ticker.csv (its `resolution` column is ignored) and writes one
row per mention to data/corpus/ledger_asset_ticker_resolved.csv, plus data/corpus/asset_xref.csv.

    .venv/Scripts/python.exe scripts/resolve_asset_tickers.py
"""

from __future__ import annotations

import argparse
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from incolor.ontology import (
    AssetSwap,
    Basis,
    Bond,
    BondSegment,
    Box,
    Breakeven,
    Calendar,
    CallPut,
    Commodity,
    CrossFly,
    Currency,
    Curve,
    Entity,
    Fly,
    Form,
    FXPair,
    Index,
    Indicator,
    Instrument,
    Market,
    Outright,
    RateIndex,
    Registry,
    SovereignBond,
    Spread,
    SwapSpread,
    Tenor,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'data' / 'corpus'
INPUT = CORPUS / 'ledger_asset_ticker.csv'
OUTPUT = CORPUS / 'ledger_asset_ticker_resolved.csv'
XREF = CORPUS / 'asset_xref.csv'
EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'

ACCEPT = 0.78   # stage 5: accept at or above, with MARGIN over the runner-up
MARGIN = 0.04
REVIEW = 0.55   # stage 6: review queue at or above, unresolved below


# ---------------------------------------------------------------------------
# result
# ---------------------------------------------------------------------------
@dataclass
class Resolution:
    stage: str           # alias_cache | pattern | search | fallback
    status: str          # resolved | identifier | review | unresolved
    confidence: float
    entity_ids: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    qlib_ids: tuple[str, ...] = ()
    instrument_key: str = ''
    structure: str = ''
    id_type: str = ''
    id_value: str = ''
    candidates: str = ''
    note: str = ''


# ---------------------------------------------------------------------------
# 1. normalise
# ---------------------------------------------------------------------------
_FRACTIONS = {'½': '.5', '¼': '.25', '¾': '.75', '⅛': '.125', '⅜': '.375', '⅝': '.625', '⅞': '.875'}
_FRACTION_RE = re.compile(r'(\d*)\s*([' + ''.join(_FRACTIONS) + '])')
_YELLOW = re.compile(r'\s+(index|curncy|comdty|govt|corp|equity|mtge|muni|pfd)$', re.I)
_NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'twelve': 12, 'fifteen': 15, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
}
_NUMBER_WORD_RE = re.compile(r'\b(' + '|'.join(_NUMBER_WORDS) + r')(?=[\s-]*(?:years?|yrs?|months?|weeks?)\b)')
_TENOR_WORDS = [
    (re.compile(r'\b(\d+)\s*-?\s*(?:years?|yrs?|yr)\b'), r'\1y'),
    (re.compile(r'\b(\d+)\s*-?\s*(?:months?|mths?|mo)\b'), r'\1m'),
    (re.compile(r'\b(\d+)\s*-?\s*(?:weeks?|wks?)\b'), r'\1w'),
    (re.compile(r'\b(\d+)\s+([ymw])\b'), r'\1\2'),
    (re.compile(r'\b(\d+[dwmy])\s*x\s*(\d+[dwmy])\b'), r'\1\2'),          # 1yx1y -> 1y1y
    (re.compile(r'\b(\d+)\s*/\s*(\d+)y\b'), r'\1s\2s'),                     # 2/10y -> 2s10s
    (re.compile(r'^([a-z]{2,6})(\d+[ym])$'), r'\1 \2'),                     # ust10y -> ust 10y
]
_VENUES = r'ice|nymex|comex|cme|cbot|lme|shfe|eurex|ose|sgx|dce|czce|ine|nybot|b3|asx|jpx|hkex|krx'
_NOISE = re.compile(
    r'\b(?:the|level|levels|price|prices|outright|trade|trades|position|positions|exposure|market|markets|'
    r'sector|benchmark|generic|' + _VENUES + r')\b'
)
# ISO 4217 codes, to tell a currency the registry lacks (PEN, RUB) from an unknown ticker.
ISO_CURRENCIES = set(
    'AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD '
    'CDF CHF CLP CNY CNH COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF '
    'GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP '
    'LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB '
    'PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL '
    'THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL'
    .split()
)
METAL_CODES = {'xau': 'cmdty:gold', 'xag': 'cmdty:silver', 'xpt': 'cmdty:platinum', 'xpd': 'cmdty:palladium'}
# Futures roots that research quotes bare ("long TY"), meaning the front contract.
BARE_ROOTS = {'TY', 'TU', 'FV', 'WN', 'UXY', 'RX', 'OE', 'DU', 'IK', 'JB', 'SFR', 'SR3', 'ER', 'CL', 'NG', 'GC',
              'HG', 'ES', 'NQ', 'VX', 'UB'}


@dataclass(frozen=True)
class Norm:
    raw: str             # stripped original, case kept (identifiers, tickers, contracts)
    text: str            # normalised: the alias-cache key
    core: str            # text without noise words
    yellow_key: str | None


def normalise(raw: str) -> Norm:
    s = _FRACTION_RE.sub(lambda m: (m[1] or '0') + _FRACTIONS[m[2]], raw)
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[‐-―−]', '-', s).replace('’', "'")
    s = ' '.join(s.split()).strip(' "\'`.,;:*')
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
    yellow = None
    if m := _YELLOW.search(s):
        yellow, s = m[1].title(), s[: m.start()].strip()
    text = s.casefold()
    text = _NUMBER_WORD_RE.sub(lambda m: str(_NUMBER_WORDS[m[1]]), text)
    for pattern, repl in _TENOR_WORDS:
        text = pattern.sub(repl, text)
    text = ' '.join(text.split()).replace('gas oil', 'gasoil')
    core = ' '.join(_NOISE.sub(' ', text).split()) or text
    return Norm(raw=s, text=text, core=core, yellow_key=yellow)


def split_mentions(cell: str) -> list[str]:
    parts = [p.strip() for p in re.split(r'\s*[;,\n]\s*', cell)]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# 3. pattern parse: identifiers
# ---------------------------------------------------------------------------
def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - 55
    return {'*': 36, '@': 37, '#': 38}[c]


def isin_ok(s: str) -> bool:
    if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', s):
        return False
    digits = ''.join(str(_char_value(c)) for c in s[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10 == int(s[-1])


def _cusip_like_check(body: str) -> int:
    total = 0
    for i, c in enumerate(body):
        v = _char_value(c) * (2 if i % 2 == 1 else 1)
        total += v // 10 + v % 10
    return (10 - total % 10) % 10


def cusip_ok(s: str) -> bool:
    return (
        bool(re.fullmatch(r'[0-9A-Z*@#]{8}\d', s))
        and any(c.isdigit() for c in s[:8])
        and _cusip_like_check(s[:8]) == int(s[8])
    )


def figi_ok(s: str) -> bool:
    return bool(re.fullmatch(r'BBG[0-9B-DF-HJ-NP-TV-Z]{8}\d', s)) and _cusip_like_check(s[:11]) == int(s[11])


_EXCHANGES = (
    'LN|US|UN|UW|UQ|UR|UA|JP|JT|HK|GR|GY|FP|IM|SM|NA|SW|SE|CN|CT|AU|KS|KQ|TT|SS|SZ|CH|C1|C2|SP|BZ|MM|SJ|PL|'
    'DC|NO|FH|ID|BB|AV|PW|TB|IJ|MK|PM|IN|IB|IS|NZ|TI|AB|QD|RM|LI'
)
_EQUITY = [
    re.compile(r'^[A-Z0-9]{1,6}(?:/[A-Z])?\s+(?:' + _EXCHANGES + r')$'),   # BNZL LN, 4553 JP
    re.compile(r'^[A-Z0-9]{1,6}\.(?:[A-Z]{1,2}|ST|DE|PA|AS|MI|SW|HK|TO|AX|KS|T)$'),  # IHG.L, EVOG.ST
]

# Bloomberg government tickers -> registry bond curve.
BBG_GOVT = {
    'T': 'bond:ust', 'B': 'bond:ust', 'UST': 'bond:ust', 'TII': 'bond:tips', 'DBR': 'bond:bund', 'OBL': 'bond:bund',
    'BKO': 'bond:bund', 'BUND': 'bond:bund', 'FRTR': 'bond:oat', 'OAT': 'bond:oat', 'BTPS': 'bond:btp',
    'BTP': 'bond:btp', 'SPGB': 'bond:spgb', 'NETHER': 'bond:dsl', 'DSL': 'bond:dsl', 'BGB': 'bond:olo',
    'OLO': 'bond:olo', 'RAGB': 'bond:ragb', 'PGB': 'bond:pgb', 'RFGB': 'bond:rfgb', 'IRISH': 'bond:irish',
    'GGB': 'bond:ggb', 'UKT': 'bond:gilt', 'UKTI': 'bond:linker', 'JGB': 'bond:jgb', 'SWISS': 'bond:swiss',
    'CAN': 'bond:goc', 'ACGB': 'bond:acgb', 'NZGB': 'bond:nzgb', 'SGB': 'bond:sgb', 'NGB': 'bond:ngb',
    'CGB': 'bond:cgb', 'KTB': 'bond:ktb', 'INDOGB': 'bond:indogb', 'MGS': 'bond:mgs', 'RPGB': 'bond:rpgb',
    'THAIGB': 'bond:thaigb', 'BNTNF': 'bond:ntnf', 'BNTNB': 'bond:ntnb', 'MBONO': 'bond:mbono', 'COLTES': 'bond:tes',
    'SAGB': 'bond:sagb', 'TURKGB': 'bond:turkgb', 'POLGB': 'bond:polgb', 'HGB': 'bond:hgb', 'REPHUN': 'bond:hgb',
    'CZGB': 'bond:czgb', 'ILGB': 'bond:ilgb', 'EU': 'bond:eu',
}
_MONTH = r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*'
_BOND_LINE = re.compile(
    r'^(?P<issuer>[A-Za-z][A-Za-z&.\'\- ]{0,30}?)\s+(?P<cpn>\d{1,2}(?:\.\d+)?)\s*%?\s+'
    r'(?P<mat>\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{2,4}|' + _MONTH + r'[\s\'-]?\d{2,4}|\'?\d{2}s|\d{4})$',
    re.I,
)
_BOND_NO_CPN = re.compile(r'^(?P<issuer>[A-Za-z]{1,8})\s+(?P<mat>' + _MONTH + r'\s?\'?\d{2,4})$', re.I)

# Bloomberg futures roots -> registry underlying.
FUT_ROOTS = {
    'TU': 'bond:ust', 'FV': 'bond:ust', 'TY': 'bond:ust', 'UXY': 'bond:ust', 'US': 'bond:ust', 'WN': 'bond:ust',
    'DU': 'bond:bund', 'OE': 'bond:bund', 'RX': 'bond:bund', 'UB': 'bond:bund', 'IK': 'bond:btp',
    'BTS': 'bond:btp', 'OAT': 'bond:oat', 'G': 'bond:gilt', 'JB': 'bond:jgb', 'XM': 'bond:acgb',
    'YM': 'bond:acgb', 'CN': 'bond:goc',
    'SFR': 'rate:sofr', 'SR3': 'rate:sofr', 'SR1': 'rate:sofr', 'FF': 'rate:fed_funds', 'ER': 'rate:euribor',
    'SFI': 'rate:sonia', 'SO3': 'rate:sonia', 'IR': 'rate:bbsw', 'CRA': 'rate:corra', 'OD': 'rate:cdi',
    'CL': 'cmdty:wti', 'CO': 'cmdty:brent', 'NG': 'cmdty:natural_gas', 'GC': 'cmdty:gold', 'SI': 'cmdty:silver',
    'HG': 'cmdty:copper', 'QS': 'cmdty:gasoil', 'PL': 'cmdty:platinum', 'PA': 'cmdty:palladium',
    'TZT': 'cmdty:ttf', 'ES': 'index:spx', 'NQ': 'index:nasdaq', 'UX': 'index:vix', 'VX': 'index:vix',
}
_CONTRACT = re.compile(r'([A-Z]{1,4})\s?([FGHJKMNQUVXZ])(\d{1,2})')
_GENERIC = re.compile(r'([A-Z]{2,4})(\d)')
_STRIP = re.compile(r'([A-Z]{1,4})\s+([FGHJKMNQUVXZ]\d{1,2}(?:\s*/\s*[FGHJKMNQUVXZ]\d{1,2}){1,2})')


# ---------------------------------------------------------------------------
# 3. pattern parse: rates grammar vocabulary
# ---------------------------------------------------------------------------
_STRUCT_WORDS = [
    ('swap_spread', re.compile(r'\bswap spreads?\b|\bswap sprds?\b|\bswapspreads?\b')),
    ('asset_swap', re.compile(r'\basw\b|\basset[- ]swaps?(?: spreads?)?\b')),
    ('breakeven', re.compile(r'\bbreak-?evens?\b|\bbeis?\b')),
    ('basis', re.compile(r'\bbasis(?: swaps?)?\b')),
    ('fly', re.compile(r'\b(?:butterfl(?:y|ies)|fly|flies)\b')),
    ('curve', re.compile(r'\b(?:steepen(?:er|ers|ing)?|flatten(?:er|ers|ing)?|curve|slope)\b')),
    ('spread', re.compile(r'\bspreads?\b|\bsprds?\b|\bdifferentials?\b')),
]
_FORM_WORDS = [
    (Form.OPTION, re.compile(
        r'\b(?:swaptions?|payers?|receivers?|vols?|volatility|options?|straddles?|strangles?|puts?|calls?|'
        r'risk reversals?|rr|put spreads?|call spreads?)\b'
    )),
    (Form.FUTURE, re.compile(r'\bfutures?\b|\bfuts?\b')),
    (Form.SWAP, re.compile(r'\b(?:swaps?|irs|ois|ndirs|nds|ndois)\b')),
    (Form.FORWARD, re.compile(r'\b(?:fwds?|forwards?|ndfs?|fras?)\b')),
    (Form.REPO, re.compile(r'\brepos?\b')),
]
_CALL_PUT = [
    (CallPut.CALL, re.compile(r'\b(?:payers?|calls?)\b')),
    (CallPut.PUT, re.compile(r'\b(?:receivers?|puts?)\b')),
    (CallPut.STRADDLE, re.compile(r'\bstraddles?\b')),
]
_BOND_WORDS = re.compile(r'\b(?:yields?|bonds?|govts?|govies|gov|cash|notes?|bills?|linkers?|paper|issues?)\b')
_GRAMMAR_NOISE = re.compile(
    r'\b(?:long|short|pay|paid|payer|receive|received|rates?|atmf|atm|otm|itm|spot|real|nominal|'
    r'wideners?|tighteners?|widening|tightening|implied|leg|legs|vs|versus|on|in|of|and|at|for|'
    r'weekly|daily|generic)\b|[+-]?\d+(?:\.\d+)?\s*(?:bps?|%)|[+-]\d+(?:\.\d+)?\b|\(|\)'
)
_FWD_START = re.compile(r'\b(\d+[dwmy])\s*(?:fwd|forward|-fwd)\b')
_MULTI_TENOR = re.compile(
    r'\b\d+s(?:\s*[/-]?\s*\d+s){1,2}\b'
    r'|\b\d+[dwmy](?:\d+[dwmy])?(?:\s*[/-]\s*\d+[dwmy](?:\d+[dwmy])?){1,2}\b'
)
_ONE_TENOR = re.compile(r'\b(\d+[dwmy])(\d+[dwmy])?\b')
_VS = re.compile(r'\s+(?:vs\.?|versus|over|against|v)\s+')
_DASH = re.compile(r'\s*[-/]\s*')

DEMONYMS = {
    'german': 'geo:de', 'ger': 'geo:de', 'deu': 'geo:de', 'french': 'geo:fr', 'fra': 'geo:fr', 'italian': 'geo:it',
    'ita': 'geo:it', 'italy': 'geo:it', 'spanish': 'geo:es', 'spa': 'geo:es', 'esp': 'geo:es', 'dutch': 'geo:nl',
    'nld': 'geo:nl', 'belgian': 'geo:be', 'bel': 'geo:be', 'austrian': 'geo:at', 'aut': 'geo:at',
    'portuguese': 'geo:pt', 'por': 'geo:pt', 'prt': 'geo:pt', 'finnish': 'geo:fi', 'fin': 'geo:fi', 'irish': 'geo:ie',
    'irl': 'geo:ie', 'greek': 'geo:gr', 'grc': 'geo:gr', 'japanese': 'geo:jp', 'jpn': 'geo:jp', 'jap': 'geo:jp',
    'british': 'geo:gb', 'uk': 'geo:gb', 'gbr': 'geo:gb', 'swiss': 'geo:ch', 'canadian': 'geo:ca',
    'australian': 'geo:au', 'aus': 'geo:au', 'kiwi': 'geo:nz', 'swedish': 'geo:se', 'norwegian': 'geo:no',
    'chinese': 'geo:cn', 'chn': 'geo:cn', 'korean': 'geo:kr', 'kor': 'geo:kr', 'taiwanese': 'geo:tw',
    'indian': 'geo:in', 'indonesian': 'geo:id', 'indo': 'geo:id', 'malaysian': 'geo:my', 'philippine': 'geo:ph',
    'thai': 'geo:th', 'brazilian': 'geo:br', 'mexican': 'geo:mx', 'chilean': 'geo:cl', 'colombian': 'geo:co',
    'south african': 'geo:za', 'sa': 'geo:za', 'turkish': 'geo:tr', 'polish': 'geo:pl', 'hungarian': 'geo:hu',
    'czech': 'geo:cz', 'israeli': 'geo:il', 'american': 'geo:us', 'us': 'geo:us', 'usa': 'geo:us', 'u.s.': 'geo:us',
    'euro area': 'geo:ea', 'euro': 'geo:ea', 'eur': 'geo:ea', 'european': 'geo:ea',
}
# Words that are surface forms of some market but mean something else inside a longer mention.
GENERIC_FORMS = {'real', 'won', 'gas', 'oil', 'eu', 'di', 'ff', 'dollar', 'euro', 'pound', 'lira', 'rand', 'kiwi',
                 'crude', 'treasury', 'linkers', 'paper'}

_KIND_HINTS = [
    ('bond', _BOND_WORDS),
    ('bond', re.compile(r'\b(?:gilts?|bunds?|treasur(?:y|ies)|sovereigns?|govts?|tips|linkers?|egbs?|jgbs?)\b')),
    ('rate_index', re.compile(r'\b(?:swaps?|irs|ois|fixings?|libor|ibor|swap rates?|stir|fras?|repo)\b')),
    ('fx', re.compile(r'\b(?:fx|currency|currencies|cross|ndfs?|spot fx|exchange rate)\b')),
    ('index', re.compile(r'\b(?:index|indices|equit(?:y|ies)|stocks?|shares|vix|vol index)\b')),
    ('commodity', re.compile(r'\b(?:crude|oil|gas|lng|metals?|gold|silver|copper|commodit(?:y|ies)|brent|wti)\b')),
    ('indicator', re.compile(r'\b(?:cpi|hicp|rpi|pce|inflation|gdp|pmi|payrolls?)\b')),
]


# ---------------------------------------------------------------------------
# 4. candidate search: trigram index + embeddings
# ---------------------------------------------------------------------------
def trigrams(text: str) -> set[str]:
    padded = f'  {text} '
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


class Embedder:
    """MiniLM sentence embeddings from the local Hugging Face cache, mean-pooled and L2-normalised."""

    def __init__(self, name: str = EMBED_MODEL) -> None:
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(name, local_files_only=True)
        self.model = AutoModel.from_pretrained(name, local_files_only=True).eval()

    def encode(self, texts: list[str], batch: int = 256) -> np.ndarray:
        torch = self._torch
        out = []
        with torch.inference_mode():
            for i in range(0, len(texts), batch):
                enc = self.tokenizer(texts[i : i + batch], padding=True, truncation=True, max_length=48,
                                     return_tensors='pt')
                hidden = self.model(**enc).last_hidden_state
                mask = enc['attention_mask'].unsqueeze(-1).float()
                vec = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                out.append(torch.nn.functional.normalize(vec, dim=1).numpy())
        return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)


# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------
class Resolver:
    def __init__(self, registry: Registry, xref: pd.DataFrame | None = None) -> None:
        self.registry = registry
        self.synthetic: dict[str, Entity] = {}
        self.markets: list[Entity] = [e for e in registry if isinstance(e, (Market, Indicator))]
        self._build_tables()
        self._build_cache()
        if xref is not None:
            self._seed_xref(xref)
        self._build_index()
        self.embedder: Embedder | None = None

    # -- lookup --------------------------------------------------------------
    def find(self, entity_id: str | None) -> Entity | None:
        if entity_id is None:
            return None
        return self.registry.find(entity_id) or self.synthetic.get(entity_id)

    def make(self, stage: str, status: str, confidence: float, entities: tuple[Entity, ...] = (),
             instrument: Instrument | None = None, **kw: str) -> Resolution:
        entities = tuple(dict.fromkeys(entities))
        qlib = []
        for e in entities:
            qid = e.qlib_id(self.find) if isinstance(e, Market) else None
            qlib.append(qid or '')
        return Resolution(
            stage=stage, status=status, confidence=round(confidence, 3),
            entity_ids=tuple(e.entity_id for e in entities), entity_names=tuple(e.name for e in entities),
            kinds=tuple(str(e.entity_kind) for e in entities), qlib_ids=tuple(qlib),
            instrument_key=instrument.key if instrument is not None else '',
            structure=str(instrument.structure) if instrument is not None else '', **kw,
        )

    # -- tables --------------------------------------------------------------
    def _build_tables(self) -> None:
        reg = self.registry
        self.currency_by_code = {e.code.casefold(): e for e in reg if isinstance(e, Currency)}
        self.geo_words: dict[str, str] = dict(DEMONYMS)
        for g in reg:
            if g.entity_id.startswith('geo:'):
                for form in g.surface_forms:
                    self.geo_words.setdefault(normalise(form).text, g.entity_id)
        self.nominal_bond: dict[str, SovereignBond] = {}
        self.linker_bond: dict[str, SovereignBond] = {}
        for e in reg:
            if isinstance(e, SovereignBond):
                table = self.linker_bond if e.segment is BondSegment.INFLATION_LINKED else self.nominal_bond
                table.setdefault(e.geography_id, e)
        self.currency_words: dict[str, str] = {}
        for c in self.currency_by_code.values():
            for form in c.surface_forms:
                key = normalise(form).text
                if key not in GENERIC_FORMS or key == c.code.casefold():
                    self.currency_words.setdefault(key, c.entity_id)
        self.currency_words.pop('real', None)

    def _attrs_of(self, e: Entity) -> tuple[set[str], set[str], str]:
        """(currency ids, geography ids, coarse kind) of a catalogue entity."""
        def geo_of_ccy(cid: str | None) -> str | None:
            c = self.find(cid)
            return getattr(c, 'geography_id', None)

        if isinstance(e, Currency):
            return {e.entity_id}, {e.geography_id}, 'fx'
        if isinstance(e, FXPair):
            ccys = {e.base_id, e.quote_id}
            return ccys, {g for g in map(geo_of_ccy, ccys) if g}, 'fx'
        if isinstance(e, RateIndex):
            return {e.currency_id}, {g for g in [geo_of_ccy(e.currency_id)] if g}, 'rate_index'
        if isinstance(e, Bond):
            return {e.currency_id}, {g for g in [getattr(e, 'geography_id', None)] if g}, 'bond'
        if isinstance(e, Commodity):
            return ({e.currency_id} if e.currency_id else set()), set(), 'commodity'
        if isinstance(e, Index):
            return set(), set(), 'index'
        if isinstance(e, Indicator):
            return set(), {e.geography_id}, 'indicator'
        return set(), set(), 'other'

    # -- 2. alias cache --------------------------------------------------------
    def _build_cache(self) -> None:
        exact: dict[str, set[str]] = defaultdict(set)
        variant: dict[str, set[str]] = defaultdict(set)
        for e in self.markets:
            for form in e.surface_forms:
                n = normalise(form)
                for key in {n.text, n.core}:
                    exact[key].add(e.entity_id)
                    # singular/plural variants: Bund <-> Bunds, OIS swap <-> OIS swaps
                    variant[key[:-1] if key.endswith('s') and len(key) > 3 else key + 's'].add(e.entity_id)
                    if ' ' in key and len(key) > 5:  # FEDFUNDS, EURSTR
                        variant[key.replace(' ', '')].add(e.entity_id)
        self.cache: dict[str, Resolution] = {}
        self.ambiguous: dict[str, tuple[str, ...]] = {}
        for key, ids in exact.items():
            if len(ids) == 1:
                self.cache[key] = self.make('alias_cache', 'resolved', 1.0, (self.registry.get(next(iter(ids))),))
            else:
                self.ambiguous[key] = tuple(sorted(ids))
        for key, ids in variant.items():
            if key not in exact and len(ids) == 1:
                self.cache[key] = self.make('alias_cache', 'resolved', 0.97, (self.registry.get(next(iter(ids))),),
                                            note='plural/singular variant')
        self.write_back: dict[str, dict] = {}

    def _seed_xref(self, xref: pd.DataFrame) -> None:
        for row in xref.itertuples(index=False):
            if row.alias in self.cache:
                continue
            ids = [i for i in str(row.entity_ids or '').split('; ') if i]
            ents = tuple(e for e in map(self.find, ids) if e is not None)
            self.cache[row.alias] = replace(
                self.make('alias_cache', row.status, float(row.confidence), ents),
                instrument_key=row.instrument_key if isinstance(row.instrument_key, str) else '',
                structure=row.structure if isinstance(row.structure, str) else '',
                id_type=row.id_type if isinstance(row.id_type, str) else '',
                note=f'xref ({row.source})',
            )

    def cache_lookup(self, norm: Norm) -> Resolution | None:
        for key in (norm.text, norm.core):
            if key in self.cache:
                return self.cache[key]
        return None

    def entity_for(self, text: str) -> Entity | None:
        """Single registry entity whose surface form (or variant) is `text`."""
        hit = self.cache.get(text)
        if hit is not None and hit.status == 'resolved' and len(hit.entity_ids) == 1 and not hit.instrument_key:
            return self.find(hit.entity_ids[0])
        return None

    def swap_index(self, currency_id: str) -> RateIndex | None:
        c = self.find(currency_id)
        if not isinstance(c, Currency):
            return None
        for suffix in ('swaps', 'ois', 'irs'):
            e = self.entity_for(f'{c.code.casefold()} {suffix}')
            if isinstance(e, RateIndex):
                return e
        return None

    def bond_for_currency(self, currency_id: str) -> SovereignBond | None:
        c = self.find(currency_id)
        return self.nominal_bond.get(getattr(c, 'geography_id', None) or '')

    # -- 3. pattern parse ------------------------------------------------------
    def pattern(self, norm: Norm) -> Resolution | None:
        for parser in (self._identifier, self._bond_line, self._future, self._named_contract, self._govt_ticker,
                       self._fx_pair, self._iso_currency, self._equity, self._grammar):
            if (res := parser(norm)) is not None:
                return res
        return None

    def _identifier(self, norm: Norm) -> Resolution | None:
        s = norm.raw.upper().replace(' ', '')
        for id_type, ok in (('isin', isin_ok), ('figi', figi_ok), ('cusip', cusip_ok)):
            if ok(s):
                note = ''
                if id_type == 'isin':
                    geo = self.geo_words.get(s[:2].casefold())
                    note = f'issuer country {s[:2]}' + (f' ({geo})' if geo else '')
                return self.make('pattern', 'identifier', 0.99, id_type=id_type, id_value=s, note=note)
        return None

    def _bond_line(self, norm: Norm) -> Resolution | None:
        m = _BOND_LINE.match(norm.raw) or _BOND_NO_CPN.match(norm.raw)
        if not m:
            return None
        issuer = m['issuer'].strip()
        bond = self.find(BBG_GOVT.get(issuer.upper()))
        if bond is None:
            e = self.entity_for(normalise(issuer).text)
            bond = e if isinstance(e, Bond) else None
        if bond is not None:
            leg = Outright(ref=bond, form=Form.CASH, security=norm.raw)  # type: ignore[arg-type]
            return self.make('pattern', 'resolved', 0.95, (bond,), leg, id_type='bond_line', id_value=norm.raw)
        geo = self.geo_words.get(normalise(issuer).text)
        note = f'issuer {issuer!r}' + (f' is sovereign {geo}; curve/currency not determined' if geo else '')
        return self.make('pattern', 'identifier', 0.9, id_type='bond_line', id_value=norm.raw, note=note)

    def _contract_leg(self, root: str, code: str) -> tuple[Entity, Outright | None, str]:
        ref = self.find(FUT_ROOTS[root])
        assert ref is not None, root
        try:
            return ref, Outright(ref=ref, form=Form.FUTURE, contract=code), ''  # type: ignore[arg-type]
        except ValueError as exc:
            return ref, None, str(exc)

    def _named_contract(self, norm: Norm) -> Resolution | None:
        """SOFR Z6, Euribor H6/M6: a registry rate or bond curve followed by contract months."""
        m = re.fullmatch(r'(.+?)\s+(?:futures?\s+)?([fghjkmnquvxz]\d{1,2}(?:\s*/\s*[fghjkmnquvxz]\d{1,2}){0,2})',
                         norm.core)
        if m:
            name, months = m[1], [c.strip().upper() for c in m[2].split('/')]
        elif m := re.fullmatch(r'(' + _MONTH + r")\s?'?(\d{2})\s+(.+)", norm.core):  # Jun26 Euribor
            name, months = m[3], [f'{m[1][:3].title()}{m[2]}']
        else:
            return None
        if not isinstance(ref := self.entity_for(name), (RateIndex, Bond)):
            return None
        codes = [f'{ref.name} {c}' for c in months]
        legs = [Outright(ref=ref, form=Form.FUTURE, contract=c) for c in codes]
        instrument: Instrument = (legs[0] if len(legs) == 1 else Calendar(front=legs[0], back=legs[1])
                                  if len(legs) == 2 else Fly(front=legs[0], belly=legs[1], back=legs[2]))
        return self.make('pattern', 'resolved', 0.9, (ref,), instrument, id_type='futures_contract',
                         id_value='/'.join(codes))

    def _govt_ticker(self, norm: Norm) -> Resolution | None:
        """Bare Bloomberg govt tickers (FRTR, BTPS) and their linkers (BTPei, DBRei, UKTi, ACGBi)."""
        raw = norm.raw.replace('€', 'e')
        if raw.upper() in BBG_GOVT and raw.upper() not in ('T', 'B', 'EU'):
            bond = self.find(BBG_GOVT[raw.upper()])
            return self.make('pattern', 'resolved', 0.95, (bond,), id_type='bbg_govt_ticker', id_value=raw.upper())
        m = re.fullmatch(r'([A-Za-z]{2,6}?)(ei|i|il|ils)', raw)
        if not m:
            return None
        base = self.find(BBG_GOVT.get(m[1].upper())) or self.entity_for(m[1].casefold())
        if not isinstance(base, Bond) or base.segment is not BondSegment.NOMINAL:
            return None
        geo = getattr(base, 'geography_id', '')
        if (linker := self.linker_bond.get(geo)) is not None:
            return self.make('pattern', 'resolved', 0.9, (linker,), id_type='linker', id_value=raw)
        return self.make('pattern', 'identifier', 0.85, id_type='linker', id_value=raw,
                         note=f'no inflation-linked curve for {base.entity_id} in registry', candidates=base.entity_id)

    def _iso_currency(self, norm: Norm) -> Resolution | None:
        """Currencies and pairs the registry lacks (PEN, USDRUB) and metal pairs (XAUUSD)."""
        raw = norm.raw.upper()
        m = re.fullmatch(r'([A-Z]{3})\s*[/\-]?\s*([A-Z]{3})', raw)
        if m and m[1].casefold() in METAL_CODES and m[2] in ISO_CURRENCIES:
            metal = self.find(METAL_CODES[m[1].casefold()])
            return self.make('pattern', 'resolved', 0.9, (metal,), note=f'metal quoted in {m[2]}')
        if m and m[1] in ISO_CURRENCIES and m[2] in ISO_CURRENCIES and m[1] != m[2]:
            missing = [c for c in (m[1], m[2]) if c.casefold() not in self.currency_by_code]
            return self.make('pattern', 'identifier', 0.9, id_type='fx_pair', id_value=f'{m[1]}{m[2]}',
                             note=f'currency not in registry: {", ".join(missing)}')
        if re.fullmatch(r'[A-Z]{3}', raw) and raw in ISO_CURRENCIES:
            return self.make('pattern', 'identifier', 0.85, id_type='currency_code', id_value=raw,
                             note='currency not in registry')
        if raw in BARE_ROOTS:
            ref = self.find(FUT_ROOTS[raw])
            try:
                leg: Instrument | None = Outright(ref=ref, form=Form.FUTURE)  # type: ignore[arg-type]
            except ValueError:
                leg = None
            return self.make('pattern', 'resolved', 0.85, (ref,), leg, id_type='futures_root', id_value=raw,
                             note='bare futures root: front contract assumed')
        return None

    def _future(self, norm: Norm) -> Resolution | None:
        raw = norm.raw.upper()
        if m := _STRIP.fullmatch(raw):
            if m[1] not in FUT_ROOTS:
                return None
            codes = [m[1] + c.strip() for c in m[2].split('/')]
        else:
            codes = [c.strip() for c in raw.split('/')]
        parsed = []
        for code in codes:
            if (m := _CONTRACT.fullmatch(code)) and m[1] in FUT_ROOTS:
                parsed.append((m[1], f'{m[1]}{m[2]}{m[3]}'))
            elif (m := _GENERIC.fullmatch(code)) and m[1] in FUT_ROOTS:
                parsed.append((m[1], code))
            else:
                return None
        if len({root for root, _ in parsed}) != 1:
            return None
        legs = [self._contract_leg(root, code) for root, code in parsed]
        ref = legs[0][0]
        outs = [leg for _, leg, _ in legs]
        note = legs[0][2]
        instrument: Instrument | None = None
        if all(outs):
            try:
                if len(outs) == 1:
                    instrument = outs[0]
                elif len(outs) == 2:
                    instrument = Calendar(front=outs[0], back=outs[1])  # type: ignore[arg-type]
                else:
                    instrument = Fly(front=outs[0], belly=outs[1], back=outs[2])  # type: ignore[arg-type]
            except ValueError as exc:
                note = str(exc)
        conf = 0.95 if instrument is not None else 0.85
        return self.make('pattern', 'resolved', conf, (ref,), instrument, id_type='futures_contract',
                         id_value='/'.join(code for _, code in parsed), note=note)

    def _fx_pair(self, norm: Norm) -> Resolution | None:
        m = re.fullmatch(r'([a-z]{3})\s*[/\-]?\s*([a-z]{3})\b\s*(.*)', norm.text)
        if not m or m[1] == m[2] or m[1] not in self.currency_by_code or m[2] not in self.currency_by_code:
            return None
        base, quote, rest = self.currency_by_code[m[1]], self.currency_by_code[m[2]], m[3]
        if rest and not self._only_terms(rest):
            return None
        if re.search(r'\b(?:swap spreads?|basis|xccy|cross-currency)\b', rest) or re.search(
            r'(?<!put )(?<!call )\bspreads?\b', rest
        ):
            return None  # MXN-USD 5y swap spread: two rates curves, not the FX pair
        note = ''
        pair = self.find(f'fx:{m[1]}{m[2]}')
        if pair is None and (inverse := self.find(f'fx:{m[2]}{m[1]}')) is not None:
            pair, note = inverse, f'quoted inverted ({m[1].upper()}/{m[2].upper()})'
        if pair is None:
            pair = FXPair(entity_id=f'fx:{m[1]}{m[2]}', name=(m[1] + m[2]).upper(),
                          base_id=base.entity_id, quote_id=quote.entity_id)
            self.synthetic[pair.entity_id] = pair
            note = 'cross not in registry: synthesised from currencies'
        instrument = None
        if rest:
            form, call_put = self._form(rest), self._call_put(rest)
            tenors = [Tenor(t2, start=t1) if t2 else Tenor(t1) for t1, t2 in _ONE_TENOR.findall(rest)]
            terms: dict[str, object] = {}
            if form is Form.OPTION:
                if tenors:
                    terms['expiry'] = Tenor(tenors[0].start or tenors[0].length)
                if call_put:
                    terms['call_put'] = call_put
            elif tenors:
                terms['tenor'] = tenors[0]
            if form is not None or terms:
                try:
                    instrument = Outright(ref=pair, form=form or Form.CASH, **terms)  # type: ignore[arg-type]
                except ValueError as exc:
                    note = '; '.join(x for x in (note, str(exc)) if x)
            if re.search(r'\b(?:put|call) spreads?\b|\brisk reversals?\b|\bstrangles?\b', rest):
                note = '; '.join(x for x in (note, 'option structure (strikes) not modelled') if x)
        return self.make('pattern', 'resolved', 0.95, (pair,), instrument, note=note)

    def _only_terms(self, text: str) -> bool:
        """True when `text` holds only tenors, form/structure words and noise."""
        rest = _ONE_TENOR.sub(' ', text)
        for _, rx in _FORM_WORDS:
            rest = rx.sub(' ', rest)
        rest = _GRAMMAR_NOISE.sub(' ', _NOISE.sub(' ', rest))
        rest = re.sub(r'\b(?:spreads?|cross|pair|fx|vol|skew|ndf|crosses)\b', ' ', rest)
        return not rest.strip(' -/')

    def _equity(self, norm: Norm) -> Resolution | None:
        if norm.yellow_key == 'Equity' or any(rx.fullmatch(norm.raw) for rx in _EQUITY):
            return self.make('pattern', 'identifier', 0.9, id_type='equity_ticker', id_value=norm.raw,
                             note='single-name equity: outside the markets registry')
        return None

    @staticmethod
    def _form(text: str) -> Form | None:
        for form, rx in _FORM_WORDS:
            if rx.search(text):
                return form
        return None

    @staticmethod
    def _call_put(text: str) -> CallPut | None:
        for cp, rx in _CALL_PUT:
            if rx.search(text):
                return cp
        return None

    # -- the rates grammar -------------------------------------------------------
    def _grammar(self, norm: Norm) -> Resolution | None:
        text = norm.core
        struct = next((name for name, rx in _STRUCT_WORDS if rx.search(text)), None)
        form = self._form(text)
        call_put = self._call_put(text)
        bondish = bool(_BOND_WORDS.search(text))
        start = None
        if m := _FWD_START.search(text):
            start, text = m[1], (text[: m.start()] + ' ' + text[m.end() :])
            if form is Form.FORWARD and not re.search(r'\b(?:fwds?|forwards?|ndfs?|fras?)\b', text):
                form = self._form(text)
        legs: tuple[Tenor, ...] = ()
        if m := _MULTI_TENOR.search(text):
            try:
                legs = Tenor.parse_legs(m[0].replace(' ', ''))
                text = text[: m.start()] + ' ' + text[m.end() :]
            except ValueError:
                legs = ()
        segments = self._segment(text, context=bool(struct or legs or bondish or start), form=form)
        if segments is None:
            return None
        if form is Form.FORWARD and re.search(r'(?:^|[-/ ])fra(?:$|[-/ ])', text) and all(
            isinstance(e, Bond) for e, _ in segments
        ):
            form = None  # ITA-FRA-GER
        vs_parts = _VS.split(' '.join(text.split()))
        if len(segments) == 3 and len(vs_parts) == 2 and not _DASH.search(vs_parts[0]):
            segments = [segments[1], segments[0], segments[2]]  # "Spain vs Italy/Germany": Spain is the belly
        has_tenor = bool(legs) or any(ts for _, ts in segments)
        # "real yields": the inflation-linked curve of that market.
        if re.search(r'\breal (?:yields?|rates?)\b', norm.core):
            fixed = []
            for e, ts in segments:
                geo = getattr(e, 'geography_id', None) or getattr(self.find(getattr(e, 'currency_id', None)),
                                                                  'geography_id', None)
                if (linker := self.linker_bond.get(geo or '')) is None:
                    return None
                fixed.append((linker, ts))
            segments, form = fixed, None
        # A currency as a rates leg means its swap curve ("JPY rates", "EUR 5y5y", "AUD vs USD basis").
        rates_word = bool(re.search(r'\brates?\b', norm.core))
        if form is Form.SWAP or has_tenor or rates_word or struct in ('basis', 'curve', 'fly', 'swap_spread'):
            fixed = []
            for e, ts in segments:
                if isinstance(e, Currency) and not (form is Form.OPTION and len(segments) == 1 and not has_tenor):
                    e = self.swap_index(e.entity_id) or e
                fixed.append((e, ts))
            segments = fixed
        entities = tuple(e for e, _ in segments)
        # Nothing beyond a name: an alias variant, not an instrument.
        if len(segments) == 1 and not (struct or legs or has_tenor or form or call_put or start):
            if norm.core == normalise(entities[0].name).core:
                return None
            return self.make('pattern', 'resolved', 0.9, entities, note='name after stripping descriptors')
        try:
            instrument = self._build(segments, legs, struct, form, call_put, start)
        except (ValueError, TypeError, KeyError) as exc:
            return self.make('pattern', 'resolved', 0.85, entities, note=f'structure not built: {exc}')
        if instrument is None:
            return self.make('pattern', 'resolved', 0.85, entities, note='structure not recognised')
        entities = tuple(r for r in instrument.refs if isinstance(r, Entity)) or entities
        return self.make('pattern', 'resolved', 0.95, entities, instrument)

    def _segment(self, text: str, context: bool, form: Form | None) -> list[tuple[Entity, list[Tenor]]] | None:
        """Split into legs and resolve each name; None unless every leg resolves."""
        text = ' '.join(text.split()).strip(' -/')
        if not text:
            return None
        for splitter in (None, _VS, 'both'):
            if splitter is None:
                parts = [text]
            elif splitter is _VS:
                parts = _VS.split(text)
            else:
                parts = [p for chunk in _VS.split(text) for p in _DASH.split(chunk)]
            parts = [p.strip() for p in parts if p.strip()]
            if splitter is not None and len(parts) < 2:
                continue
            multi = len(parts) > 1
            out = []
            for part in parts:
                leg = self._leg(part, context=context or multi, form=form)
                if leg is None:
                    break
                out.append(leg)
            else:
                if out:
                    return out
        return None

    def _leg(self, part: str, context: bool, form: Form | None = None) -> tuple[Entity, list[Tenor]] | None:
        tenors = [Tenor(t2, start=t1) if t2 else Tenor(t1) for t1, t2 in _ONE_TENOR.findall(part)]
        name = ' '.join(_ONE_TENOR.sub(' ', part).split())
        candidates = [name]
        name = ' '.join(_GRAMMAR_NOISE.sub(' ', name).split())
        candidates.append(name)
        for _, rx in _STRUCT_WORDS:
            name = rx.sub(' ', name)
        for _, rx in _FORM_WORDS:
            name = rx.sub(' ', name)
        stripped = ' '.join(_BOND_WORDS.sub(' ', name).split())
        candidates += [' '.join(name.split()), stripped]
        bondish = bool(_BOND_WORDS.search(part))
        candidates = list(dict.fromkeys(c for c in candidates if c))
        for cand in candidates:
            if (e := self.entity_for(cand)) is not None:
                return e, tenors
        for cand in candidates:  # FRA is France before it is a forward rate agreement
            if cand in self.geo_words and (context or tenors or bondish or form is not None):
                geo = self.geo_words[cand]
                bond = self.nominal_bond.get(geo)
                if form in (Form.SWAP, Form.OPTION) and not bondish:  # US swaption vol, India 5y IRS
                    ccy = next((c for c in self.currency_by_code.values() if c.geography_id == geo), None)
                    idx = self.swap_index(ccy.entity_id) if ccy else None
                    if idx is not None:
                        return idx, tenors
                if bond is not None:
                    return bond, tenors
            if cand in self.currency_by_code:
                return self.currency_by_code[cand], tenors
        return None

    def _build(self, segments: list[tuple[Entity, list[Tenor]]], legs: tuple[Tenor, ...], struct: str | None,
               form: Form | None, call_put: CallPut | None, start: str | None) -> Instrument | None:
        def leg(e: Entity, tenor: Tenor | None, leg_form: Form | None = None) -> Outright:
            f = leg_form or _leg_form(e, form)
            terms: dict[str, object] = {}
            if tenor is not None and start and not tenor.start:
                tenor = Tenor(tenor.length, start=start)
            if f is Form.OPTION:
                if tenor is not None:
                    if tenor.start:
                        terms['expiry'], terms['tenor'] = Tenor(tenor.start), Tenor(tenor.length)
                    elif isinstance(e, (FXPair, Currency)):
                        terms['expiry'] = tenor
                    else:
                        terms['tenor'] = tenor
                if call_put is not None:
                    terms['call_put'] = call_put
            elif tenor is not None:
                terms['tenor'] = tenor
            return Outright(ref=e, form=f, **terms)  # type: ignore[arg-type]

        tenors = [ts for _, ts in segments]
        shared = next((ts[0] for ts in tenors if ts), None)

        def t(i: int) -> Tenor | None:
            return tenors[i][0] if tenors[i] else shared

        n = len(segments)
        if n == 1:
            e = segments[0][0]
            if struct == 'breakeven' and isinstance(e, Bond):
                geo = getattr(e, 'geography_id', '')
                nominal = e if e.segment is BondSegment.NOMINAL else self.nominal_bond.get(geo)
                linker = e if e.segment is BondSegment.INFLATION_LINKED else self.linker_bond.get(geo)
                if nominal is None or linker is None:
                    return None
                return Breakeven(long=leg(nominal, t(0), Form.CASH), short=leg(linker, t(0), Form.CASH))
            if struct == 'swap_spread':
                if isinstance(e, RateIndex) and (bond := self.bond_for_currency(e.currency_id)):
                    return SwapSpread(long=leg(e, t(0), Form.SWAP), short=leg(bond, t(0), Form.CASH))
                if isinstance(e, Bond) and (idx := self.swap_index(e.currency_id)):
                    return SwapSpread(long=leg(idx, t(0), Form.SWAP), short=leg(e, t(0), Form.CASH))
                return None
            if struct == 'asset_swap' and isinstance(e, Bond) and (idx := self.swap_index(e.currency_id)):
                return AssetSwap(long=leg(e, t(0), Form.CASH), short=leg(idx, t(0), Form.SWAP))
            if len(legs) == 2:
                f = _leg_form(e, form)
                return Curve(front=leg(e, legs[0], f), back=leg(e, legs[1], f))
            if len(legs) == 3:
                f = _leg_form(e, form)
                return Fly(front=leg(e, legs[0], f), belly=leg(e, legs[1], f), back=leg(e, legs[2], f))
            if len(tenors[0]) == 2 and struct in ('curve', 'spread', None) and form is not Form.OPTION:
                return Curve(front=leg(e, tenors[0][0]), back=leg(e, tenors[0][1]))
            return leg(e, t(0))
        if n == 2:
            (a, _), (b, _) = segments
            if len(legs) == 2:
                return Box(long=Curve(front=leg(a, legs[0]), back=leg(a, legs[1])),
                           short=Curve(front=leg(b, legs[0]), back=leg(b, legs[1])))
            if a == b:  # 10y USTs vs 5y USTs, 2Y Treasury / 10Y Treasury
                f = _leg_form(a, form)
                return Curve(front=leg(a, t(0), f), back=leg(b, t(1), f))
            if isinstance(a, RateIndex) and isinstance(b, RateIndex):
                return Basis(long=leg(a, t(0)), short=leg(b, t(1)))
            if struct == 'swap_spread' or (isinstance(a, RateIndex) and isinstance(b, Bond)):
                swap, bond = (a, b) if isinstance(a, RateIndex) else (b, a)
                return SwapSpread(long=leg(swap, t(0), Form.SWAP), short=leg(bond, t(1), Form.CASH))
            if struct == 'asset_swap' or (isinstance(a, Bond) and isinstance(b, RateIndex)):
                bond, swap = (a, b) if isinstance(a, Bond) else (b, a)
                return AssetSwap(long=leg(bond, t(0), Form.CASH), short=leg(swap, t(1), Form.SWAP))
            if isinstance(a, Bond) and isinstance(b, Bond) and {a.segment, b.segment} == {
                BondSegment.NOMINAL, BondSegment.INFLATION_LINKED
            } and (struct == 'breakeven' or a.obligor_id == b.obligor_id):
                nominal, linker = (a, b) if a.segment is BondSegment.NOMINAL else (b, a)
                return Breakeven(long=leg(nominal, t(0)), short=leg(linker, t(1)))
            return Spread(long=leg(a, t(0)), short=leg(b, t(1)))
        if n == 3 and not legs:
            return CrossFly(left=leg(segments[0][0], t(0)), belly=leg(segments[1][0], t(1)),
                            right=leg(segments[2][0], t(2)))
        return None

    # -- 4/5. candidate search and scoring -------------------------------------
    def _build_index(self) -> None:
        self.forms: list[tuple[str, int]] = []
        for idx, e in enumerate(self.markets):
            for form in dict.fromkeys(normalise(f).core for f in e.surface_forms):
                self.forms.append((form, idx))
        self.form_grams = [trigrams(f) for f, _ in self.forms]
        self.postings: dict[str, list[int]] = defaultdict(list)
        for fi, grams in enumerate(self.form_grams):
            for g in grams:
                self.postings[g].append(fi)
        self.explain_words = {w for w in [*self.geo_words, *self.currency_words, *DEMONYMS] if ' ' not in w}
        self.explain_words |= {'crude', 'oil', 'index', 'futures', 'future', 'spot', 'rate', 'rates', 'yield',
                               'yields', 'bond', 'bonds', 'govt', 'curve', 'fx', 'nat', 'natural'}
        self.attrs = [self._attrs_of(e) for e in self.markets]
        self.by_geo: dict[str, list[int]] = defaultdict(list)
        self.by_ccy: dict[str, list[int]] = defaultdict(list)
        for idx, (ccys, geos, _) in enumerate(self.attrs):
            for c in ccys:
                self.by_ccy[c].append(idx)
            for g in geos:
                self.by_geo[g].append(idx)

    def _ensure_embeddings(self) -> None:
        if self.embedder is not None:
            return
        self.embedder = Embedder()
        texts = [f for f, _ in self.forms]
        self.form_vecs = self.embedder.encode(texts)
        self.form_entity = np.array([idx for _, idx in self.forms])

    def query_attrs(self, text: str) -> tuple[set[str], set[str], set[str], bool]:
        words = f' {text} '
        ccys = {cid for w, cid in self.currency_words.items() if f' {w} ' in words}
        geos = {gid for w, gid in self.geo_words.items() if len(w) > 2 and f' {w} ' in words}
        geos |= {gid for w, gid in DEMONYMS.items() if len(w) <= 2 and f' {w} ' in words}
        kinds = {kind for kind, rx in _KIND_HINTS if rx.search(text)}
        return ccys, geos, kinds, bool(_ONE_TENOR.search(text) or _MULTI_TENOR.search(text))

    def search(self, norms: list[Norm]) -> list[Resolution]:
        if not norms:
            return []
        self._ensure_embeddings()
        assert self.embedder is not None
        qvecs = self.embedder.encode([n.core for n in norms])
        n_ent = len(self.markets)
        results = []
        for norm, qvec in zip(norms, qvecs, strict=True):
            q = norm.core
            qgrams = trigrams(q)
            qtokens = q.split()
            overlap: Counter[int] = Counter()
            for g in qgrams:
                for fi in self.postings.get(g, ()):
                    overlap[fi] += 1
            lex = np.zeros(n_ent)
            qcov = np.zeros(n_ent)  # share of query tokens explained by the entity's best form
            for fi, ov in overlap.items():
                form, idx = self.forms[fi]
                dice = 2 * ov / (len(qgrams) + len(self.form_grams[fi]))
                ftokens = form.split()
                # Token coverage both ways: query tokens the form (or an attribute word) explains,
                # and form tokens the query contains. "EUR IG" vs "EUR" leaves IG unexplained.
                cov_q = sum(any(_tok_match(t, u) for u in ftokens) or self._explained(t) for t in qtokens)
                cov_f = sum(any(_tok_match(u, t) for t in qtokens) for u in ftokens)
                coverage = (cov_q / len(qtokens)) * (cov_f / len(ftokens))
                score = 0.5 * dice + 0.5 * coverage
                if score > lex[idx]:
                    lex[idx], qcov[idx] = score, cov_q / len(qtokens)
            sims = self.form_vecs @ qvec
            emb = np.zeros(n_ent)
            np.maximum.at(emb, self.form_entity, sims)
            ccys, geos, kinds, tenor = self.query_attrs(q)
            pool = set(np.argsort(-lex)[:10]) | set(np.argsort(-emb)[:10])
            for g in geos:
                pool |= set(self.by_geo.get(g, ()))
            for c in ccys:
                pool |= set(self.by_ccy.get(c, ()))
            scored = []
            for idx in pool:
                attr = self._attr_score(idx, ccys, geos, kinds, tenor)
                score = 0.45 * lex[idx] + 0.35 * max(emb[idx], 0.0) + 0.20 * attr
                scored.append((score, idx, lex[idx], emb[idx], attr, qcov[idx]))
            scored.sort(reverse=True)
            results.append(self._decide(norm, scored))
        return results

    def _explained(self, token: str) -> bool:
        return token in self.explain_words

    def _attr_score(self, idx: int, ccys: set[str], geos: set[str], kinds: set[str], tenor: bool) -> float:
        """Attribute agreement mapped to [0, 1]; 0.5 when the query states no attributes."""
        cand_ccys, cand_geos, cand_kind = self.attrs[idx]
        match = conflict = 0
        for want, have in ((ccys, cand_ccys), (geos, cand_geos)):
            if want:
                if want & have:
                    match += 1
                else:
                    conflict += 1
        if kinds:
            if cand_kind in kinds or (cand_kind == 'fx' and 'fx' in kinds):
                match += 1
            else:
                conflict += 1
        if tenor:
            if cand_kind in ('bond', 'rate_index'):
                match += 1
            else:
                conflict += 1
        if match + conflict == 0:
            return 0.5
        return 0.5 + 0.5 * (match - conflict) / (match + conflict)

    def _decide(self, norm: Norm, scored: list[tuple]) -> Resolution:
        top = scored[:3]
        listing = '; '.join(f'{self.markets[i].entity_id}={s:.2f}' for s, i, *_ in top)
        best = top[0] if top else None
        second = top[1][0] if len(top) > 1 else 0.0
        if best is not None:
            score, idx, lex, emb, attr, covered = best
            entity = self.markets[idx]
            detail = f'lex={lex:.2f} emb={emb:.2f} attr={attr:.2f} covered={covered:.2f}'
            if score >= ACCEPT and score - second >= MARGIN and covered == 1.0:
                return self.make('search', 'resolved', score, (entity,), candidates=listing, note=detail)
            if score >= REVIEW:
                why = ('unexplained tokens' if covered < 1.0 else 'ambiguous') if score >= ACCEPT else 'low confidence'
                return self.make('fallback', 'review', score, candidates=listing, note=f'{why}: {detail}')
        if norm.yellow_key:
            return self.make('fallback', 'identifier', 0.8, id_type='bbg_ticker',
                             id_value=f'{norm.raw} {norm.yellow_key}', candidates=listing,
                             note='Bloomberg ticker not in registry')
        conf = best[0] if best else 0.0
        shape = 'ticker_like' if re.fullmatch(r'[A-Z][A-Z0-9.]{0,5}', norm.raw) else ''
        return self.make('fallback', 'unresolved', conf, id_type=shape, candidates=listing if conf >= 0.4 else '')

    # -- 7. write back ---------------------------------------------------------
    def remember(self, norm: Norm, res: Resolution) -> None:
        if res.stage == 'alias_cache' or res.status not in ('resolved', 'identifier'):
            return
        self.cache.setdefault(norm.text, replace(res, stage='alias_cache', note=f'write-back from {res.stage}'))
        self.write_back.setdefault(norm.text, {
            'alias': norm.text, 'example': norm.raw, 'status': res.status,
            'entity_ids': '; '.join(res.entity_ids), 'instrument_key': res.instrument_key,
            'structure': res.structure, 'id_type': res.id_type, 'source': res.stage, 'confidence': res.confidence,
        })


def _tok_match(a: str, b: str) -> bool:
    """Same token, or a plural/inflection of it (gilt ~ gilts, treasury ~ treasuries)."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and len(long_) - len(short) <= 3 and long_.startswith(short[: max(4, len(short) - 1)])


def _leg_form(e: Entity, form: Form | None) -> Form:
    if form is not None:
        if form is Form.SWAP and isinstance(e, Bond):
            return Form.CASH
        return form
    if isinstance(e, (RateIndex, Indicator)):
        return Form.SWAP
    return Form.CASH


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def run(seed_xref: bool) -> None:
    t0 = time.time()
    ledger = pd.read_csv(INPUT, usecols=['corpus_filepath', 'is_redundant_duplicate', 'AssetTicker'])
    registry = Registry.load_default()
    xref = pd.read_csv(XREF) if seed_xref and XREF.exists() else None
    resolver = Resolver(registry, xref)

    rows = []
    for rec in ledger.itertuples(index=False):
        cell = rec.AssetTicker if isinstance(rec.AssetTicker, str) else ''
        mentions = split_mentions(cell) or ['']
        for i, mention in enumerate(mentions):
            rows.append((rec.corpus_filepath, rec.is_redundant_duplicate, rec.AssetTicker, i, mention))
    mentions = pd.DataFrame(rows, columns=['corpus_filepath', 'is_redundant_duplicate', 'AssetTicker',
                                           'mention_no', 'mention'])
    order = mentions['mention'].value_counts()  # most frequent first: write-backs serve the long tail
    print(f'{len(ledger):,} ledger rows -> {len(mentions):,} mentions, {len(order):,} distinct')

    results: dict[str, Resolution] = {}
    norms: dict[str, Norm] = {}
    pending: list[str] = []
    for mention in order.index:
        if not mention:
            results[mention] = Resolution('normalise', 'empty', 0.0)
            continue
        norm = norms[mention] = normalise(mention)                     # 1
        res = resolver.cache_lookup(norm)                              # 2
        if res is None:
            res = resolver.pattern(norm)                               # 3
        if res is None:
            pending.append(mention)
            continue
        results[mention] = res
        resolver.remember(norm, res)                                   # 7
    print(f'stages 1-3: {time.time() - t0:.1f}s, {len(pending):,} distinct mentions to search')

    # Write-backs from stage 3 may now cover strings that missed the cache earlier.
    still = []
    for mention in pending:
        res = resolver.cache_lookup(norms[mention])
        if res is not None:
            results[mention] = res
        else:
            still.append(mention)
    for mention, res in zip(still, resolver.search([norms[m] for m in still]), strict=True):  # 4, 5, 6
        results[mention] = res
        resolver.remember(norms[mention], res)                         # 7
    print(f'stages 4-6: {time.time() - t0:.1f}s')

    def col(attr: str, join: bool = False) -> pd.Series:
        values = mentions['mention'].map(lambda m: getattr(results[m], attr))
        return values.map(lambda v: '; '.join(v)) if join else values

    mentions['normalised'] = mentions['mention'].map(lambda m: norms[m].text if m in norms else '')
    for attr in ('stage', 'status', 'confidence'):
        mentions[attr] = col(attr)
    for attr in ('entity_ids', 'entity_names', 'kinds', 'qlib_ids'):
        mentions[attr] = col(attr, join=True)
    for attr in ('instrument_key', 'structure', 'id_type', 'id_value', 'candidates', 'note'):
        mentions[attr] = col(attr)
    mentions = mentions.rename(columns={'kinds': 'market_kinds'})
    mentions.to_csv(OUTPUT, index=False)
    pd.DataFrame(list(resolver.write_back.values())).to_csv(XREF, index=False)
    print(f'wrote {OUTPUT.relative_to(ROOT)} ({len(mentions):,} rows) and {XREF.relative_to(ROOT)} '
          f'({len(resolver.write_back):,} aliases) in {time.time() - t0:.1f}s\n')
    report(mentions)


def report(df: pd.DataFrame) -> None:
    df = df[df['status'] != 'empty']
    distinct = df.drop_duplicates('mention')
    table = pd.DataFrame({
        'mentions': df.groupby(['stage', 'status']).size(),
        'distinct': distinct.groupby(['stage', 'status']).size(),
    }).fillna(0).astype(int)
    table['mentions_%'] = (100 * table['mentions'] / len(df)).round(1)
    print(table.to_string(), '\n')
    print('status share of mentions:')
    print((100 * df['status'].value_counts(normalize=True)).round(1).to_string(), '\n')
    print('structures built:')
    print(df.loc[df['structure'] != '', 'structure'].value_counts().to_string(), '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seed-xref', action='store_true', help='seed the alias cache from a previous asset_xref.csv')
    run(parser.parse_args().seed_xref)
