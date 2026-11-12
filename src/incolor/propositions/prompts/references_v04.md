Resolve the references in a research document so that each sentence can be read on its own. The document comes one
sentence per line as `E### text`; headings (`#`) and questions are context only. After it comes a list of candidates
that code found, `C### E### word: …context «word» context…`. You name what the document refers back to and decide
every candidate; code writes the resolved text from your answer.

Return only JSON with three lists:

{"referents": [
  {"id": "R1", "type": "thing", "sid": "E012", "quote": "The Fed", "name": "the Fed"},
  {"id": "R2", "type": "claim", "sid": "E106", "quote": "Warsh delivers a hawkish hike"}],
 "decisions": [
  {"candidate": "C004", "action": "link", "referent": "R1"},
  {"candidate": "C017", "action": "link", "referent": "R5", "phrase": "these questions"},
  {"candidate": "C031", "action": "link", "referent": "R9", "phrase": "this tradeoff", "connective": "to"},
  {"candidate": "C009", "action": "leave", "reason": "expletive"},
  {"candidate": "C040", "action": "ambiguous", "referents": ["R3", "R7"]}],
 "extra": [
  {"sid": "E038", "phrase": "the move", "occurrence": 1, "referent": "R4"}]}

## Referents

Everything the candidates and extra phrases refer to, each listed once with one id.

- `thing`: a person, institution, event, measure, scenario, report. `quote`: words copied exactly from sentence
  `sid`. `name`: the most informative name for it, the one a reader of any single sentence would recognise, built only
  from the words of the quote plus the, a, an, of, 's (the Sept FOMC, Warsh's Jackson Hole speech, the 74 meetings
  where market priced some hike likelihood and Fed held). Never a relative time (next week's meeting) when the
  document gives a fixed name. Without `name`, the quote is the name.
- `claim`: a statement, view, expectation or condition that no noun phrase in the document names. `quote`: the claim
  itself as one full clause copied exactly, with its own subject and verb, and nothing else:
  - leave out who holds it or how it is introduced (we think, we expect, our best guess is, the author sees):
    `Warsh delivers a hawkish hike`, not `Our best guess is that Warsh delivers a hawkish hike`;
  - leave out lead-ins and labels before it: `their choice is likely: tolerate ...` is not a clause, quote
    `tolerate modestly higher front end rates or materially higher long end rates` and attach it with "to";
  - pronouns inside it are fine; code resolves them.
- Thing or claim: if the document names it with a noun phrase (the Sept FOMC hike, the Fed hold, the Hawkish presser),
  it is a thing, even when a whole sentence describes it: "Rates price this" -> this = the hike, a thing. Use a claim
  only for a statement that nothing names.
- A scenario the document labels ("Hawkish presser:", "Bullish USD case:") is a thing named by its label.

## Decisions: one for every candidate

- `link` to `referent`. If the candidate begins a noun phrase (this meeting, these evolving expectations), give the
  whole phrase in `phrase`. If that noun stands for a claim (this tradeoff, the puzzle), add `connective`: that, to or
  of, whichever attaches the claim to the noun (the puzzle that ..., the tradeoff to ...).
- `leave` with `reason`: expletive (it would be reasonable, it may be easier), relative (rates that would reflect),
  generic (no specific referent), time (this week), not_a_reference.
- `ambiguous` with `referents`: two or more referents fit equally well.

Code then writes: he, it, they, this -> the referent's name; his, its, their -> the name + 's; this, that or it for a
claim -> "that" + the clause; a noun phrase for a claim -> the noun + connective + the clause; "If right" / "If wrong"
-> "If the author is right/wrong that" + the clause, where the clause is the author's own claim just made, without
its frame. Possessives must link to things; "If right" / "If wrong" to claims.

## Extra

Noun phrases with "the" that point back to something the document names elsewhere (the move, the revisions, the
statement, the forecasts): code cannot find these, so list each with `sid`, `phrase` copied exactly, `occurrence` in
that sentence (1 = first) and `referent`. Not names that stand on their own (the Fed, the dollar), we/us/our, or
exhibit, figure, chart and table labels.
