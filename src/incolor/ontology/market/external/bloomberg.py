"""Bloomberg yellow keys of market definitions. Tickers belong in the alias store, not here."""

from enum import StrEnum

from ...core import DefinitionManager, Entity, TypeEnum
from ...organization import Issuer, SovereignIssuer
from ..bonds import BondProgramme, BondSegment
from ..enums import BondSector
from ..identity import MarketType


class YellowKey(StrEnum):
    """Bloomberg market sector."""

    CURNCY = 'Curncy'
    INDEX = 'Index'
    GOVT = 'Govt'
    CORP = 'Corp'
    MUNI = 'Muni'
    MTGE = 'Mtge'
    COMDTY = 'Comdty'
    EQUITY = 'Equity'


_BY_TYPE: dict[TypeEnum, YellowKey] = {
    MarketType.CURRENCY: YellowKey.CURNCY,
    MarketType.FX_PAIR: YellowKey.CURNCY,
    MarketType.RATE_INDEX: YellowKey.INDEX,
    MarketType.EQUITY_INDEX: YellowKey.INDEX,
    MarketType.BOND_INDEX: YellowKey.INDEX,
    MarketType.COMMODITY: YellowKey.COMDTY,
}
_BY_SECTOR = {BondSector.GOVT: YellowKey.GOVT, BondSector.MUNI: YellowKey.MUNI, BondSector.MBS: YellowKey.MTGE}


def yellow_key(entity: Entity, manager: DefinitionManager | None = None) -> YellowKey | None:
    """Yellow key of a market definition.

    A bond programme is Govt when its issuer is a sovereign issuer, else Corp (agencies, supranationals and
    sub-sovereigns are Corp on Bloomberg); that needs `manager` to look the issuer up. A segment follows its sector:
    Govt, Muni, Mtge, else Corp.
    """
    if isinstance(entity, BondProgramme):
        if manager is None:
            return None
        issuer = manager.ref(entity, 'obligor_id', Issuer)
        return YellowKey.GOVT if isinstance(issuer, SovereignIssuer) else YellowKey.CORP
    if isinstance(entity, BondSegment):
        return _BY_SECTOR.get(entity.sector, YellowKey.CORP)
    return next((_BY_TYPE[t] for t in entity.entity_type.lineage if t in _BY_TYPE), None)  # a policy rate: Index
