"""Compatibility facade for callers that need extracted dataframes."""

from pathlib import Path

from ..classes import ExtractedEmail
from ..parsing import EmailParser
from .jsonl import read_jsonl


class EmailExtractor:
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
    BODY_COLUMNS = ('entry_id', 'body', 'body_source', 'warnings')

    def __init__(
        self, parser: EmailParser | None = None, *, drop_inline_images: bool | None = None
    ):
        self.parser = parser if parser is not None else EmailParser()
        self.drop_inline_images = drop_inline_images

    def extract(self, message: object, *, metadata=None, attachments=None) -> ExtractedEmail:
        from ..pipeline import parse_email

        return parse_email(
            message,
            parser=self.parser,
            metadata=metadata,
            attachments=attachments,
            drop_inline_images=self.drop_inline_images,
        )

    def _parsed_messages(self, messages):
        from ..pipeline import parse_emails

        parsed = []
        for message in messages:
            if isinstance(message, ExtractedEmail):
                parsed.append(message)
            else:
                parsed.extend(
                    parse_emails(
                        [message],
                        parser=self.parser,
                        drop_inline_images=self.drop_inline_images,
                    )
                )
        return parsed

    def to_dataframe(self, messages):
        import pandas as pd

        records = (email.to_record() for email in self._parsed_messages(messages))
        return pd.DataFrame.from_records(records, columns=self.COLUMNS)

    def body_dataframe(self, messages):
        import pandas as pd

        records = (
            {
                'entry_id': email.metadata.entry_id,
                'body': email.parsed.body,
                'body_source': email.parsed.source,
                'warnings': email.parsed.warnings,
            }
            for email in self._parsed_messages(messages)
        )
        return pd.DataFrame.from_records(records, columns=self.BODY_COLUMNS)

    def load_database(
        self, messages, database: str | Path, *, duplicate_window_hours: float = 24.0
    ):
        from ..storage import EmailRepository

        emails = self._parsed_messages(messages)
        EmailRepository(database, duplicate_window_hours=duplicate_window_hours).upsert(emails)
        return self.body_dataframe(emails)

    def from_jsonl(
        self, path, *, database: str | Path | None = None, duplicate_window_hours: float = 24.0
    ):
        drop_images = (
            self.parser.drop_inline_images
            if self.drop_inline_images is None
            else self.drop_inline_images
        )
        messages = read_jsonl(path, drop_inline_images=drop_images)
        if database is not None:
            return self.load_database(
                messages, database, duplicate_window_hours=duplicate_window_hours
            )
        return self.to_dataframe(messages)
