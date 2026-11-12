"""Sell-side research corpus ingestion: MCP chunk dumps -> cleaned, logged documents in ``pdfs/``.

Per batch (one document date): validate the dump, keep documents with an FX/Rates chunk, skip corrupted ones
(``gate``), strip boilerplate by email section (``cleaning``), standardise formatting (``normalise``), write
``pdfs/<stem>.txt`` plus ``manifests/extract_<date>.json`` / ``skipped_<date>.json``, and record it in ``ledger.json``.
"""

from ...parsing.core.document import CorpusDocument, FrontMatter
from .batch import BatchRunner, BatchSummary
from .chunks import ChunkDump, DumpError, ResearchDocument
from .compiler import Compilation, DocumentCompiler
from .ledger import CorpusPaths, Ledger

__all__ = [
    "BatchRunner",
    "BatchSummary",
    "ChunkDump",
    "Compilation",
    "CorpusDocument",
    "CorpusPaths",
    "DocumentCompiler",
    "DumpError",
    "FrontMatter",
    "Ledger",
    "ResearchDocument",
]
