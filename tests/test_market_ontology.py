"""The rebuilt market ontology: identity types, definitions, factories and mention linking."""

from datetime import date

import pytest
from pydantic import ValidationError

from incolor.ontology.core import DefinitionManager, Entity, EntityType, TypeEnum, Unresolved
from incolor.ontology.dates import (
    ContractMonth,
    MeetingSchedule,
    Tenor,
    last_meeting,
    meetings_in,
    nth_imm,
    nth_meeting,
    parse_contract,
    resolve_year,
)
from incolor.ontology.geography import Country
from incolor.ontology.market import (
    IRS,
    BondIndex,
    BondProgramme,
    BondSector,
    BondSegment,
    CallPut,
    CashBond,
    Commodity,
    Corridor,
    Currency,
    FXForward,
    FXPair,
    Instance,
    MarketType,
    OptionPoint,
    PolicyRate,
    Rank,
    RateIndex,
    RatingBand,
    SegmentBond,
    Shape,
    Structure,
    Swaption,
    Template,
    shape,
)
from incolor.ontology.market.external import YellowKey, central_bank_code, qlib_id, yellow_key
from incolor.ontology.organization import (
    CentralBank,
    InflationMeasure,
    Issuer,
    OrganizationType,
    SovereignIssuer,
    Supranational,
)
from incolor.ontology.registry import ontology_manager

AS_OF = date(2026, 11, 10)


@pytest.fixture
def manager() -> DefinitionManager:
    return ontology_manager()


def instance(manager: DefinitionManager, template: Template, point: str) -> Instance:
    return manager.build(Instance, {'template_id': template.id, 'point': point}, AS_OF)


def legs(*weighted: tuple[Instance, float]) -> dict[str, list[dict[str, object]]]:
    return {'legs': [{'instance_id': i.id, 'weight': w} for i, w in weighted]}


# -- identity types and definitions ---------------------------------------------


def test_given_and_derived_keys(manager: DefinitionManager):
    assert manager.get('ccy:USD', Currency).name == 'US Dollar'
    assert manager.get('idx:USD.SOFR', RateIndex).currency_id == 'USD'
    assert manager.get('bnd:us_treasury.USD.linker', BondProgramme).name == 'TIPS'


def test_derived_key_is_never_stated_twice():
    assert FXPair(base_id='EUR', quote_id='USD').id == 'fx:EURUSD'
    assert FXPair(key='EURUSD', base_id='EUR', quote_id='USD').key == 'EURUSD'  # a stored copy may agree
    with pytest.raises(ValidationError, match='disagrees'):
        FXPair(key='USDEUR', base_id='EUR', quote_id='USD')


def test_named_entities_need_a_name_derived_ones_default_to_key():
    with pytest.raises(ValidationError, match='needs a name'):
        Currency(key='SEK')
    assert FXPair(base_id='EUR', quote_id='GBP').name == 'EURGBP'


def test_key_parts_must_be_fields():
    class _Types(TypeEnum):
        BROKEN = 'broken_test_kind', EntityType.MARKET, 'brk', '{missing}'

    with pytest.raises(TypeError, match='missing'):

        class Broken(Entity):
            entity_type = _Types.BROKEN


def test_type_lineage_and_prefix():
    assert MarketType.IRS.parent is MarketType.TEMPLATE
    assert MarketType.IRS.is_subtype(EntityType.MARKET)
    assert MarketType.TEMPLATE.prefix == 'tpl'
    assert IRS.is_subtype(MarketType.TEMPLATE)


# -- references -------------------------------------------------------------------


def test_references_resolve_to_full_ids(manager: DefinitionManager):
    usd = manager.get('ccy:USD', Currency)
    assert usd.ref_ids() == {'central_bank_id': ('org:CB.US',), 'default_ois_id': ('idx:USD.SOFR',)}
    assert manager.ref(usd, 'default_ois_id', RateIndex).code == 'SOFR'


def test_currency_links(manager: DefinitionManager):
    eur, cnh, hkd = (manager.get(f'ccy:{c}', Currency) for c in ('EUR', 'CNH', 'HKD'))
    assert (eur.default_ois_id, eur.default_ibor_id, eur.default_swap_id) == ('EUR.ESTR', 'EUR.EURIBOR', 'EUR.EURIBOR')
    assert manager.ref(cnh, 'onshore_id', Currency).key == 'CNY'
    assert manager.ref(hkd, 'anchor_id', Currency).key == 'USD'
    assert manager.get('ccy:KRW', Currency).non_deliverable
    assert not eur.non_deliverable


