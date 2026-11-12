"""Instruments: what research positions on, built per mention.

An instrument is one leg (`Outright`) or a structure of legs, as QLib composes
instruments from leg instruments (a swap spread is a swap leg and a bond leg;
a butterfly is belly, near and far swaps). A leg is an underlying (a registry
market or indicator) held in a `Form` as a `Product`, pinned by its terms
(tenor, fixing, contract, expiry, call/put):

    "10y OAT-Bund"      Spread(long=<OAT 10y cash bond>, short=<Bund 10y cash bond>)
    "10y SOFR swap spread"  SwapSpread(long=<SOFR 10y IRS>, short=<UST 10y cash bond>)
    "UST 2s10s"         Curve(front=<UST 2y cash bond>, back=<UST 10y cash bond>)

Each structure says which terms its legs share and which one differs.
"""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import ClassVar

from .macro import Indicator
from .markets import Bond, BondSegment, Commodity, Currency, FXPair, Index, Market, RateIndex
from .products import Form, Product, ProductSpec, Underlying
from .qlib_enums import AssetType, CallPut, InstrumentCategory


class Structure(StrEnum):
    """How legs combine. The QLib keyword, where QLib has one, is each class's `qlib`."""

    OUTRIGHT = 'outright'        # one leg
    SPREAD = 'spread'            # long - short, legs differ in underlying or product
    BREAKEVEN = 'breakeven'      # nominal - linker bond of one issuer
    SWAP_SPREAD = 'swap_spread'  # swap - government bond, one currency (QLib ss)
    ASSET_SWAP = 'asset_swap'    # bond - swap, one currency (QLib aswp)
    BASIS = 'basis'              # two floating rate indices (QLib bsw, xcs)
    CURVE = 'curve'              # one leg at two tenors (QLib sprd)
    CALENDAR = 'calendar'        # one leg at two contracts or expiries
    FLY = 'fly'                  # one leg at three tenors or contracts (QLib fly)
    CROSSFLY = 'crossfly'        # three underlyings at one tenor
    BOX = 'box'                  # curve of one underlying - curve of another


_PERIOD = r'(\d+)([dwmy])'
_TENOR = re.compile(r'(\d+[dwmy])(\d+[dwmy])?')
_S_LEGS = re.compile(r'\d+s(?:[-/]?\d+s){1,2}')
_FORWARD = re.compile(r'(\d+[dwmy])\s*-?\s*(?:fwd|forward)\s+(.+)')


@dataclass(frozen=True)
class Tenor:
    """A period ('10y'), optionally forward-starting ('2y2y': start 2y, length 2y).

    Whole years in months are stored as years (12m -> 1y, 120m -> 10y).
    """

    length: str
    start: str | None = None

    def __post_init__(self) -> None:
        for name in ('length', 'start'):
            value = getattr(self, name)
            if value is None:
                continue
            match = re.fullmatch(_PERIOD, value.strip().lower())
            if not match:
                raise ValueError(f'Tenor {name} must look like 10y, 6m, 2w or 1d: {value!r}')
            count, unit = int(match[1]), match[2]
            if unit == 'm' and count and count % 12 == 0:
                count, unit = count // 12, 'y'
            object.__setattr__(self, name, f'{count}{unit}')

    @classmethod
    def parse(cls, text: str) -> 'Tenor':
        match = _TENOR.fullmatch(text.strip().lower())
        if not match:
            raise ValueError(f'Not a tenor: {text!r}')
        first, second = match.groups()
        return cls(second, start=first) if second else cls(first)

    @classmethod
    def parse_legs(cls, text: str, unit: str = 'y') -> tuple['Tenor', ...]:
        """Two or three tenors in quote order: 2s10s, 2s/5s/10s, 1y1y-3y1y, 6m fwd 2s10s.

        Bare 's' counts take `unit`: 'y' for curves and flies, 'm' for fixing tenors (Euribor 3s6s).
        A forward prefix becomes every leg's start: 6m fwd 2s10s -> 6m2y, 6m10y.
        """
        text = text.strip().lower()
        start = None
        if forward := _FORWARD.fullmatch(text):
            start, text = forward.groups()
        if _S_LEGS.fullmatch(text):
            legs = [cls(f'{count}{unit}') for count in re.findall(r'\d+', text)]
        else:
            legs = [cls.parse(part) for part in re.split(r'\s*[-/]\s*', text)]
        if not 2 <= len(legs) <= 3:
            raise ValueError(f'Expected two or three tenors: {text!r}')
        if start is not None:
            if any(leg.start for leg in legs):
                raise ValueError(f'Legs are already forward-starting: {text!r}')
            legs = [cls(leg.length, start=start) for leg in legs]
        return tuple(legs)

    def __str__(self) -> str:
        return f'{self.start}{self.length}' if self.start else self.length


