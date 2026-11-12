"""Every market identity type, in one place (QLib `IdentityTypes`).

    type             prefix  key                                          example
    ───────────────  ──────  ───────────────────────────────────────────  ──────────────────────────────
    CURRENCY         ccy     given (ISO 4217)                             ccy:USD
    FX_PAIR          fx      {base_id}{quote_id}                          fx:EURUSD
    RATE_INDEX       idx     {currency_id}.{code}                         idx:USD.SOFR
    └─ POLICY_RATE   idx     {currency_id}.{code}                         idx:USD.FDTR
    BOND_PROGRAMME   bnd     {obligor_id}.{currency_id}.{coupon}.{rank}   bnd:us_treasury.USD.nominal
    BOND_SEGMENT     seg     {currency_id}.{sector}.{rating}              seg:USD.corp.ig, seg:USD.muni
    BOND_INDEX       bidx    given (slug)                                 bidx:iboxx_eur_covered
    EQUITY_INDEX     eqidx   given (ticker root)                          eqidx:SPX
    COMMODITY        cmdty   given                                        cmdty:WTI
    TEMPLATE         tpl     a product on an underlying (abstract)
    ├─ IRS           irs     {index_id}.{fixing}                          irs:USD.SOFR.1d
    ├─ SWAPTION      swpo    {index_id}.{fixing}                          swpo:EUR.EURIBOR.6m
    ├─ CASH_BOND     bond    {programme_id}                               bond:us_treasury.USD.nominal
    ├─ SEGMENT_BOND  sbnd    {segment_id}                                 sbnd:USD.muni.aaa
    └─ FX_FORWARD    fxf     {pair_id}                                    fxf:EURUSD
    INSTANCE         ins     {template_id}@{point}                        ins:irs:USD.SOFR.1d@10y
    STRUCTURE        strc    {legs}                                       strc:+1*ins:...@10y,-1*ins:...@2y

A key that names another entity uses that entity's key; an instance names its
template by full id, since a template may be of any template type. Optional
parts (rank, rating) are left out when unset: bnd:kfw.EUR.nominal, but
bnd:<bank>.EUR.nominal.t2.

A programme is one issuer's bonds; a segment is many issuers' bonds of one
kind in one currency (USD IG corporates, munis, EUR covered, EGBs), the market
research usually means by "corporates" or "munis".
"""

from ..core import Entity, EntityType, TypeEnum


class MarketType(TypeEnum):
    """Subtypes of MARKET."""

    CURRENCY = 'currency', EntityType.MARKET, 'ccy'
    FX_PAIR = 'fx_pair', EntityType.MARKET, 'fx', '{base_id}{quote_id}'
    RATE_INDEX = 'rate_index', EntityType.MARKET, 'idx', '{currency_id}.{code}'
    POLICY_RATE = 'policy_rate', RATE_INDEX, None, '{currency_id}.{code}'
    BOND_PROGRAMME = 'bond_programme', EntityType.MARKET, 'bnd', '{obligor_id}.{currency_id}.{coupon}.{rank}'
    BOND_SEGMENT = 'bond_segment', EntityType.MARKET, 'seg', '{currency_id}.{sector}.{rating}'
    BOND_INDEX = 'bond_index', EntityType.MARKET, 'bidx'
    EQUITY_INDEX = 'equity_index', EntityType.MARKET, 'eqidx'
    COMMODITY = 'commodity', EntityType.MARKET, 'cmdty'

    TEMPLATE = 'template', EntityType.MARKET, 'tpl'
    IRS = 'irs', TEMPLATE, 'irs', '{index_id}.{fixing}'
    SWAPTION = 'swaption', TEMPLATE, 'swpo', '{index_id}.{fixing}'
    CASH_BOND = 'cash_bond', TEMPLATE, 'bond', '{programme_id}'
    SEGMENT_BOND = 'segment_bond', TEMPLATE, 'sbnd', '{segment_id}'
    FX_FORWARD = 'fx_forward', TEMPLATE, 'fxf', '{pair_id}'

    INSTANCE = 'instance', EntityType.MARKET, 'ins', '{template_id}@{point}'
    STRUCTURE = 'structure', EntityType.MARKET, 'strc', '{legs}'


class Market(Entity):
    """Underlyings, the templates written on them, their instances and structures."""

    entity_type = EntityType.MARKET
