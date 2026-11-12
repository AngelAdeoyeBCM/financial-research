"""The ledger (source of truth for every batch attempt and document outcome) and the per-batch manifests."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

LEDGER_VERSION = 1


@dataclass(frozen=True)
class CorpusPaths:
    """Where the pipeline reads and writes."""

    root: Path
    pdfs: Path

    @property
    def ledger(self) -> Path:
        """``<root>/ledger.json``."""
        return self.root / "ledger.json"

    @property
    def manifests(self) -> Path:
        """``<root>/manifests``."""
        return self.root / "manifests"

    def extract_manifest(self, batch_id: str) -> Path:
        """Documents in scope for a batch, with what was stripped and changed."""
        return self.manifests / f"extract_{batch_id}.json"

    def skip_manifest(self, batch_id: str) -> Path:
        """Documents skipped in a batch, with the reasons."""
        return self.manifests / f"skipped_{batch_id}.json"


@dataclass
class DocumentRecord:
    """Latest outcome for one document; ``status`` is compiled, skipped, duplicate or protected."""

    stem: str
    document: str
    date: str
    publisher: str
    batch: str
    status: str
    codes: list[str] = field(default_factory=list)
    fingerprint: str | None = None
    output: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchRecord:
    """One batch attempt."""

    batch_id: str
    window: list[str]
    status: str
    started_at: str
    finished_at: str | None = None
    inputs: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


class Ledger:
    """``ledger.json``: every batch attempt and the latest outcome of every document, keyed by output stem."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.batches: dict[str, BatchRecord] = {}
        self.documents: dict[str, DocumentRecord] = {}

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        """Read the ledger, or start an empty one."""
        ledger = cls(path)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            ledger.batches = {k: BatchRecord(**v) for k, v in data.get("batches", {}).items()}
            ledger.documents = {k: DocumentRecord(**v) for k, v in data.get("documents", {}).items()}
        return ledger

    def save(self) -> None:
        """Write atomically."""
        data = {
            "version": LEDGER_VERSION,
            "updated_at": now(),
            "batches": {k: asdict(v) for k, v in sorted(self.batches.items())},
            "documents": {k: asdict(v) for k, v in sorted(self.documents.items())},
        }
        write_json(self.path, data)

    def record_batch(self, batch: BatchRecord, documents: list[DocumentRecord]) -> None:
        """Replace everything a previous run of this batch recorded (protected documents are kept)."""
        for stem in [s for s, d in self.documents.items() if d.batch == batch.batch_id and d.status != "protected"]:
            del self.documents[stem]
        self.batches[batch.batch_id] = batch
        for record in documents:
            self.documents[record.stem] = record

    def compiled_fingerprints(self, exclude_batch: str) -> dict[str, str]:
        """Fingerprint -> stem for documents compiled by other batches."""
        return {
            d.fingerprint: d.stem
            for d in self.documents.values()
            if d.status in {"compiled", "protected"} and d.fingerprint and d.batch != exclude_batch
        }

    def owner(self, stem: str) -> DocumentRecord | None:
        """The record that owns an output stem."""
        return self.documents.get(stem)


def write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (temp file then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def now() -> str:
    """Local time, second precision."""
    return datetime.now().replace(microsecond=0).isoformat()
