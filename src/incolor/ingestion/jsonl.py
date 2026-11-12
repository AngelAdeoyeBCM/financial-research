"""Streaming JSONL ingestion with source locations on invalid records."""

import json
from pathlib import Path

from .adapters import is_email, normalize_email


def read_jsonl(path: str | Path, *, drop_inline_images: bool = False):
    """Yield normalized emails; blank lines and non-email records are skipped."""
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise TypeError('Expected a JSON object')
                if is_email(message):
                    yield normalize_email(message, drop_inline_images=drop_inline_images)
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f'{path}: line {line_number}: {exc}') from exc
