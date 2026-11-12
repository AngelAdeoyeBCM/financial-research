"""Run every research sample through the argument-map pipeline with several Claude models and compare the maps.

Each sample starts with a ``Key: value`` metadata header (Document, Date, Source, ...) followed by a blank line. The
header is removed before the text reaches the model and is kept in ``summary.json`` instead.

Layout under ``--out`` (default ``outputs/samples_v12``)::

    inputs/<doc>.txt                  sample body without the header: exactly what the model receives
    inputs/<doc>.meta.json            the removed header
    <doc>/<model>/argument_map.yaml   or argument_map.invalid.yaml when errors remain
    <doc>/<model>/issues.json, raw_attempt<n>.txt, taxonomy_rules.yaml, diagram.mmd, summary.json
    <doc>/models_list.mmd             the models' maps side by side in list view

Runs that already produced a valid map are skipped unless ``--force`` is given, so an interrupted batch resumes and
failed runs are retried.
Needs ANTHROPIC_API_KEY and the Claude Code CLI.
Exit codes: 0 = every run produced a valid map; 1 = setup failure; 2 = some runs failed or remain invalid.
"""

import argparse
import dataclasses
import json
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incolor.argumentation.backends import BackendUnavailableError, get_backend
from incolor.argumentation.diagram import ArgumentMapDiagram, side_by_side_mermaid
from incolor.argumentation.grounding import coverage
from incolor.argumentation.ingest import InputError, normalise
from incolor.argumentation.pipeline import PipelineConfig, apply_overrides, load_config, run_pipeline
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.taxonomy import PACKAGE_DIR, load_taxonomy
from incolor.argumentation.validate import argument_edges, has_errors, scenario_edges
from incolor.argumentation.writer import argument_map_to_dict, write_argument_map, write_issues

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INCOMPLETE = 2

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "samples"
DEFAULT_OUT = ROOT / "outputs" / "samples_v12"
DEFAULT_MODELS = ("haiku", "opus")
DEFAULT_TAXONOMY = PACKAGE_DIR / "prompts" / "taxonomy_v12.yaml"
COMPARISON_NAME = "models_list.mmd"
HEADER_LINE = re.compile(r"^(?P<key>[A-Z][\w ()/]*?):\s*(?P<value>.*)$")
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


@dataclass(frozen=True)
class Job:
    """One (document, model) run."""

    doc: str
    model: str
    input_path: Path
    run_dir: Path
    config: PipelineConfig
    source_metadata: dict[str, str]


def split_header(text: str) -> tuple[dict[str, str], str]:
    """Return the ``Key: value`` header that precedes the first blank line, and the body after it.

    Text that does not start with a ``Document:`` header block is returned unchanged with an empty header.
    """
    head, sep, body = text.partition("\n\n")
    lines = head.splitlines()
    matches = [HEADER_LINE.match(line) for line in lines]
    if not sep or not lines or not lines[0].startswith("Document:") or not all(matches):
        return {}, text
    return {m["key"]: m["value"] for m in matches if m}, body.lstrip("\n")


