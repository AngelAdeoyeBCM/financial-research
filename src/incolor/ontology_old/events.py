"""Events: things that happen at a time.

The registry holds recurring series (FOMC meeting, UK Budget) and named
one-offs (French presidential election 2027). A dated occurrence such as
"FOMC Sep-26" is the series plus a mention-level date.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .base import Entity, ref
from .vocab import Category, Frequency


class EventKind(StrEnum):
    POLICY_MEETING = 'policy_meeting'  # rate-setting meetings (FOMC, MPC, Copom)
    PUBLICATION = 'publication'        # minutes, SEP, Beige Book, MPR, COFER
    FISCAL = 'fiscal'                  # budgets, refunding, auctions (tools themselves are PolicyTools)
    POLITICAL = 'political'            # elections, votes, legislation, party meetings
    GEOPOLITICAL = 'geopolitical'      # conflicts, sanctions, tariffs, summits
    CONFERENCE = 'conference'          # Jackson Hole, Sintra, IMF/WB meetings
    MARKET = 'market'                  # index inclusion, rating reviews, market rules


@dataclass(frozen=True, kw_only=True)
class Event(Entity):
    category = Category.EVENT
    entity_kind = Category.EVENT

    kind: EventKind
    recurrence: Frequency | None = None
    start_date: date | None = None
    end_date: date | None = None
    geography_id: str | None = ref(Category.GEOGRAPHY, required=False)

    def _validate(self) -> None:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(f'{self.entity_id}: end_date before start_date')

    @property
    def labels(self) -> tuple[StrEnum, ...]:
        return super().labels + (self.kind,)
