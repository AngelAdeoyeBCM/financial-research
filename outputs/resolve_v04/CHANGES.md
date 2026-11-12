# resolve_v04: the working standard for Stage 1 normalisation

Stage 1 makes every sentence of a research note readable on its own: author deixis, symbols, defined abbreviations,
references (pronouns, demonstratives, "the move", "If right") and ellipsis are resolved, and every change is stored
as an edit against the unchanged source. Adopted on 2026-10-30; replaces the whole-document rewrite (`normalise_v20`).

## Pipeline

| Step | Done by | What it does |
|---|---|---|
| 1. Rules | code (`rules.py`) | `& + = / ~` spelled out; abbreviations the document defines (`Jackson Hole (JH)`, `Food, Alcohol and Tobacco (FAT)`, `SEP (Summary of ...)`) expanded wherever used; we/our/us -> the author with verb agreement. Symbols and abbreviations apply in headings and questions too; deixis does not. Undefined shorthand (SEP, UST, mkt) is never expanded. |
| 2. Candidates | code (`referents.py`) | Every pronoun, this/these/those, standalone "that" and "If right/wrong" in body sentences; quotes, rule edits, exhibit/figure/chart/table labels, captions and time phrases ("this week") excluded. |
| 3. Referents + decisions | model, 1 call (`references_v04.md`) | A referent table (each thing named once by its most informative name; each claim as one full clause without its frame or lead-in) and one decision per candidate: link, leave (expletive, relative, generic, time, not_a_reference) or ambiguous; plus "extra" phrases code cannot find (the move, the revisions). |
| 4. Render | code | Text written from the referent: name, name + 's, "that" + clause, noun + connective + clause, "If the author is right that" + clause. Pronouns inside a claim are resolved first. |
| 5. Ellipsis | model, 1 call (`ellipsis_v01.md`) | VP ellipsis, answers to questions, continuation fragments; the copied words keep the remnant's own modality (no modal leakage) and carry the edits made inside them. |

Every model answer quotes the source; code checks each item and sends rejected items and undecided candidates back
once. The text is never rewritten by the model, so `original() == source` holds by construction.

## What changed on the way here

| Version | Change | Haiku vs Opus on BofA |
|---|---|---|
| normalise_v20 | Model rewrites the whole document with inline marks | model-driven edits: exact 0.54, places 0.85 |
| resolve_v01 | Rules for symbols/deixis/abbreviations; model points at quotes, code builds edits | 0.56 / 0.94 |
| resolve_v02 | Prompt fixes (full-clause propositions, shell nouns, no relative time names), misses sent back | 0.69 / 0.94 |
| resolve_v03 | Candidates listed by code, referent table, one decision per candidate, code renders; exhibit labels excluded | decision 1.00, coreference 0.93, text 0.68 |
| **resolve_v04** | Claims without frame or lead-in; a noun-phrase-named event is a thing; abbreviation handling widened | **decision 1.00, coreference 0.98, text 0.76 (equivalent 0.80)** |

GS Euro Area (second sample, 10 candidates): decision 0.90, coreference 0.88, text 0.56 (equivalent 0.78).
Cost per run: Opus $0.27 (BofA, 14k chars) / $0.08 (GS, 5k); Haiku $0.026 / $0.015.

## Output layout (per document)

| File | Content |
|---|---|
| `edits.jsonl` | One record per edit: offsets, original, text, kind, pointers, referent id (references). The result; everything else is derived from it and the source. |
| `run.json` | Summary (source path relative to the run folder, model, prompts, counts, cost), referent table, the decisions that are not links, issues, rejected items, usage. |
| `raw.json` | Every raw model answer per step and attempt, so `--replay` can re-check with new code at no cost. |
| `resolved.txt` | The resolved text with every edit in `[ ]`, for reading. |

`scripts/render_normalise.py` gives the other views (marks, plain, sentences); `scripts/agreement.py` compares two
runs step by step; `scripts/run_resolve.py --source pdfs/documents --out-root pdfs/normalized` runs a whole folder.

## Corpus run (pdfs/normalized, 2026-10-30)

All 353 `pdfs/documents` files with Opus: 353 ok, $54.61, 13,351 edits (deixis 5,969, noun phrases 1,975, pronouns
1,375, possessives 1,254, symbols 881, abbreviations 603, propositions 495, demonstratives 480, shells 211, ellipsis
108). 6,009 candidate decisions: 4,726 links, 1,265 leaves, 18 ambiguous; none undecided; 39 documents needed a
repair round. `pdfs/normalized/summary.json` lists every document. Fixes made during the run:

- Model calls inherit `BUN_INSPECT` from a Claude Code session and fail on its debugger port; launch batches with
  that variable removed.
- Headings, questions and captions are now judged by one test (`rules.closed`) over the pipeline's own (pysbd)
  sentences, for deixis, candidates and the final check alike; the marked-text checker's simpler splitter flagged
  valid edits.

## Known limits

- Deixis agreement: 477 "we + verb" cases where the verb is not in the list are left uninflected ("The author close
  ..."); most are trade verbs (close 72, exit 36, deem, update, extend, enter), plus curly "don’t" and hyphenated
  "re-enter". The fix is code-only and can be replayed over all runs for free.

- A claim that exists only as an elliptical answer ("We think JH ... If right") has no full clause to quote; models
  pick different stand-ins. Fix: let the reference step quote the clause restored by the ellipsis step.
- Equivalent names still differ between models ("the Sept FOMC hike" / "the Fed hike"); accepted by design.
- Opus leaves GS "their (historical averages)" as not_a_reference in both v03 and v04.
- Many `pdfs/documents` files have extraction problems (watermarks, out-of-order pages, draft copies); the pipeline
  runs on them unchanged.
