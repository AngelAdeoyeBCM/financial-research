"""Shared email dataclasses, independent of Outlook, pandas, and storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawEmail:
    """Backward-compatible alias for a normalized raw email."""

    entry_id: str
    sender_email: str
    received_at: datetime
    subject: str | None
    internet_message_id: str | None = None
    conversation_id: str | None = None
    conversation_topic: str | None = None
    html: str = ''
    attachments: tuple[Mapping, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class SyncResult:
    """Counts for a successfully committed Outlook sync."""

    scanned: int = 0
    processed: int = 0
    duplicates: int = 0
    skipped: int = 0
