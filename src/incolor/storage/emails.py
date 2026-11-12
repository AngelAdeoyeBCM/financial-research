"""Transactional persistence keyed by the email content fingerprint."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from ..classes import EmailMetadata, EmailRecord, ExtractedEmail, ParsedEmail
from ..ingestion.dedup import (
    DEFAULT_DUPLICATE_WINDOW_HOURS,
    FINGERPRINT_VERSION,
    duplicate_window,
    matching_fingerprint,
)


class EmailRepository:
    COLUMNS = (
        'entry_id',
        'sender_email',
        'received_at',
        'subject',
        'body',
        'body_source',
        'warnings',
        'fingerprint',
        'body_fingerprint',
    )
    SCHEMA = """
        CREATE TABLE IF NOT EXISTS emails (
            entry_id TEXT NOT NULL UNIQUE CHECK (length(trim(entry_id)) > 0),
            sender_email TEXT,
            received_at TEXT NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            body_source TEXT NOT NULL CHECK (body_source IN ('html', 'text', 'empty')),
            warnings TEXT NOT NULL,
            fingerprint TEXT PRIMARY KEY NOT NULL
                CHECK (length(fingerprint) = 64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
            body_fingerprint TEXT NOT NULL
                CHECK (length(body_fingerprint) = 64 AND body_fingerprint NOT GLOB '*[^0-9a-f]*')
        )
    """
    UPSERT = (
        f'INSERT INTO emails ({", ".join(COLUMNS)}) '
        f'VALUES ({", ".join("?" for _ in COLUMNS)}) '
        'ON CONFLICT(fingerprint) DO UPDATE SET '
        + ', '.join(f'{name}=excluded.{name}' for name in ('body', 'body_source', 'warnings'))
    )

    def __init__(
        self, path: str | Path, *, duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS
    ):
        duplicate_window(duplicate_window_hours)
        self.duplicate_window_hours = duplicate_window_hours
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                columns = connection.execute('PRAGMA table_info(emails)').fetchall()
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if columns and (
                    version != FINGERPRINT_VERSION
                    or not any(c[1] == 'body_fingerprint' for c in columns)
                ):
                    raise ValueError(
                        'Legacy email database: run migrate_fingerprints with original source emails first'
                    )
                self.initialize(connection)

    @classmethod
    def initialize(cls, connection):
        connection.execute(cls.SCHEMA)
        connection.execute(f'PRAGMA user_version = {FINGERPRINT_VERSION}')
        connection.execute(
            'CREATE INDEX IF NOT EXISTS emails_body_fingerprint ON emails(body_fingerprint)'
        )
        connection.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                fingerprint TEXT PRIMARY KEY NOT NULL,
                profile TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for event in ('UPDATE', 'DELETE'):
            connection.execute(f"""
                CREATE TRIGGER IF NOT EXISTS emails_invalidate_processed_{event.lower()}
                AFTER {event} ON emails BEGIN
                    DELETE FROM processed_emails WHERE fingerprint = OLD.fingerprint;
                END
            """)

    @contextmanager
    def incremental_session(self, profile: str):
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                yield EmailProcessingSession(
                    connection, profile, duplicate_window_hours=self.duplicate_window_hours
                )

    @classmethod
    def write_record(
        cls, connection, row, *, duplicate_window_hours=DEFAULT_DUPLICATE_WINDOW_HOURS
    ):
        values = list(cls._serialize(row))
        fingerprint = cls.resolve_fingerprint(
            connection,
            values[3],
            values[-1],
            values[-2],
            values[2],
            duplicate_window_hours=duplicate_window_hours,
        )
        values[-2] = fingerprint
        entry_id = values[0]
        # An edited Outlook item replaces its previous content identity.
        connection.execute(
            'DELETE FROM emails WHERE entry_id = ? AND fingerprint <> ?',
            (entry_id, fingerprint),
        )
        connection.execute(cls.UPSERT, values)
        return fingerprint

    @staticmethod
    def resolve_fingerprint(
        connection,
        subject,
        body_hash,
        exact_key,
        received_at,
        *,
        duplicate_window_hours=DEFAULT_DUPLICATE_WINDOW_HOURS,
    ):
        rows = connection.execute(
            'SELECT subject, fingerprint, received_at FROM emails WHERE body_fingerprint = ?',
            (body_hash,),
        )
        return (
            matching_fingerprint(
                subject, received_at, rows, duplicate_window_hours=duplicate_window_hours
            )
            or exact_key
        )

    def upsert(self, emails) -> int:
        def rows():
            for email in emails:
                record = email.to_email_record() if isinstance(email, ExtractedEmail) else email
                if isinstance(record, EmailRecord):
                    yield record.as_storage_row()
                elif isinstance(record, tuple) and len(record) == len(self.COLUMNS):
                    yield record
                else:
                    raise TypeError('Expected ExtractedEmail, EmailRecord, or storage row tuple')

        return self._write(rows())

    def _write(self, rows) -> int:
        count = 0
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                for row in rows:
                    self.write_record(
                        connection, row, duplicate_window_hours=self.duplicate_window_hours
                    )
                    count += 1
        return count

    def upsert_dataframe(self, frame) -> int:
        """Write frames containing the fingerprint computed during extraction."""
        import pandas as pd

        missing = set(self.COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f'Missing dataframe columns: {sorted(missing)}')
        if not frame.columns.is_unique:
            raise ValueError('Dataframe columns must be unique')

        def rows():
            for values in frame.loc[:, list(self.COLUMNS)].itertuples(index=False, name=None):
                row = list(values)
                for index in (1, 2, 3):
                    if pd.isna(row[index]):
                        row[index] = None
                yield row

        return self._write(rows())

    def iter_records(self):
        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute(
                'SELECT ' + ', '.join(self.COLUMNS) + ' FROM emails ORDER BY entry_id'
            )
            for row in cursor:
                values = dict(zip(self.COLUMNS, row, strict=False))
                values['received_at'] = datetime.fromisoformat(values['received_at'])
                values['warnings'] = tuple(json.loads(values['warnings']))
                metadata = EmailMetadata(
                    values['entry_id'],
                    values['sender_email'],
                    values['received_at'],
                    values['subject'],
                    values['fingerprint'],
                    values['body_fingerprint'],
                )
                parsed = ParsedEmail(
                    values['subject'],
                    values['sender_email'],
                    values['received_at'],
                    values['body'],
                    warnings=values['warnings'],
                )
                yield EmailRecord(metadata, parsed)

    def to_dataframe(self):
        import pandas as pd

        rows = (record.as_storage_row() for record in self.iter_records())
        return pd.DataFrame.from_records(rows, columns=self.COLUMNS)

    @staticmethod
    def _serialize(row):
        entry_id, sender, received, subject, body, source, warnings, fingerprint, body_hash = row
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise ValueError('fingerprint must be a SHA-256 hex digest from the source email')
        if not isinstance(body_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', body_hash):
            raise ValueError('body_fingerprint must be a SHA-256 hex digest')
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError('entry_id must be a non-empty string')
        if received is None:
            raise ValueError('received_at must not be missing')
        if isinstance(received, str):
            received = datetime.fromisoformat(received)
        if not isinstance(received, datetime):
            raise ValueError('received_at must be a datetime or ISO timestamp')
        if not isinstance(body, str):
            raise ValueError('body must be a string')
        if source not in ('html', 'text', 'empty'):
            raise ValueError('Invalid body_source')
        if not isinstance(warnings, (tuple, list)) or not all(
            isinstance(warning, str) for warning in warnings
        ):
            raise ValueError('warnings must be a list or tuple of strings')

        def optional_text(value):
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError('sender_email and subject must be strings or null')
            return value

        return (
            entry_id,
            optional_text(sender),
            received.isoformat(),
            optional_text(subject),
            body,
            source,
            json.dumps(warnings, ensure_ascii=False),
            fingerprint,
            body_hash,
        )


class EmailProcessingSession:
    def __init__(
        self,
        connection: sqlite3.Connection,
        profile: str,
        *,
        duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
    ):
        duplicate_window(duplicate_window_hours)
        self.duplicate_window_hours = duplicate_window_hours
        self.connection = connection
        self.profile = profile

    def resolve_fingerprint(self, subject, body_hash, exact_key, received_at):
        return EmailRepository.resolve_fingerprint(
            self.connection,
            subject,
            body_hash,
            exact_key,
            received_at,
            duplicate_window_hours=self.duplicate_window_hours,
        )

    def has_processed(self, fingerprint: str) -> bool:
        return (
            self.connection.execute(
                """SELECT 1 FROM processed_emails AS p
               JOIN emails AS e ON e.fingerprint = p.fingerprint
               WHERE p.fingerprint = ? AND p.profile = ?""",
                (fingerprint, self.profile),
            ).fetchone()
            is not None
        )

    def save(self, email: ExtractedEmail, fingerprint: str) -> None:
        record = email.to_email_record()
        if (
            self.resolve_fingerprint(
                record.subject,
                record.body_fingerprint,
                record.fingerprint,
                record.received_at,
            )
            != fingerprint
        ):
            raise ValueError('Fingerprint differs from the parsed email identity')
        row = record.as_storage_row()
        EmailRepository.write_record(
            self.connection, row, duplicate_window_hours=self.duplicate_window_hours
        )
        self.connection.execute(
            """INSERT INTO processed_emails (fingerprint, profile)
               VALUES (?, ?)""",
            (fingerprint, self.profile),
        )
