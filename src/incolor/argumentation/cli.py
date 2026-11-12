"""Command-line entry point: extract an argument map from one document and write it to YAML.

Exit codes: 0 = written with no errors; 1 = input, configuration or backend failure; 2 = errors remain (the
invalid map and issue list are still written beside the requested output).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .backends import BackendUnavailableError
from .diagram import ArgumentMapDiagram
from .ingest import InputError
from .pipeline import BACKEND_NAMES, DEFAULT_CONFIG_PATH, apply_overrides, load_config, run_pipeline
from .validate import has_errors
from .writer import argument_map_to_dict, write_argument_map, write_issues

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INVALID = 2


def _sibling(output: Path, tag: str) -> Path:
    """Return ``output`` with ``tag`` added after its stem, e.g. ``x.yaml`` gives ``x.invalid.yaml``."""
    return output.with_name(f"{output.stem}.{tag}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description="Extract a Phase 1 argument map from a document.")
    parser.add_argument("input", type=Path, help="Source document (.txt, .json or .pdf).")
    parser.add_argument("-o", "--output", type=Path, help="Output YAML path (default: <input stem>_argument_map.yaml).")
    parser.add_argument("--backend", choices=BACKEND_NAMES, help="Model backend; overrides the config file.")
    parser.add_argument("--model", help="Model name for the selected backend; overrides the config file.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Pipeline config file.")
    parser.add_argument("--diagram", type=Path, help="Also write a Mermaid diagram to this path (written as .mmd).")
    parser.add_argument("--no-example", action="store_true", help="Do not include the few-shot example in the prompt.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pipeline from the command line and return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        config = apply_overrides(
            load_config(args.config), backend=args.backend, model=args.model, no_example=args.no_example
        )
        result = run_pipeline(args.input, config)
    except (InputError, BackendUnavailableError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    output = args.output or args.input.with_name(f"{args.input.stem}_argument_map.yaml")
    errors = has_errors(result.issues)
    if result.map is not None:
        target = _sibling(output, "invalid.yaml") if errors else output
        write_argument_map(result.map, target)
        print(f"wrote {target}")
        # The diagram assumes valid IDs and taxonomy values, so skip it for invalid maps.
        if args.diagram and not errors:
            diagram_path = ArgumentMapDiagram(argument_map_to_dict(result.map)).save(args.diagram)
            print(f"wrote {diagram_path}")
    if result.issues:
        issues_path = _sibling(output, "issues.json")
        write_issues(result.issues, issues_path)
        print(f"wrote {issues_path}")

    error_count = sum(issue.severity == "error" for issue in result.issues)
    warning_count = len(result.issues) - error_count
    print(f"attempts: {result.attempts}, errors: {error_count}, warnings: {warning_count}")
    return EXIT_INVALID if errors else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
