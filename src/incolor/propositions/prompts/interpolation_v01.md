# Contextual interpolation (v0.1)

You receive one financial research document, already split into evidence segments. Each line is
`<ID> (<container>) <text>`. Containers are `heading`, `run_in_heading` (a label such as "Fed hold:" that introduces
the paragraph after it), `metadata`, `paragraph` and `list_item`.

Your task: for every segment listed under TARGETS, rewrite the segment so that a reader who sees **only that one
line** understands it, by adding bracketed, source-grounded context. Do not split, summarise, classify or paraphrase.

## What to interpolate

1. **References** – replace pronouns and anaphoric phrases whose referent is in another segment or earlier in the
   same segment: `it`, `this`, `that`, `they`, `these`, `the move`, `the choice set`, "those changes" … The bracket
   **replaces** the anaphor: `stop it` → `stop [a sharp and disorderly UST long end move]`.
2. **Author** – replace authorial `we` / `We` / `us` with `[The Author]`, `our` / `Our` with `[The Author's]`,
   `We're` with `[The Author is]`. Fix the verb that follows with a separate inflection insert:
   `we expect` → `[The Author] expect[s]`, `We think` → `[The Author] think[s]`. Do not inflect modals
   (`[The Author] might guess`) or past tense verbs.
3. **Inherited conditions** – if the segment's claims only hold under a condition, assumption or scenario stated in
   an EARLIER segment (e.g. the sentences after "If Warsh continues …", or "This would likely see …"), insert the
   antecedent clause, copied verbatim, at the start: `[If the Fed does not hike with current pricing,] US 30Y could …`.
   Do not add a condition the segment already states itself.
4. **Scenario labels** – a run-in label (e.g. "Base case:", "Risk-on case:") names a scenario.
   - If the text after the label states the scenario's **defining conditions** – an "if" clause, or a statement of
     what must happen such as "The ECB hikes and one of the following occurs:" together with its list items – those
     segments ARE the definition of the label. Do not prefix them with the label.
   - Insert the label only into segments that make claims *within* the scenario and have no condition of their own:
     `[In the Base case scenario,] rate reaction will depend …`.
   - When a later segment refers back to a scenario whose conditions span several segments or a list, replace the
     anaphor with the label instead of copying the conditions: `This would lift EUR` →
     `[The Risk-on case] would lift EUR`.
5. **Ellipsis** – restore elided material only when the segment is unintelligible without it, copied from the source:
   `Even without forward guidance.` → `[Greater transparency decreases the risk of miscommunication] even without
   forward guidance.`; `Or if he brings up …` → `[It would be dovish] … if he brings up …`.
6. **Elliptical answers** – "If right" / "If wrong" refer to an earlier view. Restore it from quoted source words plus
   function words only, e.g. `If [JH Warsh in presser is] right` (pointers to both source segments). Do not
   paraphrase it as "the Author's view that …".

Leave a segment unchanged (`"edits": []`) if it is already understandable.

## Hard constraints

- Every bracket is one edit. Edits are listed in the order their brackets appear in `text`.
- Outside the brackets, `text` must be the original segment text, character for character. Do not fix typos,
  spacing, quotes or capitalisation outside brackets.
- Bracket words must come from the `quote` of the edit's pointers, plus only these function words:
  a, an, the, of, in, on, at, to, for, by, with, from, and, or, if, under, scenario, case, is, are, was, were, be,
  been, being, that, which, as, than, there, where, when, 's.
  Exceptions: `author` and `inflection` edits, which have no pointers.
- Pointers point to the same segment or an EARLIER one (headings and run-in labels allowed). `quote` must be an exact
  substring of that segment's text.
- Never insert `[…]` or `[...]`. Never add negation, modality, numbers or opinions that are not in the quotes.
- If a reference cannot be resolved with confidence, leave it unchanged. If an inherited condition is plausible but not
  certain (e.g. where a scenario's scope ends), insert it with `"uncertain": true`.

## Edit fields

- `op`: `insert` (adds text) or `replace` (substitutes the `replaces` text)
- `type`: `reference` | `author` | `inflection` | `condition` | `label` | `ellipsis`
- `bracket`: the text inside the square brackets, without the brackets
- `replaces`: the exact original text that the bracket substitutes (`replace` only), else null
- `pointers`: list of `{"evidence_id": "E###", "quote": "..."}` (empty for `author` and `inflection`)
- `uncertain`: true / false

## Output

Return only JSON, no commentary:

```json
{"segments": [
  {"id": "E002", "text": "...", "edits": [ ... ]},
  ...
]}
```

Include **every** TARGET id exactly once, in document order, including unchanged ones.

## Example (illustrative document, not the input)

```
E010 (paragraph) If oil stays above $90, we expect the ECB to hike in March.
E011 (paragraph) This would push Bund yields higher.
```

```json
{"segments": [
  {"id": "E010", "text": "If oil stays above $90, [The Author] expect[s] the ECB to hike in March.", "edits": [
    {"op": "replace", "type": "author", "bracket": "The Author", "replaces": "we", "pointers": [], "uncertain": false},
    {"op": "insert", "type": "inflection", "bracket": "s", "replaces": null, "pointers": [], "uncertain": false}]},
  {"id": "E011", "text": "[If oil stays above $90,] [the ECB to hike in March] would push Bund yields higher.", "edits": [
    {"op": "insert", "type": "condition", "bracket": "If oil stays above $90,", "replaces": null,
     "pointers": [{"evidence_id": "E010", "quote": "If oil stays above $90,"}], "uncertain": false},
    {"op": "replace", "type": "reference", "bracket": "the ECB to hike in March", "replaces": "This",
     "pointers": [{"evidence_id": "E010", "quote": "the ECB to hike in March"}], "uncertain": false}]}
]}
```
