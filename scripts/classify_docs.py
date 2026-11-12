"""Classify every .txt in a folder against taxonomy.yaml and write CSV + HTML reports.

Usage: python scripts/classify_docs.py [--input pdfs] [--output output] [--model sonnet] [--workers 4]
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from incolor.classification import (
    ClaudeClassifier,
    CsvReporter,
    EntityReporter,
    HtmlReporter,
    Pipeline,
    PipelineSummary,
    Taxonomy,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    """Command-line options."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=ROOT / "pdfs", help="folder with .txt files")
    p.add_argument("--output", type=Path, default=ROOT / "output", help="folder for CSV/HTML/cache/log")
    p.add_argument("--taxonomy", type=Path, default=ROOT / "taxonomy.yaml")
    p.add_argument("--model", default="sonnet", help="Claude model alias or id")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--head-chars", type=int, default=6000, help="characters read first; full text only if low confidence"
    )
    p.add_argument("--limit", type=int, default=None, help="only the first N files (smoke test)")
    return p.parse_args()


def print_summary(summary: PipelineSummary, total: int) -> None:
    """Files processed, failures, label distribution and the 5 most ambiguous documents."""
    results = summary.results
    print(f"\nFiles processed: {len(results)} of {total} ({summary.cached} from cache)")
    print(f"Failures: {len(summary.failures)}")
    for name, reason in summary.failures.items():
        print(f"  - {name}: {reason}")
    flagged = sum(r.needs_review for r in results)
    print(f"Needs review: {flagged} ({100 * flagged / max(1, len(results)):.0f}%)")

    print("\nLabel distribution (primary category > subcategory):")
    by_category = Counter(r.classification.primary.category for r in results)
    by_label = Counter(str(r.classification.primary) for r in results)
    for category, n in by_category.most_common():
        print(f"  {category}: {n}")
        for label, m in sorted(by_label.items(), key=lambda kv: -kv[1]):
            if label.startswith(f"{category} > "):
                print(f"      {label.split(' > ', 1)[1]}: {m}")

    print("\n5 most ambiguous documents (close runner-up first, then lowest confidence):")
    ranked = sorted(results, key=lambda r: (not r.classification.runner_up_close, r.classification.confidence))
    for r in ranked[:5]:
        c = r.classification
        print(f"  {c.confidence:.2f} {r.file}\n      {c.primary}  vs  {c.runner_up}: {c.runner_up_reason}")


def main() -> int:
    """Run the pipeline; exit code 1 if any file failed."""
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(args.output / "pipeline.log", encoding="utf-8")],
    )

    from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

    taxonomy = Taxonomy.load(args.taxonomy)
    classifier = ClaudeClassifier(
        taxonomy, ClaudeAgentBackend(args.model), model=args.model, head_chars=args.head_chars
    )
    pipeline = Pipeline(
        classifier,
        reporters=[
            CsvReporter(args.output / "classifications.csv"),
            EntityReporter(args.output / "entities.csv"),
            HtmlReporter(args.output / "review.html", taxonomy),
        ],
        cache_dir=args.output / "cache",
        failures_path=args.output / "failures.json",
        workers=args.workers,
    )
    summary = pipeline.run(args.input, limit=args.limit)
    print_summary(summary, len(summary.results) + len(summary.failures))
    return 1 if summary.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
