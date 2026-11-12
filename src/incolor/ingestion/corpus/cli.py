"""Command line: ``python -m incolor.ingestion.corpus <command>``.

Commands:
    batch DUMP...        compile saved browse_metadata results (one batch per document date)
    validate [DIR]       check compiled files; exit 1 on errors
    status               batches, coverage and document outcomes from the ledger
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ...parsing.corpus.validate import FormatValidator
from .batch import BatchRunner, BatchSummary
from .chunks import DumpError
from .ledger import CorpusPaths, Ledger

EXIT_OK = 0
EXIT_FAILURE = 1


def build_parser() -> argparse.ArgumentParser:
    """Argument parser with one sub-command per pipeline action."""
    parser = argparse.ArgumentParser(
        prog="python -m incolor.ingestion.corpus", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--root", type=Path, default=Path("research_chunks"), help="ledger + manifests folder")
    parser.add_argument("--pdfs", type=Path, default=Path("pdfs"), help="compiled documents folder")
    commands = parser.add_subparsers(dest="command", required=True)

    batch = commands.add_parser("batch", help="compile saved browse_metadata dumps")
    batch.add_argument("dumps", nargs="+", type=Path)
    batch.add_argument("--keep-inputs", action="store_true", help="do not delete dumps under --root afterwards")

    check = commands.add_parser("validate", help="check compiled files")
    check.add_argument("directory", nargs="?", type=Path)

    commands.add_parser("status", help="summarise the ledger")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the exit code."""
    args = build_parser().parse_args(argv)
    paths = CorpusPaths(args.root, args.pdfs)
    if args.command == "batch":
        try:
            summaries = BatchRunner(paths).run_dumps(args.dumps, keep_inputs=args.keep_inputs)
        except DumpError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_FAILURE
        _print_summaries(summaries)
    elif args.command == "validate":
        return _validate(args.directory or paths.pdfs)
    else:
        _status(Ledger.load(paths.ledger))
    return EXIT_OK


def _print_summaries(summaries: list[BatchSummary]) -> None:
    totals: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    for s in summaries:
        totals.update(s.counts)
        codes.update(s.skipped_by_code)
        print(
            f"{s.batch_id}: {s.counts.get('in_scope', 0)} in scope, {s.counts.get('compiled', 0)} compiled, "
            f"{s.counts.get('skipped', 0)} skipped, {s.counts.get('duplicate', 0)} duplicate"
        )
    print(f"\n{len(summaries)} batches: " + ", ".join(f"{k} {v}" for k, v in totals.items()))
    if codes:
        print("skip codes: " + ", ".join(f"{k} {v}" for k, v in codes.most_common()))


def _validate(directory: Path) -> int:
    validator = FormatValidator()
    errors: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    files = sorted(directory.glob("*.txt"))
    for path in files:
        errs, warns = validator.validate(path.read_text(encoding="utf-8"))
        errors.update(e.code for e in errs)
        warnings.update(w.code for w in warns)
        for e in errs:
            print(f"ERROR {path.name}: {e.code}: {e.detail}")
    print(f"{len(files)} files: {sum(errors.values())} errors, {sum(warnings.values())} warnings")
    for code, n in warnings.most_common():
        print(f"  warning {code}: {n}")
    return EXIT_FAILURE if errors else EXIT_OK


def _status(ledger: Ledger) -> None:
    statuses = Counter(d.status for d in ledger.documents.values())
    codes = Counter(code for d in ledger.documents.values() for code in d.codes)
    failed = [b.batch_id for b in ledger.batches.values() if b.status != "compiled"]
    dates = sorted(b.window[0] for b in ledger.batches.values() if b.status == "compiled" and b.window)
    print(f"{len(ledger.batches)} batches ({len(failed)} not compiled: {', '.join(failed) or 'none'})")
    if dates:
        print(f"dates covered: {dates[0]} .. {dates[-1]} ({len(dates)} days with data)")
    print("documents: " + ", ".join(f"{k} {v}" for k, v in statuses.most_common()))
    print("skip codes: " + ", ".join(f"{k} {v}" for k, v in codes.most_common()))
    warned = Counter(w for d in ledger.documents.values() for w in d.warnings)
    print("compiled with warnings: " + (", ".join(f"{k} {v}" for k, v in warned.most_common()) or "none"))


if __name__ == "__main__":
    raise SystemExit(main())
