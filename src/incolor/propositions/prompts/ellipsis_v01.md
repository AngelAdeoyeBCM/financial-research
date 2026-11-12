Find the places in a research document where the writer left words out that a reader of one sentence alone would
need, and point each to the words that fill the gap. The document comes one sentence per line as `E### text`, with a
blank line between paragraphs. Headings (`#`) and questions are context only: never list a gap inside them.

Return only JSON: `{"items": [...]}`, one item per gap, in document order:

{"sid": "E058", "kind": "vp", "remnant": "We think it will", "insert": "incorporate the PCE methodology changes scheduled for September 30 into its projections", "antecedent": {"sid": "E057", "quote": "whether the Fed will incorporate the PCE methodology changes scheduled for September 30 into its projections"}}

- `remnant`: words copied exactly from sentence `sid` that end exactly where the gap is (for `fragment`, the whole
  fragment).
- `antecedent.quote`: words copied exactly from sentence `antecedent.sid`.
- `insert`: one continuous span copied exactly from `quote`. Code places it and resolves any pronouns in it.

## Kinds

- `vp`: an auxiliary or modal left without its verb (it will, they did, he does, as they did). `insert` is the verb
  and what follows it in the clause the remnant echoes, never that clause's auxiliary, modal, not or hedge words
  (will, may, might, likely, probably): the remnant keeps its own.
- `answer`: a short answer to a question just asked ("Which Warsh in presser? ... We think JH"): `insert` is the words
  of the question that complete the answer.
- `fragment`: a phrase standing as its own sentence that continues an earlier one ("Even without forward guidance.").
  `insert` is the clause it attaches to, copied whole with its own modal words; code adds it after the fragment.

## Not gaps

- Headline-style sentences that only lack is/are or an article ("Fed likely to hike 25bp.").
- References (it, this, the move): they are handled separately.
