from __future__ import annotations

import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from .types import InlineFigure

CID = re.compile(r'^cid:', re.I)

# Logos, banners, analyst photos, social buttons, QR codes, trackers.
REJECT = re.compile(
    r'(?:logo|icon|banner|header|footer|spacer|pixel|track|beacon|social|facebook|twitter|linkedin|youtube|'
    r'instagram|whatsapp|avatar|profile|photo|headshot|portrait|analyst|author|\bqr\b|qr[-_ ]?code|flag|button|'
    r'arrow|bullet|divider|separator|signature|badge|app[-_ ]?store|google[-_ ]?play|unsubscribe|marketing|'
    r'sponsor|advert|promo|\bbio\b|thumb|placeholder|hero|bloomberg|symphony|\bchat\b|meeting|email|\bmail\b|'
    r'phone|download|\bpdf\b|calendar|checkmark|share|print|globe|ribbon|transparent|1x1|picture of|contact)',
    re.I,
)
ACCEPT = re.compile(r'(?:exhibit|chart|graph|figure|\bfig[-_ ]?\d|plot|infographic|heat-?map|table|diagram)', re.I)

MIN_PIXEL_WIDTH, MIN_PIXEL_HEIGHT, MIN_BYTES = 250, 100, 5000
MIN_DECLARED_HEIGHT, MIN_DECLARED_WIDTH, WIDE_DECLARED_WIDTH, WIDE_PERCENT = 60, 120, 300, 60
SPARE_MIN_PIXEL_WIDTH, SPARE_MIN_BYTES = 400, 10000


@dataclass(frozen=True, slots=True)
class ImageFacts:
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None


