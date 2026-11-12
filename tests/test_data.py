"""Seed registries (config/registries) must load, pass integrity checks and
cover the closed sets every Rates/FX narrative relies on."""

import pytest

from incolor.ontology import (
    Bond,
    Category,
    Currency,
    Event,
    EventKind,
    FXPair,
    Indicator,
    MarketKind,
    OrgKind,
    PolicyDomain,
    RateIndex,
    Registry,
    RegistryError,
    Relation,
)

# Currency boards / offshore currencies without their own rate-setting meeting.
NO_OWN_MEETING = {'ccy:hkd'}


@pytest.fixture(scope='module')
def reg():
    return Registry.load_default()  # raises on any integrity error


def _of(reg, cls):
    return [e for e in reg if isinstance(e, cls)]


def test_seed_is_valid(reg):
    assert reg.validate() == []
    assert len(reg) > 0


def test_no_alias_conflicts_within_a_category(reg):
    assert reg.alias_conflicts() == {}


def test_every_currency_has_usd_pair_curves_and_central_bank(reg):
    pairs = {(p.base_id, p.quote_id) for p in _of(reg, FXPair)}
    bench_ccys = {m.currency_id for m in _of(reg, RateIndex)}
    bond_ccys = {m.currency_id for m in _of(reg, Bond)}
    meeting_hosts = {
        h
        for e in _of(reg, Event) if e.kind is EventKind.POLICY_MEETING
        for h in e.related(Relation.HELD_BY)
    }
    missing = []
    for ccy in _of(reg, Currency):
        cid = ccy.entity_id
        if cid != 'ccy:usd' and (cid, 'ccy:usd') not in pairs and ('ccy:usd', cid) not in pairs:
            missing.append(f'{cid}: no USD pair')
        if cid not in bench_ccys:
            missing.append(f'{cid}: no rate_index')
        if cid not in bond_ccys:
            missing.append(f'{cid}: no bond')
        cb = reg.get(ccy.issuer_id)
        if not cb.is_kind(OrgKind.CENTRAL_BANK):
            missing.append(f'{cid}: issuer {cb.entity_id} is not a central bank')
        elif cb.entity_id not in meeting_hosts and cid not in NO_OWN_MEETING:
            missing.append(f'{cid}: {cb.entity_id} holds no policy_meeting')
    assert missing == []


def test_with_link_filters_by_ref(reg):
    def ids(field, target):
        return {e.entity_id for e in reg.with_link(field, target)}

    assert ids('currency_id', 'ccy:usd') >= {'rate:sofr', 'rate:fed_funds', 'bond:ust', 'bond:tips'}
    assert ids('geography_id', 'geo:us') >= {'ccy:usd', 'org:fed', 'bond:ust', 'ind:us:cpi'}
    assert ids('issuer_id', 'org:ecb') == {'ccy:eur'}


def test_resolution_examples(reg):
    def ids(text, category=None):
        return [e.entity_id for e in reg.resolve(text, category)]

    assert ids('Federal Reserve') == ['org:fed']
    assert ids('FOMC', Category.EVENT) == ['event:fomc']
    assert ids('FOMC', Category.ORGANIZATION) == ['org:fed']
    assert ids('USD/JPY') == ['fx:usdjpy']
    assert ids('Treasuries') == ['bond:ust']
    assert ids('€STR') == ['rate:estr']
    assert ids('core PCE') == ['ind:us:core_pce']
    assert ids('Japan core CPI') == ['ind:jp:core_cpi']
    assert ids('r-star') == ['meas:neutral_rate']
    assert ids('Warsh') == ['person:kevin_warsh']
    assert ids('Treasury buybacks') == ['policy:ust_buybacks']
    assert ids('TPI', Category.POLICY) == ['policy:ecb_tpi']


def test_indicators_are_unique_by_parts(reg):
    keys = [i.key for i in _of(reg, Indicator)]
    assert len(keys) == len(set(keys))
    assert reg.get('ind:us:adp').key == 'IND[meas:payrolls|geo:us|headline|org:adp]'
    assert reg.get('meas:pce').default_geography_id == 'geo:us'


