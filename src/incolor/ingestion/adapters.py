"""Normalize source values once, without importing Outlook COM libraries."""

from collections.abc import Mapping
from datetime import datetime

from ..classes import EmailMetadata, RawEmail
from .dedup import email_fingerprint


def is_email(message: object) -> bool:
    if isinstance(message, Mapping):
        return message.get('kind', 'email') == 'email'
    # Outlook folders can also contain meeting requests and other item types.
    return isinstance(message, RawEmail) or getattr(message, 'Class', 43) == 43


def normalize_email(
    message: object,
    *,
    metadata=None,
    attachments=None,
    drop_inline_images=False,
) -> RawEmail:
    if isinstance(message, RawEmail):
        if not message.metadata.fingerprint:
            message.metadata.fingerprint = email_fingerprint(message)
        return message
    if not is_email(message):
        raise ValueError('Expected an email record')
    warnings = []
    html = read_text(message, 'HTMLBody', 'html_body', warnings)
    text = read_text(message, 'Body', 'text', warnings)
    figures = (
        ()
        if drop_inline_images or not html.strip()
        else read_attachments(message, attachments, warnings)
    )
    raw = RawEmail(
        metadata if metadata is not None else read_metadata(message),
        html,
        text,
        tuple(figures),
        tuple(warnings),
    )
    raw.metadata.fingerprint = email_fingerprint(raw)
    return raw


def read_metadata(message: object) -> EmailMetadata:
    if isinstance(message, Mapping):
        entry_id = message.get('entry_id', message.get('message_id'))
        received_at = message.get('received_at', message.get('received'))
        sender_email = message.get('sender_email', message.get('sender'))
        subject = message.get('subject')
    else:
        entry_id = message.EntryID
        received_at = message.ReceivedTime
        sender_email = message.SenderEmailAddress
        subject = message.Subject
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ValueError('A non-empty entry_id is required')
    if isinstance(received_at, str):
        received_at = datetime.fromisoformat(received_at)
    if not isinstance(received_at, datetime):
        raise ValueError('received_at/received must be a datetime or ISO timestamp')
    return EmailMetadata(entry_id, sender_email, received_at, subject)


def read_attachments(message, supplied, warnings):
    if supplied is not None:
        return supplied
    if isinstance(message, Mapping):
        return message.get('attachments') or ()
    try:
        collection = getattr(message, 'Attachments', None)
        if collection is None:
            return ()
        records = []
        for index in range(1, collection.Count + 1):
            item = collection.Item(index)
            content_id = None
            for tag in ('0x3712001F', '0x3712001E'):
                try:
                    content_id = item.PropertyAccessor.GetProperty(
                        'http://schemas.microsoft.com/mapi/proptag/' + tag
                    )
                    break
                except Exception:
                    continue
            records.append({'attachment_name': item.FileName, 'content_id': content_id})
        return records
    except Exception as exc:
        warnings.append(f'Attachment metadata unavailable ({type(exc).__name__}).')
        return ()


def read_text(message, attribute, key, warnings):
    try:
        value = (
            message.get(key, message.get(attribute, ''))
            if isinstance(message, Mapping)
            else getattr(message, attribute, '')
        )
    except Exception as exc:
        # COM property access can fail even when the other body is readable.
        warnings.append(f'{attribute} unavailable ({type(exc).__name__}).')
        return ''
    if value is None:
        return ''
    if not isinstance(value, str):
        raise TypeError(f'{attribute}/{key} must be a string or None')
    return value

# from abc import ABC, abstractmethod
# from dataclasses import dataclass

# @dataclass
# class Element:
#     kind: str          # text | table | figure
#     content: str
#     page: int
#     bbox: tuple
#     meta: dict

# class Handler(ABC):
#     kind: str
#     @abstractmethod
#     def process(self, region) -> Element: ...

# class TableHandler(Handler):
#     kind = "table"
#     def process(self, region):
#         grid = self.to_grid(region)
#         return Element("table", self.verbalise(grid), region.page, region.bbox, {"grid": grid})
#     def to_grid(self, region): ...
#     def verbalise(self, grid): ...

# class FigureHandler(Handler):
#     kind = "figure"
#     prompts: dict = {}                      # figure type -> prompt
#     def process(self, region):
#         ftype = self.classify(region.image)
#         return Element("figure", self.describe(region, self.prompts[ftype]),
#                        region.page, region.bbox, {"type": ftype})

# class ChartFigureHandler(FigureHandler):    # specialise via inheritance
#     prompts = {"chart": "Extract axes, series, values, trend."}

# class Pipeline:
#     def __init__(self, parser, handlers: dict[str, Handler], filters=("page_header", "page_footer")):
#         self.parser, self.handlers, self.filters = parser, handlers, filters
#     def run(self, pdf):
#         regions = (r for r in self.parser.parse(pdf) if r.label not in self.filters)
#         return [self.handlers[r.kind].process(r) for r in regions]

# class TemplateRegistry:                     # per-publisher overrides
#     _templates: list = []
#     @classmethod
#     def resolve(cls, doc): return next((t for t in cls._templates if t.matches(doc)), Pipeline)