def test_geography_references_currencies():
    japan = Country(key='JP', currency_id='JPY')
    assert japan.ref_ids() == {'currency_id': ('ccy:JPY',)}


# -- factories: mention parts -> canonical entity ----------------------------------


def test_bare_currency_swap_takes_default_index_and_fixing(manager: DefinitionManager):
    assert manager.build(IRS, {'currency_id': 'USD'}, AS_OF).id == 'irs:USD.SOFR.1d'
    assert manager.build(IRS, {'currency_id': 'EUR'}, AS_OF).id == 'irs:EUR.EURIBOR.6m'
    assert manager.build(IRS, {'currency_id': 'EUR', 'family': 'ois'}, AS_OF).id == 'irs:EUR.ESTR.1d'


def test_missing_family_default_is_unresolved(manager: DefinitionManager):
    with pytest.raises(Unresolved, match='no default ibor index'):
        manager.build(IRS, {'currency_id': 'USD', 'family': 'ibor'}, AS_OF)  # LIBOR is gone
    with pytest.raises(Unresolved, match='expected ois or ibor'):
        manager.build(IRS, {'currency_id': 'USD', 'family': 'policy'}, AS_OF)


def test_overnight_index_fixes_daily_term_index_states_its_tenor(manager: DefinitionManager):
    sofr, euribor = manager.get('idx:USD.SOFR', RateIndex), manager.get('idx:EUR.EURIBOR', RateIndex)
    assert (sofr.is_ois, str(sofr.default_fixing)) == (True, '1d')
    assert (euribor.is_ois, str(euribor.default_fixing)) == (False, '6m')
    with pytest.raises(ValidationError, match='default_fixing'):
        RateIndex(currency_id='USD', code='X', name='x', is_ois=False)


def test_index_and_fixing_distinguish_templates(manager: DefinitionManager):
    ids = {
        manager.build(IRS, parts, AS_OF).id
        for parts in (
            {'currency_id': 'EUR', 'code': 'ESTR'},
            {'index_id': 'EUR.EURIBOR', 'fixing': '3m'},
            {'index_id': 'EUR.EURIBOR', 'fixing': '6M'},
            {'currency_id': 'EUR'},
        )
    }
    assert ids == {'irs:EUR.ESTR.1d', 'irs:EUR.EURIBOR.3m', 'irs:EUR.EURIBOR.6m'}


def test_unknown_parts_are_unresolved(manager: DefinitionManager):
    with pytest.raises(Unresolved):
        manager.build(IRS, {'currency_id': 'AED'}, AS_OF)  # no default index
    with pytest.raises(Unresolved):
        manager.build(IRS, {'index_id': 'USD.LIBOR'}, AS_OF)
    with pytest.raises(Unresolved):
        manager.build(CashBond, {'programme_id': 'nobody.USD.nominal'}, AS_OF)


def test_fx_pair_in_either_order(manager: DefinitionManager):
    assert manager.build(FXPair, {'base_id': 'USD', 'quote_id': 'EUR'}, AS_OF).id == 'fx:EURUSD'
    assert manager.build(FXForward, {'pair_id': 'JPYUSD'}, AS_OF).id == 'fxf:USDJPY'


# -- instances: linking mentions ----------------------------------------------------


def test_same_parts_same_instance(manager: DefinitionManager):
    sofr = manager.build(IRS, {'currency_id': 'USD'}, AS_OF)
    named = manager.build(IRS, {'index_id': 'USD.SOFR'}, AS_OF)
    assert sofr is named
    assert instance(manager, sofr, '10y') is instance(manager, named, '120m')
    assert instance(manager, sofr, '10y').id == 'ins:irs:USD.SOFR.1d@10y'


def test_same_template_different_point(manager: DefinitionManager):
    sofr = manager.build(IRS, {'currency_id': 'USD'}, AS_OF)
    five, ten = instance(manager, sofr, '5y'), instance(manager, sofr, '10y')
    assert five.id != ten.id
    assert five.template_id == ten.template_id == sofr.id


def test_point_must_fit_the_template(manager: DefinitionManager):
    swaption = manager.build(Swaption, {'currency_id': 'EUR'}, AS_OF)
    payer = instance(manager, swaption, '2yx30y.call')
    assert payer.id == 'ins:swpo:EUR.EURIBOR.6m@2yx30y.call'
    two, thirty = Tenor.model_validate('2y'), Tenor.model_validate('30y')
    assert payer.point == OptionPoint(expiry=two, tenor=thirty, call_put=CallPut.CALL)
    with pytest.raises(Unresolved):
        instance(manager, swaption, '10y')