def underlying_of(ref: object) -> Underlying:
    """Product group of a leg's reference."""
    match ref:
        case RateIndex():
            return Underlying.RATE_INDEX
        case Bond():
            return Underlying.BOND
        case FXPair() | Currency():
            return Underlying.FX
        case Indicator():
            return Underlying.INFLATION
        case Index():
            return Underlying.INDEX
        case Commodity():
            return Underlying.COMMODITY
        case Curve():
            return Underlying.CURVE
    raise TypeError(f'references must be markets or indicators, got {ref!r}')


@dataclass(frozen=True, kw_only=True)
class Instrument:
    """Abstract. Subclasses name their legs; `key` is deterministic from them."""

    structure: ClassVar[Structure]
    _qlib: ClassVar[str | None] = None
    _classes: ClassVar[dict[Structure, type['Instrument']]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        structure = cls.__dict__.get('structure')
        if structure is None or structure in Instrument._classes:
            raise TypeError(f'{cls.__name__} needs its own unique structure')
        Instrument._classes[structure] = cls

    @classmethod
    def for_structure(cls, structure: Structure) -> type['Instrument']:
        return Instrument._classes[structure]

    def __post_init__(self) -> None:
        if type(self) is Instrument:
            raise TypeError('Instrument is abstract')
        self._normalise()
        self._validate()

    def _normalise(self) -> None:
        """Fill defaults so equal instruments get equal keys."""

    def _validate(self) -> None:
        """Structure-specific invariants, checked at construction."""

    @property
    def legs(self) -> tuple['Outright', ...]:
        raise NotImplementedError

    @property
    def refs(self) -> tuple['Market | Indicator', ...]:
        """Markets and indicators positioned on, in leg order."""
        return tuple(dict.fromkeys(ref for leg in self.legs for ref in leg.refs))

    @property
    def qlib(self) -> str | None:
        """QLib instrument keyword for this structure, where QLib has one."""
        return self._qlib

    @property
    def label(self) -> str:
        """Key without the INS: prefix; structures nest their legs' labels."""
        parts = ', '.join(part.label for part in self._parts())
        return f'{self.structure.name}({parts})'

    def _parts(self) -> tuple['Instrument', ...]:
        return self.legs

    @property
    def key(self) -> str:
        """Deterministic id, e.g. INS:CURVE(OUTRIGHT[bond:ust]:2y:cash_bond, OUTRIGHT[bond:ust]:10y:cash_bond)."""
        return f'INS:{self.label}'


@dataclass(frozen=True, kw_only=True)
class Outright(Instrument):
    """One leg: 10y UST, EURUSD spot, a 2y30y payer swaption, TYM4, one ISIN.

    `product` defaults from the underlying and form (rate index + option ->
    swaption); name it when they don't decide it (a meeting-dated OIS).
    Options carry `expiry` separately from `tenor`: a 2y30y swaption is
    expiry=2y, tenor=30y. A payer swaption is a call on the rate.
    """

    structure = Structure.OUTRIGHT

    ref: 'Market | Indicator | Curve'
    form: Form
    product: Product | None = None
    tenor: Tenor | None = None
    fixing: Tenor | None = None      # rate index fixing tenor: 3m in 3m Euribor (QLib flt maturity)
    security: str | None = None      # ISIN when research names one bond line
    contract: str | None = None      # exchange contract: TYM4, SFRZ7
    expiry: Tenor | None = None      # options only
    call_put: CallPut | None = None  # options only

    def _normalise(self) -> None:
        if self.product is None:
            underlying = underlying_of(self.ref)
            product = Product.default(underlying, self.form, on_future=self.contract is not None)
            if product is None:
                raise ValueError(f'{self.form} on {underlying}: no default product, name one')
            object.__setattr__(self, 'product', product)

    def _validate(self) -> None:
        underlying, spec = underlying_of(self.ref), self.spec
        if spec.form is not self.form:
            raise ValueError(f'{self.product} takes form {spec.form}, not {self.form}')
        if underlying not in spec.underlyings:
            raise ValueError(f'{self.product} is not written on a {underlying}')
        given = [n for n in ('tenor', 'security', 'contract') if getattr(self, n) is not None]
        if len(given) > 1:
            raise ValueError(f'Outright takes one of tenor, security or contract, got {given}')
        if self.form is not Form.OPTION and (self.expiry is not None or self.call_put is not None):
            raise ValueError('expiry and call_put are only for options')
        if self.form is Form.OPTION and self.tenor is not None and self.tenor.start is not None:
            raise ValueError('Options take expiry, not a forward-start tenor')
        if self.contract is not None and not spec.listed:
            raise ValueError(f'contract is for futures and options on futures, not {self.product}')
        if self.fixing is not None and underlying is not Underlying.RATE_INDEX:
            raise ValueError('fixing is the tenor of a rate index')

    @property
    def spec(self) -> ProductSpec:
        assert self.product is not None  # filled by _normalise
        return self.product.spec

    @property
    def underlying(self) -> Underlying:
        return underlying_of(self.ref)

    @property
    def legs(self) -> tuple['Outright', ...]:
        return (self,)

    @property
    def refs(self) -> tuple['Market | Indicator', ...]:
        return self.ref.refs if isinstance(self.ref, Instrument) else (self.ref,)

    @property
    def qlib(self) -> str | None:
        return self.spec.qlib

    @property
    def asset_type(self) -> AssetType | None:
        """QLib AssetType; a cash linker is an inflation bond (ib)."""
        if self.product is Product.CASH_BOND and getattr(self.ref, 'segment', None) is BondSegment.INFLATION_LINKED:
            return AssetType.INFLATION_BOND
        return self.spec.asset_type

    @property
    def instrument_category(self) -> InstrumentCategory | None:
        """How QLib quotes this leg as a rate index curve point: cash (m), swap (s) or future (f)."""
        return self.spec.category

    @property
    def label(self) -> str:
        ref = self.ref.label if isinstance(self.ref, Instrument) else self.ref.entity_id
        head = f'OUTRIGHT[{ref}@{self.fixing}]' if self.fixing else f'OUTRIGHT[{ref}]'
        terms = [str(t) for t in (self.tenor, self.security, self.contract) if t]
        terms.append(str(self.product))
        if self.call_put is not None:
            terms.append(self.call_put.value.lower())
        if self.expiry is not None:
            terms.append(f'x{self.expiry}')
        return ':'.join([head, *terms])


def _check_legs(*legs: object, kind: type = Outright) -> None:
    """Runtime guard: records built from parsed data are not type-checked."""
    if not all(isinstance(leg, kind) for leg in legs):
        raise TypeError(f'legs must be {kind.__name__}, got {legs!r}')


def _without(leg: Outright, *terms: str) -> Outright:
    return replace(leg, **dict.fromkeys(terms))


@dataclass(frozen=True, kw_only=True)
class Spread(Instrument):
    """long - short across underlyings, products or both.

    10y OAT-Bund, KTB 20y vs UST 10y, AUD 2y2y vs USD 2y2y, bond futures basis
    (future - cash bond). One underlying and product across tenors, contracts or three legs is a
    Curve, Calendar or Fly; two rate indices is a Basis.
    """

    structure = Structure.SPREAD

    long: Outright
    short: Outright

    @classmethod
    def of(cls, long: 'Market | Indicator', short: 'Market | Indicator', form: Form, **terms: object) -> 'Spread':
        """Both legs in one form with the same terms: Spread.of(oat, bund, Form.CASH, tenor=10y)."""
        return cls(long=Outright(ref=long, form=form, **terms), short=Outright(ref=short, form=form, **terms))  # type: ignore[arg-type]

    def _validate(self) -> None:
        _check_legs(self.long, self.short)
        self._shape()

    def _shape(self) -> None:
        if self.long.ref == self.short.ref and self.long.product is self.short.product:
            raise ValueError(f'{self.structure}: same underlying and product is a Curve, Calendar or Basis')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (self.long, self.short)


def _bond(leg: Outright) -> Bond:
    if not isinstance(leg.ref, Bond) or leg.product is not Product.CASH_BOND:
        raise ValueError(f'expected a cash bond leg, got {leg.label}')
    return leg.ref


def _swap(leg: Outright) -> RateIndex:
    if not isinstance(leg.ref, RateIndex) or leg.product not in (Product.IRS, Product.MEETING_SWAP):
        raise ValueError(f'expected a rate index swap leg, got {leg.label}')
    return leg.ref


@dataclass(frozen=True, kw_only=True)
class Breakeven(Spread):
    """Nominal minus inflation-linked cash bonds of one issuer: 10y TIPS breakeven."""

    structure = Structure.BREAKEVEN

    def _shape(self) -> None:
        nominal, linker = _bond(self.long), _bond(self.short)
        if nominal.segment is not BondSegment.NOMINAL or linker.segment is not BondSegment.INFLATION_LINKED:
            raise ValueError(f'{self.structure}: long must be nominal and short inflation-linked')
        if nominal.obligor_id != linker.obligor_id:
            raise ValueError(f'{self.structure}: legs must share an issuer')


@dataclass(frozen=True, kw_only=True)
class SwapSpread(Spread):
    """Swap minus government bond in one currency: 10y SOFR swap spread (QLib ss)."""

    structure = Structure.SWAP_SPREAD
    _qlib = 'ss'

    def _shape(self) -> None:
        if _swap(self.long).currency_id != _bond(self.short).currency_id:
            raise ValueError(f'{self.structure}: swap and bond must share a currency')


@dataclass(frozen=True, kw_only=True)
class AssetSwap(Spread):
    """Bond against a swap in its currency: Bund ASW, BTP asset swap spread (QLib aswp)."""

    structure = Structure.ASSET_SWAP
    _qlib = 'aswp'

    def _shape(self) -> None:
        if _bond(self.long).currency_id != _swap(self.short).currency_id:
            raise ValueError(f'{self.structure}: bond and swap must share a currency')


@dataclass(frozen=True, kw_only=True)
class Basis(Spread):
    """Two floating rate indices in one form: SOFR/FF, Euribor 3s6s, EUR/USD cross-currency basis.

    QLib bsw in one currency, xcs across two.
    """

    structure = Structure.BASIS

    def _shape(self) -> None:
        long, short = self.long, self.short
        if not (isinstance(long.ref, RateIndex) and isinstance(short.ref, RateIndex)):
            raise ValueError(f'{self.structure}: both legs must be rate indices')
        if long.form is not short.form:
            raise ValueError(f'{self.structure}: legs must share a form')
        if long.ref == short.ref and long.fixing == short.fixing:
            raise ValueError(f'{self.structure}: legs must differ in index or fixing tenor')

    @property
    def qlib(self) -> str | None:
        """QLib bsw for a basis swap in one currency, xcs for a cross-currency swap."""
        currencies = {getattr(leg.ref, 'currency_id', None) for leg in self.legs}
        return 'bsw' if len(currencies) == 1 else 'xcs'


@dataclass(frozen=True, kw_only=True)
class Curve(Instrument):
    """One leg at two tenors, back - front: UST 2s10s, €STR 1y1y-3y1y (QLib sprd)."""

    structure = Structure.CURVE
    _qlib = 'sprd'

    front: Outright
    back: Outright

    @classmethod
    def of(cls, ref: 'Market | Indicator', form: Form, front: Tenor, back: Tenor, **terms: object) -> 'Curve':
        return cls(
            front=Outright(ref=ref, form=form, tenor=front, **terms),  # type: ignore[arg-type]
            back=Outright(ref=ref, form=form, tenor=back, **terms),  # type: ignore[arg-type]
        )

    def _validate(self) -> None:
        _check_legs(self.front, self.back)
        if None in (self.front.tenor, self.back.tenor) or self.front.tenor == self.back.tenor:
            raise ValueError(f'{self.structure}: legs need two different tenors')
        if _without(self.front, 'tenor') != _without(self.back, 'tenor'):
            raise ValueError(f'{self.structure}: legs may differ only in tenor')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (self.front, self.back)


@dataclass(frozen=True, kw_only=True)
class Calendar(Instrument):
    """One leg at two contracts or expiries, back - front: SFRZ5/SFRZ6, a futures roll."""

    structure = Structure.CALENDAR

    front: Outright
    back: Outright

    def _validate(self) -> None:
        _check_legs(self.front, self.back)
        if _without(self.front, 'contract', 'expiry') != _without(self.back, 'contract', 'expiry'):
            raise ValueError(f'{self.structure}: legs may differ only in contract or expiry')
        if (self.front.contract, self.front.expiry) == (self.back.contract, self.back.expiry):
            raise ValueError(f'{self.structure}: legs need two contracts or expiries')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (self.front, self.back)


@dataclass(frozen=True, kw_only=True)
class Fly(Instrument):
    """One leg at three tenors or contracts, 2*belly - wings: UST 2s5s10s, SFR H6/M6/U6 (QLib fly)."""

    structure = Structure.FLY
    _qlib = 'fly'

    front: Outright
    belly: Outright
    back: Outright

    @classmethod
    def of(
        cls, ref: 'Market | Indicator', form: Form, front: Tenor, belly: Tenor, back: Tenor, **terms: object
    ) -> 'Fly':
        def leg(tenor: Tenor) -> Outright:
            return Outright(ref=ref, form=form, tenor=tenor, **terms)  # type: ignore[arg-type]

        return cls(front=leg(front), belly=leg(belly), back=leg(back))

    def _validate(self) -> None:
        _check_legs(*self.legs)
        for term in ('tenor', 'contract'):
            values = [getattr(leg, term) for leg in self.legs]
            if None not in values and len(set(values)) == 3:
                if len({_without(leg, term) for leg in self.legs}) != 1:
                    raise ValueError(f'{self.structure}: legs may differ only in {term}')
                return
        raise ValueError(f'{self.structure}: legs need three different tenors or contracts')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (self.front, self.belly, self.back)


@dataclass(frozen=True, kw_only=True)
class CrossFly(Instrument):
    """Three underlyings, same product and terms, 2*belly - wings: 10y ITA-FRA-GER."""

    structure = Structure.CROSSFLY

    left: Outright
    belly: Outright
    right: Outright

    def _validate(self) -> None:
        _check_legs(*self.legs)
        if len({leg.ref for leg in self.legs}) < 3:
            raise ValueError(f'{self.structure}: underlyings must differ')
        if len({replace(leg, ref=self.belly.ref) for leg in self.legs}) != 1:
            raise ValueError(f'{self.structure}: legs may differ only in underlying')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (self.left, self.belly, self.right)


@dataclass(frozen=True, kw_only=True)
class Box(Instrument):
    """Curve of one underlying minus the same curve of another: SPGB-Bund 5s30s.

    The only representation of that trade; never also build it as a Spread of curves.
    """

    structure = Structure.BOX

    long: Curve
    short: Curve

    def _validate(self) -> None:
        _check_legs(self.long, self.short, kind=Curve)
        if self.long.refs == self.short.refs:
            raise ValueError(f'{self.structure}: underlyings must differ; one underlying is a Curve')
        tenors = [(c.front.tenor, c.back.tenor, c.front.product) for c in (self.long, self.short)]
        if tenors[0] != tenors[1]:
            raise ValueError(f'{self.structure}: curves must share tenors and product')

    @property
    def legs(self) -> tuple[Outright, ...]:
        return (*self.long.legs, *self.short.legs)

    def _parts(self) -> tuple[Instrument, ...]:
        return (self.long, self.short)
