"""Chunk dumps from the ``browse_metadata`` MCP tool, and the documents rebuilt from them."""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHUNK_ID_RE = re.compile(r"^(?P<document>.+)-(?P<page>\d+)-(?P<index>\d+)$")
# Identifiers kept on each chunk but never promoted to document-level metadata.
ID_FIELDS = frozenset({"chunk_id", "point_id", "text"})
MIN_OVERLAP = 20


class DumpError(ValueError):
    """A dump cannot be used: unreadable, truncated or inconsistent."""


@dataclass(frozen=True)
class Chunk:
    """One chunk record; ``index`` is its 0-based position in the document."""

    document: str
    date: str
    page: int
    index: int
    chunk_id: str
    point_id: str
    text: str
    record: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def parse(cls, record: dict[str, Any]) -> "Chunk | None":
        """Build a chunk from a dump record, or None when its ``chunk_id`` is not ``<document>-<page>-<index>``."""
        match = CHUNK_ID_RE.match(record.get("chunk_id") or "")
        if not match:
            return None
        return cls(
            document=match["document"],
            date=record.get("DocumentDate") or "",
            page=int(match["page"]),
            index=int(match["index"]),
            chunk_id=record["chunk_id"],
            point_id=record.get("point_id") or record["chunk_id"],
            text=record.get("text") or "",
            record=record,
        )


@dataclass(frozen=True)
class ChunkDump:
    """A saved ``browse_metadata`` result (``{count, records, truncated}``) fetched with ``include_text=true``."""

    path: Path
    sha256: str
    records: tuple[dict[str, Any], ...]

    @classmethod
    def load(cls, path: Path) -> "ChunkDump":
        """Read and validate a dump.

        Raises:
            DumpError: If the file is unreadable, truncated, has no text, or its count disagrees with its records.
        """
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise DumpError(f"{path}: {exc}") from exc
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise DumpError(f"{path}: no 'records' list")
        if payload.get("truncated"):
            raise DumpError(f"{path}: truncated at {len(records)} records; fetch a smaller date window")
        if isinstance(payload.get("count"), int) and payload["count"] != len(records):
            raise DumpError(f"{path}: count {payload['count']} != {len(records)} records")
        if records and not any(r.get("text") for r in records):
            raise DumpError(f"{path}: records carry no text; fetch with include_text=true")
        return cls(path, hashlib.sha256(raw).hexdigest(), tuple(records))

    @property
    def dates(self) -> list[str]:
        """Distinct ``DocumentDate`` values, sorted."""
        return sorted({r.get("DocumentDate") or "" for r in self.records})

    def summary(self) -> dict[str, Any]:
        """Provenance record for manifests and the ledger."""
        dates = self.dates
        return {
            "file": self.path.as_posix(),
            "sha256": self.sha256,
            "records": len(self.records),
            "dates": [dates[0], dates[-1]] if dates else [],
        }


