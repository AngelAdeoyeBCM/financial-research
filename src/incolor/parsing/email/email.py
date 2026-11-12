from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .cleaner import clean, renumber
from .html import HTMLTextExtractor
from .images import attachment_facts, classify_figure, resolve_attachments
from .types import InlineFigure, ParsedEmail


class EmailParser:
    """Parse an Outlook HTML email into core content.

    Header banners, navigation, footers and disclaimers are removed; author names and sign-offs are
    returned separately in ``signature``. Inline images are kept only when they look like charts or
    exhibits (logos, photos, icons and trackers are dropped) and are linked to their attachments.
    """

    def __init__(
        self,
        *,
        drop_inline_images: bool = False,
        keep_links: bool = False,
        attachment_root: str | Path | None = None,
    ) -> None:
        self.drop_inline_images = drop_inline_images
        self.keep_links = keep_links
        self.attachment_root = Path(attachment_root) if attachment_root else None

    def parse(
        self,
        message: object,
        *,
        attachments: Sequence[Mapping] = (),
    ) -> ParsedEmail:
        html = self._field(message, 'HTMLBody', 'html_body', 'html')
        if not isinstance(html, str) or not html.strip():
            raise ValueError('EmailParser requires a non-empty HTML body')

        extractor = HTMLTextExtractor(
            drop_inline_images=self.drop_inline_images,
            keep_links=self.keep_links,
        )
        extractor.feed(html)
        extractor.close()

        figures = self._classify(extractor.figures, attachments)
        result = clean(extractor.text(), {i for i, f in enumerate(figures, 1) if f.is_content})

        numbering = {old: new for new, old in enumerate(result.figures, 1)}
        kept = tuple(
            replace(figures[old - 1], marker=f'[Inline figure {new}]') for old, new in numbering.items()
        )

        return ParsedEmail(
            subject=self._field(message, 'Subject', 'subject'),
            sender_email=self._field(message, 'SenderEmailAddress', 'sender_email', 'sender'),
            received_at=self._received(self._field(message, 'ReceivedTime', 'received_at', 'received')),
            body=renumber(result.body, numbering),
            signature=result.signature,
            figures=kept,
        )

    def _classify(
        self,
        figures: Sequence[InlineFigure],
        attachments: Sequence[Mapping],
    ) -> list[InlineFigure]:
        matches = resolve_attachments(figures, attachments, self.attachment_root)
        classified = []
        for figure, attachment in zip(figures, matches):
            facts = attachment_facts(attachment, self.attachment_root)
            is_content, reason = classify_figure(figure, attachment, facts)
            classified.append(
                replace(
                    figure,
                    attachment_name=attachment.get('attachment_name') if attachment else None,
                    attachment_path=attachment.get('attachment_path') if attachment else None,
                    is_content=is_content,
                    reason=reason,
                )
            )
        return classified
    @staticmethod
    def _field(message: object, *names: str):
        for name in names:
            try:
                value = (
                    message.get(name)
                    if isinstance(message, Mapping)
                    else getattr(message, name, None)
                )
            except Exception:
                continue
            if value is not None:
                return value
        return None

    @staticmethod
    def _received(value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return value if isinstance(value, datetime) else None
