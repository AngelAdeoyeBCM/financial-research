# Handoff: rebuild the corpus from 2026-01-01 to today

Your job is to **fetch and re-compile every research document from 2026-01-01 to today** with the current corpus pipeline, then check and report the result. **Do not change any code.** The pipeline is finished and tested. If something fails, stop and report it; do not patch `src/`.

Follow the steps in order. Each step says what "done" looks like. Do not skip the checks.

## Rules

- **Never delete anything.** The only exception is the pipeline itself removing stale `pdfs/*.txt` files during a batch, which is expected.
- **Always pass `--keep-inputs` to `batch`.** Without it, the pipeline deletes the input dumps, including the only copies of the July data in `research_chunks/_recovery/`.
- **Do not open, edit or re-save the dump JSON files.** Copy them byte for byte with `Copy-Item`. Re-saving them through PowerShell adds a BOM or changes the encoding, and the batch then rejects them.
- Do not touch `research_chunks/_recovery/`. In particular, do not run `research_chunks/_recovery/diff_legacy.py`: it imports a module that no longer exists.
- Do not create new scripts or markdown files.
- If a step's check fails, stop and report the exact command and output to the user.

## Environment

- Windows PowerShell 5.1. Chain commands with `;`, never `&&`.
- Call Python by absolute path. At the start of each terminal session, set this variable:
  ```
  $py = "C:\Users\angel.adeoye\dev\financial_research\.venv\Scripts\python.exe"
  ```
- Run every command from the repo root: `C:\Users\angel.adeoye\dev\financial_research`.
- Never redirect output with `*>`: it writes UTF-16 files. Print to the terminal instead.
- Do not start a second `batch` while one is still running. Both runs write to the same ledger.
- Never type curly quotes (`’`, `“`) in a PowerShell command: PowerShell treats them as string delimiters and the command hangs at a `>>` prompt. Use `\u2019` inside a regex instead.
- If a command returns no output, run it again in async mode and read the output.

## How the pipeline works

```
browse_metadata (MCP)  ->  raw dump JSON  ->  batch  ->  pdfs/<stem>.txt
                                                     ->  research_chunks/manifests/extract_<date>.json, skipped_<date>.json
                                                     ->  research_chunks/ledger.json
```

- CLI: `& $py -m incolor.ingestion.corpus {batch,validate,status}`. The defaults are `--root research_chunks` and `--pdfs pdfs`.
- A dump is the saved result of one `browse_metadata` call: `{"count": N, "records": [...], "truncated": false}`.
- `batch` checks every dump before it writes anything. A truncated dump, a count mismatch or a dump without text aborts the whole run with `error: ...`.
- `batch` runs one batch per `DocumentDate`. Re-running a date replaces that date's earlier results in the ledger and manifests. It also removes `pdfs/*.txt` files that no longer compile. Protected documents are never overwritten.
- When two documents have identical text, the one from the earlier batch is kept and the other is marked as a duplicate. This is why batches must run in date order.

## Step 0: Pre-flight

```
& $py -m pytest -q
```
**Done when:** the output ends with `passed` and shows no failures. If anything fails, stop.

## Step 1: Back up the current output (copy only)

```
$stamp = Get-Date -Format "yyyyMMddTHHmmss"
$bk = "research_chunks\_backup_$stamp"
New-Item -ItemType Directory $bk | Out-Null
Copy-Item -Recurse pdfs "$bk\pdfs"
Copy-Item -Recurse research_chunks\manifests "$bk\manifests"
Copy-Item research_chunks\ledger.json "$bk\ledger.json"
& $py -m incolor.ingestion.corpus status
```
Do not clear `pdfs/`, `manifests/` or `ledger.json`. The ledger holds the protected documents, and the re-run replaces every date's results anyway.

**Done when:** the backup folder has the same number of `.txt` files as `pdfs/`. Keep the `status` output for the final report.

