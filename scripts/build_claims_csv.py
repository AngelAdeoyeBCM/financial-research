"""Flatten every valid argument map (model runs under ``outputs/`` and the gold fixtures) into statement-level CSVs.

Writes, under ``--out`` (default ``outputs/claims_analysis``):

* ``claims_all.csv``: one row per statement, with run, model and document metadata, evidence spans, argument roles
  and summaries, and alignment columns (``gold_match_id``, ``cluster_id``) for comparing the same statement across runs.
* ``claims_exclusions.csv``: one row per excluded source sentence, with the same run metadata.

Maps that failed validation (``argument_map.invalid.yaml``) are skipped. A separate batch, such as the sample runs, is
built by pointing ``--runs-root`` and ``--texts-dir`` at it, e.g.::

    build_claims_csv.py --runs-root outputs/samples_v08 --texts-dir outputs/samples_v08/inputs --no-gold \
        --pivot-model opus --out outputs/samples_v08/claims_analysis

Exit codes: 0 = written; 1 = input failure.
"""

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incolor.argumentation.evaluate import match_statements
from incolor.argumentation.schema import ArgumentMap
from incolor.argumentation.writer import load_argument_map

EXIT_OK = 0
EXIT_FAILURE = 1

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT / "outputs"
GOLD_DIR = ROOT / "tests" / "fixtures" / "gold"
TEXTS_DIR = ROOT / "tests" / "fixtures" / "texts"
DEFAULT_OUT = OUTPUTS_DIR / "claims_analysis"

DOCS = ("ING", "MS", "Ocado", "SundayTea")
GOLD_PREFIX_TO_DOC = {"ing_fx_daily": "ING", "ms_d1_sales": "MS", "ocado_phase1": "Ocado"}
SOURCE_TEXT_FILES = {
    "ING": "ING.txt",
    "MS": "MS.txt",
    "Ocado": "Ocado.txt",
    "SundayTea": "sunday_tea_bnpp_k_shaped_market.txt",
}
# Alignment pivot for documents without a gold map.
FALLBACK_PIVOT_RUN = {"SundayTea": "new_rules_v2/SundayTea/opus"}
GOLD_MODEL = "gold"
# Batches under outputs/ that use a different taxonomy and are built on their own.
DEFAULT_EXCLUDE = ("samples_v07", "samples_v08", "samples_v09", "samples_v10", "samples_v11", "samples_v12")

_WHITESPACE = re.compile(r"\s+")
_STATEMENT_REF = re.compile(r"\bS\d{3}\b")

RUN_COLUMNS = ["run_id", "source_family", "variant", "doc", "model", "map_path", "schema_version", "taxonomy_version"]
DOC_COLUMNS = [
    "doc_title",
    "doc_publisher",
    "doc_authors",
    "doc_desk",
    "doc_asset_classes",
    "doc_source_email_sent_at",
    "doc_publication_date",
    "doc_source_preprocessing",
    "doc_source_notes",
]
STATEMENT_COLUMNS = [
    "statement_uid",
    "statement_id",
    "brief",
    "statement",
    "claim_type",
    "proposition_kind",
    "subkinds",
    "attribution",
    "modality",
    "modality_cue",
    "modality_cue_in_evidence",
    "scenario_ids",
    "scenario_slots",
    "n_evidence",
    "evidence_ids",
    "evidence_texts",
    "evidence_in_source",
    "first_evidence_offset",
    "is_core",
    "is_isolated",
    "n_arguments",
    "role_set",
    "roles",
    "argument_ids",
    "argument_summaries",
    "argument_core_types",
    "gold_match_id",
    "gold_claim_type",
    "gold_modality",
    "cluster_id",
    "cluster_pivot",
    "cluster_pivot_claim_type",
    "cluster_pivot_proposition_kind",
    "cluster_pivot_subkinds",
    "cluster_pivot_modality",
    "gold_rejected_links",
    "gold_adjudication_notes",
]
EXCLUSION_COLUMNS = ["exclusion_index", "text", "code", "reason", "text_in_source"]


@dataclass(frozen=True)
class Run:
    """One argument map with the metadata derived from its location."""

    run_id: str
    source_family: str
    variant: str | None
    doc: str
    model: str
    path: Path
    map: ArgumentMap
    summary: dict[str, Any]
    taxonomy_version: str | None


