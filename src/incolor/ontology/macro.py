"""Macro: measured concepts and the published series that measure them.

    Macro           MACRO       macro:<key>
    ├── Variable    VARIABLE    var:<key>
    └── Indicator   INDICATOR   ind:<key>   (a Variable 'cpi' and an Indicator 'cpi' stay distinct)
"""

from .core import Entity, EntityType, TypeEnum


class MacroType(TypeEnum):
    """Subtypes of MACRO."""

    VARIABLE = 'variable', EntityType.MACRO, 'var'
    INDICATOR = 'indicator', EntityType.MACRO, 'ind'


class Macro(Entity):
    """Economic and market measurement."""

    entity_type = EntityType.MACRO


class Variable(Macro):
    """A measured concept, independent of geography: CPI, unemployment rate."""

    entity_type = MacroType.VARIABLE


class Indicator(Macro):
    """A published series: a variable for a geography (US CPI, BLS)."""

    entity_type = MacroType.INDICATOR
