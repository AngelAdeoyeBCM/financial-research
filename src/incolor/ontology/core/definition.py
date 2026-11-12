"""The Entity base: every definition in the ontology (QLib `IDefinition`).

A class states which type it is; the type decides the id prefix and whether
the key is given or derived:

    class RateIndex(Market):
        entity_type = MarketType.RATE_INDEX        # key_format '{currency_id}.{code}'
        currency_id: CurrencyKey
        code: str

    RateIndex(currency_id='USD', code='SOFR', ...).id  -> 'idx:USD.SOFR'

A derived key is never passed in (a stored copy may pass it, if it agrees),
so an entity cannot state its identity twice. Derived entities default their
`name` to the key; others must name themselves.
"""

from functools import cache
from typing import Annotated, Any, ClassVar, Self, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.fields import FieldInfo

from .identity import TypeEnum
from .refs import Ref


class Entity(BaseModel):
    """Canonical named entity, identified by `<prefix>:<key>` ('geo:east_asia', 'idx:USD.SOFR')."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    entity_type: ClassVar[TypeEnum]

    key: str = ''
    name: str = ''

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        entity_type = cls.__dict__.get('entity_type')
        if entity_type is None:
            return
        missing = [part for part in entity_type.key_parts if part not in cls.model_fields]
        if missing:
            raise TypeError(f'{cls.__name__}: key parts {missing} of {entity_type!r} are not fields')

    @model_validator(mode='after')
    def _identity(self) -> Self:
        entity_type = self.entity_type
        if entity_type.key_format:
            key = entity_type.format_key({part: getattr(self, part) for part in entity_type.key_parts})
            if self.key and self.key != key:
                raise ValueError(f'key {self.key!r} disagrees with its parts ({key!r}); leave it out')
            object.__setattr__(self, 'key', key)
        elif not self.key:
            raise ValueError(f'{type(self).__name__} needs a key')
        if not self.name:
            if not entity_type.key_format:
                raise ValueError(f'{type(self).__name__} {self.key!r} needs a name')
            object.__setattr__(self, 'name', self.key)
        return self

    @property
    def id(self) -> str:
        """'geo:east_asia', 'cntry:JP', 'idx:USD.SOFR'."""
        return self.entity_type.id_of(self.key)

    @classmethod
    def is_subtype(cls, entity_type: TypeEnum) -> bool:
        """True if the class's type is `entity_type` or lies below it."""
        return cls.entity_type.is_subtype(entity_type)

    @classmethod
    def ref_fields(cls) -> dict[str, Ref]:
        """Reference fields and their targets: {'currency_id': Ref('currency')}."""
        return _ref_fields(cls)

    def refs(self) -> list[tuple[str, TypeEnum, str]]:
        """(field, target type, full id) for every populated reference: ('currency_id', CURRENCY, 'ccy:USD')."""
        found = []
        for name, ref in self.ref_fields().items():
            value = getattr(self, name)
            if value is None:
                continue
            target = TypeEnum.lookup(ref.type_code)
            for key in value if isinstance(value, tuple) else (value,):
                found.append((name, target, target.id_of(key)))
        return found

    def ref_ids(self) -> dict[str, tuple[str, ...]]:
        """Full ids of everything this entity references, by field: {'currency_id': ('ccy:USD',)}."""
        ids: dict[str, tuple[str, ...]] = {}
        for name, _, entity_id in self.refs():
            ids[name] = (*ids.get(name, ()), entity_id)
        return ids


@cache
def _ref_fields(cls: type[Entity]) -> dict[str, Ref]:
    found = {name: _ref_of(field) for name, field in cls.model_fields.items()}
    return {name: ref for name, ref in found.items() if ref is not None}


def _ref_of(field: FieldInfo) -> Ref | None:
    """The Ref on a field, top-level or nested (`CurrencyKey | None`, `tuple[CountryKey, ...]`)."""
    for meta in field.metadata:
        if isinstance(meta, Ref):
            return meta
    return _find_ref(field.annotation)


def _find_ref(annotation: Any) -> Ref | None:
    if get_origin(annotation) is Annotated:
        for meta in annotation.__metadata__:
            if isinstance(meta, Ref):
                return meta
    for arg in get_args(annotation):
        if (ref := _find_ref(arg)) is not None:
            return ref
    return None
