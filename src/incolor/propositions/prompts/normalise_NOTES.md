# Stage 1 normalisation: notes for reflection

Test document: BofA "Sept FOMC: hike or bond spike" (143 sentences). Models: Opus (reference), Haiku (target
for a 1–3B SLM later). Kept: prompts v15, v19, v20 and their runs under `outputs/normalise_v15|v19|v20`.
Everything v01–v18 except v15 was deleted on 2026-10-26.

## Purpose (as it settled)

- Stage 1 resolves **references** so each sentence reads on its own; atomisation and argument building do the rest.
- The argument LLM receives the full text plus atoms, so Stage 1 need not carry all context (conditions, scenarios).
- Concept references matter most: "the revisions" -> "the PCE methodology changes", "this meeting" -> "the Sept FOMC".
- Must stay trainable: short prompt, rules a small model can follow, output checked mechanically.

## Contract

- Inline marks `{{original => resolution}}`; `original()` must equal the source exactly (hard check).
- Resolutions rooted in the text: copied spans + glue words + "the author" (UNGROUNDED_WORD warning, retried).
- Sentence count unchanged (pysbd); no marks in headings or questions; modality markers kept (warning).

## Version history (condensed)

| Versions | Idea | Outcome |
|---|---|---|
| v01–v04 | Bracket/inline marks, use the document's own words, verb insertion tables | Worked; wordy, paraphrase crept in |
| v05–v11 | "One name per referent", mood/modality rules, checklists ("Method") | Longer prompts did not help Haiku; checklists ignored |
| v07–v08 | Condition/scenario forwarding added, then removed | Prefixes broke constructions |
| v12–v13 | Carry conditions forward; "resolve in place" | Scenario prefixes ("In the bullish USD case, this") read badly -> resolve in place |
| v14 | JSON reference log after `=== LOG ===` (types, antecedents, unresolved) | Opus ok, Haiku failed 3x; judged overly complicated |
| **v15** | Marked text only, table of reference kinds, conditions as prefixes, "If right/wrong" | **Best earlier run: both models pass in 1 attempt, F1 0.65/0.81** |
| v16 | Shorter bullets; relative pronouns resolved (reverted: atomisation's job) | Both 1 attempt; Haiku ungrounded words |
| v17 | "Root every addition", implicit conditions, clipped verbs, "leave unchanged if unsure" | Models turned conservative: 13–19 pronouns left; Haiku failed |
| v18 | Dropped "leave unchanged"; pronouns always resolved | Opus 0 pronouns left; Haiku failed whole-doc (jargon expansion, fragment merges) |
| v18 sections | Parallel per-section calls with whole doc as context | Haiku passed but rejected: loses context, more calls |
| v19 | Only document-defined abbreviations; fragments completed at their end; `=>` spacing tolerated | Both pass (Haiku 2 attempts), F1 0.68/0.80 |
| v20 | Conditions/scenarios dropped; concept references strengthened; copy first-to-last line | See `outputs/normalise_v20/compare.txt` |

## Lessons

- **Shorter beats complete.** Every long version (checklists, logs, tables) hurt Haiku more than it helped Opus.
- **Escape hatches backfire.** "Leave it if you can't resolve" made both models skip easy pronouns (v17).
- **Name the forbidden thing.** Haiku expanded jargon from world knowledge (Gov., SEP, u-rate, presser) until the
  prompt said "never, even when you know what it means".
- **Conditions are where models disagree most.** Most Opus/Haiku diffs in v18–v19 were condition prefixes
  ("Assuming a hawkish presser, ..."). They are context, not references; left to the argument stage from v20.
- **Claims vs names.** Haiku restates whole claims ("That Warsh continues to sound ...") where Opus uses the
  document's name ("the hawkish presser"); prefer names, claims only when nothing names it.
- **Check the checker.** Haiku's v19 first attempt "failed" only because it dropped the title line, which also
  shifted offsets and produced spurious question/heading errors. Fixed with `restore_edges` and offset lookup in
  `original()`; mechanical copy slips should be repaired, not retried.
- **Deterministic repairs are for copying only** (typography, edges, `=>` spacing). Linguistic work stays with the
  model, as the SLM will have to learn it.
- **Sectioning trades context for reliability.** Not worth it while whole-doc Haiku passes.

## Staged pipeline (resolve_v01-v02, 2026-10-29)

Replaces the whole-document rewrite: `rules.py` (symbols, defined abbreviations, we -> the author) then two model
stages (`references_v0x.md`, `ellipsis_v01.md`) that return JSON items quoting the source; code checks each item,
builds `Edit`s and renders copies (pronouns inside a copied span keep their antecedent-site referent). Runs store
`edits.jsonl`, `run.json`, `raw.json` and `resolved.txt` (layout since 2026-10-30; see
`outputs/resolve_v04/CHANGES.md`); other views come from `render_normalise.py`.

| Run (BofA) | Haiku vs Opus, model-driven edits: exact / span F1 | Opus cost | Haiku cost |
|---|---|---|---|
| v20 (whole doc) | 0.54 / 0.85 | $0.39 | $0.045 |
| resolve_v01 | 0.56 / 0.94 | $0.52 | $0.035 |
| resolve_v02 (+ shortest name per entity, misses sent back, prompt fixes) | 0.69 / 0.94 | $0.41 | $0.051 |

The shortest-name canonicalisation (worth 0.56 -> 0.59 alone) was removed on 2026-10-30 as over-engineered:
equivalent names are acceptable, and the goal is the most informative name, not the shortest.

**resolve_v03 (2026-10-30): candidates -> referent table -> render.** Code lists every pronoun, this/these/those,
standalone that and If right/wrong; the model names each referent once (thing: most informative name; claim: full
clause) and gives every candidate link / leave(reason) / ambiguous, plus extra phrases (the move); code writes the
text. Exhibit/figure labels and captions are excluded in code. `scripts/agreement.py` scores each step separately:

| v03, Haiku vs Opus | decision | coreference (B3) | type | text exact / equivalent | extra | cost Opus / Haiku |
|---|---|---|---|---|---|---|
| BofA (55 candidates) | 1.00 | 0.93 | 0.92 | 0.68 / 0.76 | 0.75 | $0.36 / $0.030 |
| GS (10 candidates) | 0.90 | 1.00 | 1.00 | 0.44 / 0.67 | 0.00 | $0.17 / $0.008 |

No rejections and no undecided candidates on the first attempt. Remaining text differences are claim extent
(attitude frame kept or not: "the author's best guess is that ..."), thing vs claim for events ("Rates price this"),
and a quote that swallows a lead-in ("For Trump admin, ...").

**resolve_v04 (2026-10-30):** claims without their frame or lead-in; a thing whenever a noun phrase names it.
Symbols and defined abbreviations are now standardised in headings and questions too, abbreviations wherever used
(before their definition as well), and definitions may contain commas and link words ("Food, Alcohol and Tobacco
(FAT)") or come reversed ("SEP (Summary of Economic Projections)"). Undefined shorthand (SEP, UST, mkt, presser) is
still never expanded.

| v04, Haiku vs Opus | decision | coreference | type | text exact / equivalent | extra | cost Opus / Haiku |
|---|---|---|---|---|---|---|
| BofA | 1.00 | 0.98 | 0.94 | 0.76 / 0.80 | 0.67 | $0.27 / $0.026 |
| GS | 0.90 | 0.88 | 1.00 | 0.56 / 0.78 | 0.57 | $0.08 / $0.015 |

Open: a claim that exists only as an elliptical answer ("We think JH ... If right") has no full clause to quote, so
the models pick different stand-ins; references and ellipsis would need to share the restored clause. Opus twice left
GS "their (historical averages)" as not_a_reference.

About 55% of edits (symbols, deixis) are now rules. GS Euro Area (second sample, 5k chars, ~16 model edits):
0.52 / 0.81. Lessons:

- **Locating is solved before wording.** Pointing instead of rewriting fixed which spans get edited (0.94); wording
  agreement needed explicit tie-breaks (shortest name, fixed not relative names, full-clause propositions).
- **Check the checker, again.** Stemming turned "is" into "i", so correct items were rejected and the model "fixed"
  them into worse text. Every glue list must go through the same normalisation as the text it is compared with.
- **Repairs resend.** Models return already-accepted items in a repair round; later items at the same place replace
  earlier ones.
- Haiku errors left: wrong antecedent between two candidates in one sentence (GS "its"), and non-anaphoric phrases
  treated as references ("Exhibit 1", "the flash print").

## Open questions

- Is F1 against Opus the right target, or should a small gold set be hand-marked?
- How should "this meeting"-type event references be separated from relative time ("this week") for training data?
- Does dropping condition prefixes hurt atomisation, or does the argument LLM recover them from the full text?
- Test on documents other than the BofA sample before the next prompt change to avoid overfitting.
