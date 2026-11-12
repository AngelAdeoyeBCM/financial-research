Find the references in a research document that a reader of one sentence alone could not resolve, and point each to
what it refers to. The document comes one sentence per line as `E### text`, with a blank line between paragraphs.
Headings (`#`) and questions are context only: never list a reference inside them.

Return only JSON: `{"items": [...]}`, one item per reference, in document order:

{"sid": "E041", "phrase": "his", "occurrence": 1, "kind": "pronoun", "antecedent": {"sid": "E041", "quote": "Gov. Waller"}, "use": "Waller's"}

- `phrase`: the referring words exactly as written in sentence `sid`; `occurrence`: which match in that sentence
  (1 = first).
- `antecedent.quote`: words copied exactly from sentence `antecedent.sid`: the mention the phrase refers to.
- `use`: the words that replace `phrase`. Build it only from words of `quote` and `phrase`, plus the, a, an, of,
  that, is, 's. Never add a word of your own or change a word's form.

## Kinds

- `pronoun`: he, him, his, she, her, it, its, they, them, their, even when the antecedent is in the same sentence.
  Possessives take 's: `its` -> `the Fed's`. Not expletive it ("it would be reasonable").
- `noun_phrase`: this/that/these/those + noun, or the + noun, that points to something the document names elsewhere
  (the move, the revisions, this meeting, these questions). Keep the phrase's own noun where the quote allows:
  `the move` -> `the UST long end move`; otherwise use the quote's name: `the revisions` -> `the PCE methodology
  changes`.
- `shell`: a general noun that stands for a whole claim or situation (the puzzle, this tradeoff, the choice set).
  Keep it and add the claim: `the puzzle` -> `the puzzle that the dollar has also been unable to rally`.
- `proposition`: this/that/it standing alone for a whole claim: `This` -> `That the bar for this committee to
  “out-hawk” both expectations as well as other G10 central banks appears high`.
- `verdict`: "If right" / "If wrong" -> `If the author is right that` / `If the author is wrong that` + the claim.

## Choosing the antecedent

- Quote the nearest earlier mention that names the thing (not another pronoun); look forward only if nothing earlier
  names it.
- Quote only the words that name it; keep the quote's own modal and hedge words only when they are part of the claim.
- Do not list we, us, our or I: they are handled separately.
- Leave alone: relative pronouns (which, who, that), time expressions (this week, next year), names that stand on
  their own (the Fed, the dollar), and anything you cannot tie to one mention.
