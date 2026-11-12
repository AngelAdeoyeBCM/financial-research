from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import rules

FIGURE_LINE = re.compile(r'^\[Inline figure (\d+)\]$')
FIGURE_NUMBER = re.compile(r'\[Inline figure (\d+)\]')
BULLET_PREFIX = re.compile(r'^[●•▪·]\s*(?=\S)')
BULLET_ONLY = frozenset({'*', '•', '●', '·', '▪', '-'})
CREDIT_SUFFIX = ('Inc.', 'Ltd.', 'Co.')

MIN_CHARS_BEFORE_FOOTER = 150
MIN_BODY_LINE = 110
MAX_CONTACT_LINE_CHARS = 120
MAX_SIGNATURE_LINES = 25


@dataclass(slots=True)
class Paragraph:
    lines: list[str] = field(default_factory=list)
    figure: int | None = None
    drop: bool = False

    @property
    def text(self) -> str:
        if self.figure is not None:
            return f'[Inline figure {self.figure}]'
        return '\n'.join(self.lines)

    @property
    def is_text(self) -> bool:
        return self.figure is None and not self.drop


@dataclass(frozen=True, slots=True)
class CleanResult:
    body: str
    signature: str
    figures: tuple[int, ...]


def clean(text: str, content_figures: set[int]) -> CleanResult:
    """Strip header, footer and disclaimer text; return body, signature and kept figure numbers.

    ``content_figures`` holds the 1-based figure numbers judged to be real chart/exhibit content.
    """
    items = _paragraphs(text)
    _drop_boilerplate_lines(items)
    _strip_contact_details(items)
    _drop_repeated_paragraphs(items)
    cut = _footer_cut(items)
    header_authors = _clean_header(items, cut)
    kept = _filter_figures(items, cut, content_figures)
    signature = _extract_signature(items, cut)
    for line in header_authors:
        names = _name_parts(re.sub(r'^By\s+', '', line, flags=re.I))
        if not all(n.lower() in signature.lower() for n in names):
            signature = f'{signature}\n{line}'.strip()
    signature = '\n'.join(dict.fromkeys(signature.splitlines()))

    body = '\n\n'.join(p.text for p in items[:cut] if not p.drop and (p.lines or p.figure is not None))
    return CleanResult(body.strip(), signature.strip(), tuple(kept))


def renumber(text: str, mapping: dict[int, int]) -> str:
    """Rewrite figure markers using ``mapping``; markers absent from it are removed."""

    def replace(match: re.Match) -> str:
        number = mapping.get(int(match.group(1)))
        return f'[Inline figure {number}]' if number else ''

    return FIGURE_NUMBER.sub(replace, text)

def _paragraphs(text: str) -> list[Paragraph]:
    items: list[Paragraph] = []
    current: Paragraph | None = None
    for raw in text.split('\n'):
        line = BULLET_PREFIX.sub('* ', raw.strip())
        if not line:
            current = None
            continue
        marker = FIGURE_LINE.match(line)
        if marker:
            items.append(Paragraph(figure=int(marker.group(1))))
            current = None
            continue
        if current is None:
            current = Paragraph()
            items.append(current)
        current.lines.append(line)
    _merge_bullets(items)
    return items


def _merge_bullets(items: list[Paragraph]) -> None:
    for index, para in enumerate(items):
        if para.figure is not None:
            continue
        position = 0
        while position < len(para.lines):
            if para.lines[position] not in BULLET_ONLY:
                position += 1
                continue
            if position + 1 < len(para.lines):
                para.lines[position + 1] = '* ' + para.lines[position + 1]
            else:
                following = next(
                    (p for p in items[index + 1 :] if p.figure is None and p.lines),
                    None,
                )
                if following and not following.lines[0].startswith('* '):
                    following.lines[0] = '* ' + following.lines[0]
            del para.lines[position]


def _is_boilerplate(line: str) -> bool:
    return any(rule.match(line) for rule in rules.LINE_DROP) or bool(rules.ANALYST_ACCREDITATION.match(line))


def _drop_boilerplate_lines(items: list[Paragraph]) -> None:
    for para in items:
        if para.figure is None:
            para.lines = [line for line in para.lines if not _is_boilerplate(line)]
            para.drop = not para.lines


def _strip_contact_details(items: list[Paragraph]) -> None:
    """Remove phone numbers and e-mail addresses from short lines, keeping names and roles."""
    for para in items:
        if not para.is_text:
            continue
        kept = []
        for line in para.lines:
            if len(line) > MAX_CONTACT_LINE_CHARS or not (rules.EMAIL.search(line) or rules.PHONE.search(line)):
                kept.append(line)
                continue
            stripped = rules.PHONE.sub('', rules.EMAIL.sub('', line))
            stripped = rules.CONTACT_LABEL.sub('', stripped)
            stripped = re.sub(r'\s{2,}', ' ', stripped).strip(' ,;:|-–—')
            if len(stripped) > 2 and re.search(r'[A-Za-z]{2}', stripped):
                kept.append(stripped)
        para.lines = kept
        para.drop = not kept

def _drop_repeated_paragraphs(items: list[Paragraph]) -> None:
    previous: Paragraph | None = None
    for para in items:
        if para.drop:
            continue
        if para.figure is not None:
            previous = None
            continue
        if previous is not None and previous.text.casefold() == para.text.casefold():
            para.drop = True
            continue
        previous = para


def _chars_before(items: list[Paragraph], upto: int) -> int:
    return sum(len(line) for p in items[:upto] if p.is_text for line in p.lines)


