"""Identity types: the entity taxonomy and how each type forms its key (QLib `IdentityTypes`).

A type is a `TypeEnum` member, `code[, parent[, prefix[, key_format]]]`:

    EntityType      PERSON  ORGANIZATION  GEOGRAPHY  MARKET  MACRO  EVENT  POLICY
    GeographyType                         ├─ COUNTRY  ├─ CURRENCY        (geography.py, market/identity.py)
                                          └─ REGION   └─ RATE_INDEX ...

    class MarketType(TypeEnum):
        CURRENCY = 'currency', EntityType.MARKET, 'ccy'
        RATE_INDEX = 'rate_index', EntityType.MARKET, 'idx', '{currency_id}.{code}'

IDs are `<prefix>:<key>`. A type without its own prefix inherits its parent's,
and a top-level type's prefix is its code. A type with a `key_format` derives
its key from the named fields (`idx:USD.SOFR`); one without takes its key as
given (`ccy:USD`). Codes are unique across all type enums.
"""

import string
from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Any, Self


def format_part(value: Any) -> str:
    """How one field value is written in a key: enums by value, sequences comma-joined, the rest by `str`."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple | list):
        return ','.join(format_part(item) for item in value)
    return str(value)


_KEYS = string.Formatter()


class TypeEnum(StrEnum):
    """Base for entity type enums. A member is `code[, parent[, prefix[, key_format]]]`.

    The parent is a member of another TypeEnum, or an earlier member of the
    same one. The prefix is inherited from the parent unless given.
    """

    _parent: 'TypeEnum | str | None'
    _prefix: str | None
    _key_format: str | None

    def __new__(
        cls,
        code: str,
        parent: 'TypeEnum | str | tuple[Any, ...] | None' = None,
        prefix: str | None = None,
        key_format: str | None = None,
    ) -> Self:
        """A member from its enum-body tuple."""
        member = str.__new__(cls, code)
        member._value_ = code
        # A sibling named in the enum body is still its raw value: keep its code.
        member._parent = parent[0] if isinstance(parent, tuple) else parent
        member._prefix = prefix
        member._key_format = key_format
        return member

    @property
    def parent(self) -> 'TypeEnum | None':
        """The broader type: COUNTRY -> GEOGRAPHY; None at the top."""
        parent = self._parent
        if parent is None or isinstance(parent, TypeEnum):
            return parent
        return type(self)(parent)  # sibling, by code

    @property
    def prefix(self) -> str:
        """ID prefix: own, else the parent's; a top-level type uses its code."""
        if self._prefix:
            return self._prefix
        return self.parent.prefix if self.parent else self.value

    @property
    def key_format(self) -> str | None:
        """How the key is built from fields ('{currency_id}.{code}'); None when the key is given."""
        return self._key_format

    @property
    def key_parts(self) -> tuple[str, ...]:
        """Fields the key is built from: ('currency_id', 'code')."""
        if not self._key_format:
            return ()
        return tuple(field for _, field, _, _ in _KEYS.parse(self._key_format) if field)

    def format_key(self, values: Mapping[str, Any]) -> str:
        """The key for these key-part values: {'currency_id': 'USD', 'code': 'SOFR'} -> 'USD.SOFR'.

        An unset (None) part is left out with the separator before it, so optional parts can be added to a
        format without changing existing keys: '{currency_id}.{sector}.{rating}' -> 'USD.muni' or 'USD.muni.aaa'.
        A missing part is a KeyError.
        """
        if not self._key_format:
            raise TypeError(f'{self}: key is given, not derived')
        out = []
        for literal, field, _, _ in _KEYS.parse(self._key_format):
            value = values[field] if field else None
            if field and value is None:
                continue
            out.append(literal)
            if field:
                out.append(format_part(value))
        return ''.join(out)

    def id_of(self, key: str) -> str:
        """'USD' -> 'ccy:USD'."""
        return f'{self.prefix}:{key}'

    @property
    def lineage(self) -> tuple['TypeEnum', ...]:
        """This type, then each broader one: COUNTRY -> (COUNTRY, GEOGRAPHY)."""
        types: list[TypeEnum] = []
        current: TypeEnum | None = self
        while current is not None:
            types.append(current)
            current = current.parent
        return tuple(types)

    def is_subtype(self, other: 'TypeEnum') -> bool:
        """True if this type is `other` or lies below it."""
        return other in self.lineage

    @classmethod
    def lookup(cls, code: str) -> 'TypeEnum':
        """The type with this code, across every loaded type enum: 'currency' -> MarketType.CURRENCY."""
        for enum in _type_enums(TypeEnum):
            if code in enum._value2member_map_:
                return enum(code)
        raise KeyError(f'no entity type {code!r}')


def _type_enums(base: type[TypeEnum]) -> Iterator[type[TypeEnum]]:
    for sub in base.__subclasses__():
        yield sub
        yield from _type_enums(sub)


class EntityType(TypeEnum):
    """Top-level entity types. The code is the branch's default ID prefix."""

    PERSON = 'person'
    ORGANIZATION = 'org'
    GEOGRAPHY = 'geo'
    MARKET = 'mkt'
    MACRO = 'macro'
    EVENT = 'event'
    POLICY = 'policy'
