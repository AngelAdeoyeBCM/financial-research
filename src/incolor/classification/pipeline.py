"""Pipeline: concurrent, resumable classification with per-file failure logging."""

import hashlib
import json
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .classifier import Classifier
from .models import Document, DocumentResult
from .reporters import Reporter

log = logging.getLogger(__name__)


class ResultCache:
    """JSON files keyed by document hash plus classifier fingerprint, so edits to a file or the taxonomy re-run."""

    def __init__(self, directory: Path, fingerprint: str) -> None:
        self._dir = directory
        self._fingerprint = fingerprint
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, document: Document) -> Path:
        key = hashlib.sha256(f"{document.sha256}|{self._fingerprint}".encode()).hexdigest()[:24]
        return self._dir / f"{key}.json"

    def get(self, document: Document) -> DocumentResult | None:
        """Return the cached result, or None if missing or unreadable."""
        path = self._path(document)
        if not path.is_file():
            return None
        try:
            return DocumentResult.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("Ignoring unreadable cache entry %s", path.name)
            return None

    def put(self, document: Document, result: DocumentResult) -> None:
        """Write atomically so an interrupted run never leaves a half-written entry."""
        path = self._path(document)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result.to_json(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


@dataclass
class PipelineSummary:
    """Outcome of one run."""

    results: list[DocumentResult] = field(default_factory=list)
    cached: int = 0
    failures: dict[str, str] = field(default_factory=dict)


class Pipeline:
    """Classify every file in a folder, then hand the results to the reporters."""

    def __init__(
        self,
        classifier: Classifier,
        reporters: Sequence[Reporter],
        cache_dir: Path,
        failures_path: Path,
        workers: int = 4,
    ) -> None:
        self._classifier = classifier
        self._reporters = reporters
        self._cache = ResultCache(cache_dir, classifier.fingerprint)
        self._failures_path = failures_path
        self._workers = workers

    def run(self, input_dir: Path, pattern: str = "*.txt", limit: int | None = None) -> PipelineSummary:
        """Process matching files; failures are logged and skipped rather than raised."""
        summary = PipelineSummary()
        files = sorted(input_dir.glob(pattern))[:limit]
        log.info("Found %d files in %s", len(files), input_dir)

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(self._process, path): path for path in files}
            try:
                for done, future in enumerate(as_completed(futures), start=1):
                    path = futures[future]
                    try:
                        result, was_cached = future.result()
                    except Exception as exc:
                        summary.failures[path.name] = f"{type(exc).__name__}: {exc}"
                        log.error("[%d/%d] FAILED %s: %s", done, len(files), path.name, exc)
                        continue
                    summary.results.append(result)
                    summary.cached += was_cached
                    log.info(
                        "[%d/%d] %s %s (%.2f)",
                        done,
                        len(files),
                        "cached" if was_cached else "done",
                        path.name,
                        result.classification.confidence,
                    )
            except KeyboardInterrupt:
                pool.shutdown(wait=False, cancel_futures=True)
                log.warning("Interrupted; finished files are cached and will be skipped next run")
                raise

        self._write_failures(summary.failures)
        for reporter in self._reporters:
            log.info("Wrote %s", reporter.write(summary.results))
        return summary

    def _process(self, path: Path) -> tuple[DocumentResult, bool]:
        document = Document.load(path)
        if (hit := self._cache.get(document)) is not None:
            return hit, True
        result = self._classifier.classify(document)
        self._cache.put(document, result)
        return result, False

    def _write_failures(self, failures: dict[str, str]) -> None:
        self._failures_path.parent.mkdir(parents=True, exist_ok=True)
        self._failures_path.write_text(json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8")