def test_policy_tools_carry_their_domain(reg):
    assert reg.get('policy:ecb_pepp').is_kind(PolicyDomain.MONETARY)
    assert reg.get('policy:uk_vat').is_kind(PolicyDomain.FISCAL)
    assert reg.get('policy:ust_buybacks').authority_id == 'org:us_treasury'


def test_geography_hierarchy(reg):
    assert [g.entity_id for g in reg.ancestors('geo:br')] == ['geo:latam', 'geo:em']
    assert {g.entity_id for g in reg.ancestors('geo:fr')} >= {'geo:ea', 'geo:eu', 'geo:europe'}


def test_bad_reference_fails_load(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text(
        '- {type: fx_pair, entity_id: fx:x, name: X, base_id: ccy:nope, quote_id: ccy:usd}\n'
    )
    with pytest.raises(RegistryError, match="base_id -> unknown 'ccy:nope'"):
        Registry.load_default(bad)


def test_wrong_category_target_fails(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text(
        '- {type: currency, entity_id: ccy:x, name: X, code: X, '
        'geography_id: org:bcb, issuer_id: org:bcb}\n'
    )
    with pytest.raises(RegistryError, match="geography_id -> 'org:bcb' must be geography"):
        Registry.load_default(bad)


def test_currency_id_must_be_currency(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text('- {type: rate_index, entity_id: rate:x, name: X, currency_id: fx:usdjpy}\n')
    with pytest.raises(RegistryError, match='must be currency'):
        Registry.load_default(bad)


def test_bond_family_label_spans_both_kinds(reg):
    ids = {e.entity_id for e in reg.with_label(MarketKind.BOND)}
    assert {'bond:ust', 'bond:eu'} <= ids
    assert 'bond:eu' not in {e.entity_id for e in reg.with_label(MarketKind.SOVEREIGN_BOND)}


@pytest.mark.parametrize(
    ('refs', 'error'),
    [
        ('geography_id: geo:latam', "geography_id -> 'geo:latam' must be country/bloc"),
        ('geography_id: geo:us, issuer_id: org:fed', "issuer_id -> 'org:fed' must be government"),
        ('geography_id: geo:fr, issuer_id: org:us_treasury', "issuer 'org:us_treasury' is not in 'geo:fr'"),
    ],
)
def test_sovereign_bond_safety(tmp_path, refs, error):
    bad = tmp_path / 'bad.yaml'
    bad.write_text(f'- {{type: sovereign_bond, entity_id: bond:x, name: X, currency_id: ccy:usd, {refs}}}\n')
    with pytest.raises(RegistryError, match=error):
        Registry.load_default(bad)


def test_currency_issuer_must_share_its_geography(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text(
        '- {type: currency, entity_id: ccy:x, name: X, code: X, '
        'geography_id: geo:fr, issuer_id: org:ecb}\n'
    )
    with pytest.raises(RegistryError, match="issuer 'org:ecb' is not in 'geo:fr'"):
        Registry.load_default(bad)


def test_duplicate_id_fails(tmp_path):
    dup = tmp_path / 'dup.yaml'
    dup.write_text(
        '- {type: currency, entity_id: ccy:usd, name: Again, code: USD, '
        'geography_id: geo:us, issuer_id: org:fed}\n'
    )
    with pytest.raises(RegistryError, match='Duplicate'):
        Registry.load_default(dup)


def test_indicator_basket_must_be_allowed_by_measure(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text(
        '- {type: indicator, entity_id: ind:x, name: X, measure_id: meas:gdp, '
        'basket: core, geography_id: geo:us}\n'
    )
    with pytest.raises(RegistryError, match='basket'):
        Registry.load_default(bad)


def test_indicator_needs_geography(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text('- {type: indicator, entity_id: ind:x, name: X, measure_id: meas:gdp}\n')
    with pytest.raises(RegistryError, match='geography_id'):
        Registry.load_default(bad)


def test_policy_tool_needs_authority(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text('- {type: policy, entity_id: policy:x, name: X, kind: tax}\n')
    with pytest.raises(RegistryError, match='authority_id'):
        Registry.load_default(bad)
