from __future__ import annotations

import re
from collections.abc import Sequence
from html.parser import HTMLParser

from .types import InlineFigure

FIGURE_MARKER = re.compile(r'\[Inline figure \d+\]')


class HTMLTextExtractor(HTMLParser):
    """Extract visible text and preserve inline-image positions.

    Image attachments are matched and classified later (see ``images.py``); here every
    non-tracking ``<img>`` becomes a numbered marker carrying its raw attributes.
    """

    BLOCKS = {
        'p',
        'div',
        'table',
        'tr',
        'li',
        'ul',
        'ol',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'section',
        'article',
        'header',
        'footer',
        'blockquote',
        'center',
        'dl',
        'dd',
        'dt',
        'pre',
        'form',
        'caption',
    }

    HIDDEN = {
        'head',
        'style',
        'script',
        'title',
        'template',
        'noscript',
    }

    VOID = {
        'area',
        'base',
        'br',
        'col',
        'embed',
        'hr',
        'img',
        'input',
        'link',
        'meta',
        'param',
        'source',
        'track',
        'wbr',
    }

    HIDDEN_STYLE = re.compile(r'(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all)\b', re.I)
    TRACKING_PIXEL_MAX = 5

    def __init__(
        self,
        *,
        drop_inline_images: bool = False,
        keep_links: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)

        self.drop_inline_images = drop_inline_images
        self.keep_links = keep_links

        self.parts: list[str] = []
        self.figures: list[InlineFigure] = []
        self.stack: list[tuple[str, bool, str]] = []

    def text(self) -> str:
        return self._normalize_text(''.join(self.parts))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = attrs.get('style') or ''
        hidden = (
            any(item[1] for item in self.stack)
            or tag in self.HIDDEN
            or 'hidden' in attrs
            or bool(self.HIDDEN_STYLE.search(style))
        )
        href = attrs.get('href') or ''
        if not hidden:
            if tag in self.BLOCKS or tag in {'br', 'hr'}:
                self.parts.append('\n')
            elif tag in {'td', 'th'}:
                self.parts.append(' ')
            if tag in {'img', 'v:imagedata'}:
                self._handle_image(attrs)
            if tag == 'li':
                self.parts.append('* ')
        if tag not in self.VOID:
            self.stack.append((tag, hidden, href))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                _, hidden, href = self.stack[index]
                del self.stack[index:]
                if not hidden:
                    if self.keep_links and tag == 'a' and re.match(r'^(?:https?://|mailto:)', href, re.I):
                        self.parts.append(' <' + href + '>')
                    if tag in self.BLOCKS:
                        self.parts.append('\n')
                    elif tag in {'td', 'th'}:
                        self.parts.append(' ')
                break

    def handle_data(self, data):
        if not any(item[1] for item in self.stack):
            self.parts.append(re.sub(r'\s+', ' ', data))

    def _handle_image(self, attrs):
        if self.drop_inline_images:
            self.parts.append(' ')
            return
        source = attrs.get('src') or ''
        if not source:
            return
        width, width_percent = self._dimension('width', attrs)
        height, height_percent = self._dimension('height', attrs)
        limit = self.TRACKING_PIXEL_MAX
        if (width is not None and not width_percent and width <= limit) or (
            height is not None and not height_percent and height <= limit
        ):
            return
        marker = f'[Inline figure {len(self.figures) + 1}]'
        self.figures.append(
            InlineFigure(
                marker,
                source,
                attrs.get('alt') or '',
                title=attrs.get('title') or '',
                css_class=attrs.get('class') or '',
                width=width,
                height=height,
                width_is_percent=width_percent,
            )
        )
        self.parts.append('\n' + marker + '\n')

    @staticmethod
    def _dimension(name: str, attrs: dict) -> tuple[float | None, bool]:
        value = (attrs.get(name) or '').strip()
        match = re.search(
            r'(?:^|;)\s*' + name + r'\s*:\s*([\d.]+)(px|%)?(?:\s|;|!|$)',
            attrs.get('style') or '',
            re.I,
        )
        percent = False
        if match:
            value = match.group(1)
            percent = match.group(2) == '%'
        else:
            value = re.sub(r'px$', '', value, flags=re.I)
            if value.endswith('%'):
                value, percent = value[:-1], True
        return (float(value), percent) if re.fullmatch(r'\d+(?:\.\d+)?', value) else (None, False)

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = text.replace('\xa0', ' ')
        for char in ('\u200b', '\u200c', '\u034f', '\u00ad', '\ufeff'):
            text = text.replace(char, '')

        lines = [re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.splitlines()]

        return re.sub(
            r'\n{3,}',
            '\n\n',
            '\n'.join(lines),
        ).strip()
