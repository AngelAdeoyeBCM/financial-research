Rewrite the document so that every reference in it can be understood on its own, using context from anywhere in the
document. Mark every change inline as {{original => resolution}}. Output only the marked document.

## Markup

- Outside marks, copy the input exactly, from its first line to its last: characters, quote styles, blank lines and
  line breaks. Replacing each mark with its original must give back the input.
- `original` is the exact text replaced. To insert words, anchor on a neighbouring word: `Bob coffee` ->
  `{{Bob => Bob likes}} coffee`.
- Mark only the words that change. Never mark inside a heading or a question.

## Root every addition in the text

A resolution is made of text copied from the document, as one continuous span wherever possible. Besides copied text
you may add only linking words (the, a, of, to, in, and, or, that, if, not, is, are, was, be), "the author", and
agreement endings (think -> thinks). Never reword, never change a word's form (delivers -> delivering), and never add
a word of your own. This governs how you resolve a reference, not whether: every reference below is still resolved.

## Resolve

- I, we, our -> the author: `{{We think => The author thinks}}`, `{{our => the author's}}`.
- Pronouns and possessives (he, his, it, its, they, their, ...) -> always, even when the antecedent is in the same
  sentence: `Smith may dissent, depending on {{his => Smith's}} view`.
- Concept references: a noun phrase with the, this, that, these or such that points to something the document names
  or describes elsewhere (the move, the revisions, this meeting, the puzzle, such risks) -> the document's most
  specific name for it: `{{the revisions => the GDP methodology changes}}`,
  `{{this meeting => the June ECB meeting}}`, `{{the move => the cut}}`.
- this/that/these/those standing alone, the former/latter -> what they refer to: a thing by its name, or, only if the
  document gives it no name, a claim as "that" + the claim (`{{This => That Waller may dissent}}`).
- "If right" / "If wrong" -> "If" + the claim, with "not" for wrong.
- Left-out words. A modal or auxiliary without its verb ("it will", "they did", "Or if he does") gets the verb and
  object copied from the clause it echoes: "Will the ECB cut rates? We think it will." ->
  `{{We think it will => The author thinks the ECB will cut rates}}`. A fragment that continues the previous
  sentence ("Even without a cut.") is completed at its end: `Even without a {{cut. => cut, yields may fall.}}`.
- An abbreviation the document itself defines ("Annual Meeting (AM)") -> `{{AM => Annual Meeting}}`. Never expand
  any other abbreviation or jargon, even when you know what it means (Gov., CPI, QE, IG, mgmt).
- &, +, =, ~, / used as words -> and, and, is, approximately, or. Never turn words into symbols.

## Rules

- Name each thing the same way every time, in the shortest copied form that identifies it.
- Replace the referring words themselves; never wrap them in extra framing.
- Keep the meaning exactly: modality, stance, mood, tense, voice, negation and numbers. Add no new claim.
- Do not add conditions or scenarios a sentence sits under; later stages read the whole document for those.
- Leave alone: relative pronouns (which, who, that, whose), time words (this week, next year), standard jargon (FOMC,
  bp), expletive it (it would be reasonable), list items, and anything ambiguous.
