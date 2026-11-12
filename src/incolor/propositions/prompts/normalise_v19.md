Rewrite the document so that every sentence can be understood on its own, using context from anywhere in the
document. Mark every change inline as {{original => resolution}}. Output only the marked document.

## Markup

- Outside marks, copy the input exactly: characters, quote styles, line breaks. Replacing each mark with its original
  must give back the input.
- `original` is the exact text replaced. To insert words, anchor on a neighbouring word: `Bob coffee` ->
  `{{Bob => Bob likes}} coffee`.
- Mark only the words that change. Never mark inside a heading or a question.

## Root every addition in the text

A resolution is made of text copied from the document: the referent, claim or condition exactly as written, as one
continuous span wherever possible. Besides copied text you may add only linking words (the, a, of, to, in, and, or,
that, if, not, is, are, was, be), "the author", and agreement endings (think -> thinks). Never reword, never change a
word's form (delivers -> delivering, unable -> failure), and never add a word of your own. This governs how you
resolve a reference, not whether: every reference below is still resolved.

## Resolve

- I, we, our -> the author: `{{We think => The author thinks}}`, `{{our => the author's}}`.
- Pronouns and possessives (he, his, it, its, they, their, ...) -> always, even when the antecedent is in the same
  sentence: `Smith may dissent, depending on {{his => Smith's}} view`. A pronoun inside text you copy is resolved
  too.
- this/that/these/those (+ noun), the former/latter, such -> what they refer to: a thing by its name
  (`{{it => the cut}}`), a claim as "that" + the claim (`{{This => That Waller may dissent}}`), several claims joined
  with "and".
- Concepts that point elsewhere in the document (the move, the puzzle, this tradeoff, a term the document defines)
  -> their content: `{{this tradeoff => the tradeoff to cut costs or raise capital}}`.
- "If right" / "If wrong" -> "If" + the claim, with "not" for wrong.
- Left-out subjects, verbs, clauses or verb phrases ("Or if he does", "as they did") -> fill them in. A fragment that
  continues the previous sentence ("Even without a cut.") is completed at its end, so it stays its own sentence:
  `Even without a {{cut. => cut, yields may fall.}}`.
- Finish clipped verb phrases. A modal or auxiliary left without its verb or object ("it will", "they did", "he may
  not", "we expect so") gets the verb and object copied from the clause it echoes, so the sentence states what will
  or did happen: "Will the ECB cut rates? We think it will." -> `{{We think it will => The author thinks the ECB will
  cut rates}}`.
- A condition, assumption or scenario that governs the sentence (If X, Assuming X, a label such as "Bear case:")
  -> add it at the start: `{{Spreads => Assuming a cut, spreads}}`. It governs until the text moves on: a new
  condition or label, a contrast ("But even ..."), or a new topic.
- Make implicit conditions explicit. A statement that only holds under a condition the document sets elsewhere
  (a scenario label, a heading, a label such as "Fed hold:", or a condition a few sentences back) gets that condition
  written in as "If X," or "Assuming X," using the document's own words for X: under "Bear case: if the ECB holds,
  ...", `{{Spreads => If the ECB holds, spreads}} could widen`. A statement that holds whatever the condition gets
  nothing.
- An abbreviation the document itself defines ("Annual Meeting (AM)") -> what it stands for:
  `{{AM => Annual Meeting}}`. Never expand any other abbreviation or jargon, even when you know what it means (Gov.,
  CPI, QE, IG, mgmt).
- &, +, =, ~, / used as words -> and, and, is, approximately, or. Never turn words into symbols.

## Rules

- Name each thing the same way every time, in the shortest copied form that identifies it.
- Replace the referring words themselves; never wrap them in extra framing.
- Keep the meaning exactly: modality, stance, mood, tense, voice, negation and numbers. Add no new claim.
- Leave alone: relative pronouns (which, who, that, whose), time words (this week, next year), standard jargon (FOMC,
  bp), expletive it (it would be reasonable), list items, and anything ambiguous.
