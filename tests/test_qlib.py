"""QLib alignment: QLib enums, yellow keys, bond classes and derived QLib ids.

Tests that need the QLib source or a QCL definitions bundle skip when they are
not on this machine. Point QLIB_MARKET_SOURCE / QCL_DEFINITIONS elsewhere to run them.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from incolor.ontology import (
    PRODUCTS,
    AssetClass,
    BondClassification,
    BondSegment,
    Category,
    CdsIndexName,
    Commodity,
    CommodityType,
    Currency,
    Entity,
    FXPair,
    Geography,
    GeoLevel,
    Index,
    Instrument,
    IssuerKind,
    Market,
    MarketType,
    NonSovereignBond,
    RateIndex,
    Registry,
    SovereignBond,
    YellowKey,
    qlib_definition_name,
)
from incolor.ontology.qlib_enums import CURRENCY_CODES

ROOT = Path(__file__).resolve().parents[1]
QLIB_SOURCE = Path(
    os.environ.get('QLIB_MARKET_SOURCE', r'C:\src\FO\JunkoMarket\trunk\src\BlueCrest.QR.QLib.Core.Src\Market')
)
QCL_DEFINITIONS = Path(os.environ.get('QCL_DEFINITIONS', r'C:\Temp\QCL\5.4.528\cfg\market\definitions'))

# Seed markets whose derived id has no QCL 5.4.528 definition: QLib does not cover them yet.
KNOWN_GAPS = {
    'fx:clpcop', 'fx:mxncop', 'fx:twdkrw',
    'bond:dim_sum', 'bond:hkgb', 'bond:igb', 'bond:indogb', 'bond:mgs',
    'bond:ntnb', 'bond:rpgb', 'bond:sgs', 'bond:tgb', 'bond:thaigb',
}


def _ccy(code: str) -> Currency:
    return Currency(entity_id=f'ccy:{code.lower()}', name=code, code=code, geography_id='geo:x', issuer_id='org:x')


def _geo(code: str | None, level: GeoLevel = GeoLevel.COUNTRY) -> Geography:
    return Geography(entity_id=f'geo:{(code or "ea").lower()}', name=code or 'EA', level=level, code=code)


@pytest.fixture(scope='module')
def mini():
    currencies = [_ccy('USD'), _ccy('EUR'), _ccy('JPY')]
    return Registry([*currencies, _geo('US'), _geo('EU', GeoLevel.BLOC), _geo(None, GeoLevel.BLOC)])


@pytest.fixture(scope='module')
def reg():
    return Registry.load_default()


# -- mapping rules -------------------------------------------------------------------------------------------------
def test_qlib_ids_are_built_from_fields_and_referenced_codes(mini):
    def q(market: Market) -> str | None:
        return market.qlib_id(mini.find)

    assert q(_ccy('USD')) == 'ccy[USD]'
    assert q(FXPair(entity_id='fx:usdjpy', name='USDJPY', base_id='ccy:usd', quote_id='ccy:jpy')) == 'fx[USD,cc:JPY]'
    assert q(RateIndex(entity_id='rate:x', name='x', currency_id='ccy:usd', ref_code='SOFR')) == 'idx[USD,SOFR]'
    assert q(RateIndex(entity_id='rate:x', name='x', currency_id='ccy:usd')) is None
    tips = SovereignBond(
        entity_id='bond:x', name='x', currency_id='ccy:usd', geography_id='geo:us',
        segment=BondSegment.INFLATION_LINKED,
    )
    assert q(tips) == 'bndcnv[US,Infl,USD]'
    eu = NonSovereignBond(
        entity_id='bond:eu', name='EU', currency_id='ccy:eur', geography_id='geo:eu',
        issuer_id='org:ec', issuer_kind=IssuerKind.SUPRA,
    )
    assert q(eu) == 'bndcnv[EU,Govt,EUR]'
    assert q(SovereignBond(entity_id='bond:egb', name='x', currency_id='ccy:eur', geography_id='geo:ea')) is None


def test_commodities_map_to_an_index_or_a_metal_currency(mini):
    wti = Commodity(
        entity_id='cmdty:wti', name='WTI', commodity_type=CommodityType.CRUDE_OIL, currency_id='ccy:usd', ref_code='WTI'
    )
    gold = Commodity(entity_id='cmdty:gold', name='Gold', commodity_type=CommodityType.METAL, code='XAU')
    oil = Commodity(entity_id='cmdty:oil', name='Oil', commodity_type=CommodityType.CRUDE_OIL)
    assert (wti.qlib_id(mini.find), wti.yellow_key) == ('idx[USD,WTI]', YellowKey.COMDTY)
    assert (gold.qlib_id(mini.find), gold.yellow_key) == ('ccy[XAU]', YellowKey.COMDTY)  # yellow key is fixed per kind
    assert oil.qlib_id(mini.find) is None
    assert gold.is_kind(CommodityType.METAL)
    with pytest.raises(ValueError, match='go together'):
        Commodity(entity_id='cmdty:x', name='x', commodity_type=CommodityType.CRUDE_OIL, ref_code='WTI')
    with pytest.raises(ValueError, match='not both'):
        Commodity(
            entity_id='cmdty:x', name='x', commodity_type=CommodityType.METAL, code='XAU',
            currency_id='ccy:usd', ref_code='GOLD',
        )


def test_indices_map_only_where_qlib_defines_them(mini):
    def index(asset_class: AssetClass, code: str | None) -> Index:
        return Index(entity_id='index:x', name='x', asset_class=asset_class, code=code)

    assert index(AssetClass.EQUITY, 'SPX').qlib_id(mini.find) == 'eqidx[SPX]'
    assert index(AssetClass.EQUITY, 'MXWO').qlib_id(mini.find) is None  # not a QLib IndexIdentifier
    assert index(AssetClass.FX, 'DXY').qlib_id(mini.find) == 'ccy[DXY]'
    assert index(AssetClass.CREDIT, 'CDX.NA.IG').qlib_id(mini.find) is None  # needs the series
    assert index(AssetClass.EQUITY, 'MXWO').surface_forms[-1] == 'MXWO'


def test_yellow_key_and_bond_class_follow_kind_issuer_and_segment():
    def bond(kind: IssuerKind, segment: BondSegment = BondSegment.NOMINAL) -> NonSovereignBond:
        return NonSovereignBond(
            entity_id='bond:x', name='x', currency_id='ccy:eur', issuer_id='org:x', issuer_kind=kind, segment=segment
        )

    bund = SovereignBond(entity_id='bond:x', name='x', currency_id='ccy:eur', geography_id='geo:de')
    assert (bund.yellow_key, bund.bond_class) == (YellowKey.GOVT, BondClassification.GOVT)
    assert (bond(IssuerKind.SUPRA).yellow_key, bond(IssuerKind.SUPRA).bond_class) == (
        YellowKey.CORP, BondClassification.GOVT,
    )
    assert bond(IssuerKind.CORP).bond_class is BondClassification.CORP
    assert bond(IssuerKind.AGENCY, BondSegment.FLOATING).bond_class is BondClassification.FLOATER
    assert bund.is_kind(YellowKey.GOVT)
    assert bund.is_kind(BondClassification.GOVT)
    assert _ccy('USD').yellow_key is YellowKey.CURNCY
    assert RateIndex(entity_id='rate:x', name='x', currency_id='ccy:usd').yellow_key is YellowKey.INDEX


def test_every_market_kind_fixes_its_yellow_key():
    kinds = [cls for (category, _), cls in Entity._classes.items() if issubclass(cls, Market)]
    assert len(kinds) == len([kind for kind, _ in Entity._classes if kind is Category.MARKET])
    assert {cls.__name__: cls.yellow_key for cls in kinds} == {
        'Currency': YellowKey.CURNCY, 'FXPair': YellowKey.CURNCY, 'RateIndex': YellowKey.INDEX,
        'SovereignBond': YellowKey.GOVT, 'NonSovereignBond': YellowKey.CORP,
        'Index': YellowKey.INDEX, 'Commodity': YellowKey.COMDTY,
    }


def test_asset_classes_map_to_qlib_market_types():
    assert AssetClass.RATES.market_type is MarketType.RATES_MARKET
    assert AssetClass.FX.market_type is MarketType.FX_MARKET
    assert AssetClass.EQUITY.market_type is None


def test_definition_files_spell_qualifiers_with_equals():
    assert qlib_definition_name('fx[EUR,cc:USD]') == 'fx[EUR,cc=USD]'
    assert qlib_definition_name('ccy[USD]') == 'ccy[USD]'


def test_product_and_structure_keywords_are_qlib_keywords():
    identity_types = QLIB_SOURCE.parent / 'Identifiable' / 'IdentityTypes.cs'
    if not identity_types.is_file():
        pytest.skip(f'no QLib source at {identity_types}')
    source = identity_types.read_text(encoding='utf-8-sig')
    keywords = set(re.findall(r'CreateStructureIdentityType\(\s*"([^"]+)"', source))
    ours = {spec.qlib for spec in PRODUCTS.values() if spec.qlib}
    ours |= {cls._qlib for cls in Instrument._classes.values() if cls._qlib} | {'bsw', 'xcs'}
    assert ours - keywords == set()


# -- seed data -----------------------------------------------------------------------------------------------------
def test_seed_codes_are_qlib_codes(reg):
    markets = [e for e in reg if isinstance(e, Market)]
    currencies = {m.code for m in markets if isinstance(m, Currency)}
    metals = {m.code for m in markets if isinstance(m, Commodity) and m.code}
    assert currencies | metals <= CURRENCY_CODES
    credit = {m.code for m in markets if isinstance(m, Index) and m.asset_class is AssetClass.CREDIT and m.code}
    assert credit
    assert credit <= set(CdsIndexName)


def test_seed_qlib_ids_exist_in_the_qcl_bundle(reg):
    if not QCL_DEFINITIONS.is_dir():
        pytest.skip(f'no QCL definitions at {QCL_DEFINITIONS}')
    folders = {'ccy': 'ccy', 'idx': 'inst', 'fx': 'inst', 'bndcnv': 'inst'}  # keywords with definition files
    missing = set()
    for market in (e for e in reg if isinstance(e, Market)):
        identifier = market.qlib_id(reg.find)
        if identifier is None or (folder := folders.get(identifier.split('[')[0])) is None:
            continue
        if not (QCL_DEFINITIONS / folder / qlib_definition_name(identifier)).exists():
            missing.add(market.entity_id)
    assert missing == KNOWN_GAPS


def test_generated_enums_match_qlib_source():
    if not QLIB_SOURCE.is_dir():
        pytest.skip(f'no QLib source at {QLIB_SOURCE}')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'sync_qlib_enums.py'), '--check', '--source', str(QLIB_SOURCE)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
