"""Relative to absolute, against the document date (`as_of`), never today.

QLib resolves two-digit contract years against `DateTime.Today`; reprocessing
an old document that way would give the wrong decade, so everything here takes
the date of the document the mention came from.
"""

import re
from bisect import bisect_right
from datetime import date

from .contract import MONTH_CODES, QUARTERLY, ContractMonth
from .meetings import Meeting, MeetingSchedule

_MONTH_NAMES = {name: n for n, name in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
                                                   'nov', 'dec'), start=1)}
_CODE_FORM = re.compile(rf'([{MONTH_CODES}])(\d{{1,4}})', re.IGNORECASE)
_NAME_FORM = re.compile(r'([a-z]{3})[a-z]*[\s\-\']*(\d{2}|\d{4})', re.IGNORECASE)


def resolve_year(digits: str, as_of: date) -> int:
    """Year a short contract year means on `as_of`.

    One digit: the year ending in it from one year back to eight ahead (Z5 in 2026 -> 2025, Z7 -> 2027).
    Two digits: the nearest such year within fifty years either side. Four digits are taken as written.
    """
    if len(digits) == 4:
        return int(digits)
    span = 10 if len(digits) == 1 else 100
    earliest = as_of.year - (1 if span == 10 else span // 2)
    year = earliest - earliest % span + int(digits)
    return year if year >= earliest else year + span


def parse_contract(text: str, as_of: date) -> ContractMonth:
    """'Z5', 'Z25', 'Dec-25', 'December 2025' -> ContractMonth(2025, 12), on `as_of`."""
    text = text.strip()
    if match := _CODE_FORM.fullmatch(text):
        month = MONTH_CODES.index(match[1].upper()) + 1
    elif (match := _NAME_FORM.fullmatch(text)) and match[1].lower() in _MONTH_NAMES:
        month = _MONTH_NAMES[match[1].lower()]
    else:
        raise ValueError(f'not a contract month: {text!r}')
    return ContractMonth(year=resolve_year(match[2], as_of), month=month)


def nth_imm(n: int, as_of: date) -> ContractMonth:
    """The n-th quarterly IMM month whose IMM date falls after `as_of`: 1st IMM on 2026-03-20 is Jun-26."""
    if n < 1:
        raise ValueError('n counts from 1')
    year, found = as_of.year, 0
    while True:
        for month in QUARTERLY:
            contract = ContractMonth(year=year, month=month)
            if contract.imm_date > as_of:
                found += 1
                if found == n:
                    return contract
        year += 1


def nth_meeting(schedule: MeetingSchedule, n: int, as_of: date) -> Meeting | None:
    """The n-th decision after `as_of`: 'the next meeting' (n=1), 'in two meetings'. None past the schedule's end."""
    if n < 1:
        raise ValueError('n counts from 1')
    i = bisect_right([m.decided for m in schedule.meetings], as_of) + n - 1
    return schedule.meetings[i] if i < len(schedule.meetings) else None


def last_meeting(schedule: MeetingSchedule, as_of: date) -> Meeting | None:
    """The latest decision on or before `as_of`: 'the last meeting', 'today's decision'."""
    i = bisect_right([m.decided for m in schedule.meetings], as_of)
    return schedule.meetings[i - 1] if i else None


def meetings_in(schedule: MeetingSchedule, year: int, month: int) -> tuple[Meeting, ...]:
    """Decisions in a month: 'the December FOMC'. Usually one; two where a bank met twice (an emergency cut)."""
    return tuple(m for m in schedule.meetings if (m.decided.year, m.decided.month) == (year, month))
