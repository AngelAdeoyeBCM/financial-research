"""Copy QLib's central-bank meeting dates into config/registries/dates/central_bank_meetings.yaml.

QLib keeps them per currency in a tab-separated file (currency, decision date[, effective date]) read by
`Market/Tenor/MeetingDatesFileFactory.cs`. The seed keys them by central bank instead; each bank's list loads as
a `dates.MeetingSchedule` (mtg:CB.US). Rerun to refresh:

    python scripts/import_cb_meetings.py [path/to/CentralBankMeetingDatesUnadjusted.dat]
"""

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

SOURCE = Path(r'\\bluecrest\cfs\Production\Apps\Risk\Models\Meetings\CentralBankMeetingDatesUnadjusted.dat')
TARGET = Path(__file__).resolve().parents[1] / 'config' / 'registries' / 'dates' / 'central_bank_meetings.yaml'

def bank_of(ccy: str) -> str:
    """The currency's central bank key: USD -> CB.US, EUR -> CB.EZ (the ECB).

    An ISO 4217 code starts with its country's ISO 3166 code; the euro's is the eurozone's reserved EZ.
    """
    return 'CB.EZ' if ccy == 'EUR' else f'CB.{ccy[:2]}'


def read(path: Path) -> dict[str, list[tuple[date, date | None]]]:
    """Meetings by bank key, sorted: [(decision, effective or None)]."""
    meetings: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        ccy, decided, *rest = line.split('\t')
        effective = date.fromisoformat(rest[0]) if rest and rest[0] else None
        meetings[bank_of(ccy)].append((date.fromisoformat(decided), effective))
    return {bank: sorted(set(rows)) for bank, rows in sorted(meetings.items())}


def write(meetings: dict[str, list[tuple[date, date | None]]], source: Path) -> str:
    """The seed file: one meeting per line, `{decided, effective}` where QLib gives an effective date."""
    lines = [
        f'# Central bank policy meetings: decision dates by bank (org:<KEY> -> mtg:<KEY>). Imported {date.today()}',
        f'# from {source}',
        '# by scripts/import_cb_meetings.py; rerun to refresh, do not edit by hand. A mapping gives the date the',
        '# decision takes effect where QLib has it.',
        '',
    ]
    for bank, rows in meetings.items():
        lines.append(f'{bank}:')
        lines += [f'  - {{decided: {d}, effective: {e}}}' if e else f'  - {d}' for d, e in rows]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    meetings = read(source)
    TARGET.write_text(write(meetings, source), encoding='utf-8')
    print(f'{TARGET}: {sum(map(len, meetings.values()))} meetings, {len(meetings)} banks')
