"""Small validation helpers shared by immutable models."""

from enum import StrEnum


def require_nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a non-empty string')
    return value.strip()


def require_mapping(value: object, field: str | None = None) -> dict:
    """Require value is a non-empty mapping."""
    if not isinstance(value, dict):
        raise TypeError(f'{field} must be a mapping, got {type(value).__name__}')
    return value


def require_type(
    value: object, expected: type | tuple[type, ...], field: str | None = None
) -> object:
    """Require value is an instance of expected type(s)."""
    if isinstance(value, expected):
        return value
    names = (
        expected.__name__
        if isinstance(expected, type)
        else ' or '.join(t.__name__ for t in expected)
    )
    raise TypeError(f'{field} must be a {names}, got {type(value).__name__}')


def require_enum[T: StrEnum](value: object, enum: type[T], field: str) -> T:
    """Validate and convert a single enum value."""
    value = require_type(value, str, field)
    try:
        return enum(value)
    except ValueError:
        raise ValueError(f'{field} has invalid value: {value!r}') from None


def require_dict[K, V](
    value: object, key_type: type[K], value_type: type[V], field: str
) -> dict[K, V]:
    """Require a dictionary with specified key and value types."""
    mapping = require_type(value, dict, field)
    for key, item in mapping.items():
        require_type(key, key_type, f'{field}.key')
        require_type(item, value_type, f'{field}[{key!r}]')

    return mapping


def require_probability(value: object, field: str | None = None) -> float:
    value = require_type(value, float, field)
    if not 0 <= value <= 1:
        raise ValueError(f'{field} must be between 0 and 1')

    return value
