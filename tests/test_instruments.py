"""Instruments: legs (form, product, terms), structures of legs, and keys."""

from typing import Any

import pytest

from incolor.ontology import (
    PRODUCTS,
    AssetSwap,
    AssetType,
    Basis,
    Box,
    Breakeven,
    Calendar,
    CallPut,
    CrossFly,
    Curve,
    Fly,
    Form,
    Instrument,
    InstrumentCategory,
    Outright,
    Product,
    Registry,
    Spread,
    Structure,
    SwapSpread,
    Tenor,
    Underlying,
)

T = Tenor.parse
_REGISTRY = Registry.load_default()


def R(entity_id: str) -> Any:
    """Registry entity, untyped so tests can pass it where a Market is expected."""
    return _REGISTRY.get(entity_id)


# -- tenors -------------------------------------------------------------------------------------------------------
def test_tenor_parse_and_normalise():
    assert T('10Y') == Tenor('10y')
    assert T('2y2y') == Tenor('2y', start='2y')
    assert str(T('6m10y')) == '6m10y'
    assert T('12m') == T('1y')
    assert T('120M') == T('10y')
    assert T('18m') == Tenor('18m')
    assert T('060m') == T('5y')
    with pytest.raises(ValueError):
        T('2s10s')


def test_tenor_legs():
    legs = Tenor.parse_legs
    assert legs('2s10s') == legs('2s/10s') == legs('2s-10s') == legs('2y-10y') == (T('2y'), T('10y'))
    assert legs('2s5s10s') == (T('2y'), T('5y'), T('10y'))
    assert legs('3s6s', unit='m') == (T('3m'), T('6m'))
    assert legs('1y1y-3y1y') == (T('1y1y'), T('3y1y'))
    assert legs('6m fwd 2s10s') == legs('6m forward 2s10s') == (T('6m2y'), T('6m10y'))
    for bad in ('2s', '10y', '1s2s3s4s', '6m fwd 1y1y-3y1y'):
        with pytest.raises(ValueError):
            legs(bad)


# -- products -----------------------------------------------------------------------------------------------------
def test_every_product_has_a_spec_and_defaults_fit_their_spec():
    assert set(PRODUCTS) == set(Product)
    for underlying in Underlying:
        for form in Form:
            product = Product.default(underlying, form)
            if product is not None:
                assert product.form is form
                assert underlying in product.spec.underlyings


def test_products_default_from_underlying_and_form():
    sofr, ust, eurusd = R('rate:sofr'), R('bond:ust'), R('fx:eurusd')
    assert Outright(ref=sofr, form=Form.SWAP, tenor=T('10y')).product is Product.IRS
    assert Outright(ref=sofr, form=Form.OPTION, tenor=T('10y'), expiry=T('1y')).product is Product.SWAPTION
    assert Outright(ref=ust, form=Form.FUTURE, contract='TYM4').product is Product.BOND_FUTURE
    assert Outright(ref=ust, form=Form.OPTION, contract='TYM4').product is Product.BOND_FUTURE_OPTION
    assert Outright(ref=ust, form=Form.REPO, tenor=T('1w')).product is Product.REPO
    assert Outright(ref=eurusd, form=Form.SWAP, tenor=T('3m')).product is Product.FX_SWAP
    assert Outright(ref=R('ind:fr:cpi'), form=Form.SWAP, tenor=T('10y')).product is Product.INFLATION_SWAP


def test_named_products_must_fit_form_and_underlying():
    meeting = Outright(ref=R('rate:estr'), form=Form.SWAP, product=Product.MEETING_SWAP)
    assert meeting.qlib == 'cbs'
    with pytest.raises(ValueError, match='takes form option'):
        Outright(ref=R('rate:sofr'), form=Form.SWAP, product=Product.SWAPTION)
    with pytest.raises(ValueError, match='not written on a bond'):
        Outright(ref=R('bond:ust'), form=Form.SWAP, product=Product.IRS)
    with pytest.raises(ValueError, match='no default product'):  # bond TRS: not in the research vocabulary
        Outright(ref=R('bond:ust'), form=Form.SWAP)
    for subject in ('index:dxy', 'index:itraxx_main', 'cmdty:brent'):
        assert Outright(ref=R(subject), form=Form.CASH).qlib is None  # levels research cites; QLib has no keyword


def test_legs_carry_qlib_asset_type_and_curve_category():
    sofr, tips = R('rate:sofr'), R('bond:tips')
    assert Outright(ref=sofr, form=Form.SWAP, tenor=T('2y')).instrument_category is InstrumentCategory.SWAP
    assert Outright(ref=sofr, form=Form.FUTURE, contract='SFRZ6').asset_type is AssetType.INTEREST_RATE_FUTURE
    assert Outright(ref=tips, form=Form.CASH, tenor=T('10y')).asset_type is AssetType.INFLATION_BOND
    assert Outright(ref=R('bond:ust'), form=Form.CASH, tenor=T('10y')).asset_type is AssetType.BOND