def _squash(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _cell(value: Any) -> Any:
    """Return scalars unchanged and encode lists and dicts as JSON."""
    return _json(value) if isinstance(value, list | dict) else value


def _taxonomy_version(run_dir: Path) -> str | None:
    for candidate in (run_dir / "taxonomy_rules.yaml", run_dir.parent.parent / "taxonomy_rules.yaml"):
        if candidate.is_file():
            match = re.search(r'^version:\s*"?([^"\n]+)"?', candidate.read_text(encoding="utf-8"), re.MULTILINE)
            if match:
                return match.group(1).strip()
    return None


def _doc_from_title(title: str | None) -> str:
    if title and "Sunday Tea" in title:
        return "SundayTea"
    raise ValueError(f"cannot infer document from title {title!r}")


def discover_runs(runs_root: Path, include_gold: bool, exclude: Sequence[str]) -> list[Run]:
    """Load every valid model-output map under ``runs_root`` and, if asked, every gold map.

    Runs whose first folder below ``runs_root`` is in ``exclude`` are skipped.
    """
    runs: list[Run] = []
    for path in sorted(runs_root.glob("**/argument_map.yaml")):
        run_dir = path.parent
        if run_dir.relative_to(runs_root).parts[0] in exclude:
            continue
        parts = run_dir.relative_to(OUTPUTS_DIR if run_dir.is_relative_to(OUTPUTS_DIR) else runs_root).parts
        map_ = load_argument_map(path)
        summary_path = run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        doc_part = next((p for p in parts if p in DOCS), None)
        runs.append(
            Run(
                run_id="/".join(parts),
                source_family=parts[0],
                variant=parts[1] if parts[0] == "ablation" else None,
                doc=summary.get("doc") or doc_part or _doc_from_title(map_.document.title),
                model=parts[-1],
                path=path,
                map=map_,
                summary=summary,
                taxonomy_version=summary.get("taxonomy_version") or _taxonomy_version(run_dir),
            )
        )
    if not include_gold:
        return runs
    for path in sorted(GOLD_DIR.glob("*_argument_map_gold_*.yaml")):
        doc = next(d for prefix, d in GOLD_PREFIX_TO_DOC.items() if path.name.startswith(prefix))
        runs.append(
            Run(
                run_id=f"gold/{doc}",
                source_family="gold",
                variant=None,
                doc=doc,
                model=GOLD_MODEL,
                path=path,
                map=load_argument_map(path),
                summary={},
                taxonomy_version=None,
            )
        )
    return runs


def _pivots(runs: Sequence[Run], pivot_model: str | None) -> dict[str, Run]:
    """Per document: the gold map, else the fixed fallback run, else the first run by ``pivot_model``."""
    by_id = {run.run_id: run for run in runs}
    pivots: dict[str, Run] = {}
    for doc in dict.fromkeys(run.doc for run in runs):
        pivot = by_id.get(f"gold/{doc}") or by_id.get(FALLBACK_PIVOT_RUN.get(doc, ""))
        if pivot is None and pivot_model:
            pivot = next((run for run in runs if run.doc == doc and run.model == pivot_model), None)
        if pivot is not None:
            pivots[doc] = pivot
    return pivots


def _alignment(run: Run, pivot: Run | None) -> dict[str, str]:
    if pivot is None:
        return {}
    if pivot.run_id == run.run_id:
        return {s.id: s.id for s in run.map.statements}
    return match_statements(run.map, pivot.map)


def _run_cells(run: Run, summary_keys: Sequence[str]) -> dict[str, Any]:
    doc = run.map.document
    row: dict[str, Any] = {
        "run_id": run.run_id,
        "source_family": run.source_family,
        "variant": run.variant,
        "doc": run.doc,
        "model": run.model,
        "map_path": (run.path.relative_to(ROOT) if run.path.is_relative_to(ROOT) else run.path).as_posix(),
        "schema_version": run.map.schema_version,
        "taxonomy_version": run.taxonomy_version,
    }
    for name in DOC_COLUMNS:
        row[name] = _cell(getattr(doc, name.removeprefix("doc_")))
    for key in summary_keys:
        row[f"run_{key}"] = _cell(run.summary.get(key))
    return row


def _statement_rows(
    run: Run, run_cells: dict[str, Any], source: str, pivot: Run | None, gold: Run | None
) -> list[dict[str, Any]]:
    map_ = run.map
    evidence_text = {e.id: e.text for e in map_.evidence}
    statement_type = {s.id: s.claim_type for s in map_.statements}
    memberships: dict[str, list[dict[str, str]]] = {s.id: [] for s in map_.statements}
    summaries: dict[str, str] = {}
    core_types: dict[str, str] = {}
    conclusion_of = {argument.id: argument.conclusion for argument in map_.arguments}
    for argument in map_.arguments:
        summaries[argument.id] = argument.summary
        core_type = core_types[argument.id] = statement_type.get(argument.conclusion, "")
        roles = {"core_claim": [argument.conclusion], **argument.model_dump(exclude={"id", "summary", "conclusion"})}
        for role, refs in roles.items():
            # An argument reference (v0.12) counts as membership of that argument's conclusion.
            for sid in (conclusion_of.get(ref, ref) for ref in refs):
                member = {"argument_id": argument.id, "role": role, "core_claim": argument.conclusion}
                memberships.setdefault(sid, []).append({**member, "core_type": core_type})
    scenario_slots: dict[str, list[str]] = {}
    for scenario in map_.scenarios:
        for slot in ("assumptions", "implications", "recommendations"):
            for sid in getattr(scenario, slot):
                scenario_slots.setdefault(sid, []).append(f"{scenario.id}:{slot}")

    to_gold = _alignment(run, gold)
    to_pivot = to_gold if pivot is gold else _alignment(run, pivot)
    gold_by_id = {s.id: s for s in gold.map.statements} if gold else {}
    pivot_by_id = {s.id: s for s in pivot.map.statements} if pivot else {}

    rows = []
    for statement in map_.statements:
        sid = statement.id
        texts = [evidence_text.get(eid, "") for eid in statement.evidence]
        offsets = [source.find(_squash(t)) for t in texts] if source else []
        found = [o for o in offsets if o >= 0]
        member = memberships.get(sid, [])
        argument_ids = list(dict.fromkeys(m["argument_id"] for m in member))
        gold_id = to_gold.get(sid)
        pivot_id = to_pivot.get(sid)
        rejected = [link for link in map_.rejected_links if sid in (link.get("source"), link.get("target"))]
        notes = [n for n in map_.adjudication_notes if sid in _STATEMENT_REF.findall(n)]
        row = dict(run_cells)
        row.update(
            statement_uid=f"{run.run_id}/{sid}",
            statement_id=sid,
            brief=statement.brief,
            statement=statement.statement,
            claim_type=statement.claim_type,
            proposition_kind=statement.proposition_kind,
            subkinds="|".join(statement.subkinds) or None,
            attribution=statement.attribution,
            modality=statement.modality,
            modality_cue=statement.modality_cue,
            modality_cue_in_evidence=any(_squash(statement.modality_cue).lower() in _squash(t).lower() for t in texts),
            scenario_ids="|".join(dict.fromkeys(s.split(":")[0] for s in scenario_slots.get(sid, []))) or None,
            scenario_slots="|".join(scenario_slots.get(sid, [])) or None,
            n_evidence=len(texts),
            evidence_ids=_json(statement.evidence),
            evidence_texts=_json(texts),
            evidence_in_source=bool(source) and len(found) == len(texts),
            first_evidence_offset=min(found) if found else None,
            is_core=any(m["role"] == "core_claim" for m in member),
            is_isolated=not member and sid not in scenario_slots,
            n_arguments=len(argument_ids),
            role_set="|".join(sorted({m["role"] for m in member})),
            roles=_json(member),
            argument_ids=_json(argument_ids),
            argument_summaries=_json([summaries[a] for a in argument_ids if a in summaries]),
            argument_core_types=_json([core_types.get(a, "") for a in argument_ids]),
            gold_match_id=gold_id,
            gold_claim_type=gold_by_id[gold_id].claim_type if gold_id else None,
            gold_modality=gold_by_id[gold_id].modality if gold_id else None,
            cluster_id=f"{run.doc}:{pivot_id}" if pivot_id else None,
            cluster_pivot=pivot.run_id if pivot else None,
            cluster_pivot_claim_type=pivot_by_id[pivot_id].claim_type if pivot_id else None,
            cluster_pivot_proposition_kind=pivot_by_id[pivot_id].proposition_kind if pivot_id else None,
            cluster_pivot_subkinds=("|".join(pivot_by_id[pivot_id].subkinds) or None) if pivot_id else None,
            cluster_pivot_modality=pivot_by_id[pivot_id].modality if pivot_id else None,
            gold_rejected_links=_json(rejected) if map_.rejected_links else None,
            gold_adjudication_notes=_json(notes) if map_.adjudication_notes else None,
        )
        rows.append(row)
    return rows


def _exclusion_rows(run: Run, run_cells: dict[str, Any], source: str) -> list[dict[str, Any]]:
    return [
        {
            **run_cells,
            "exclusion_index": index,
            "text": item.text,
            "code": item.code,
            "reason": item.reason,
            "text_in_source": bool(source) and _squash(item.text) in source,
        }
        for index, item in enumerate(run.map.exclusions)
    ]


def _write(path: Path, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel detects the encoding.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _source_texts(texts_dir: Path, docs: Sequence[str]) -> dict[str, str]:
    """Return the whitespace-squashed source text per document: a known fixture name, else ``<doc>.txt``."""
    sources = {}
    for doc in docs:
        candidates = [texts_dir / name for name in (SOURCE_TEXT_FILES.get(doc), f"{doc}.txt") if name]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            print(f"warning: no source text for {doc} in {texts_dir}", file=sys.stderr)
            continue
        sources[doc] = _squash(path.read_text(encoding="utf-8"))
    return sources


def build(
    out_dir: Path,
    runs_root: Path = OUTPUTS_DIR,
    texts_dir: Path = TEXTS_DIR,
    include_gold: bool = True,
    pivot_model: str | None = None,
    exclude: Sequence[str] = DEFAULT_EXCLUDE,
) -> int:
    """Build both CSVs and print per-run row counts. Returns the process exit code."""
    runs = discover_runs(runs_root, include_gold, exclude)
    if not runs:
        print(f"No argument maps found under {runs_root}.", file=sys.stderr)
        return EXIT_FAILURE
    sources = _source_texts(texts_dir, list(dict.fromkeys(run.doc for run in runs)))
    pivots = _pivots(runs, pivot_model)
    golds = {run.doc: run for run in runs if run.model == GOLD_MODEL}
    summary_keys = sorted({key for run in runs for key in run.summary})
    run_columns = RUN_COLUMNS + DOC_COLUMNS + [f"run_{key}" for key in summary_keys]

    statements: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for run in runs:
        cells = _run_cells(run, summary_keys)
        source = sources.get(run.doc, "")
        rows = _statement_rows(run, cells, source, pivots.get(run.doc), golds.get(run.doc))
        statements.extend(rows)
        exclusions.extend(_exclusion_rows(run, cells, source))
        expected = run.summary.get("statements")
        flag = "" if expected in (None, len(rows)) else f"  (summary.json says {expected})"
        print(f"{run.run_id:<45} {len(rows):>4} statements  {len(run.map.exclusions):>3} exclusions{flag}")

    _write(out_dir / "claims_all.csv", run_columns + STATEMENT_COLUMNS, statements)
    _write(out_dir / "claims_exclusions.csv", run_columns + EXCLUSION_COLUMNS, exclusions)
    print(f"\n{len(runs)} maps -> {len(statements)} statements, {len(exclusions)} exclusions in {out_dir}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and build the CSVs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory.")
    parser.add_argument("--runs-root", type=Path, default=OUTPUTS_DIR, help="Folder searched for argument maps.")
    parser.add_argument("--texts-dir", type=Path, default=TEXTS_DIR, help="Folder of source texts.")
    parser.add_argument("--no-gold", action="store_true", help="Do not include the gold maps.")
    parser.add_argument("--pivot-model", help="Model whose run is the alignment pivot when a doc has no gold map.")
    parser.add_argument(
        "--exclude", nargs="*", default=list(DEFAULT_EXCLUDE), help="Top-level folders under --runs-root to skip."
    )
    args = parser.parse_args(argv)
    return build(
        args.out.resolve(),
        runs_root=args.runs_root.resolve(),
        texts_dir=args.texts_dir.resolve(),
        include_gold=not args.no_gold,
        pivot_model=args.pivot_model,
        exclude=args.exclude,
    )


if __name__ == "__main__":
    sys.exit(main())
