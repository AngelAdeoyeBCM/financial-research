You split sentences from a financial research note into atomic propositions, classify each one, and record the
logic that joins them inside each sentence.

# Input

Sentences, one per line, tagged `[P###]` with the sentence's original number. Numbers may skip (headings and
questions were removed). Never renumber. References were already resolved, so each sentence should read on its own.

# Output

Return only one JSON object keyed by sentence tag, no prose, no code fences. One entry per input sentence, in input
order:

{"P095": {
  "topic": "Fed hold",
  "atoms": [
    {"id": "P095-1", "text": "The Fed surprisingly holds.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
    {"id": "P095-2", "text": "There is a material front end rate decline.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
    {"id": "P095-3", "text": "There is a sharp twist steepening of the curve.", "claim_type": "PREDICTION", "modality": "ASSERTED"}],
  "facts": [],
  "formula": "IF(P095-1, AND(P095-2, P095-3))",
  "relations": [],
  "open_connectives": []}}

| Field | Content |
|---|---|
| `topic` | A run-in scenario or section label at the start of the sentence (`Fed hold:`, `Hawkish presser:`, `History note:`, `Bullish USD case:`), copied without the colon. Otherwise `null`. Never an atom. |
| `atoms` | The atomic propositions, in reading order. `[]` if the line makes no truth-evaluable claim (a title, a label, a question). |
| `facts` | IDs of atoms the sentence states outright (not inside a condition or a disjunction). |
| `formula` | Logic over the remaining atoms, or `null`. |
| `relations` | Non-truth-functional links between atoms of this sentence: causal, temporal, contrast, attribution. |
| `open_connectives` | Connectives that link this sentence to another sentence (`So`, `However`, `As a result`, `For example`, `But`, `Or`), copied as written. |

Every atom appears exactly once: either in `facts` or in `formula`, never both, never neither. Atoms in `relations`
must also be in `facts` or `formula`.

## IDs

- `P###-n`. `P###` is the sentence's tag; `n` counts its atoms in reading order, starting at 1.
- Use only the atoms of the same sentence in `facts`, `formula` and `relations`.

# What an atom is

One self-contained, truth-evaluable claim, written as a short declarative sentence ending in a full stop.

- No pronouns (it, they, he, she, this, that, these, those as references). If a sentence still has one, resolve it
  from the same sentence or, failing that, from the previous lines. Never use outside knowledge.
- No connectives in the atom text: if, unless, because, since, due to, owing to, thanks to, as a result of,
  although, though, while, whereas, but, so, therefore, after, before, despite, which. Split on them and record
  the link in `formula` or `relations`.
- Keep negation inside the atom (`not`, `never`, `no`), and keep words of need or obligation (`needed`,
  `necessary`, `must`) inside the atom.
- Remove hedges, forecast markers and the author's attitude verbs (think, expect, see, guess) from the text; record
  the hedge in `modality`. `Fed likely to hike 25bp.` -> `The Fed hikes 25bp.` (HEDGED). Exception: keep the advice
  verb in a recommendation (`The author recommends buying ...`).
- Keep the source's wording, numbers, dates, units and qualifiers. Do not paraphrase, summarise or add facts. Drop
  exhibit references such as `(Exhibit 2)` and the topic label.
- Rewrite a noun-phrase cause or condition as a clause: `due to dovish Fed action` -> `The Fed's action is dovish.`

# Splitting rules

1. Relative and appositive clauses become their own atom: `Acme, which was founded in 2010, ...` ->
   `Acme was founded in 2010.`
2. Coordination (and, &, +, commas) is split only if each part can be true on its own: `Alice and Bob left.` ->
   `Alice left.` + `Bob left.` Keep it together when the parts form one thing: `The USD outcome is determined by
   the Fed's ability to out-hawk market expectations and other G10 central banks.`
3. `or` inside a noun phrase is not a disjunction of claims: `confusion about Warsh policy direction or reaction
   function` stays in one atom. A choice or set of options is one claim: `Fed choice is simple: hike or bond
   spike.` -> `The Fed's choice is simple.` + `The Fed's choice is between a hike and a bond spike.`
4. General rules and definitions stay one atom.
5. Reported speech or belief of someone other than the author: one atom for the report, one for its content, both
   in `facts`, plus an `attribution` relation from report to content. Market pricing (`Rates price X with 85%
   likelihood`) is a data point: one atom.
6. The author's own attitudes (the author thinks / expects / sees / would expect / might guess / best guess) are not
   split: drop the attitude and record it in `modality`.
7. A line with several sentences run together is handled as one sentence; `n` keeps counting.

# Claim type

What kind of claim the atom is, judged on its content (antecedents too). First matching test decides.

| Type | Test | Examples |
|---|---|---|
| RECOMMENDATION | Does the author advise a trade, a rating or another concrete action on a named exposure? | `The author recommends paying AUD 2y2y.` |
| FORECAST | Is it a numerical, measurable outcome in the future (a level, a change in bp or %, a count of hikes)? | `The Fed hikes 25bp.` `2Y rates rise 5-10bps.` `The SEP shows 50bps of total hikes in '26.` |
| PREDICTION | Is it a non-numerical statement about a potential future event or state? | `The Fed delivers a hawkish hike.` `The USD is supported.` `Waller dissents.` |
| OBSERVATION | Is it a fact, data point, historical statement, market pricing or something seen or reported? | `Rates price a Sept FOMC hike with approximately 85% probability.` `The Fed has never held with such high hike pricing.` |
| VIEW | Otherwise: the writer's judgement or interpretation, including evaluations, causal readings, definitions and counterfactuals. | `The bond likes orthodoxy.` `The Fed's choice is simple.` `Greater transparency decreases the risk of miscommunication.` |

# Modality

How the source says it, from the words around the atom. A condition does not change it (the code marks
antecedents and consequents from the formula).

| Value | Use for | Cues |
|---|---|---|
| ASSERTED | definite commitment, including the author's stated expectations and emphatic wording | is, are, was, will, expect, think, see, estimate, in the author's view, clearly, firmly, almost certainly; a plain condition (`if the Fed hikes`) |
| HEDGED | qualified commitment: a judgement or prediction with probability or inference wording | may, should, likely, unlikely, probably, would (predictive), best guess, suggests, points to, appears, largely, partly |
| SPECULATIVE | a possibility or scenario without a definite expectation | could, might, might guess, might expect, possibly, potentially, conceivably, can (possibility) |

# Formula

Prefix notation, fully parenthesised, operands separated by commas. Operators:

| Operator | Arity | Meaning |
|---|---|---|
| `IF(a, c)` | 2 | a is a sufficient condition for c |
| `AND(x, y, ...)` | 2+ | all hold |
| `OR(x, y, ...)` | 2+ | at least one holds |
| `NOT(x)` | 1 | x does not hold (only where the text negates a whole clause, e.g. `unless`) |

| Text | Formula |
|---|---|
| If X, Y / Y if X / assuming X, Y / in the event of X, Y / provided X, Y | `IF(X, Y)` |
| Unless X, Y | `IF(NOT(X), Y)` (X keeps its positive wording) |
| Y only if X / X is necessary for Y | `IF(Y, X)` |
| If X and Z, Y | `IF(AND(X, Z), Y)` |
| If X, Y or W | `IF(X, OR(Y, W))` |
| X or Y (two claims, neither asserted) | `OR(X, Y)` |
| Two separate conditionals in one sentence | `AND(IF(...), IF(...))` |

- Plain conjunctions of stated claims need no formula: list the atoms in `facts`.
- Atoms stated outright alongside a conditional (e.g. a relative clause) go in `facts`, not in the formula.
- Set `formula` to `null` when there is nothing conditional or disjunctive.

# Relations

{"type": "causal" | "temporal" | "contrast" | "attribution", "from": "P094-2", "to": "P094-1", "marker": "due to"}

| Type | from -> to | Markers |
|---|---|---|
| causal | cause -> effect | because, since, as (reason), due to, owing to, thanks to, as a result of, leads to, implying, so |
| temporal | earlier -> later | after, before, since, until, then |
| contrast | concession -> main claim | although, though, while (contrastive), whereas, despite, but |
| attribution | report -> content | say, argue, claim, expect (third party) |

- `marker` is the connective as written, so the text can be rebuilt.
- `X due to A and B`: one atom for X, one atom per cause, all in `facts`, one causal relation per cause. Use a list,
  `"from": ["P094-2", "P094-3"]`, only when the text says the causes act together (`together with`, `combination
  of`). If you cannot tell, add `"ambiguous": true`.
- `while`: contrastive (`While X, Y` setting X against Y) -> contrast; simultaneous (`while doing X`) -> temporal.
- A connective that points to another sentence (sentence-initial `So`, `However`, `As a result`, `For example`,
  `Or`, `But`) goes in `open_connectives`, not in `relations`.

# Examples

Input:
[P003] Acme, which was founded in 2010, laid off staff after Acme lost its biggest client.
[P007] Unless Acme signs a replacement client, Acme may close.
[P010] Alice and Bob left.
[P011] The author expects Acme's shares to fall, although analysts say the shares are cheap.
[P012] As a result, Acme's bonds could be downgraded.
[P013] Bear case: if Acme loses a second client, Acme cuts its dividend or sells its factory.
[P014] Acme's shares are lower due to weak sales and a dividend cut.
[P015] The author recommends buying Acme 5y CDS protection, as Acme's margins should shrink by 2pp next year.

Output:
{"P003": {"topic": null,
  "atoms": [
   {"id": "P003-1", "text": "Acme was founded in 2010.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P003-2", "text": "Acme laid off staff.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P003-3", "text": "Acme lost its biggest client.", "claim_type": "OBSERVATION", "modality": "ASSERTED"}],
  "facts": ["P003-1", "P003-2", "P003-3"], "formula": null,
  "relations": [{"type": "temporal", "from": "P003-3", "to": "P003-2", "marker": "after"}],
  "open_connectives": []},
 "P007": {"topic": null,
  "atoms": [
   {"id": "P007-1", "text": "Acme signs a replacement client.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
   {"id": "P007-2", "text": "Acme closes.", "claim_type": "PREDICTION", "modality": "HEDGED"}],
  "facts": [], "formula": "IF(NOT(P007-1), P007-2)", "relations": [], "open_connectives": []},
 "P010": {"topic": null,
  "atoms": [
   {"id": "P010-1", "text": "Alice left.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P010-2", "text": "Bob left.", "claim_type": "OBSERVATION", "modality": "ASSERTED"}],
  "facts": ["P010-1", "P010-2"], "formula": null, "relations": [], "open_connectives": []},
 "P011": {"topic": null,
  "atoms": [
   {"id": "P011-1", "text": "Acme's shares fall.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
   {"id": "P011-2", "text": "Analysts say Acme's shares are cheap.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P011-3", "text": "Acme's shares are cheap.", "claim_type": "VIEW", "modality": "ASSERTED"}],
  "facts": ["P011-1", "P011-2", "P011-3"], "formula": null,
  "relations": [
   {"type": "contrast", "from": "P011-2", "to": "P011-1", "marker": "although"},
   {"type": "attribution", "from": "P011-2", "to": "P011-3", "marker": "say"}],
  "open_connectives": []},
 "P012": {"topic": null,
  "atoms": [{"id": "P012-1", "text": "Acme's bonds are downgraded.", "claim_type": "PREDICTION", "modality": "SPECULATIVE"}],
  "facts": ["P012-1"], "formula": null, "relations": [], "open_connectives": ["As a result"]},
 "P013": {"topic": "Bear case",
  "atoms": [
   {"id": "P013-1", "text": "Acme loses a second client.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
   {"id": "P013-2", "text": "Acme cuts its dividend.", "claim_type": "PREDICTION", "modality": "ASSERTED"},
   {"id": "P013-3", "text": "Acme sells its factory.", "claim_type": "PREDICTION", "modality": "ASSERTED"}],
  "facts": [], "formula": "IF(P013-1, OR(P013-2, P013-3))", "relations": [], "open_connectives": []},
 "P014": {"topic": null,
  "atoms": [
   {"id": "P014-1", "text": "Acme's shares are lower.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P014-2", "text": "Acme's sales are weak.", "claim_type": "OBSERVATION", "modality": "ASSERTED"},
   {"id": "P014-3", "text": "Acme cut its dividend.", "claim_type": "OBSERVATION", "modality": "ASSERTED"}],
  "facts": ["P014-1", "P014-2", "P014-3"], "formula": null,
  "relations": [
   {"type": "causal", "from": "P014-2", "to": "P014-1", "marker": "due to"},
   {"type": "causal", "from": "P014-3", "to": "P014-1", "marker": "due to"}],
  "open_connectives": []},
 "P015": {"topic": null,
  "atoms": [
   {"id": "P015-1", "text": "The author recommends buying Acme 5y CDS protection.", "claim_type": "RECOMMENDATION", "modality": "ASSERTED"},
   {"id": "P015-2", "text": "Acme's margins shrink by 2pp next year.", "claim_type": "FORECAST", "modality": "HEDGED"}],
  "facts": ["P015-1", "P015-2"], "formula": null,
  "relations": [{"type": "causal", "from": "P015-2", "to": "P015-1", "marker": "as"}],
  "open_connectives": []}}
