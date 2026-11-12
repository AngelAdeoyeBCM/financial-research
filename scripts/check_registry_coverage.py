"""Measure how much of an extracted-entity CSV the seed registries cover.

    python scripts/check_registry_coverage.py output/entities.csv

Each mention is resolved against config/registries: exact alias match first,
then after stripping mention-level qualifiers (tenors, dates, "swap",
"futures" ...), then as a multi-leg structure ("OAT-Bund spread"). Unresolved
mentions are bucketed into the documented out-of-scope groups; anything left
in `unmapped` needs a registry entry or is extraction noise.
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from incolor.ontology import Category, Registry

ALLOWED = {
    'central_bank': {Category.ORGANIZATION},
    'institution': {Category.ORGANIZATION, Category.GEOGRAPHY},
    'person': {Category.PERSON},
    'currency': {Category.MARKET},
    'instrument': {Category.MARKET, Category.INDICATOR, Category.MEASURE, Category.POLICY},
    'event': {Category.EVENT, Category.INDICATOR, Category.MEASURE, Category.POLICY},
}

# Case-sensitive: 'SEP' (Summary of Economic Projections) is not a month.
_MONTHS = (
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|'
    r'Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
)
_DATES = [
    rf'\b\d{{1,2}}[-\s]?{_MONTHS}(?:[-\s]?\d{{2,4}})?\b',  # 28 Aug, 28-Oct-26, 15Dec26
    rf'\b{_MONTHS}(?:[-\s]?\d{{2,4}})?\b',                  # Sep-26, September, Aug
]
_QUALIFIERS = [
    r'\b\d{4}(?:/\d{2,4})?\b',                         # 2027, 2026/27
    r'\bq[1-4]\b',
    r'\b\d+(?:\.\d+)?[dwmy](?:\d+[dwmy])*\b',          # 10y, 2y2y, 6m30y
    r'(?<=[A-Z])\d+[dwmy]\b',                          # USD30y
    r'\b\d+s\d+s(?:\d+s)?\b',                          # 2s10s
    r'\b\d+x\d+(?:\.\d+)?\b',                          # 1x1.5
    r'\b\d{1,2}(?:th|st|nd|rd)\b',                     # 15th
]
_WORDS = (
    r'\b(?:swaps?|yields?|futures?|options?|spot|ndf|forwards?|flash|final|'
    r'advance|preliminary|data|release|announcement|outright|longs?|shorts?|'
    r'basis|third|second|equities|front-end|long-end|long-term|rates|bonds?)\b'
)
_LEG_SPLIT = re.compile(r'\s+vs\.?\s+|\s*[–—]\s*|(?<=\w)-(?=[A-Z])|\s*/\s*')
_STRUCTURE = (
    r'\b(?:spreads?|steepeners?|flatteners?|fly|tighteners?|wideners?|receivers?|'
    r'payers?|straddles?|call|put|seagull|collar|dual digital|credit|bear|bull|'
    r'curve|hedge|fwd|year-end)\b'
)

BUCKETS = {
    'contract_ticker': r'\b[A-Z0-9]{2,7}[FGHJKMNQUVXZ]\d\b|\d+/\d+/\d+',
    'trade_structure': r'steepener|flattener|\bfly\b|payer|receiver|straddle|seagull|'
                       r'call spread|widener|tightener|collar|digital|crack spread|\bspread|'
                       r'\bcurve\b',
    'policy_tool': r'\bQT\b|\bTPI\b|\bOMT\b|PEPP|\bAPP\b|LTRO|\bRRR\b|\bSLF\b|Standing Lending|'
                   r'\bAPF\b|intervention|reserve management|eSLR|SRBI|FCNR|relending|'
                   r'lending rate|subsidy|quotas?\b|policy-based|Livret|Transmission Protection|'
                   r'structural (?:portfolio|tender)|OMOs|\bhikes?\b|hiking cycle|reverse repo|'
                   r'benchmark deposit|financing tool|easing|gas reserve|\bTGA\b|^repo$',
    'fiscal_measure': r'\bVAT\b|duty|\btax\b|Warm Homes|fares freeze|Renewables Obligation|'
                      r'Ofgem|overseas aid|special LGB|LGFV|debt issuance',
    'theme': r'\bAI\b|regime|capex|Goldilocks|K-shaped|concerns|leverage|positioning|'
             r'energy price|oil prices|time deposit|productivity and jobs|labour market$|'
             r're-entering|fading|consumer spending|catalyst|floods|approvals pause',
    'publisher_product': r'Tracker|Chartbook|DBSI|Portfolio 365|STEER|dbDataInsights|dbDIG|'
                         r'sector flows|strategy weekly|roadmap|Multi-Factor|factor$|'
                         r'Risk Premium strategy|FX carry|BNPBCHDY|SAFE survey|OMFIF',
    'participant_group': r'funds?\b|NBFI|exporters|\bbanks\b|money market|administration$',
    'other_asset': r'credit$|\bCDS\b|ETFs?\b|exports$|\bCTA\b|Refined|agencies$|federal states',
    'concept': r'Solvency|Basel|Taylor rule|HLW|forward curve|consensus|swaption vol|'
               r'volatility$|cross-currency basis|\bvol\b|task force|neutral rate|'
               r'implied yields|loan-to-deposit|FX implied|airfares|airline|HICP$|'
               r'equivalent rent|terminal rate|benchmark revisions|term premium|'
               r'fireside|speech|testimony',
}


def _clean(text: str) -> str:
    return ' '.join(text.replace('(', ' ').replace(')', ' ').split())


def _strip(text: str, words: bool = True) -> str:
    """Remove dates and tenors; with `words`, also instrument/release words."""
    out = text
    for pattern in _DATES:
        out = re.sub(pattern, ' ', out)
    for pattern in _QUALIFIERS:
        out = re.sub(pattern, ' ', out, flags=re.IGNORECASE)
    if words:
        out = re.sub(_WORDS, ' ', out, flags=re.IGNORECASE)
    return _clean(out)


def _find(reg: Registry, text: str, allowed: set[Category]) -> list[str]:
    for candidate in dict.fromkeys((text, _strip(text, words=False), _strip(text))):
        if candidate:
            hits = [e.entity_id for e in reg.resolve(candidate) if e.category in allowed]
            if hits:
                return hits
    return []


def resolve(reg: Registry, text: str, csv_type: str | None) -> tuple[str, list[str]]:
    """Return (how, entity_ids): how in exact|stripped|structure|''."""
    allowed = ALLOWED.get(csv_type, set(Category)) if csv_type else set(Category)
    exact = [e.entity_id for e in reg.resolve(text) if e.category in allowed]
    if exact:
        return 'exact', exact
    stripped = _find(reg, text, allowed)
    if stripped:
        return 'stripped', stripped
    # Structures ("OAT-Bund spread", "Italy vs Germany", "SORA 1y1y receiver")
    # are covered when every leg resolves; country legs stand for their curve.
    leg_allowed = allowed | {Category.GEOGRAPHY} if Category.MARKET in allowed else allowed
    base = _clean(re.sub(_STRUCTURE, ' ', _strip(text), flags=re.IGNORECASE))
    legs = [p for p in _LEG_SPLIT.split(base) if p.strip()]
    if legs:
        found = [_find(reg, leg, leg_allowed) for leg in legs]
        if all(found):
            return 'structure', [ids[0] for ids in found]
    return '', []


def bucket(text: str) -> str:
    for name, pattern in BUCKETS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return name
    return 'unmapped'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('csv', type=Path)
    parser.add_argument('--registries', type=Path, default=None)
    parser.add_argument('--show', choices=['unmapped', 'out_of_scope', 'resolved'], default='unmapped')
    args = parser.parse_args()

    reg = Registry.load(args.registries) if args.registries else Registry.load_default()
    rows = list(csv.DictReader(args.csv.open(encoding='utf-8')))

    stats: dict[str, Counter] = defaultdict(Counter)
    details: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        text, kind = row['entity'].strip(), row['type'].strip()
        how, ids = resolve(reg, text, kind)
        if how:
            stats[kind]['resolved'] += 1
            details['resolved'][f'{kind:<12} {text}  ->  {", ".join(ids)}'] += 1
        else:
            # Covered by the registry, but the extractor gave it the wrong type.
            b = 'mistyped' if resolve(reg, text, None)[0] else bucket(text)
            stats[kind][b] += 1
            key = 'unmapped' if b == 'unmapped' else 'out_of_scope'
            details[key][f'{kind:<12} {b:<20} {text}'] += 1

    def row(label: str, s: Counter) -> str:
        covered = s['resolved'] + s['mistyped']
        in_scope = covered + s['unmapped']
        cov = covered / in_scope if in_scope else 1.0
        return (f'{label:<13}{sum(s.values()):>6}{s["resolved"]:>10}{s["mistyped"]:>10}'
                f'{cov:>13.0%}{s["unmapped"]:>10}')

    print(f'{"type":<13}{"rows":>6}{"resolved":>10}{"mistyped":>10}{"in-scope cov":>13}{"unmapped":>10}')
    total = Counter()
    for kind in sorted(stats):
        total.update(stats[kind])
        print(row(kind, stats[kind]))
    print(row('TOTAL', total))
    print('\nout of scope: ' + ', '.join(f'{c}={total[c]}' for c in BUCKETS if total[c]))

    print(f'\n-- {args.show} --')
    for line, count in sorted(details[args.show].items()):
        print(f'{count:>3}  {line}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