def _footer_cut(items: list[Paragraph]) -> int:
    """Index of the first footer/disclaimer paragraph (footer lines near the very top are just removed)."""
    index = 0
    while index < len(items):
        para = items[index]
        if not para.is_text:
            index += 1
            continue
        hit = next(
            (k for k, line in enumerate(para.lines) if any(r.match(line) for r in rules.FOOTER_START)),
            None,
        )
        if hit is None:
            index += 1
            continue
        before = _chars_before(items, index) + sum(len(line) for line in para.lines[:hit])
        if before < MIN_CHARS_BEFORE_FOOTER:
            del para.lines[hit]
            para.drop = not para.lines
            continue
        if hit > 0:
            del para.lines[hit:]
            return index + 1
        return index
    return len(items)


def _clean_header(items: list[Paragraph], cut: int) -> list[str]:
    """Drop dates, region labels and author bylines ahead of the first body paragraph.

    Author lines are returned so they can be kept in the signature.
    """
    first_body = next(
        (
            i
            for i in range(cut)
            if items[i].is_text and any(len(line) >= MIN_BODY_LINE for line in items[i].lines)
        ),
        cut,
    )
    authors: list[str] = []
    kept_paragraphs = 0
    for para in items[:first_body]:
        if not para.is_text:
            continue
        if (
            kept_paragraphs >= 1
            and 2 <= len(para.lines) <= 4
            and all(len(line) <= 40 and rules.NAME.match(line) for line in para.lines)
        ):
            authors.extend(para.lines)
            para.drop = True
            continue
        kept_paragraphs += 1
        kept = []
        for line in para.lines:
            if rules.DATE_ONLY.match(line) or rules.REGION_LABEL.match(line) or rules.DATED_LINE.search(line):
                continue
            if (
                rules.BYLINE.match(line)
                or rules.NAME_WITH_CREDENTIAL.match(line)
                or (',' in line and _is_name_list(line))
            ):
                authors.append(line)
                continue
            kept.append(line)
        para.lines = kept
        para.drop = not kept
    return authors


def _name_parts(line: str) -> list[str]:
    return [p.strip() for p in re.split(r',\s*|\s+and\s+|\s*&\s*', line) if p.strip()]


def _is_name_list(line: str, min_parts: int = 2) -> bool:
    if len(line) >= 120 or line.endswith('.'):
        return False
    parts = _name_parts(line)
    return len(parts) >= min_parts and all(rules.NAME.match(p) for p in parts)

def _filter_figures(items: list[Paragraph], cut: int, content_figures: set[int]) -> list[int]:
    first_text = next((i for i in range(cut) if items[i].is_text), None)
    kept: list[int] = []
    for index, para in enumerate(items):
        if para.figure is None:
            continue
        if index < cut and first_text is not None and index > first_text and para.figure in content_figures:
            kept.append(para.figure)
        else:
            para.drop = True
    return kept


def _is_signature_line(line: str) -> bool:
    if line.startswith(('Source', 'Note')) or len(line) > 90:
        return False
    if line.endswith('.') and not line.endswith(CREDIT_SUFFIX):
        return False
    return bool(
        rules.NAME.match(line)
        or _is_name_list(line)
        or rules.ENTITY.match(line)
        or rules.EMAIL.search(line)
        or rules.PHONE.search(line)
        or (len(line) <= 60 and rules.TITLE.search(line) and not re.search(r'\d{2,}', line))
        or rules.CONTACT_LEAD.match(line)
    )


def _is_signature_paragraph(para: Paragraph) -> bool:
    return (
        para.figure is None
        and 0 < len(para.lines) <= 6
        and all(_is_signature_line(line) for line in para.lines)
    )


def _extract_signature(items: list[Paragraph], cut: int) -> str:
    """Pull the trailing sign-off / author block out of the body and return it."""
    start = _signature_start(items, cut)
    if start is not None:
        index, line_index = start
        lines: list[str] = []
        for para in items[index:cut]:
            if not para.is_text:
                para.drop = True
                continue
            lines.extend(para.lines[line_index:] if para is items[index] else para.lines)
            if para is items[index]:
                del para.lines[line_index:]
                para.drop = not para.lines
            else:
                para.drop = True
        return '\n'.join(_signature_lines(lines))

    collected: list[str] = []
    last = cut - 1
    while last >= 0:
        para = items[last]
        if para.drop:
            last -= 1
            continue
        if para.figure is not None or not _is_signature_paragraph(para):
            break
        collected = para.lines + collected
        para.drop = True
        last -= 1
    return '\n'.join(collected)


def _signature_start(items: list[Paragraph], cut: int) -> tuple[int, int] | None:
    for index in range(cut):
        para = items[index]
        if not para.is_text:
            continue
        for line_index, line in enumerate(para.lines):
            if not any(r.match(line) for r in rules.SIGNATURE_START):
                continue
            before = _chars_before(items, index) + sum(len(x) for x in para.lines[:line_index])
            following = items[index:cut]
            remaining = sum(len(p.lines) for p in following if p.is_text) - line_index
            if (
                before >= MIN_CHARS_BEFORE_FOOTER
                and remaining <= MAX_SIGNATURE_LINES
                and all(p.figure is None for p in following)
            ):
                return index, line_index
    return None


def _signature_lines(lines: list[str]) -> list[str]:
    kept = []
    for line in lines:
        if any(r.match(line) for r in rules.SIGNATURE_START) or _is_signature_line(line):
            kept.append(line)
    return kept[:MAX_SIGNATURE_LINES]
