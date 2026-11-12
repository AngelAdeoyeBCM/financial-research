"""Mention resolution against the market ontology (scripts/resolve_market_mentions.py)."""

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from resolve_market_mentions import Resolver  # pyright: ignore[reportMissingImports]

from incolor.ontology.registry import ontology_manager

Resolve = Callable[[str], dict[str, str]]


@pytest.fixture(scope='module')
def resolve() -> Resolve:
    manager = ontology_manager()
    resolver = Resolver(manager)
    return lambda text: resolver.resolve(text).row(manager)


@pytest.mark.parametrize(
    ('mention', 'entity_id'),
    [
        ('EURUSD', 'fx:EURUSD'),
        ('USD/EUR', 'fx:EURUSD'),
        ('S&P 500', 'eqidx:SPX'),
        ('10Y UST', 'ins:bond:us_treasury.USD.nominal@10y'),
        ('US10Y', 'ins:bond:us_treasury.USD.nominal@10y'),
        ('1Yx1Y SONIA', 'ins:irs:GBP.SONIA.1d@1y1y'),
        ('EUR 5y5y', 'ins:irs:EUR.EURIBOR.6m@5y5y'),
        ('2y10y EUR swaption', 'ins:swpo:EUR.EURIBOR.6m@2yx10y'),
        ('EURUSD 1y', 'ins:fxf:EURUSD@1y'),
        ('OATei', 'bnd:fr_aft.EUR.linker'),
        ('Bunds', 'bnd:de_finanzagentur.EUR.nominal'),
        ('KfW', 'bnd:kfw.EUR.nominal'),
        ('EIB', 'bnd:eib.EUR.nominal'),
        ('NRW', 'bnd:nrw.EUR.nominal'),
        ('AGFRNC', 'bnd:afd.EUR.nominal'),
        ('USD IG corporates', 'seg:USD.corp.ig'),
        ('EUR HY bonds', 'seg:EUR.corp.hy'),
        ('US Corporate Bonds', 'seg:USD.corp'),
        ('munis', 'seg:USD.muni'),
        ('10yr AAA MMD', 'ins:sbnd:USD.muni.aaa@10y'),
        ('EGBs', 'seg:EUR.govt'),
        ('French covered bonds', 'seg:EUR.covered'),
        ('Agency MBS', 'seg:USD.mbs'),
        ('iBoxx EUR Covered Bond Index', 'bidx:iboxx_eur_covered'),
        ('Bloomberg Municipal Bond Index', 'bidx:bbg_muni'),
        ('USD swaps', 'irs:USD.SOFR.1d'),
        ('EUR swaps', 'irs:EUR.EURIBOR.6m'),
        ('EUR OIS', 'irs:EUR.ESTR.1d'),
        ('AUD OIS', 'irs:AUD.AONIA.1d'),
        ('5y EUR OIS', 'ins:irs:EUR.ESTR.1d@5y'),
        ('KRW NDF', 'fxf:USDKRW'),
        ('Bank Rate', 'idx:GBP.BANKRATE'),
        ('ECB deposit rate', 'idx:EUR.DFR'),
        ('IORB', 'idx:USD.IORB'),
        ('cash rate', 'idx:AUD.CASHRATE'),
        ('BoJ policy rate', 'idx:JPY.BOJRATE'),
        ('Brazil policy rate', 'idx:BRL.SELIC'),
        ('fed funds target', 'idx:USD.FDTR'),
        ('Fed funds', 'idx:USD.FEDFUNDS'),
        ('3m TWD NDF', 'ins:fxf:USDTWD@3m'),
        ('XAUUSD', 'cmdty:GOLD'),
    ],
)
def test_resolves_to_canonical_id(resolve: Resolve, mention: str, entity_id: str):
    row = resolve(mention)
    assert (row['status'], row['entity_id']) == ('resolved', entity_id)


@pytest.mark.parametrize(
    ('mention', 'shape'),
    [('UST 2s10s', 'curve'), ('Gilt 5/10/30s', 'fly'), ('10y OAT-Bund', 'spread'), ('SPGB-Bund 5s30s', 'box'),
     ('2Y UST vs 10Y UST', 'curve'), ('10y SOFR swap spread', 'spread'), ('10y JGB OIS', 'spread')],
)
def test_structures_get_their_shape(resolve: Resolve, mention: str, shape: str):
    assert resolve(mention)['shape'] == shape


def test_same_market_two_phrasings_one_id(resolve: Resolve):
    assert resolve('10Y UST')['entity_id'] == resolve('US 10y')['entity_id'] == resolve('UST 10Y')['entity_id']


@pytest.mark.parametrize(
    ('mention', 'qlib_kind'),
    [('TYH6', 'bf'), ('SOFR futures', 'rf'), ('Jun26 Euribor', 'rf'), ('USDJPY 3m vol', 'fxo'), ('CDX IG', 'cdsidx'),
     ('T 4.25 11/34', 'bnd-ins'), ('Jul25 ECB €STR', 'cbs'), ('SOFR vs Fed Funds', 'bsw')],
)
def test_unmodelled_kinds_are_named(resolve: Resolve, mention: str, qlib_kind: str):
    row = resolve(mention)
    assert (row['status'], row['qlib_kind']) == ('kind_gap', qlib_kind)


@pytest.mark.parametrize(
    ('mention', 'status'),
    [('China', 'unrecognised'), ('Canada and Mexico', 'unrecognised'), ('EU-US trade', 'unrecognised'),
     ('US tariffs', 'partial'), ('credit spreads', 'asset_class'), ('EM FX', 'asset_class'), ('G7', 'unrecognised'),
     ('swap spreads', 'generic'), ('carry', 'unrecognised'), ('IG corporates', 'generic'), ('AT1s', 'generic'),
     ('municipal elections', 'unrecognised'), ('municipal supply', 'unrecognised'), ('policy rate', 'generic'),
     ('Fed', 'unrecognised'), ('ECB', 'unrecognised'), ('price target', 'unrecognised'),
     ('benchmark discount', 'unrecognised')],
)
def test_concepts_are_not_instruments(resolve: Resolve, mention: str, status: str):
    assert resolve(mention)['status'] == status
