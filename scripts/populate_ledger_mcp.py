"""Populate data/corpus/ledger_v2.csv with Research Assistant MCP metadata.

Inputs are browse_metadata dumps (JSON: {count, records, truncated}) saved by the host under tool-results/.
Alignment key: ledger file_name == chunk_id minus the trailing "-<page>-<idx>". State Street files
(UUID file names) are aligned by page-1 text + date instead.

Document-level fields (Source, DocumentDate, DocumentType, TradeIdeaFlag) are written as scalars.
Everything that is extracted per chunk is written as a JSON list, one entry per chunk in chunk order.

usage: python populate_ledger_mcp.py <dump-dir> [--ledger PATH] [--dry-run]
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime

DOC_FIELDS = ["Source", "DocumentDate", "DocumentType", "TradeIdeaFlag"]
CHUNK_FIELDS = ["Author", "AuthorRole", "Conviction", "Sentiment", "ResearchDepth", "SignalQuality",
                "DataQuality", "MacroTheme", "RegionCountry", "Asset", "Catalyst", "Keywords"]
CHUNK_RE = re.compile(r"-(\d+)-(\d+)$")


def load_records(dump_dir):
    seen, n_files = {}, 0
    for path in glob.glob(os.path.join(dump_dir, "*browse_metadata*.txt")):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        n_files += 1
        for r in data.get("records", []):
            seen[r.get("point_id") or r["chunk_id"]] = r
    return list(seen.values()), n_files


def parse_creation(s):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", s or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def build_docs(records):
    """(doc_key, DocumentDate) -> list of chunk records ordered by chunk index."""
    docs = defaultdict(list)
    for r in records:
        m = CHUNK_RE.search(r["chunk_id"])
        if not m:
            continue
        docs[(r["chunk_id"][: m.start()], r.get("DocumentDate") or "")].append((int(m[2]), r))
    return {k: [r for _, r in sorted(v, key=lambda t: t[0])] for k, v in docs.items()}


def mode(vals):
    vals = [json.dumps(v, sort_keys=True) for v in vals if v not in (None, "", [])]
    return json.loads(Counter(vals).most_common(1)[0][0]) if vals else None


def author_names(a):
    if isinstance(a, list):
        return [x.get("Name") for x in a if isinstance(x, dict) and x.get("Name")]
    return [a] if a else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump_dir")
    ap.add_argument("--ledger", default=os.path.join("data", "corpus", "ledger_v2.csv"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ss-map", help="optional JSON {ledger file_path: [doc_key, DocumentDate]} for State Street")
    args = ap.parse_args()

    records, n_files = load_records(args.dump_dir)
    docs = build_docs(records)
    by_name = defaultdict(list)
    for (name, d), chunks in docs.items():
        by_name[name].append((d, chunks))
    ss_map = json.load(open(args.ss_map, encoding="utf-8")) if args.ss_map else {}
    print(f"{n_files} dumps, {len(records)} unique chunks, {len(docs)} (doc,date) groups")

    rows = list(csv.DictReader(open(args.ledger, encoding="utf-8-sig", newline="")))
    # PDF "Author" is the PowerPoint/PDF creator account, not the research author: dropped.
    base_cols = [c for c in rows[0].keys() if c not in ("Author", "Author_pdf")]
    new_cols = ["mcp_status", "mcp_note", "mcp_n_chunks", "mcp_chunk_ids", "Author_MCP"] + DOC_FIELDS + \
               [f for f in CHUNK_FIELDS if f != "Author"]
    out_cols = base_cols + [c for c in new_cols if c not in base_cols]

    stats = Counter()
    for row in rows:
        row.pop("Author", None)
        row.pop("Author_pdf", None)
        created = parse_creation(row.get("CreationDate"))
        chosen, note = None, ""
        if row["file_path"] in ss_map:
            key, d = ss_map[row["file_path"]]
            chosen = next((c for dd, c in by_name.get(key, []) if dd == d), None)
            note = "aligned by page-1 text + date" if chosen else ""
        else:
            cands = by_name.get(row["file_name"], [])
            if len(cands) == 1:
                chosen = cands[0][1]
            elif len(cands) > 1:
                dated = [(abs((parse_iso(d) - created).days) if parse_iso(d) and created else 10**6, d, c)
                         for d, c in cands]
                dated.sort(key=lambda t: t[0])
                chosen = dated[0][2]
                note = "multiple dates for file name %s; chose %s (closest to CreationDate)" % (
                    sorted(d for d, _ in cands), dated[0][1])
        if not chosen:
            row["mcp_status"] = "undetermined"
            row["mcp_note"] = ("no unique MCP title+date match in PDF pages 1-2" if row["file_path"].startswith("statestreet/")
                               else "no MCP chunks with this file name in fetched windows (e.g. empty DocumentDate)")
            stats["undetermined"] += 1
            continue
        row["mcp_status"] = "matched" if not note or note.startswith("aligned") else "matched_ambiguous"
        row["mcp_note"] = note
        row["mcp_n_chunks"] = len(chosen)
        row["mcp_chunk_ids"] = json.dumps([c["chunk_id"] for c in chosen], ensure_ascii=False)
        for f in DOC_FIELDS:
            row[f] = mode([c.get(f) for c in chosen])
            if f == "TradeIdeaFlag":
                row[f] = any(c.get(f) for c in chosen)
        row["Author_MCP"] = json.dumps([c.get("Author") for c in chosen], ensure_ascii=False)
        for f in CHUNK_FIELDS:
            if f != "Author":
                row[f] = json.dumps([c.get(f) for c in chosen], ensure_ascii=False)
        stats[row["mcp_status"]] += 1

    print(dict(stats))
    if args.dry_run:
        return
    shutil.copyfile(args.ledger, args.ledger + ".bak")
    with open(args.ledger, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    und = os.path.splitext(args.ledger)[0] + "_mcp_undetermined.csv"
    with open(und, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_path", "CreationDate", "Title", "reason"])
        for r in rows:
            if r["mcp_status"] == "undetermined":
                w.writerow([r["file_path"], r["CreationDate"], r["Title"], r["mcp_note"]])
    print("wrote", args.ledger, "and", und)


if __name__ == "__main__":
    main()