## Step 2: Fetch the missing dates

These dumps are already on disk. **Do not fetch these dates again:**

| Dates | File |
|---|---|
| 2026-06-30 | `research_chunks/research_chunks_jan_jun/raw/browse_2026-06-30_2026-06-30.json` |
| 2026-07-01 .. 07-26 | `research_chunks/_recovery/july_01_26.json` |
| 2026-07-27 .. 07-31 | `research_chunks/_recovery/july_27_31.json` |
| 2026-10-20 .. 10-23 | `research_chunks/research_chunks_20261028_new/raw/browse_2026-10-2{0,1,2,3}_*.json` (four files) |
| 2026-10-25 .. 10-27 | `research_chunks/research_chunks_20261028_new/raw/browse_2026-10-25_2026-10-27.json` |
| 2026-10-28 | `research_chunks/research_chunks_20261028_new/raw/browse_2026-10-28_2026-10-28.json` |

Fetch every window below. In VS Code the tool is `mcp_rag_hybrid_r2_browse_metadata`; load it with tool search first. Call it with exactly these arguments:

```
{"date_from": "<from>", "date_to": "<to>", "include_text": true, "max_records": 4000}
```

**Group A: Jan–Jun (45 windows).** Save to `research_chunks/research_chunks_jan_jun/raw/`.
```
2026-01-01..01-04  01-05..01-08  01-09..01-12  01-13..01-16  01-17..01-20  01-21..01-24  01-25..01-28
2026-01-29..02-01  02-02..02-05  02-06..02-09  02-10..02-13  02-14..02-17  02-18..02-21  02-22..02-25
2026-02-26..03-01  03-02..03-05  03-06..03-09  03-10..03-13  03-14..03-17  03-18..03-21  03-22..03-25
2026-03-26..03-29  03-30..04-02  04-03..04-06  04-07..04-10  04-11..04-14  04-15..04-18  04-19..04-22
2026-04-23..04-26  04-27..04-30  05-01..05-04  05-05..05-08  05-09..05-12  05-13..05-16  05-17..05-20
2026-05-21..05-24  05-25..05-28  05-29..06-01  06-02..06-05  06-06..06-09  06-10..06-13  06-14..06-17
2026-06-18..06-21  06-22..06-25  06-26..06-29
```

**Group B: Aug–Oct gaps (22 windows).** Save to `research_chunks/research_chunks_aug_oct/raw/`.
```
2026-08-01..08-04  08-05..08-08  08-09..08-12  08-13..08-16  08-17..08-20  08-21..08-24  08-25..08-28
2026-08-29..09-01  09-02..09-05  09-06..09-09  09-10..09-13  09-14..09-17  09-18..09-21  09-22..09-25
2026-09-26..09-29  09-30..10-03  10-04..10-07  10-08..10-11  10-12..10-15  10-16..10-19
2026-10-24..10-24  <today>..<today>   (use today's date, e.g. 2026-10-29)
```

### Saving each result

1. VS Code saves a large tool result to a file named `content.json` and gives you its path in the tool result. Copy that file without changing it:
   ```
   New-Item -ItemType Directory -Force research_chunks\research_chunks_jan_jun\raw | Out-Null
   Copy-Item "<path to content.json>" "research_chunks\research_chunks_jan_jun\raw\browse_<from>_<to>.json"
   ```
   Use the full dates in the file name, for example `browse_2026-01-01_2026-01-04.json`.
2. If the result came back inline with `"count": 0`, save nothing. Note the window as "no data" and move on.
3. If the result came back inline **with records** (no `content.json` path), stop and ask the user. Do not retype or paste JSON into a file.
4. If `truncated` is `true`, or `count` is 4000, the window was too large. Fetch it again as single days (`date_from` = `date_to`), save each day separately, and do not save the truncated file. If a single day is truncated, stop and ask the user.

You may run up to 4 fetches at a time. Copy each result before you start the next group.