def prepare_inputs(
    samples_dir: Path, out_dir: Path, only: str | None, limit: int | None = None
) -> dict[str, tuple[Path, dict[str, str]]]:
    """Write each sample body without its header to ``out_dir/inputs`` and return ``{doc: (path, header)}``.

    Samples are taken in file-name order; ``limit`` keeps the first N after the ``only`` filter.
    """
    inputs_dir = out_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    samples = [s for s in sorted(samples_dir.glob("*.txt")) if not only or only.lower() in s.stem.lower()]
    prepared = {}
    for sample in samples[:limit]:
        header, body = split_header(sample.read_text(encoding="utf-8-sig"))
        if not header:
            print(f"warning: no metadata header found in {sample.name}; sending the whole file", file=sys.stderr)
        input_path = inputs_dir / sample.name
        input_path.write_text(body, encoding="utf-8")
        (inputs_dir / f"{sample.stem}.meta.json").write_text(
            json.dumps(header, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        prepared[sample.stem] = (input_path, header)
    return prepared


def model_config(base: PipelineConfig, model: str, example: Path | None, taxonomy: Path) -> PipelineConfig:
    """Return the pipeline config for one Claude model and taxonomy, with or without a few-shot example."""
    config = apply_overrides(base, backend="claude", model=model, no_example=example is None, taxonomy=taxonomy)
    return config if example is None else dataclasses.replace(config, few_shot_example=example)


def longest_chain(edges: Sequence[tuple[str, str, str]]) -> int:
    """Return the number of arguments on the longest path of argument links; 0 when there are no links."""
    graph: dict[str, set[str]] = defaultdict(set)
    for source, _, target in edges:
        graph[source].add(target)

    def depth(node: str, path: frozenset[str]) -> int:
        # Invalid maps can contain cycles; the path guard stops at a repeated argument.
        if node in path:
            return 0
        return 1 + max((depth(n, path | {node}) for n in graph[node]), default=0)

    return max((depth(node, frozenset()) for node in list(graph)), default=0)


def map_stats(map_: ArgumentMap, source: str | None = None, must_keep: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the structural counts recorded in ``summary.json``; with ``source``, also the sentence coverage."""
    edges = argument_edges(map_)
    linked = {source for source, _, _ in edges} | {target for _, _, target in edges}
    kinds = Counter(s.proposition_kind for s in map_.statements if s.proposition_kind)
    subkinds = Counter(f"{s.claim_type}:{value}" for s in map_.statements for value in s.subkinds)
    stats = {
        "arguments": len(map_.arguments),
        "statements": len(map_.statements),
        "evidence": len(map_.evidence),
        "exclusions": len(map_.exclusions),
        "scenarios": len(map_.scenarios),
        "edges": len(edges),
        "scenario_links": len(scenario_edges(map_)),
        "isolated": sum(argument.id not in linked for argument in map_.arguments),
        "max_chain": longest_chain(edges),
        "types": dict(Counter(s.claim_type for s in map_.statements)),
        "proposition_kinds": dict(kinds),
        "subkinds": dict(subkinds),
        "modalities": dict(Counter(s.modality for s in map_.statements)),
    }
    if source is not None:
        stats["coverage"] = coverage(map_, source, must_keep or {}).as_dict()
    return stats


def usage_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Sum cost and token usage over the backend calls of one run (one call per attempt)."""
    costs = [r["cost_usd"] for r in records if r.get("cost_usd") is not None]
    tokens = {key: sum((r.get("usage") or {}).get(key) or 0 for r in records) for key in TOKEN_KEYS}
    return {
        "cost_usd": round(sum(costs), 4) if costs else None,
        "api_seconds": round(sum(r.get("duration_ms") or 0 for r in records) / 1000, 1),
        **tokens,
        "resolved_models": sorted({m for r in records for m in r.get("models", [])}),
    }


def run_job(job: Job, taxonomy_version: str, force: bool) -> dict[str, Any]:
    """Run one document with one model, write its outputs and return its summary."""
    summary_path = job.run_dir / "summary.json"
    if summary_path.exists() and not force:
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
        if previous.get("ok"):
            return {**previous, "skipped": True}
    if job.run_dir.exists():
        shutil.rmtree(job.run_dir)
    job.run_dir.mkdir(parents=True)

    summary: dict[str, Any] = {
        "doc": job.doc,
        "model": job.model,
        "example": job.config.few_shot_example.name if job.config.few_shot_example else None,
        "taxonomy_version": taxonomy_version,
        "source_metadata": job.source_metadata,
    }
    start = time.perf_counter()
    backend = None
    try:
        backend = get_backend(job.config)
        result = run_pipeline(job.input_path, job.config, backend=backend)
    except (InputError, BackendUnavailableError, ValueError, OSError) as exc:
        summary.update(ok=False, error=str(exc), seconds=round(time.perf_counter() - start, 1))
        summary.update(usage_summary(getattr(backend, "usage", [])))
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return summary

    errors = has_errors(result.issues)
    for n, raw in enumerate(result.raw_outputs, start=1):
        (job.run_dir / f"raw_attempt{n}.txt").write_text(raw, encoding="utf-8")
    shutil.copyfile(job.config.taxonomy, job.run_dir / "taxonomy_rules.yaml")
    if result.issues:
        write_issues(result.issues, job.run_dir / "issues.json")
    if result.map is not None:
        taxonomy = load_taxonomy(job.config.taxonomy)
        roles = taxonomy.argument_roles
        name = "argument_map.invalid.yaml" if errors else "argument_map.yaml"
        write_argument_map(result.map, job.run_dir / name, roles)
        source = normalise(job.input_path.read_text(encoding="utf-8"), job.config.furniture_patterns)
        summary.update(map_stats(result.map, source, taxonomy.must_keep_patterns))
        if not errors:
            diagram = ArgumentMapDiagram(argument_map_to_dict(result.map, roles), show_observations=True)
            diagram.save(job.run_dir / "diagram.mmd")

    summary.update(
        ok=result.ok,
        attempts=result.attempts,
        errors=sum(issue.severity == "error" for issue in result.issues),
        warnings=sum(issue.severity != "error" for issue in result.issues),
        issue_codes=dict(Counter(issue.code for issue in result.issues)),
        seconds=round(time.perf_counter() - start, 1),
        src_chars=len(job.input_path.read_text(encoding="utf-8")),
        **usage_summary(getattr(backend, "usage", [])),
    )
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def write_comparison(doc_dir: Path, models: Sequence[str]) -> Path | None:
    """Write the valid maps of ``doc_dir`` side by side in list view; return the path, or None if none are valid."""
    diagrams, titles = [], []
    for model in models:
        path = doc_dir / model / "argument_map.yaml"
        if path.is_file():
            diagrams.append(ArgumentMapDiagram.from_yaml(path, view="list", show_observations=True))
            titles.append(model)
    if not diagrams:
        return None
    out = doc_dir / COMPARISON_NAME
    out.write_text(side_by_side_mermaid(diagrams, titles), encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES, help="Folder of sample .txt files.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder.")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS), help="Claude model names or aliases.")
    parser.add_argument("--workers", type=int, default=6, help="Runs in parallel; lower it if rate limits are hit.")
    parser.add_argument("--example", type=Path, help="Few-shot example map; default is no example.")
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY, help="Taxonomy YAML file.")
    parser.add_argument("--only", help="Only samples whose file name contains this text (case-insensitive).")
    parser.add_argument("--limit", type=int, help="Only the first N samples in file-name order.")
    parser.add_argument("--force", action="store_true", help="Re-run runs that already produced a valid map.")
    parser.add_argument("--prepare-only", action="store_true", help="Only write the header-free inputs.")
    parser.add_argument("--diagrams-only", action="store_true", help="Only redraw the side-by-side diagrams.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Prepare inputs, run every (sample, model) pair, then draw the side-by-side diagrams."""
    args = build_parser().parse_args(argv)
    prepared = prepare_inputs(args.samples, args.out, args.only, args.limit)
    if not prepared:
        print(f"No samples found in {args.samples}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"{len(prepared)} samples prepared in {args.out / 'inputs'}")
    if args.prepare_only:
        return EXIT_OK

    summaries: list[dict[str, Any]] = []
    if not args.diagrams_only:
        base = load_config()
        configs = {model: model_config(base, model, args.example, args.taxonomy) for model in args.models}
        try:
            get_backend(configs[args.models[0]])
        except BackendUnavailableError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_FAILURE
        taxonomy_version = load_taxonomy(args.taxonomy).version
        jobs = [
            Job(doc, model, input_path, args.out / doc / model, configs[model], header)
            for doc, (input_path, header) in prepared.items()
            for model in args.models
        ]
        print(f"{len(jobs)} runs, {args.workers} in parallel, taxonomy v{taxonomy_version}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_job, job, taxonomy_version, args.force): job for job in jobs}
            for done, future in enumerate(as_completed(futures), start=1):
                job, summary = futures[future], future.result()
                summaries.append(summary)
                status = "skipped" if summary.get("skipped") else ("ok" if summary.get("ok") else "FAILED")
                detail = summary.get("error") or (
                    f"{summary.get('statements', 0)} stmts, {summary.get('attempts')} att, "
                    f"{summary.get('seconds')}s, ${summary.get('cost_usd')}"
                )
                print(f"[{done}/{len(jobs)}] {status:<7} {job.model:<6} {job.doc[:60]}  {detail}")

    for doc in prepared:
        path = write_comparison(args.out / doc, args.models)
        if path is None:
            print(f"no valid maps for {doc}; comparison diagram skipped", file=sys.stderr)

    if args.diagrams_only:
        return EXIT_OK
    failed = [s for s in summaries if not s.get("ok")]
    cost = sum(s.get("cost_usd") or 0 for s in summaries if not s.get("skipped"))
    print(f"\n{len(summaries) - len(failed)}/{len(summaries)} runs valid; this batch cost ${cost:.2f}")
    return EXIT_INCOMPLETE if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