# -- leg terms ----------------------------------------------------------------------------------------------------
def test_option_terms():
    estr = R('rate:estr')
    payer = Outright(ref=estr, form=Form.OPTION, tenor=T('30y'), expiry=T('2y'), call_put=CallPut.CALL)
    assert payer.key == 'INS:OUTRIGHT[rate:estr]:30y:swaption:call:x2y'
    with pytest.raises(ValueError, match='only for options'):
        Outright(ref=estr, form=Form.SWAP, tenor=T('30y'), expiry=T('2y'))
    with pytest.raises(ValueError, match='forward-start'):
        Outright(ref=estr, form=Form.OPTION, tenor=T('2y30y'))
    sfr_call = Outright(ref=R('rate:sofr'), form=Form.OPTION, contract='SFRZ6', call_put=CallPut.CALL)
    assert sfr_call.product is Product.RATE_FUTURE_OPTION


def test_outright_takes_one_of_tenor_security_contract():
    ust = R('bond:ust')
    with pytest.raises(ValueError, match='one of'):
        Outright(ref=ust, form=Form.CASH, tenor=T('10y'), security='US91282CJL54')
    assert Outright(ref=ust, form=Form.FUTURE, contract='TYM4').key == 'INS:OUTRIGHT[bond:ust]:TYM4:bond_future'
    with pytest.raises(ValueError, match='futures'):
        Outright(ref=ust, form=Form.CASH, contract='TYM4')
    with pytest.raises(ValueError, match='fixing'):
        Outright(ref=ust, form=Form.CASH, tenor=T('10y'), fixing=T('3m'))


def test_option_on_a_curve_is_a_cms_spread_option():
    curve = Curve.of(R('rate:estr'), Form.SWAP, T('10y'), T('30y'))
    ycso = Outright(ref=curve, form=Form.OPTION, expiry=T('10y'))
    assert ycso.product is Product.CMS_SPREAD_OPTION
    assert ycso.refs == (R('rate:estr'),)
    assert ycso.key == (
        'INS:OUTRIGHT[CURVE(OUTRIGHT[rate:estr]:10y:irs, OUTRIGHT[rate:estr]:30y:irs)]:cms_spread_option:x10y'
    )
    with pytest.raises(ValueError, match='no default product'):
        Outright(ref=curve, form=Form.SWAP)


def test_references_must_be_markets_or_indicators():
    with pytest.raises(ValueError, match='no default product'):
        Outright(ref=R('ind:fr:cpi'), form=Form.CASH)
    with pytest.raises(TypeError, match='markets or indicators'):
        Outright(ref=R('org:fed'), form=Form.CASH)
    with pytest.raises(TypeError, match='markets or indicators'):
        Outright(ref='bond:ust', form=Form.CASH)  # type: ignore[arg-type]


# -- structures ---------------------------------------------------------------------------------------------------
def test_instrument_is_abstract_and_structures_are_unique():
    with pytest.raises(TypeError):
        Instrument()
    assert Instrument.for_structure(Structure.BOX) is Box
    assert Breakeven.structure is Structure.BREAKEVEN
    with pytest.raises(TypeError, match='unique structure'):
        class Forgot(Spread):  # inherits SPREAD without declaring its own
            pass


def test_curves_from_leg_notation():
    thor = Curve.of(R('rate:thor'), Form.SWAP, *Tenor.parse_legs('1s5s'))
    assert thor.key == 'INS:CURVE(OUTRIGHT[rate:thor]:1y:irs, OUTRIGHT[rate:thor]:5y:irs)'
    assert thor.qlib == 'sprd'
    estr = Curve.of(R('rate:estr'), Form.SWAP, *Tenor.parse_legs('6m fwd 2s10s'))
    assert estr.legs[0].tenor == T('6m2y')
    with pytest.raises(ValueError, match='two different tenors'):
        Curve.of(R('bond:ust'), Form.CASH, T('10y'), T('10y'))
    with pytest.raises(ValueError, match='only in tenor'):
        Curve(
            front=Outright(ref=R('bond:ust'), form=Form.CASH, tenor=T('2y')),
            back=Outright(ref=R('bond:bund'), form=Form.CASH, tenor=T('10y')),
        )


def test_spreads_across_underlyings_and_forms():
    oat_bund = Spread.of(R('bond:oat'), R('bond:bund'), Form.CASH, tenor=T('10y'))
    assert oat_bund.key == 'INS:SPREAD(OUTRIGHT[bond:oat]:10y:cash_bond, OUTRIGHT[bond:bund]:10y:cash_bond)'
    ktb_ust = Spread(
        long=Outright(ref=R('bond:ktb'), form=Form.CASH, tenor=T('20y')),
        short=Outright(ref=R('bond:ust'), form=Form.CASH, tenor=T('10y')),
    )
    assert ktb_ust.refs == (R('bond:ktb'), R('bond:ust'))
    futures_basis = Spread(  # one underlying, two products: allowed
        long=Outright(ref=R('bond:ust'), form=Form.FUTURE, contract='TYM4'),
        short=Outright(ref=R('bond:ust'), form=Form.CASH, security='US91282CJL54'),
    )
    assert futures_basis.refs == (R('bond:ust'),)
    with pytest.raises(ValueError, match='Curve, Calendar or Basis'):
        Spread.of(R('bond:oat'), R('bond:oat'), Form.CASH, tenor=T('10y'))