# -- structures -------------------------------------------------------------------


def test_curve_key_is_order_free_and_shape_derived(manager: DefinitionManager):
    ust = manager.build(CashBond, {'programme_id': 'us_treasury.USD.nominal'}, AS_OF)
    two, ten = instance(manager, ust, '2y'), instance(manager, ust, '10y')
    curve = manager.build(Structure, legs((ten, 1), (two, -1)), AS_OF)
    assert manager.build(Structure, legs((two, -1), (ten, 1)), AS_OF) is curve
    assert shape(curve, manager) is Shape.CURVE


def test_swap_spread_fly_and_box(manager: DefinitionManager):
    ust = manager.build(CashBond, {'programme_id': 'us_treasury.USD.nominal'}, AS_OF)
    sofr = manager.build(IRS, {'currency_id': 'USD'}, AS_OF)
    swap_spread = manager.build(
        Structure, legs((instance(manager, sofr, '10y'), 1), (instance(manager, ust, '10y'), -1)), AS_OF
    )
    fly = manager.build(
        Structure,
        legs(
            (instance(manager, ust, '2y'), -1), (instance(manager, ust, '5y'), 2), (instance(manager, ust, '10y'), -1)
        ),
        AS_OF,
    )
    box = manager.build(
        Structure,
        legs(
            (instance(manager, sofr, '30y'), 1),
            (instance(manager, sofr, '5y'), -1),
            (instance(manager, ust, '30y'), -1),
            (instance(manager, ust, '5y'), 1),
        ),
        AS_OF,
    )
    assert [shape(s, manager) for s in (swap_spread, fly, box)] == [Shape.SPREAD, Shape.FLY, Shape.BOX]


# -- dates ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'canonical'),
    [('10y', '10y'), ('120m', '10y'), ('12M', '1y'), ('6m', '6m'), ('2y2y', '2y2y'), ('1y 1y', '1y1y')],
)
def test_tenor_canonical_form(text: str, canonical: str):
    assert str(Tenor.model_validate(text)) == canonical


def test_short_years_resolve_against_the_document_date():
    assert resolve_year('5', date(2026, 11, 10)) == 2025
    assert resolve_year('4', date(2026, 11, 10)) == 2034
    assert resolve_year('25', date(2026, 11, 10)) == 2025
    assert resolve_year('5', date(2016, 1, 1)) == 2015
    assert parse_contract('Z5', AS_OF) == parse_contract('Dec-25', AS_OF) == ContractMonth(year=2025, month=12)


def test_imm_dates():
    assert ContractMonth(year=2026, month=12).imm_date == date(2026, 12, 16)
    assert nth_imm(1, date(2026, 3, 18)) == ContractMonth(year=2026, month=6)  # Mar-26 IMM is that day
    assert nth_imm(2, AS_OF) == ContractMonth(year=2027, month=3)


# -- external identifiers -----------------------------------------------------------


def test_qlib_ids(manager: DefinitionManager):
    assert qlib_id(manager.get('ccy:USD', Currency)) == 'ccy[USD]'
    assert qlib_id(manager.get('fx:EURUSD', FXPair)) == 'fx[EUR,cc:USD]'
    assert qlib_id(manager.get('idx:JPY.TONA', RateIndex)) == 'idx[JPY,TONAROIS]'
    assert qlib_id(manager.get('cmdty:GOLD', Commodity)) == 'ccy[XAU]'
    assert qlib_id(manager.get('cmdty:NATGAS', Commodity)) == 'idx[USD,NG]'
    assert qlib_id(manager.build(IRS, {'currency_id': 'USD'}, AS_OF)) is None


def test_yellow_keys(manager: DefinitionManager):
    assert yellow_key(manager.get('fx:EURUSD', FXPair)) is YellowKey.CURNCY
    bunds = manager.get('bnd:de_finanzagentur.EUR.nominal', BondProgramme)
    kfw = manager.get('bnd:kfw.EUR.nominal', BondProgramme)
    assert yellow_key(bunds, manager) is YellowKey.GOVT  # issuer is a sovereign issuer
    assert yellow_key(kfw, manager) is YellowKey.CORP  # issuer is an agency
    assert yellow_key(bunds) is None  # needs the issuer


# -- organizations ------------------------------------------------------------------


def test_every_seeded_reference_resolves_to_its_type(manager: DefinitionManager):
    assert manager.check() == []


