# Financial research email pipeline

The primary source is Outlook. Run an incremental sync from the project root:

```powershell
python -m src.pipeline --database data/research.sqlite3 --drop-inline-

 uv sync --project \\bluecrest.local\cfs\Home\angel.adeoye\Projects\dev\financial_research
```

This defaults to the current Outlook profile's Inbox, all time. Both start
and end dates are optional. Select a folder or either received-time bound:

```powershell
python -m src.pipeline --folder "Research/Rates" --since 2026-09-01 --until 2026-10-01 --database data/research.sqlite3
```

The command performs one sync per invocation. Run it again to pick up new or
changed emails; it is not a background scheduler. There is no implicit date
watermark, so older messages subsequently moved into the folder are discovered.
--since is inclusive and --until is exclusive. For all of September use
--since 2026-09-01 --until 2026-10-01. Either option may be used alone; omit both
for all time. Naive dates/times use the local timezone. An explicit range
deliberately limits coverage. --mailbox selects a named mailbox; --folder then
starts at its root, for example --mailbox "Research" --folder "Inbox/Rates".

## Incremental processing and email identity

Outlook ? source bodies ? body hash and subject comparison ? duplicate check ? parser ? SQLite.

A duplicate requires matching body content, a fuzzy subject match, and receipt
times no more than 24 hours apart (inclusive). Sender and Outlook entry ID do not
affect matching. Matching reports outside 24 hours are separate email occurrences.

The window compares UTC instants, not calendar dates, and works across midnight.
Naive timestamps are interpreted in local time. The stored canonical receipt time
anchors the window; skipped duplicates never extend it into a multi-day chain.

Subjects are normalized for Unicode, case, punctuation and spacing, then compared
with fuzzy text matching at a 90% similarity threshold. Numeric tokens must match
to avoid conflating different dates or report figures. The threshold is defined
by SUBJECT_SIMILARITY_THRESHOLD in ingestion/dedup.py.

Bodies must match exactly after line-ending and outer-whitespace normalization.
Both HTML and plain-text source bodies contribute. Body punctuation, markup, URLs
and case remain significant; attachment files are not hashed.

A SHA-256 body_fingerprint narrows comparisons to emails with the same content
using a database index. email_fingerprint() produces a deterministic candidate ID
from normalized subject, body and receipt time so separate occurrences can
coexist. Sender and Outlook entry ID are excluded. Hashing alone
cannot express fuzzy similarity: storage compares subjects and resolves a fuzzy
match within 24 hours to the existing canonical fingerprint. Fuzzy matches are compared directly
with canonical subjects, not chained through previously rejected variants.

emails.fingerprint is the canonical primary key. Sender and receipt time are
retained as metadata from the first stored representative. Different body content
is retained even when subjects are similar. Image-retention options do not change
identity; reprocessing updates parsed text under the same canonical ID.

Rows and processing receipts commit atomically. Errors roll back the run, leaving
candidates eligible for retry. The processing profile includes fingerprint
version, 24-hour window, fuzzy threshold, parser version and image mode. Updates/deletes invalidate
previous processing receipts.

storage.migration.migrate_fingerprints() upgrades older databases using original
source emails. It checks complete coverage, creates a timestamped SQLite backup,
and merges exact/fuzzy subject duplicates with identical bodies across senders
only within 24 hours. A recover_from backup can restore deliveries removed by
the older unlimited-window policy; recovered candidates are checked again under
the current rule. Original metadata stays available in the backup. Processing
receipts are rebuilt by the next sync.

Inbox/all-time remains the default; start and end bounds are independently
optional. Each sync holds a transaction while processing; use a single loader.

## Modules

- src/classes.py: shared dataclasses.
- src/ingestion/: Outlook access, normalization, and duplicate rules.
- src/parsing/: HTML rendering and email segmentation.
- src/pipeline.py: orchestration and Outlook command.
- src/storage/: transactional email and processed-state persistence.
- src/extraction/: optional dataframe compatibility facade.

## Python

```python
from src.pipeline import sync_outlook

result = sync_outlook("data/research.sqlite3", drop_inline_images=True)
print(result.processed, result.duplicates)
```

Outlook access requires pywin32 and an available Outlook profile. The parsing
and storage core does not require pandas. Dataframes are available through
EmailExtractor and EmailRepository.to_dataframe().

JSONL readers and load_jsonl() remain available for offline imports and tests;
they are not the primary sync path. Existing python -m src.storage invocations
now invoke the Outlook sync command too.

Dates retain input timezone information. HTML is preferred with text fallback.
body excludes heuristically classified boilerplate; full_text retains it.
Images remain included unless --drop-inline-images is specified.

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Tests use synthetic Outlook items and temporary databases. The sample-parser
test additionally uses the local research export and writes inspection reports.
