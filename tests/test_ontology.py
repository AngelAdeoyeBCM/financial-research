"""Schema invariants (no data files involved)."""

import pytest

from incolor.ontology import (
    AssetClass,
    Bond,
    Category,
    Currency,
    Entity,
    Event,
    EventKind,
    FXPair,
    Index,
    IssuerKind,
    MarketKind,
    NonSovereignBond,
    Organization,
    OrgKind,
    Registry,
    RiskFactor,
    SovereignBond,
    WikidataMap,
)
from incolor.ontology.registry import RegistryError


def test_labels_do_not_collide_across_enums():
    # AssetClass.FX == 'fx' == RiskFactor.FX as strings; must stay distinct.
    dxy = Index(entity_id='index:x', name='x', asset_class=AssetClass.FX)
    assert dxy.is_kind(AssetClass.FX)
    assert not dxy.is_kind(RiskFactor.FX)


def test_organization_needs_kind():
    with pytest.raises(ValueError):
        Organization(entity_id='o:x', name='x', kinds=frozenset())


def test_multi_kind_org():
    bank = Organization(
        entity_id='o:x', name='x',
        kinds=frozenset({OrgKind.CENTRAL_BANK, OrgKind.REGULATOR}),
    )
    assert bank.is_kind(OrgKind.REGULATOR) and bank.is_kind(Category.ORGANIZATION)


def test_fxpair_base_quote_differ():
    with pytest.raises(ValueError):
        FXPair(entity_id='fx:x', name='x', base_id='ccy:a', quote_id='ccy:a')


def test_rates_market_needs_currency():
    with pytest.raises(TypeError, match='currency_id'):
        SovereignBond(entity_id='bond:x', name='x', geography_id='geo:x')
    with pytest.raises(ValueError, match='needs currency_id'):
        SovereignBond(entity_id='bond:x', name='x', currency_id=None, geography_id='geo:x')


def test_bond_is_abstract_over_sovereign_and_non_sovereign():
    with pytest.raises(TypeError, match='abstract'):
        Bond(entity_id='bond:x', name='x', currency_id='ccy:eur')
    bund = SovereignBond(entity_id='bond:bund', name='Bunds', currency_id='ccy:eur', geography_id='geo:de')
    kfw = NonSovereignBond(
        entity_id='bond:kfw', name='KfW', issuer_kind=IssuerKind.AGENCY,
        currency_id='ccy:eur', geography_id='geo:de', issuer_id='org:kfw',
    )
    assert bund.obligor_id == 'geo:de' and kfw.obligor_id == 'org:kfw'
    assert all(b.is_kind(MarketKind.BOND) for b in (bund, kfw))
    assert bund.is_kind(MarketKind.SOVEREIGN_BOND) and not kfw.is_kind(MarketKind.SOVEREIGN_BOND)
    assert kfw.is_kind(IssuerKind.AGENCY)
    assert kfw.links == (
        ('currency_id', 'ccy:eur'), ('issuer_id', 'org:kfw'), ('geography_id', 'geo:de'),
    )


def test_sovereign_needs_geography_and_non_sovereign_an_issuer():
    with pytest.raises(TypeError, match='geography_id'):
        SovereignBond(entity_id='bond:x', name='x', currency_id='ccy:eur')
    with pytest.raises(TypeError, match='issuer_id'):
        NonSovereignBond(entity_id='bond:x', name='x', currency_id='ccy:eur', issuer_kind=IssuerKind.SUPRA)
    with pytest.raises(TypeError, match='issuer_kind'):
        NonSovereignBond(entity_id='bond:x', name='x', currency_id='ccy:eur', issuer_id='org:eib')
    with pytest.raises(ValueError):
        IssuerKind('gov')


def test_ref_specs_carry_kinds_and_wikidata_map():
    specs = Currency.ref_specs()
    assert list(specs) == ['geography_id', 'issuer_id']
    assert specs['geography_id'].kinds == (Category.GEOGRAPHY,)
    assert specs['geography_id'].wikidata == WikidataMap('P1001', fallback='P562/P1001')
    assert Organization.ref_specs()['geography_id'].wikidata.tie_break == 'P38/P1001'
    assert not Organization.ref_specs()['geography_id'].required


def test_wikidata_map_rejects_non_paths():
    with pytest.raises(ValueError):
        WikidataMap('currency')
    with pytest.raises(ValueError):
        WikidataMap('P1001', fallback='P562/')


def test_wikidata_id_must_be_a_unique_qid():
    with pytest.raises(ValueError, match='QID'):
        Organization(entity_id='org:x', name='x', kinds=frozenset({OrgKind.CENTRAL_BANK}), wikidata_id='8901')
    ecb = Organization(entity_id='org:ecb', name='ECB', kinds=frozenset({OrgKind.CENTRAL_BANK}), wikidata_id='Q8901')
    reg = Registry([ecb])
    assert reg.find_by_qid('Q8901') is ecb and reg.find_by_qid('Q1') is None
    with pytest.raises(RegistryError, match='Q8901'):
        reg.add(Organization(entity_id='org:y', name='y', kinds=frozenset({OrgKind.CENTRAL_BANK}), wikidata_id='Q8901'))


