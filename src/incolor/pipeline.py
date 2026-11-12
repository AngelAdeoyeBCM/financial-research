"""Stream normalized emails through parsing into transactional storage."""

from collections.abc import Iterable
from pathlib import Path

from .classes import ExtractedEmail, SyncResult
from .ingestion.adapters import is_email, normalize_email
from .ingestion.dedup import (
    DEFAULT_DUPLICATE_WINDOW_HOURS,
    duplicate_window,
    extracted_fingerprint,
    is_duplicate,
    processing_profile,
)
from .ingestion.jsonl import read_jsonl
from .parsing import EmailParser
from .storage import EmailRepository


def parse_email(
    message: object,
    *,
    parser: EmailParser | None = None,
    metadata=None,
    attachments=None,
    drop_inline_images: bool | None = None,
) -> ExtractedEmail:
    parser = parser if parser is not None else EmailParser()
    drop_images = parser.drop_inline_images if drop_inline_images is None else drop_inline_images
    raw = normalize_email(
        message, metadata=metadata, attachments=attachments, drop_inline_images=drop_images
    )
    parsed = parser.parse(raw, drop_inline_images=drop_images)
    metadata = raw.metadata
    metadata.body_fingerprint = extracted_fingerprint(raw, parsed.body)
    return ExtractedEmail(metadata, parsed)


def parse_emails(
    messages: Iterable[object],
    *,
    parser: EmailParser | None = None,
    drop_inline_images: bool | None = None,
):
    parser = parser if parser is not None else EmailParser()
    for message in messages:
        if is_email(message):
            yield parse_email(message, parser=parser, drop_inline_images=drop_inline_images)


def load_emails(
    messages: Iterable[object],
    database: str | Path,
    *,
    drop_inline_images: bool = False,
    duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
) -> int:
    """Load a stream atomically. Return processed rows, including updates."""
    parsed = parse_emails(messages, drop_inline_images=drop_inline_images)
    return EmailRepository(database, duplicate_window_hours=duplicate_window_hours).upsert(parsed)


def load_jsonl(
    source: str | Path,
    database: str | Path,
    *,
    drop_inline_images: bool = False,
    duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
) -> int:
    return load_emails(
        read_jsonl(source, drop_inline_images=drop_inline_images),
        database,
        drop_inline_images=drop_inline_images,
        duplicate_window_hours=duplicate_window_hours,
    )


def sync_emails(
    messages: Iterable[object],
    database: str | Path,
    *,
    drop_inline_images: bool = False,
    parser: EmailParser | None = None,
    duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
) -> SyncResult:
    """Process only new/changed candidates; duplicates are rejected before parsing.

    A failed scan, parse, or write rolls back the run, including deduplication
    state. Successful reruns see previously committed fingerprints. Existing
    legacy rows without fingerprints are processed once to seed that state.
    """
    parser = parser if parser is not None else EmailParser()
    repository = EmailRepository(database, duplicate_window_hours=duplicate_window_hours)
    result = SyncResult()
    profile = processing_profile(
        drop_inline_images=drop_inline_images,
        duplicate_window_hours=duplicate_window_hours,
    )
    with repository.incremental_session(profile) as session:
        for message in messages:
            result.scanned += 1
            if not is_email(message):
                result.skipped += 1
                continue
            # Always read attachment metadata for stable identity across modes.
            raw = normalize_email(message)
            if raw.warnings:
                # Incomplete source reads must not overwrite good data or become
                # permanent duplicate matches. Retry after the source is fixed.
                raise ValueError(
                    f'Incomplete Outlook email {raw.metadata.entry_id}: ' + '; '.join(raw.warnings)
                )
            metadata_fingerprint = raw.metadata.fingerprint
            if is_duplicate(metadata_fingerprint, session.has_processed):
                result.duplicates += 1
                continue
            email = parse_email(raw, parser=parser, drop_inline_images=drop_inline_images)
            fingerprint = session.resolve_fingerprint(
                raw.metadata.subject,
                email.body_fingerprint,
                metadata_fingerprint,
                raw.metadata.received_at,
            )
            if is_duplicate(fingerprint, session.has_processed):
                result.duplicates += 1
                continue
            session.save(email, fingerprint)
            result.processed += 1
    return result


def sync_outlook(
    database: str | Path,
    *,
    client=None,
    folder=None,
    since=None,
    until=None,
    drop_inline_images: bool = False,
    duplicate_window_hours: float = DEFAULT_DUPLICATE_WINDOW_HOURS,
) -> SyncResult:
    """Incrementally update the database from the selected Outlook folder."""
    duplicate_window(duplicate_window_hours)
    if client is None:
        from .ingestion.outlook import OutlookClient

        client = OutlookClient()
    return sync_emails(
        client.iter_messages(folder, since=since, until=until),
        database,
        drop_inline_images=drop_inline_images,
        duplicate_window_hours=duplicate_window_hours,
    )


def main():
    import argparse
    from datetime import datetime

    from .ingestion.outlook import OutlookClient

    parser = argparse.ArgumentParser(description='Incrementally sync Outlook emails into SQLite')
    parser.add_argument('--database', type=Path, default=Path('data/research.sqlite3'))
    parser.add_argument('--folder', help='Folder path, e.g. Inbox/Research/Rates')
    parser.add_argument('--mailbox', help='Mailbox name; folder paths then start at its root')
    parser.add_argument(
        '--until', type=datetime.fromisoformat, help='Exclusive ISO received-time upper bound'
    )
    parser.add_argument(
        '--since',
        type=datetime.fromisoformat,
        help='Inclusive ISO received-time cutoff; local time if no offset',
    )
    parser.add_argument('--drop-inline-images', action='store_true')
    parser.add_argument(
        '--duplicate-window-hours',
        type=float,
        default=DEFAULT_DUPLICATE_WINDOW_HOURS,
        help='Maximum receipt-time separation for duplicates (default: 24)',
    )
    args = parser.parse_args()
    try:
        duplicate_window(args.duplicate_window_hours)
    except ValueError as exc:
        parser.error(str(exc))
    client = OutlookClient()
    result = sync_outlook(
        args.database,
        client=client,
        folder=client.get_folder(args.folder, mailbox=args.mailbox),
        since=args.since,
        until=args.until,
        drop_inline_images=args.drop_inline_images,
        duplicate_window_hours=args.duplicate_window_hours,
    )
    print(
        f'Processed {result.processed}; rejected {result.duplicates} duplicates; '
        f'skipped {result.skipped} non-email items'
    )


if __name__ == '__main__':
    main()