def test_wrong_reference_type_is_rejected(manager: DefinitionManager):
    with pytest.raises(ValidationError):  # the Fed is a central bank, not an issuer: its key cannot even be named
        BondProgramme(obligor_id='CB.US', currency_id='USD', name='x')
    unknown = BondProgramme(obligor_id='nobody', currency_id='USD', name='x')
    assert manager.dangling(unknown) == ['obligor_id=org:nobody']


def test_policy_rates(manager: DefinitionManager):
    fed = manager.get('org:CB.US', CentralBank)
    target = manager.ref(fed, 'policy_rate_id', PolicyRate)
    assert (target.id, target.entity_type, target.is_ois) == ('idx:USD.FDTR', MarketType.POLICY_RATE, True)
    assert target.is_subtype(MarketType.RATE_INDEX)  # a policy rate is a rate index: same idx prefix and key
    assert isinstance(manager.get('idx:USD.FDTR', RateIndex), PolicyRate)
    assert not isinstance(manager.get('idx:USD.SOFR', RateIndex), PolicyRate)
    iorb = manager.get('idx:USD.IORB', PolicyRate)  # another Fed rate: its bank is its currency's issuer
    assert manager.ref(manager.ref(iorb, 'currency_id', Currency), 'central_bank_id', CentralBank) is fed
    assert qlib_id(manager.get('idx:GBP.BANKRATE', RateIndex)) == 'idx[GBP,BASE]'
    assert yellow_key(target) is YellowKey.INDEX
    with pytest.raises(Unresolved, match='policy rate'):
        manager.build(IRS, {'index_id': 'GBP.BANKRATE'}, AS_OF)  # swaps reference SONIA, not Bank Rate
    bad = CentralBank(key='CB.US', name='x', short_name='x', jurisdiction_id='cntry:US', policy_rate_id='USD.SOFR')
    assert manager.dangling(bad) == ['policy_rate_id=idx:USD.SOFR']  # a market index is not a policy rate


def test_policy_rate_corridor_and_range(manager: DefinitionManager):
    dfr, mro, mlf = (manager.get(f'idx:EUR.{code}', PolicyRate) for code in ('DFR', 'MRO', 'MLF'))
    assert (dfr.corridor, mro.corridor, mlf.corridor) == (Corridor.FLOOR, None, Corridor.CEILING)
    assert manager.get('idx:USD.FDTR', PolicyRate).is_range  # 3.75-4.00%
    assert not manager.get('idx:GBP.BANKRATE', PolicyRate).is_range


def test_inflation_mandate(manager: DefinitionManager):
    fed, snb = manager.get('org:CB.US', CentralBank), manager.get('org:CB.CH', CentralBank)
    assert (fed.inflation_target, fed.inflation_band, fed.inflation_measure) == (2.0, None, InflationMeasure.PCE)
    assert (snb.inflation_target, snb.inflation_band) == (None, (0, 2))  # a range, no point
    assert manager.get('org:CB.SG', CentralBank).inflation_measure is None  # MAS steers the exchange rate
    with pytest.raises(ValidationError, match='measure'):
        CentralBank(key='CB.US', name='x', short_name='x', jurisdiction_id='cntry:US', inflation_target=2.0)
    with pytest.raises(ValidationError, match='low, high'):
        CentralBank(key='CB.US', name='x', short_name='x', jurisdiction_id='cntry:US', inflation_band=(3, 1),
                    inflation_measure=InflationMeasure.CPI)


def test_meetings_resolve_against_the_document_date(manager: DefinitionManager):
    fed = manager.get('mtg:CB.US', MeetingSchedule)
    assert manager.ref(fed, 'bank_id', CentralBank).short_name == 'Fed'
    assert [m.decided for m in meetings_in(fed, 2026, 12)] == [date(2026, 12, 9)]  # 'the December FOMC'
    assert nth_meeting(fed, 1, AS_OF).decided == date(2026, 12, 9)  # 'the next meeting', said on 2026-11-10
    assert nth_meeting(fed, 2, AS_OF).decided == date(2027, 1, 27)
    assert last_meeting(fed, AS_OF).decided == date(2026, 10, 28)
    assert last_meeting(fed, date(2026, 10, 28)).decided == date(2026, 10, 28)  # decided that day
    assert nth_meeting(fed, 1, date(2026, 10, 28)).decided == date(2026, 12, 9)
    assert nth_meeting(fed, 999, AS_OF) is None  # past the schedule's end
    assert meetings_in(manager.get('mtg:CB.EZ', MeetingSchedule), 2025, 12)[0].effective == date(2025, 12, 23)
    assert len(meetings_in(manager.get('mtg:CB.PE', MeetingSchedule), 2020, 3)) == 2  # an emergency cut
    with pytest.raises(Unresolved):
        manager.get('mtg:CB.SG', MeetingSchedule)  # no schedule seeded for MAS
    with pytest.raises(ValidationError, match='date order'):
        MeetingSchedule(bank_id='CB.US', meetings=[date(2026, 2, 1), date(2026, 1, 1)])
    assert manager.dangling(MeetingSchedule(bank_id='CB.ZZ', meetings=[])) == ['bank_id=org:CB.ZZ']


