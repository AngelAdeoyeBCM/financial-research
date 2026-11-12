from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class InlineFigure:
    marker: str
    source: str
    alt: str = ''
    attachment_name: str | None = None
    attachment_path: str | None = None
    title: str = ''
    css_class: str = ''
    width: float | None = None
    height: float | None = None
    width_is_percent: bool = False
    is_content: bool = True
    reason: str = ''


@dataclass(frozen=True)
class ParsedEmail:
    """Email with header, footer, and disclaimers removed; authors kept in the signature."""

    subject: str
    sender_email: str
    received_at: datetime
    body: str
    signature: str
    figures: tuple[InlineFigure, ...] = ()

    @property
    def has_image_content(self) -> bool:
        """True when the body holds chart/exhibit images (logos, photos and trackers are excluded)."""
        return bool(self.figures)

    @property
    def as_text(self) -> str:
        """Return model-ready email text."""
        header = (
            f'Subject: {self.subject}\n'
            f'Sender: {self.sender_email}\n'
            f'Received: {self.received_at.isoformat()}'
        )

        return '\n\n'.join(
            part
            for part in (
                header,
                self.body,
                self.signature,
            )
            if part
        )

    def __str__(self) -> str:
        return self.as_text