@dataclass
class ResearchDocument:
    """One document rebuilt from its chunks, in index order."""

    name: str
    date: str
    chunks: list[Chunk]
    metadata: dict[str, Any]
    stem: str = ""

    @classmethod
    def from_chunks(cls, name: str, date: str, chunks: Iterable[Chunk]) -> "ResearchDocument":
        """Collate chunks; document metadata is every field with the same value on all chunks."""
        ordered = sorted(chunks, key=lambda c: (c.index, c.page))
        records = [c.record for c in ordered]
        keys = sorted({k for r in records for k in r} - ID_FIELDS)
        shared = {k: records[0].get(k) for k in keys if len({_canonical(r.get(k)) for r in records}) == 1}
        return cls(name, date, ordered, shared)

    @classmethod
    def from_legacy_json(cls, data: dict[str, Any], stem: str) -> "ResearchDocument":
        """Read a document JSON written by the old ``rebuild_documents.py``."""
        meta = data["metadata"]
        chunks = [
            Chunk(
                document=data["document"],
                date=c["metadata"].get("DocumentDate") or meta.get("DocumentDate") or "",
                page=c["page_number"],
                index=c["index"],
                chunk_id=c["chunk_id"],
                point_id=c.get("point_id") or c["chunk_id"],
                text=c.get("text") or "",
                record={**meta, **c["metadata"]},
            )
            for c in data["chunks"]
        ]
        date = meta.get("DocumentDate") or min((c.date for c in chunks if c.date), default="")
        return cls(data["document"], date, sorted(chunks, key=lambda c: (c.index, c.page)), meta, stem)

    @property
    def missing_indices(self) -> list[int]:
        """Chunk indices absent from the 0-based range up to the last chunk."""
        indices = {c.index for c in self.chunks}
        return sorted(set(range(max(indices) + 1)) - indices) if indices else []

    @property
    def page_count(self) -> int:
        """Number of distinct pages."""
        return len({c.page for c in self.chunks})

    @property
    def publisher(self) -> str:
        """``Source`` metadata, or empty."""
        return str(self.metadata.get("Source") or "")

    @property
    def document_type(self) -> str:
        """``DocumentType`` metadata, or empty."""
        return str(self.metadata.get("DocumentType") or "")

    def asset_classes(self) -> list[str]:
        """Every asset class tagged on the chunks, one entry per tag."""
        classes: list[str] = []
        for chunk in self.chunks:
            assets = chunk.record.get("Asset") or self.metadata.get("Asset") or []
            for asset in assets if isinstance(assets, list) else [assets]:
                if isinstance(asset, dict):
                    value = asset.get("Class")
                    classes.extend(v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str))
        return classes

    def merged_text(self) -> str:
        """Chunk texts joined in order, dropping the overlap where a chunk repeats the tail of the previous one."""
        return merge_texts([c.text for c in self.chunks])

    def manifest_entry(self) -> dict[str, Any]:
        """Identity and shape fields shared by every manifest record."""
        return {
            "stem": self.stem,
            "document": self.name,
            "date": self.date,
            "publisher": self.publisher,
            "document_type": self.document_type,
            "chunk_count": len(self.chunks),
            "page_count": self.page_count,
        }


class DocumentAssembler:
    """Groups chunks from one or more dumps into documents, de-duplicating chunks by ``point_id``."""

    def __init__(self) -> None:
        self.duplicates = 0
        self.unparsed: list[str] = []
        self._groups: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
        self._seen: set[str] = set()

    def add(self, records: Iterable[dict[str, Any]]) -> None:
        """Add dump records; recurring publications are kept apart by ``DocumentDate``."""
        for record in records:
            chunk = Chunk.parse(record)
            if chunk is None:
                self.unparsed.append(record.get("chunk_id") or str(record.get("point_id")))
                continue
            if chunk.point_id in self._seen:
                self.duplicates += 1
                continue
            self._seen.add(chunk.point_id)
            self._groups[(chunk.document, chunk.date)].append(chunk)

    def documents(self) -> Iterator[ResearchDocument]:
        """Documents in (name, date) order."""
        for (name, date), chunks in sorted(self._groups.items()):
            yield ResearchDocument.from_chunks(name, date, chunks)


def merge_texts(texts: list[str]) -> str:
    """Join chunk texts, dropping the overlap where a chunk starts with the tail of the previous one."""
    if not texts:
        return ""
    merged = texts[0]
    for text in texts[1:]:
        limit = min(len(merged), len(text))
        overlap = next((k for k in range(limit, MIN_OVERLAP - 1, -1) if merged.endswith(text[:k])), 0)
        merged = merged + text[overlap:] if overlap else f"{merged}\n{text}"
    return merged


def safe_stem(document: str) -> str:
    """Filesystem-safe stem for a document name (as the old ``rebuild_documents.py`` produced)."""
    return (re.sub(r"[^\w\-.]", "_", Path(document).stem).strip("._") or "document")[:150]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