def test_issuers_and_central_banks(manager: DefinitionManager):
    usd = manager.get('ccy:USD', Currency)
    fed = manager.ref(usd, 'central_bank_id', CentralBank)
    assert (fed.id, fed.name, fed.short_name, fed.jurisdiction_id) == (
        'org:CB.US', 'Federal Reserve System', 'Fed', 'cntry:US')
    ecb = manager.get('org:CB.EZ', CentralBank)  # ISO's code reserved for the eurozone
    assert (ecb.short_name, ecb.jurisdiction_id) == ('ECB', 'geo:euro_area')  # a group, not a country
    bundesbank = manager.get('org:CB.DE', CentralBank)
    assert manager.ref(bundesbank, 'system_id', CentralBank) is ecb
    assert central_bank_code(fed) == 'FED'  # QLib's code, if it has one
    assert central_bank_code(bundesbank) is None
    with pytest.raises(ValidationError):
        CentralBank(key='CB.US', name='x', short_name='x', jurisdiction_id='US')  # a full id: cntry:US
    with pytest.raises(ValidationError, match=r'keyed CB\.GB'):
        CentralBank(key='CB.US', name='x', short_name='x', jurisdiction_id='cntry:GB')
    with pytest.raises(ValidationError):
        CentralBank(key='FED', name='x', short_name='x', jurisdiction_id='cntry:US')  # CB.<ISO alpha-2>
    bunds = manager.get('bnd:de_finanzagentur.EUR.nominal', BondProgramme)
    issuer = manager.ref(bunds, 'obligor_id', Issuer)
    assert isinstance(issuer, SovereignIssuer)
    assert issuer.country_id == 'DE'
    assert isinstance(manager.get('org:eib', Issuer), Supranational)
    assert OrganizationType.AGENCY.is_subtype(OrganizationType.ISSUER)


def test_optional_key_parts_are_left_out():
    assert BondProgramme(obligor_id='kfw', currency_id='EUR', name='x').id == 'bnd:kfw.EUR.nominal'
    assert BondProgramme(obligor_id='kfw', currency_id='EUR', rank=Rank.TIER2, name='x').id == 'bnd:kfw.EUR.nominal.t2'
    assert BondSegment(currency_id='USD', sector=BondSector.MUNI, name='x').id == 'seg:USD.muni'
    aaa_munis = BondSegment(currency_id='USD', sector=BondSector.MUNI, rating=RatingBand.AAA, name='x')
    assert aaa_munis.id == 'seg:USD.muni.aaa'


def test_segments_and_indices(manager: DefinitionManager):
    ig = manager.get('seg:USD.corp.ig', BondSegment)
    assert (yellow_key(ig), yellow_key(manager.get('seg:USD.muni', BondSegment))) == (YellowKey.CORP, YellowKey.MUNI)
    assert yellow_key(manager.get('seg:EUR.govt', BondSegment)) is YellowKey.GOVT
    covered = manager.get('bidx:iboxx_eur_covered', BondIndex)
    assert manager.ref(covered, 'segment_id', BondSegment).id == 'seg:EUR.covered'
    mmd = manager.build(SegmentBond, {'segment_id': 'USD.muni.aaa'}, AS_OF)
    assert manager.build(Instance, {'template_id': mmd.id, 'point': '10y'}, AS_OF).id == 'ins:sbnd:USD.muni.aaa@10y'


def test_bond_conventions(manager: DefinitionManager):
    def bond(key: str) -> str | None:
        return qlib_id(manager.get(f'bnd:{key}', BondProgramme), manager)

    assert bond('de_finanzagentur.EUR.nominal') == 'bndcnv[DE,Govt,EUR]'
    assert bond('european_commission.EUR.nominal') == 'bndcnv[EU,Govt,EUR]'
    assert bond('us_treasury.USD.linker') is None  # no Infl convention in the bundle
    assert bond('kfw.EUR.nominal') is None
