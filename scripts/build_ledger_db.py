"""One-off migration: build data/corpus/ledger.duckdb from data/corpus/ledger_v3_matched.csv.

Retired. ledger.duckdb is now the source of truth and the CSV is no longer maintained, so this script refuses
to overwrite an existing database (pass --force to do it anyway). To recover the ledger, load the Parquet
archive instead: CREATE TABLE ledger AS FROM 'data/corpus/ledger.parquet' (then recreate the key and view).

One table, `ledger`, one row per corpus file (key: corpus_filepath). The CSV's JSON strings become typed
lists: Author is a list of {name, role}, Catalyst a list of {phase, date, entity, metric, type}, and the
tagging columns are lists of strings. True/False columns become BOOLEAN, dates DATE. Blank cells are NULL.

Catalyst arrives per chunk (a list of lists, with nulls for chunks without one). It is flattened to one
list per document and exact repeats are dropped. A catalyst naming several entities becomes one entry per
entity; list-valued metric or date is joined with "; ".

The `mentions` view unnests catalyst entities, author names and asset tickers into
(corpus_filepath, hash_id, kind, surface) rows, so "which documents mention X?" is a plain filter.

The database is built from scratch (written to a temp file, then swapped in).

usage: python build_ledger_db.py [--csv PATH] [--db PATH] [--force]
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from typing import Any

import duckdb

LIST_COLS = ["Region", "Country", "MacroTheme", "AssetClass", "AssetSubClass", "AssetTicker", "Keywords", "Sentiment"]
BOOL_COLS = ["TradeIdeaFlag", "mcp_missing_chunks", "is_redundant_duplicate"]

CATALYST = "STRUCT(phase VARCHAR, date VARCHAR, entity VARCHAR, metric VARCHAR, type VARCHAR)[]"
SCHEMA = {
    "corpus_filepath": "VARCHAR",
    "corpus_filename": "VARCHAR",
    "hash_id": "VARCHAR",
    "Source": "VARCHAR",
    "Author": "STRUCT(name VARCHAR, role VARCHAR)[]",
    "Title": "VARCHAR",
    "CreationDate": "DATE",
    "DocumentDate": "DATE",
    **dict.fromkeys(LIST_COLS, "VARCHAR[]"),
    "Catalyst": CATALYST,
    "TradeIdeaFlag": "BOOLEAN",
    "mcp_status": "VARCHAR",
    "mcp_note": "VARCHAR",
    "mcp_ref_chunk_id": "VARCHAR",
    "mcp_missing_chunks": "BOOLEAN",
    "is_redundant_duplicate": "BOOLEAN",
}

MENTIONS_VIEW = """
CREATE VIEW mentions AS
SELECT corpus_filepath, hash_id, 'catalyst_entity' AS kind, c.entity AS surface
FROM ledger, unnest(Catalyst) AS t(c) WHERE c.entity IS NOT NULL
UNION ALL
SELECT corpus_filepath, hash_id, 'author', a.name
FROM ledger, unnest(Author) AS t(a) WHERE a.name IS NOT NULL
UNION ALL
SELECT corpus_filepath, hash_id, 'asset_ticker', x
FROM ledger, unnest(AssetTicker) AS t(x) WHERE x IS NOT NULL
"""


def text(v: Any) -> str | None:
    """List-valued fields joined with '; ', everything else as a string or None."""
    if v is None:
        return None
    if isinstance(v, list):
        parts = [str(x) for x in v if x is not None]
        return "; ".join(parts) if parts else None
    return str(v)


def flatten_catalysts(v: Any) -> list[dict[str, str | None]]:
    """Per-chunk nested lists -> one deduplicated list of catalyst dicts."""
    out, seen, stack = [], set(), [v]
    while stack:
        x = stack.pop(0)
        if isinstance(x, list):
            stack[:0] = x
        elif isinstance(x, dict):
            entities = x.get("Entity")
            entities = [e for e in entities if e is not None] if isinstance(entities, list) else [entities]
            for e in entities or [None]:
                item = {
                    "phase": text(x.get("Phase")),
                    "date": text(x.get("Date")),
                    "entity": text(e),
                    "metric": text(x.get("Metric")),
                    "type": text(x.get("Type")),
                }
                key = tuple(item.values())
                if key not in seen:
                    seen.add(key)
                    out.append(item)
    return out


def convert(row: dict[str, str]) -> dict[str, Any]:
    """One CSV row -> one JSON-ready dict matching SCHEMA."""
    out = {c: (row[c] or None) for c in SCHEMA}
    for c in LIST_COLS:
        out[c] = json.loads(row[c]) if row[c] else None
    out["Author"] = (
        [{"name": a.get("Name"), "role": a.get("Role")} for a in json.loads(row["Author"])] if row["Author"] else None
    )
    out["Catalyst"] = flatten_catalysts(json.loads(row["Catalyst"])) if row["Catalyst"] else None
    for c in BOOL_COLS:
        out[c] = {"True": True, "False": False}.get(row[c])
    return out


def main() -> None:
    """Read the CSV, convert every row, and swap in a freshly built database."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join("data", "corpus", "ledger_v3_matched.csv"))
    ap.add_argument("--db", default=os.path.join("data", "corpus", "ledger.duckdb"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing database")
    args = ap.parse_args()
    if os.path.exists(args.db) and not args.force:
        sys.exit(f"{args.db} exists and is the source of truth; refusing to overwrite it (use --force)")

    csv.field_size_limit(2**30)  # some list cells exceed 128 KB
    with open(args.csv, encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in SCHEMA if c not in rd.fieldnames]
        if missing:
            sys.exit(f"columns missing from {args.csv}: {missing}")
        rows = [convert(r) for r in rd]

    tmp_db = args.db + ".tmp"
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    with tempfile.TemporaryDirectory() as tmp:
        ndjson = os.path.join(tmp, "ledger.ndjson")
        with open(ndjson, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        columns = ", ".join(f"'{c}': '{t}'" for c, t in SCHEMA.items())
        with duckdb.connect(tmp_db) as con:
            con.execute(
                f"CREATE TABLE ledger ({', '.join(f'{c} {t}' for c, t in SCHEMA.items())}, "
                "PRIMARY KEY (corpus_filepath))"
            )
            con.execute(
                f"INSERT INTO ledger SELECT * FROM read_json(?, format='newline_delimited', columns={{{columns}}})",
                [ndjson],
            )
            con.execute(MENTIONS_VIEW)
            n = con.execute("SELECT count(*) FROM ledger").fetchone()[0]
    os.replace(tmp_db, args.db)
    print(f"wrote {args.db}: {n} rows")


if __name__ == "__main__":
    main()
