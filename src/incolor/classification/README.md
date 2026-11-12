# Document classification

Classifies each `.txt` in `pdfs/` against `taxonomy.yaml` (labels are never hardcoded) using Claude, and writes:

- `output/classifications.csv` - one row per document
- `output/entities.csv` - one row per entity mention
- `output/review.html` - single-file review report (open in a browser)

## Run

```powershell
.\.venv\Scripts\python.exe scripts\classify_docs.py                 # all files
.\.venv\Scripts\python.exe scripts\classify_docs.py --limit 3       # smoke test
```

Options: `--input`, `--output`, `--taxonomy`, `--model` (default `sonnet`), `--workers` (default 4), `--head-chars`.
Needs the `claude` extra (`claude-agent-sdk`) and `ANTHROPIC_API_KEY` or a Claude Code login.

## Behaviour

- Resumable: results are cached in `output/cache/` by file hash + model + prompt + taxonomy. Re-running skips finished files; editing `taxonomy.yaml` or the prompt re-classifies.
- Failures never stop the run; they are listed in `output/failures.json` and `output/pipeline.log` (exit code 1).
- The model first sees the opening (`--head-chars`); it rereads the full text only if confidence < 0.7.
- Invalid labels, countries or document types are rejected and the model is asked to fix them (3 attempts).
- `needs_review` = confidence < 0.7, close runner-up, empty/garbled text.
- CSV: `countries` are `;`-joined, labels are `Category > Subcategory`, `secondary` is `; `-joined.

## Layout

`src/incolor/classification/`: `Taxonomy`, `Classifier` -> `ClaudeClassifier`, `Reporter` -> `CsvReporter` / `EntityReporter` / `HtmlReporter`, `Pipeline`. Prompt: `prompts/classify_document.md`. Entity aliases (e.g. "Banco Central do Brasil" -> `BCB`) live in `taxonomy.yaml`.