def test_swap_spread_and_asset_swap_pair_a_swap_with_a_bond():
    sofr, ust, bund = R('rate:sofr'), R('bond:ust'), R('bond:bund')
    swap, bond = Outright(ref=sofr, form=Form.SWAP, tenor=T('10y')), Outright(ref=ust, form=Form.CASH, tenor=T('10y'))
    spread = SwapSpread(long=swap, short=bond)
    assert spread.qlib == 'ss'
    assert AssetSwap(long=bond, short=swap).qlib == 'aswp'
    with pytest.raises(ValueError, match='currency'):
        SwapSpread(long=swap, short=Outright(ref=bund, form=Form.CASH, tenor=T('10y')))
    with pytest.raises(ValueError, match='swap leg'):
        SwapSpread(long=bond, short=bond)


def test_basis_on_fixing_tenors_and_currencies():
    euribor = R('rate:euribor')
    three_six = Basis(
        long=Outright(ref=euribor, form=Form.SWAP, tenor=T('10y'), fixing=T('3m')),
        short=Outright(ref=euribor, form=Form.SWAP, tenor=T('10y'), fixing=T('6m')),
    )
    assert three_six.key == (
        'INS:BASIS(OUTRIGHT[rate:euribor@3m]:10y:irs, OUTRIGHT[rate:euribor@6m]:10y:irs)'
    )
    assert three_six.qlib == 'bsw'
    xccy = Basis.of(R('rate:estr'), R('rate:sofr'), Form.SWAP, tenor=T('5y'))
    assert xccy.qlib == 'xcs'
    with pytest.raises(ValueError, match='differ'):
        Basis.of(euribor, euribor, Form.SWAP, tenor=T('10y'))
    with pytest.raises(ValueError, match='rate indices'):
        Basis.of(R('rate:sofr'), R('bond:ust'), Form.CASH)


def test_breakeven_needs_nominal_and_linker_of_one_issuer():
    ust, tips = R('bond:ust'), R('bond:tips')
    assert Breakeven.of(ust, tips, Form.CASH, tenor=T('10y')).refs == (ust, tips)
    with pytest.raises(ValueError, match='nominal'):
        Breakeven.of(tips, ust, Form.CASH)
    with pytest.raises(ValueError, match='issuer'):
        Breakeven.of(R('bond:bund'), tips, Form.CASH)


def test_calendar_and_fly_on_contracts_or_tenors():
    sofr = R('rate:sofr')

    def fut(code: str) -> Outright:
        return Outright(ref=sofr, form=Form.FUTURE, contract=code)

    roll = Calendar(front=fut('SFRZ5'), back=fut('SFRZ6'))
    assert roll.key == 'INS:CALENDAR(OUTRIGHT[rate:sofr]:SFRZ5:rate_future, OUTRIGHT[rate:sofr]:SFRZ6:rate_future)'
    with pytest.raises(ValueError, match='two contracts'):
        Calendar(front=fut('SFRZ5'), back=fut('SFRZ5'))
    assert Fly(front=fut('SFRH6'), belly=fut('SFRM6'), back=fut('SFRU6')).qlib == 'fly'
    assert Fly.of(R('bond:ust'), Form.CASH, T('2y'), T('5y'), T('10y')).legs[1].tenor == T('5y')
    with pytest.raises(ValueError, match='three different'):
        Fly.of(R('bond:ust'), Form.CASH, T('2y'), T('2y'), T('10y'))


def test_crossfly_and_box():
    btp, oat, bund, spgb = R('bond:btp'), R('bond:oat'), R('bond:bund'), R('bond:spgb')

    def ten(ref: object) -> Outright:
        return Outright(ref=ref, form=Form.CASH, tenor=T('10y'))  # type: ignore[arg-type]

    assert CrossFly(left=ten(btp), belly=ten(oat), right=ten(bund)).refs == (btp, oat, bund)
    with pytest.raises(ValueError, match='underlyings must differ'):
        CrossFly(left=ten(btp), belly=ten(oat), right=ten(btp))
    box = Box(long=Curve.of(spgb, Form.CASH, T('5y'), T('30y')), short=Curve.of(bund, Form.CASH, T('5y'), T('30y')))
    assert box.key.startswith('INS:BOX(CURVE(OUTRIGHT[bond:spgb]:5y:cash_bond')
    assert len(box.legs) == 4
    with pytest.raises(ValueError, match='underlyings must differ'):
        Box(long=Curve.of(spgb, Form.CASH, T('5y'), T('30y')), short=Curve.of(spgb, Form.CASH, T('5y'), T('30y')))
    with pytest.raises(ValueError, match='share tenors'):
        Box(long=Curve.of(spgb, Form.CASH, T('5y'), T('30y')), short=Curve.of(bund, Form.CASH, T('2y'), T('10y')))
