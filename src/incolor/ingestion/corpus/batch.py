"""Batch runner: one batch per document date, from validated dumps to ``pdfs/``, manifests and the ledger."""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...parsing.core.document import CorpusDocument
from ...parsing.corpus.steps import Vocabulary
from .chunks import ChunkDump, DocumentAssembler, ResearchDocument, safe_stem
from .compiler import Compilation, DocumentCompiler
from .gate import Issue
from .ledger import BatchRecord, CorpusPaths, DocumentRecord, Ledger, now, write_json
from .selection import AssetClassFilter


@dataclass
class BatchSummary:
    """What one batch did."""

    batch_id: str
    counts: dict[str, int]
    skipped_by_code: dict[str, int]
    written: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)


class StemAllocator:
    """Output stems: the safe document name, plus ``__<date>`` when another issue of the publication owns it."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def allocate(self, docs: Sequence[ResearchDocument]) -> None:
        """Set ``stem`` on every document that has none."""
        taken: dict[str, tuple[str, str]] = {}
        for doc in docs:
            if doc.stem:
                taken[doc.stem.lower()] = (doc.name, doc.date)
        for doc in docs:
            if doc.stem:
                continue
            base = safe_stem(doc.name)
            for stem in (base, f"{base}__{doc.date}", f"{base}__{_short_hash(doc.name + doc.date)}"):
                if self._free(stem, doc, taken):
                    doc.stem = stem
                    break
            taken[doc.stem.lower()] = (doc.name, doc.date)

    def _free(self, stem: str, doc: ResearchDocument, taken: dict[str, tuple[str, str]]) -> bool:
        identity = (doc.name, doc.date)
        owner = self.ledger.owner(stem)
        return taken.get(stem.lower(), identity) == identity and (
            owner is None or (owner.document, owner.date) == identity
        )


class BatchRunner:
    """Compiles batches and records every outcome in the manifests and the ledger."""

    def __init__(
        self, paths: CorpusPaths, compiler: DocumentCompiler | None = None, selector: AssetClassFilter | None = None
    ) -> None:
        self.paths = paths
        self.compiler = compiler or DocumentCompiler()
        self.selector = selector or AssetClassFilter()
        self.ledger = Ledger.load(paths.ledger)

    def run_dumps(self, dump_paths: Sequence[Path], keep_inputs: bool = False) -> list[BatchSummary]:
        """Validate every dump first, then run one batch per document date; delete inputs under ``root`` after.

        Raises:
            DumpError: If any dump is truncated or unreadable (nothing is written).
        """
        dumps = [ChunkDump.load(path) for path in dump_paths]
        assembler = DocumentAssembler()
        for dump in dumps:
            assembler.add(dump.records)
        by_date: dict[str, list[ResearchDocument]] = defaultdict(list)
        for doc in assembler.documents():
            by_date[doc.date].append(doc)
        summaries = []
        for date in sorted(by_date):
            inputs = [
                {**dump.summary(), "records_for_batch": n}
                for dump in dumps
                if (n := sum((r.get("DocumentDate") or "") == date for r in dump.records))
            ]
            extra = {"duplicate_chunks": assembler.duplicates, "unparsed_chunks": len(assembler.unparsed)}
            summaries.append(self.run_batch(date or "undated", [date, date], by_date[date], inputs, extra))
        if not keep_inputs:
            self._delete_inputs(dump_paths)
        return summaries

    def run_batch(
        self,
        batch_id: str,
        window: list[str],
        docs: list[ResearchDocument],
        inputs: list[dict[str, Any]],
        extra_counts: dict[str, int] | None = None,
    ) -> BatchSummary:
        """Compile one batch; a failure is recorded in the ledger before it is re-raised."""
        batch = BatchRecord(batch_id, window, "running", now(), inputs=inputs)
        try:
            return self._run(batch, docs, extra_counts or {})
        except Exception as exc:
            batch.status, batch.finished_at, batch.error = "failed", now(), f"{type(exc).__name__}: {exc}"
            self.ledger.batches[batch_id] = batch
            self.ledger.save()
            raise

    def _run(self, batch: BatchRecord, docs: list[ResearchDocument], extra: dict[str, int]) -> BatchSummary:
        in_scope = [d for d in docs if self.selector.matches(d)]
        StemAllocator(self.ledger).allocate(in_scope)
        vocabulary = Vocabulary.from_texts([d.merged_text() for d in in_scope] + self._existing_contents())
        results: list[Compilation] = []
        for doc in in_scope:
            owner = self.ledger.owner(doc.stem)
            if owner and owner.status == "protected":
                results.append(Compilation(doc, "protected"))
            else:
                results.append(self.compiler.compile(doc, vocabulary))
        self._mark_duplicates(batch.batch_id, results)

        summary = BatchSummary(batch.batch_id, {}, {})
        self.paths.pdfs.mkdir(parents=True, exist_ok=True)
        compiled_stems = set()
        for result in results:
            if result.status == "compiled" and result.rendered:
                path = self.paths.pdfs / f"{result.doc.stem}.txt"
                path.write_text(result.rendered, encoding="utf-8", newline="\n")
                summary.written.append(path)
                compiled_stems.add(result.doc.stem)
        for stem, record in list(self.ledger.documents.items()):
            if record.batch == batch.batch_id and record.status == "compiled" and stem not in compiled_stems:
                stale = self.paths.pdfs / f"{stem}.txt"
                if stale.is_file():
                    stale.unlink()
                    summary.removed.append(stale)

        statuses = Counter(r.status for r in results)
        summary.skipped_by_code = dict(
            Counter(i.code for r in results if r.status != "compiled" for i in r.issues).most_common()
        )
        summary.counts = {
            "documents": len(docs),
            "in_scope": len(in_scope),
            "out_of_scope": len(docs) - len(in_scope),
            **{status: statuses.get(status, 0) for status in ("compiled", "skipped", "duplicate", "protected")},
            "compiled_with_warnings": sum(1 for r in results if r.status == "compiled" and r.issues),
            "stripped_items": sum(len(r.ignored) for r in results),
            "edits": sum(len(r.edits) for r in results),
            **extra,
        }
        self._write_manifests(batch, results, summary)
        batch.status, batch.finished_at, batch.counts = "compiled", now(), summary.counts
        self.ledger.record_batch(batch, [self._record(batch.batch_id, r) for r in results])
        self.ledger.save()
        return summary

    def _mark_duplicates(self, batch_id: str, results: list[Compilation]) -> None:
        """Keep one document per text: earlier batches win, then the copy whose file name is in its text."""
        elsewhere = self.ledger.compiled_fingerprints(exclude_batch=batch_id)
        groups: dict[str, list[Compilation]] = defaultdict(list)
        for result in results:
            if result.status == "compiled" and result.fingerprint:
                groups[result.fingerprint].append(result)
        for fingerprint, group in groups.items():
            keeper = (
                None if fingerprint in elsewhere else max(group, key=lambda r: (r.title_in_text, len(r.doc.chunks)))
            )
            for result in group:
                if result is keeper:
                    continue
                original = elsewhere.get(fingerprint) or (keeper.doc.stem if keeper else "")
                result.status, result.rendered = "duplicate", None
                result.issues = [Issue("DUPLICATE_CONTENT", f"same text as {original}")]

    def _write_manifests(self, batch: BatchRecord, results: list[Compilation], summary: BatchSummary) -> None:
        header = {
            "batch_id": batch.batch_id,
            "window": batch.window,
            "generated_at": now(),
            "asset_classes": sorted(self.selector.classes),
            "inputs": batch.inputs,
            "counts": summary.counts,
        }
        extract = [
            {
                **r.doc.manifest_entry(),
                "status": r.status,
                "output": (self.paths.pdfs / f"{r.doc.stem}.txt").as_posix() if r.status == "compiled" else None,
                "asset_class_share": round(self.selector.share(r.doc), 3),
                "fingerprint": r.fingerprint,
                "gate_warnings": [vars(i) for i in r.issues] if r.status == "compiled" else [],
                **(r.log() if r.status == "compiled" else {}),
            }
            for r in results
        ]
        skipped = [
            {
                **r.doc.manifest_entry(),
                "status": r.status,
                "missing_indices": r.doc.missing_indices,
                "issues": [vars(i) for i in r.issues],
            }
            for r in results
            if r.status in {"skipped", "duplicate"}
        ]
        write_json(self.paths.extract_manifest(batch.batch_id), {**header, "documents": extract})
        write_json(
            self.paths.skip_manifest(batch.batch_id),
            {**header, "skipped_by_code": summary.skipped_by_code, "documents": skipped},
        )

    def _record(self, batch_id: str, result: Compilation) -> DocumentRecord:
        doc = result.doc
        if result.status == "protected":
            return self.ledger.documents[doc.stem]
        compiled = result.status == "compiled"
        reasons = sorted({i.code for i in result.issues})
        return DocumentRecord(
            stem=doc.stem,
            document=doc.name,
            date=doc.date,
            publisher=doc.publisher,
            batch=batch_id,
            status=result.status,
            codes=[] if compiled else reasons,
            warnings=reasons if compiled else [],
            fingerprint=result.fingerprint,
            output=(self.paths.pdfs / f"{doc.stem}.txt").as_posix() if compiled else None,
        )

    def _existing_contents(self) -> list[str]:
        contents = []
        for path in sorted(self.paths.pdfs.glob("*.txt")) if self.paths.pdfs.is_dir() else []:
            try:
                contents.append(CorpusDocument.load(path).content)
            except ValueError:
                continue
        return contents

    def _delete_inputs(self, dump_paths: Sequence[Path]) -> None:
        root = self.paths.root.resolve()
        for path in dump_paths:
            resolved = path.resolve()
            if resolved.is_relative_to(root) and resolved.is_file():
                resolved.unlink()
                parent = resolved.parent
                if parent != root and parent.is_relative_to(root) and not any(parent.iterdir()):
                    parent.rmdir()


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
