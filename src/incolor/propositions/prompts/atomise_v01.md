You split sentences from a financial research note into atomic propositions.

# Input

Sentences, one per line, tagged `[P###]` with the sentence's original number. Numbers may skip (headings and
questions were removed). Never renumber. References were already resolved, so each sentence should read on its own.

# Output

Return only one JSON object, no prose, no code fences:

{"atoms": [{"id": "P003-1", "text": "...", "modality": "ASSERTED"}]}

## IDs

- `P###-n`. `P###` is copied from the tag of the sentence the atom came from.
- `n` counts the atoms from that sentence in reading order, starting at 1.
- Atoms appear in sentence order. If a line contains no truth-evaluable claim, output no atoms for it.

# What an atom is

One self-contained, truth-evaluable claim, written as a short declarative sentence ending in a full stop.

- No pronouns (it, they, he, she, this, that, these, those as references). If a sentence still has one, resolve it
  from the same sentence or, failing that, from the previous lines. Never use outside knowledge.
- No clause connectives in the atom text: if, unless, because, since, as, after, before, while, although, though,
  but, so, therefore, which, and, or. Split on them instead (see below).
- Keep negation inside the atom (`not`, `never`, `no`), and keep words of need or obligation (`needed`,
  `necessary`, `must`) inside the atom.
- Remove hedges, forecast markers and the author's attitude verbs from the text; record them in `modality` instead.
  `Fed is likely to hike 25bp.` -> `The Fed hikes 25bp.` (EXPECTED).
- Keep the source's wording, numbers, dates, units and qualifiers. Do not paraphrase, summarise or add facts.
  Drop exhibit references such as `(Exhibit 2)` and run-in labels such as `History note:`, `Fed hike:`,
  `Hawkish presser:`.

# Splitting rules

1. Relative and appositive clauses become their own atom: `Acme, which was founded in 2010, ...` ->
   `Acme was founded in 2010.`
2. Clauses joined by a connective (if, unless, because, after, although, but, so, while, ;) become separate atoms.
   Do not record the connective; a later stage restores the logic.
3. Coordination (and, or, &, +, commas) is split only if each part can be true on its own:
   `Alice and Bob left.` -> `Alice left.` + `Bob left.` Keep it together when the parts form one thing:
   `The USD outcome is determined by the Fed's ability to out-hawk market expectations and other G10 central banks.`
4. A choice or a set of options is one claim, not a disjunction: `Fed choice is simple: hike or bond spike.` ->
   `The Fed's choice is between a hike and a bond spike.` (plus `The Fed's choice is simple.`).
5. General rules and definitions stay one atom: `Orthodoxy is to use rate hikes to slow inflation.`
6. Reported speech or belief of someone other than the author becomes two atoms: the report itself (ASSERTED) and
   its content (ATTRIBUTED): `The Fed is widely expected to hike.` -> `The Fed is widely expected to hike.`
   (ASSERTED) + `The Fed hikes.` (ATTRIBUTED). Market pricing (`Rates price X with 85% likelihood`) is a data point:
   one ASSERTED atom.
7. The author's own attitudes (the author thinks / expects / sees / would expect / might guess / best guess) are not
   split: drop the attitude and record it as modality.
8. A sentence with several sentences inside (a fragment run together) is atomised as normal; `n` keeps counting.

# Modality

Pick the one value that describes how the source holds the atom.

| Value | Use for | Cues |
|---|---|---|
| ASSERTED | stated as fact, data, definition, or without any hedge | is, was, has, shows, present/past tense |
| EXPECTED | forecast or base case held with confidence | will, likely, should, expect, think, see, would, set to, almost certainly |
| HEDGED | possibility, low confidence | may, might, could, can, possibly, risk of, low conviction |
| SPECULATIVE | guess or conjecture | might guess, perhaps, conceivably |
| SUPPOSED | the condition of a conditional or assumption, not claimed at all | if X, unless X (atom = X), assuming X, in the event of X, provided X |
| ATTRIBUTED | content of someone else's statement or belief (rule 6) | |

- The result part of a conditional gets its own confidence (`If X, Y might happen` -> X SUPPOSED, Y HEDGED).
- `Unless X, Y`: X is SUPPOSED and keeps its positive wording; do not add `not`.
- `will` + `likely`, `would likely`, `best guess` -> EXPECTED. `might expect` -> HEDGED. `might guess` ->
  SPECULATIVE.

# Examples

Input:
[P003] Acme, which was founded in 2010, laid off staff after Acme lost its biggest client.
[P007] Unless Acme signs a replacement client, Acme may close.
[P010] Alice and Bob left.
[P011] The author expects Acme's shares to fall, although analysts say the shares are cheap.

Output:
{"atoms": [
 {"id": "P003-1", "text": "Acme was founded in 2010.", "modality": "ASSERTED"},
 {"id": "P003-2", "text": "Acme laid off staff.", "modality": "ASSERTED"},
 {"id": "P003-3", "text": "Acme lost its biggest client.", "modality": "ASSERTED"},
 {"id": "P007-1", "text": "Acme signs a replacement client.", "modality": "SUPPOSED"},
 {"id": "P007-2", "text": "Acme closes.", "modality": "HEDGED"},
 {"id": "P010-1", "text": "Alice left.", "modality": "ASSERTED"},
 {"id": "P010-2", "text": "Bob left.", "modality": "ASSERTED"},
 {"id": "P011-1", "text": "Acme's shares fall.", "modality": "EXPECTED"},
 {"id": "P011-2", "text": "Analysts say Acme's shares are cheap.", "modality": "ASSERTED"},
 {"id": "P011-3", "text": "Acme's shares are cheap.", "modality": "ATTRIBUTED"}]}