### Check the dumps

Run this after each group, changing the folder name:
```
& $py -c "import json,glob;[print(f, (d:=json.load(open(f,encoding='utf-8')))['count'], len(d['records']), d.get('truncated')) for f in sorted(glob.glob('research_chunks/research_chunks_jan_jun/raw/*.json'))]"
```
**Done when:** every line shows the same two numbers, `False` at the end, and one file (or "no data" note) per window.

## Step 3: Compile, one month at a time, in date order

Run each command and wait for it to finish before you start the next. **Every command needs `--keep-inputs`.** `$ja`, `$ao` and `$oc` hold the three raw folders. If a month has no dump files at all (every window was "no data"), skip that month's command, because `batch` needs at least one file.

```
$ja = "research_chunks\research_chunks_jan_jun\raw"
$ao = "research_chunks\research_chunks_aug_oct\raw"
$oc = "research_chunks\research_chunks_20261028_new\raw"
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-01-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-02-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-03-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-04-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-05-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ja\browse_2026-06-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch research_chunks\_recovery\july_01_26.json research_chunks\_recovery\july_27_31.json --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ao\browse_2026-08-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ao\browse_2026-09-*.json").FullName --keep-inputs
& $py -m incolor.ingestion.corpus batch (Get-ChildItem "$ao\browse_2026-10-*.json").FullName (Get-ChildItem "$oc\*.json").FullName --keep-inputs
```
The window `01-29..02-01` falls under January, and `02-26..03-01` under February. This is fine: the pipeline splits batches by document date, not by file.

Each run prints one line per date (`<date>: N in scope, N compiled, N skipped, N duplicate`) and then the totals and skip codes.

- `error: ... truncated` or `count ... != ...`: nothing was written for that run. Fix the dump as described in Step 2, then re-run the same command.
- A Python traceback: stop and report it.

**Done when:** all 10 commands have finished without `error:` or a traceback. Keep every summary for the report.

## Step 4: Validate and check

```
& $py -m incolor.ingestion.corpus validate
& $py -m incolor.ingestion.corpus status
```
**Done when:** `validate` reports `0 errors`, and `status` shows `0 not compiled` and dates covered from `2026-01-..` to today. Warnings are allowed; list them in the report.

Then run these defect checks on `pdfs/`. Each should print `0`:
```
(Select-String -Path pdfs\*.txt -Pattern '```yaml ignore' -SimpleMatch).Count
(Select-String -Path pdfs\*.txt -Pattern '_{3,}').Count
(Select-String -Path pdfs\*.txt -Pattern '^asas' -CaseSensitive).Count
(Select-String -Path pdfs\*.txt -Pattern '\w [\u2019'']s\b').Count
& $py -c "import json,glob;print(sum(1 for f in glob.glob('research_chunks/manifests/extract_*.json') for d in json.load(open(f,encoding='utf-8'))['documents'] for s in d.get('stripped',[]) if not s.get('section')))"
```
Two leftovers are known and do not need action:
- A few `letter_spaced` warnings, such as `E M – L O C A L E YE S`.
- A plain word left behind after its spaced banner is removed, such as `FOCUS`.

Report any other non-zero count, with up to 3 example lines.

## Step 5: Report to the user

Keep the report short:
1. A table with one row per month: in scope / compiled / skipped / duplicate. Sum the per-date lines from Step 3.
2. The top skip codes overall.
3. The `validate` warning counts.
4. The defect-check counts from Step 4.
5. `status` before (Step 1) and after.
6. Any window recorded as "no data", and any window you had to split into single days.
7. The backup folder path.

## Step 6: Update memory

In `/memories/repo/environment.md`, replace the `CORPUS (current, ...)` line with one short line. It should cover:
- The CLI command (`python -m incolor.ingestion.corpus`).
- That `--keep-inputs` is always required.
- The raw folders.
- The new date range and the counts from `status`.