def test_with_link_indexes_refs_and_rejects_unknown_fields():
    usd = Currency(entity_id='ccy:usd', name='US Dollar', code='USD', geography_id='geo:us', issuer_id='org:fed')
    eur = Currency(entity_id='ccy:eur', name='Euro', code='EUR', geography_id='geo:ea', issuer_id='org:ecb')
    pair = FXPair(entity_id='fx:eurusd', name='EURUSD', base_id='ccy:eur', quote_id='ccy:usd')
    reg = Registry([usd, eur, pair])
    assert reg.with_link('quote_id', 'ccy:usd') == (pair,)
    assert reg.with_link('geography_id', 'geo:us') == (usd,)
    assert reg.with_link('base_id', 'ccy:usd') == ()
    with pytest.raises(KeyError):
        reg.with_link('currency', 'ccy:usd')


def test_event_dates_ordered():
    import datetime as dt

    with pytest.raises(ValueError):
        Event(
            entity_id='event:x', name='x', kind=EventKind.POLITICAL,
            start_date=dt.date(2026, 2, 1), end_date=dt.date(2026, 1, 1),
        )


def test_abstract_classes_not_instantiable():
    with pytest.raises(TypeError):
        Entity(entity_id='x', name='x')


def test_entity_classes_register_by_category_and_kind():
    assert Entity.for_kind(Category.MARKET, MarketKind.SOVEREIGN_BOND) is SovereignBond
    assert Entity.for_type('sovereign_bond') is SovereignBond
    assert Entity.for_type('non_sovereign_bond') is NonSovereignBond
    assert Entity.for_type('bond') is None  # family label, not a record type
    assert Entity.for_type('event') is Event
    with pytest.raises(TypeError, match='duplicate'):
        class AnotherBond(Bond):
            entity_kind = MarketKind.SOVEREIGN_BOND


def test_from_record_rejects_unknown_type_and_field():
    with pytest.raises(ValueError):
        Entity.from_record({'type': 'nope', 'entity_id': 'x', 'name': 'x'})
    with pytest.raises(ValueError):
        Entity.from_record(
            {'type': 'currency', 'entity_id': 'c:x', 'name': 'x', 'code': 'X', 'bogus': 1}
        )


def test_from_record_coerces_enums_aliases_and_refs():
    e = Entity.from_record({
        'type': 'sovereign_bond', 'entity_id': 'bond:x', 'name': 'X bonds',
        'segment': 'inflation_linked', 'aliases': ['XGBs'],
        'currency_id': 'ccy:x', 'geography_id': 'geo:x',
    })
    assert e.aliases == {'XGBs'}
    assert e.currency_id == 'ccy:x' and e.geography_id == 'geo:x'


def test_from_record_rejects_relations_that_became_refs():
    with pytest.raises(ValueError, match='denominated_in'):
        Entity.from_record({
            'type': 'rate_index', 'entity_id': 'rate:x', 'name': 'X',
            'currency_id': 'ccy:x', 'relations': {'denominated_in': ['ccy:x']},
        })


def test_resolve_is_case_and_space_insensitive_and_uses_codes():
    usd = Currency(
        entity_id='ccy:usd', name='US Dollar', code='USD', aliases=frozenset({'greenback'}),
        geography_id='geo:us', issuer_id='org:fed',
    )
    eur = Currency(entity_id='ccy:eur', name='Euro', code='EUR', geography_id='geo:ea', issuer_id='org:ecb')
    pair = FXPair(entity_id='fx:eurusd', name='EURUSD', base_id='ccy:eur', quote_id='ccy:usd')
    reg = Registry([usd, eur, pair])
    assert reg.resolve('  us   DOLLAR') == (usd,)
    assert reg.resolve('Greenback') == (usd,)
    assert reg.resolve('usd') == (usd,)
    assert reg.resolve('EUR/USD') == (pair,)
    assert reg.resolve('nothing') == ()


def test_alias_conflicts_only_within_category():
    a = Organization(entity_id='org:a', name='A', kinds=frozenset({OrgKind.CENTRAL_BANK}))
    meeting = Event(entity_id='event:a', name='A meeting', kind=EventKind.POLICY_MEETING, aliases=frozenset({'A'}))
    reg = Registry([a, meeting])
    assert reg.alias_conflicts() == {}
    assert reg.resolve('A', Category.EVENT) == (meeting,)
    b = Organization(entity_id='org:b', name='B', kinds=frozenset({OrgKind.GOVERNMENT}), aliases=frozenset({'a'}))
    reg.add(b)
    assert reg.alias_conflicts() == {'a': ('org:a', 'org:b')}