def read_image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a PNG, GIF or JPEG read from its header; None if unknown."""
    try:
        with path.open('rb') as stream:
            head = stream.read(32)
            if head.startswith(b'\x89PNG\r\n\x1a\n') and len(head) >= 24:
                return struct.unpack('>II', head[16:24])
            if head[:6] in (b'GIF87a', b'GIF89a'):
                return struct.unpack('<HH', head[6:10])
            if head[:2] == b'\xff\xd8':
                stream.seek(2)
                while True:
                    marker = stream.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    (length,) = struct.unpack('>H', stream.read(2))
                    if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        _, height, width = struct.unpack('>BHH', stream.read(5))
                        return width, height
                    stream.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def attachment_facts(attachment: Mapping | None, root: Path | None) -> ImageFacts:
    """Byte and pixel size of an attachment, from explicit keys or from the file under ``root``."""
    if not attachment:
        return ImageFacts()
    size = attachment.get('size_bytes') or attachment.get('size')
    width, height = attachment.get('width'), attachment.get('height')
    path = attachment.get('attachment_path')
    if path and root is not None:
        file = Path(root) / path
        if size is None and file.is_file():
            size = file.stat().st_size
        if (width is None or height is None) and file.is_file():
            width, height = read_image_size(file) or (None, None)
    return ImageFacts(size, width, height)


def _norm_cid(value: str) -> str:
    value = unquote(value.strip()).removeprefix('cid:').strip('<>').lower()
    return value.split('@', 1)[0].replace('_5f', '_')


def _strip_ext(value: str) -> str:
    stem, dot, _ = value.rpartition('.')
    return stem if dot and stem else value


def _strip_hash(value: str) -> str:
    return re.sub(r'-[0-9a-f]{8}$', '', value)


def _names_match(attachment_name: str, cid: str) -> bool:
    name = unquote(attachment_name.lower().replace('_5f', '_'))
    return (
        name == cid
        or _strip_ext(name) == cid
        or _strip_hash(name) == cid
        or (len(cid) > 6 and _strip_hash(_strip_ext(_strip_hash(name))) == _strip_hash(_strip_ext(cid)))
    )


def resolve_attachments(
    figures: Sequence[InlineFigure],
    attachments: Sequence[Mapping],
    root: Path | None = None,
) -> list[Mapping | None]:
    """Match each figure to an attachment record, trying progressively looser rules.

    1. Content-ID equality, then attachment name equal to the CID prefix.
    2. Normalised file name (extension / trailing hash stripped).
    3. Positional pairing for ``ATT00001``-style exports when counts agree.
    4. For still-unmatched wide ``cid:`` images, a large attachment no other figure uses
       (stands in for the real file when sizing the image).
    """
    found: list[Mapping | None] = [None] * len(figures)
    cids = [_norm_cid(f.source) if CID.match(f.source) else None for f in figures]

    for index, figure in enumerate(figures):
        if cids[index] is None:
            continue
        reference = unquote(figure.source).removeprefix('cid:').strip('<>')
        by_id = [
            a for a in attachments if a.get('content_id') and unquote(a['content_id']).strip('<>') == reference
        ]
        by_name = [
            a
            for a in attachments
            if not a.get('content_id') and a.get('attachment_name') == reference.split('@', 1)[0]
        ]
        for candidates in (by_id, by_name):
            if len(candidates) == 1:
                found[index] = candidates[0]
                break
        if found[index] is None:
            loose = [a for a in attachments if _names_match(a.get('attachment_name') or '', cids[index])]
            if loose:
                found[index] = loose[0]

    unique = list(dict.fromkeys(c for c in cids if c))
    positional = sorted(
        (a for a in attachments if re.match(r'^ATT\d+', a.get('attachment_name') or '', re.I)),
        key=lambda a: a['attachment_name'],
    )
    if positional and len(positional) == len(unique):
        for index, cid in enumerate(cids):
            if cid and found[index] is None:
                found[index] = positional[unique.index(cid)]

    used = {id(a) for a in found if a is not None}
    spare = []
    for a in attachments:
        if id(a) in used:
            continue
        facts = attachment_facts(a, root)
        if (facts.width or 0) >= SPARE_MIN_PIXEL_WIDTH and (facts.size_bytes or 0) >= SPARE_MIN_BYTES:
            spare.append(a)
    for index, figure in enumerate(figures):
        if not spare:
            break
        if found[index] is not None or cids[index] is None or figure.width is None:
            continue
        wide = figure.width >= (WIDE_PERCENT if figure.width_is_percent else WIDE_DECLARED_WIDTH)
        if wide:
            found[index] = spare.pop(0)
    return found

def classify_figure(
    figure: InlineFigure,
    attachment: Mapping | None,
    facts: ImageFacts,
) -> tuple[bool, str]:
    """Return (is_content, reason): True for charts/exhibits, False for logos, photos and chrome."""
    source_path = re.split(r'[?#]', figure.source, maxsplit=1)[0]
    file_name = source_path.rsplit('/', 1)[-1]
    attachment_name = (attachment or {}).get('attachment_name') or ''
    haystack = ' '.join((figure.alt, figure.title, figure.css_class, file_name, attachment_name))
    accepted = bool(ACCEPT.search(' '.join((figure.alt, figure.title, attachment_name, source_path))))

    if not accepted and REJECT.search(haystack):
        return False, 'logo/photo/chrome keyword'
    if facts.width:
        if facts.width < MIN_PIXEL_WIDTH or (facts.height or 0) < MIN_PIXEL_HEIGHT:
            return False, 'small image'
        if facts.size_bytes is not None and facts.size_bytes < MIN_BYTES:
            return False, 'small file'
        return True, 'image size'
    if not figure.width_is_percent and figure.width is not None and figure.width < MIN_DECLARED_WIDTH:
        return False, 'small declared width'
    if figure.height is not None and not figure.width_is_percent and figure.height < MIN_DECLARED_HEIGHT:
        return False, 'small declared height'
    if accepted:
        return True, 'chart keyword'
    if not figure.width_is_percent and figure.width is not None and figure.width >= WIDE_DECLARED_WIDTH:
        return True, 'wide declared width'
    if (
        figure.width_is_percent
        and figure.width is not None
        and figure.width >= WIDE_PERCENT
        and not CID.match(figure.source)
    ):
        return True, 'wide remote image'
    return False, 'unknown'
