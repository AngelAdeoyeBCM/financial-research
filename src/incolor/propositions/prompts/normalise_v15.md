You prepare a document for claim extraction. You see the whole document; the next stage sees one sentence at a time.
Write into each statement the context it needs, so that its claims can be extracted and reconciled on their own.
Return the whole document with each change marked inline as {{original => resolution}}, and nothing else: no
preamble, no explanation, no code fences.

## Markup

- Outside marks, copy the input exactly: every character, quote style (’ “ ”), markdown marker, line break and blank
  line. Replacing each mark with its original must give back the input.
- `original` is the exact input text replaced and is never empty. To insert words, anchor on a neighbouring word and
  repeat it: `Bob coffee` -> `{{Bob => Bob likes}} coffee`. When you put words before a sentence's first word,
  lowercase that word unless it is a name.
- Keep marks short (only the words that change, plus one anchor for an insertion); no nesting, overlap or line break
  inside a mark; never move a phrase. A resolution never contains `[`, `]`, `{{`, `}}` or ` => `.
- Never mark anything inside a heading or a question.

## What to write in

| reference | edit | example |
|---|---|---|
| I, we, our | the author | `{{We think => The author thinks}}`, `{{our => the author's}}` |
| he/she/it/they forms; "this/these + noun" and definite descriptions that point back to a thing | the thing's name | `{{her => Smith's}}`, `{{the move => the June cut}}` |
| bare this/that/it/so pointing at a claim | "that" + the claim | `{{This => That Waller may dissent}} would be dovish` |
| "If right" / "If wrong" | the claim, with "not" for wrong | `{{If wrong => If Smith will not speak}}` |
| "these/those + noun" or "the above" pointing at up to three claims | the noun + the claims joined with "and" | `{{These conditions => The conditions that inflation falls and wages slow}}` |
| a concept: an abstract label (this tradeoff, the puzzle) or a term the document defines, also before its definition | the concept + one glue word + its content | `{{this tradeoff => the tradeoff to cut costs or raise capital}}` |
| a statement governed by an earlier condition, assumption or scenario (if X, assuming X, "Bear case:") | that condition as a prefix | `{{Spreads => If the ECB holds, spreads}} could tighten` |
| left-out subject, verb, clause or verb phrase | the missing words | `as {{they did => markets did price more cuts}}` |
| the document's own abbreviation or a label built on it | its expansion | `{{AM Smith => Smith as at the Annual Meeting}}` |
| `&`, `+`, `=`, `~85%`, `/` used as words | and, and, is, approximately 85%, or | `{{& => and}}` |

## How to write it

- **Use the document's words.** Every resolution is built from words in the document (the claim, condition or name
  copied as written) plus function words and "the author". Copy the shortest span that carries the meaning; never
  paraphrase, and never change a word's form (hike -> hiking).
- **Names.** A thing's name is the noun phrase the document uses for it, with "the", keeping words that identify it
  (UST, Sept, 2027) and dropping words that only describe it (sharp, disorderly). Use the same name every time.
- **Replace in place.** Replace the referring words themselves; never wrap them (`{{This => In the bear case, this}}`
  is wrong, `{{This => The bear case}}` is right).
- **Scope.** A condition, assumption or scenario label governs the statements that follow it while they describe its
  consequences, until the next condition, label or change of topic; it may be several sentences back. Add it as a
  prefix to each statement it governs, unless the statement already names it. Do not add it to a statement that
  holds regardless, or to the items of a list that define it ("some of the following occur: 1) ... 2) ...").

## Preserve the meaning exactly

Keep modality (may, would, likely, roughly), stance (who thinks, expects, says), mood (statement, question,
condition, scenario), tense and aspect, voice, polarity (not, no, without) and quantity (numbers, only, at least).
What you write in only makes explicit what the document already says in context; it never adds a claim.

## Leave alone

Relative pronouns (who, which, that, whose), including a "which" that refers to a whole clause; the next stage
splits these clauses. Phrases that already name their referent (Wednesday's meeting, the Fed, the rate increase).
Time words anchored to the publication date (this week, next year, today). Standard abbreviations and jargon the
document does not define (FOMC, CPI, bp, presser). Expletive it (it would be reasonable). "that" introducing a clause
("says that ..."). Note-style statements without a verb (Spreads wider). Items of a list and their lead-in's words.
A set of more than three claims. Use no outside knowledge; if a reference is ambiguous, leave it.

## Example

Input:
## Outlook

Pricing = ~85% odds of a June cut. Chair Smith's Annual Meeting (AM) speech was hawkish; her May testimony was dovish. We think AM Smith will speak. If right, yields likely to rise. If wrong, the curve steepens. Banks like discipline. Discipline = cut costs before raising capital. Banks face a choice: cut costs or raise capital. This tradeoff is hard. Waller may dissent. This would be dovish. Markets may price more cuts, as they did in 2019, which helped banks.

Bear case: if the ECB holds, Bunds would rally. Spreads could tighten. The euro would firm. Spreads have been stable all year.

Bull case: The ECB cuts and some of the following occur:

1) inflation falls;
2) wages slow.

This would lift banks. Yields fall. These conditions look likely.

Output:
## Outlook

Pricing {{= => is}} {{~85% => approximately 85%}} odds of a June cut. Chair Smith's Annual Meeting (AM) speech was hawkish; {{her => Smith's}} May testimony was dovish. {{We think => The author thinks}} {{AM Smith => Smith as at the Annual Meeting}} will speak. {{If right => If Smith as at the Annual Meeting will speak}}, yields likely to rise. {{If wrong => If Smith as at the Annual Meeting will not speak}}, the curve steepens. Banks like {{discipline => discipline to cut costs before raising capital}}. Discipline {{= => is to}} cut costs before raising capital. Banks face a choice: cut costs or raise capital. {{This tradeoff => The tradeoff to cut costs or raise capital}} is hard. Waller may dissent. {{This => That Waller may dissent}} would be dovish. Markets may price more cuts, as {{they did => markets did price more cuts}} in 2019, which helped banks.

Bear case: if the ECB holds, Bunds would rally. {{Spreads => If the ECB holds, spreads}} could tighten. {{The => If the ECB holds, the}} euro would firm. Spreads have been stable all year.

Bull case: The ECB cuts and some of the following occur:

1) inflation falls;
2) wages slow.

{{This => The bull case}} would lift banks. {{Yields => In the bull case, yields}} fall. {{These conditions => The conditions that inflation falls and wages slow}} look likely.
