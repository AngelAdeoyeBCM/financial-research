"""Explicit, backed-up migration of legacy databases using original emails."""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from ..classes import RawEmail
from ..ingestion.dedup import (
    DEFAULT_DUPLICATE_WINDOW_HOURS,
    FINGERPRINT_VERSION,
    duplicate_window,
    email_fingerprint,
    extracted_fingerprint,
    matching_fingerprint,
    utc_received,
)
from .emails import EmailRepository


def migrate_fingerprints(
    path: str | Path,
    candidates: Iterable[RawEmail],
    *,
    recover_from: str | Path | None = None,
    duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
) -> dict:
    """Backfill content IDs, coalesce duplicates and retain a complete backup.

    Original bodies are required: parsed text cannot reconstruct a raw-content
    fingerprint. Missing source emails stop the migration before any DB change.
    The earliest received legacy row is retained for each shared fingerprint.
    recover_from may name a pre-deduplication backup to restore lost deliveries.
    Old processing receipts are cleared; the next live sync seeds v4 receipts.
    """
    duplicate_window(duplicate_window_hours)
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with closing(sqlite3.connect(path)) as connection:
        columns = connection.execute('PRAGMA table_info(emails)').fetchall()
        if connection.execute('PRAGMA user_version').fetchone()[0] == FINGERPRINT_VERSION:
            return {'migrated': False}
        rows = connection.execute(
            'SELECT entry_id, sender_email, received_at, subject, body, body_source, warnings '
            'FROM emails ORDER BY received_at, entry_id'
        ).fetchall()
        current_rows = rows
        if recover_from is not None:
            # Read the pre-deduplication backup to restore deliveries that the
            # previous unlimited-window policy may have removed.
            recovery_path = Path(recover_from)
            if not recovery_path.is_file():
                raise FileNotFoundError(recovery_path)
            with closing(sqlite3.connect(recovery_path)) as recovery:
                recovered = recovery.execute(
                    'SELECT entry_id, sender_email, received_at, subject, body, body_source, warnings '
                    'FROM emails'
                ).fetchall()
            by_id = {row[0]: row for row in recovered}
            by_id.update({row[0]: row for row in current_rows})
            rows = list(by_id.values())
        rows = sorted(rows, key=lambda row: (utc_received(row[2]), row[0]))
        required = {row[0] for row in rows}
        body_by_id = {row[0]: row[4] for row in rows}
        keys = {}
        for raw in candidates:
            if raw.metadata.entry_id in required:
                if raw.warnings:
                    raise ValueError(f'Incomplete source email: {raw.metadata.entry_id}')
                keys[raw.metadata.entry_id] = (
                    email_fingerprint(raw),
                    extracted_fingerprint(raw, body_by_id[raw.metadata.entry_id]),
                )
        missing = required - keys.keys()
        if missing:
            raise ValueError(f'Missing original source emails for {len(missing)} database rows')

        stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.with_name(path.stem + '.before-fingerprint-v5-' + stamp + path.suffix)
        with backup.open('xb'):
            pass
        with closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            current = connection.execute(
                'SELECT entry_id, sender_email, received_at, subject, body, body_source, warnings '
                'FROM emails ORDER BY received_at, entry_id'
            ).fetchall()
            if current != current_rows:
                raise RuntimeError(
                    'Database changed while gathering source emails; retry migration'
                )
            connection.execute(EmailRepository.SCHEMA.replace('emails (', 'emails_v4 (', 1))
            insert = (
                'INSERT OR IGNORE INTO emails_v4 ('
                + ', '.join(EmailRepository.COLUMNS)
                + ') VALUES ('
                + ', '.join('?' for _ in EmailRepository.COLUMNS)
                + ')'
            )
            groups = {}
            unique = 0
            for row in rows:
                key, body_hash = keys[row[0]]
                group = groups.setdefault(body_hash, [])
                if (
                    matching_fingerprint(
                        row[3], row[2], group, duplicate_window_hours=duplicate_window_hours
                    )
                    is not None
                ):
                    continue
                connection.execute(insert, (*row, key, body_hash))
                group.append((row[3], key, row[2]))
                unique += 1
            count = connection.execute('SELECT count(*) FROM emails_v4').fetchone()[0]
            if count != unique:
                raise RuntimeError('Migration row count verification failed')
            connection.execute('DROP TABLE IF EXISTS processed_emails')
            connection.execute('DROP TABLE emails')
            connection.execute('ALTER TABLE emails_v4 RENAME TO emails')
            EmailRepository.initialize(connection)
        return {
            'migrated': True,
            'before': len(current_rows),
            'after': count,
            'recovered_candidates': len(rows) - len(current_rows),
            'duplicates_merged': len(rows) - count,
            'backup': str(backup),
        }
