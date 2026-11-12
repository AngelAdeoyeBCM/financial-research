# Claim Classification Revision — Coding Agent Instructions

Update the financial-research argument-map taxonomy, system prompt, output schema, and validators to implement the decision process below. Preserve the existing argument-mapping workflow and its strict textual-evidence requirements. Do not introduce new argument edges as part of this change.

## Primary claim types

`RECOMMENDATION | VALUATION | FORECAST | VIEW | DATA_POINT | OBSERVATION`

`DATA_POINT` and `OBSERVATION` are factual grounding categories; neither may be an argument core. Both are eligible for `rationale`, not `supporting`. `supporting` sources must be non-observation primary claims (RECOMMENDATION, VALUATION, FORECAST, VIEW). Maintain one unique core claim per argument and one argument per core claim.

## Classification decision tree

Apply to **atomic propositions**, after separating distinct factual and evaluative content within composite sentences. Use the first applicable classification.

1. **RECOMMENDATION:** Does the author advise an investment action or exposure? If yes, classify RECOMMENDATION.
2. **VALUATION:** Does the proposition assess worth relative to market price, fair value, or an appropriate valuation benchmark (cheap/rich/overvalued/undervalued)? If yes, classify VALUATION. Include house-model valuations expressed as the author's assessment, including quantified mispricing.
3. **FORECAST:** Does the author predict an identifiable future outcome, event, state, or change? If yes, classify FORECAST. Do not classify a proposition as FORECAST merely because it mentions the future, an ongoing risk, hypothetical scenario, or qualitative outlook. Predictions need not be numeric. Author-expected policy decisions and directional price moves qualify. Clarify treatment of speculative scenarios and nowcasts as explicit policy rather than accidental side effects of this rule.
4. **FACT VS JUDGMENT:** Does the proposition **report an actual/historical fact, measurement, event, or attributed information without adding the author's substantive analytical judgment**? If yes, proceed to Test 5. If no, proceed to Test 6. **This factual-versus-evaluative test must come before DATA_POINT versus OBSERVATION.** Verifiable or attributed reporting is not necessarily objectively true; classification concerns what the statement reports, not an external truth assessment.
5. **DATA_POINT vs OBSERVATION:** If factual reporting contains a substantive quantitative measurement, numerical estimate, or numerical comparison, classify DATA_POINT. Otherwise classify OBSERVATION. A sentence merely containing a date or incidental number is not automatically a DATA_POINT.
6. **VIEW vs NONE:** If the proposition expresses an explicit analytical judgment, qualitative market/environment assessment, interpretation, or causal attribution and is not already VALUATION or FORECAST, classify VIEW. Otherwise return NONE/exclude it; VIEW must **not** be a catch-all fallback.

## Boundary examples

| Text | Label | Reason |
|---|---|---|
| "USD net long positioning reached 24% of open interest." | DATA_POINT | Quantitative reported market measurement |
| "USD rallied 2% yesterday." | DATA_POINT | Quantitative historical change |
| "USD rallied yesterday." | OBSERVATION | Qualitative factual market movement |
| "The BoE signalled readiness to hike." | OBSERVATION | Reported past policy signal |
| "Markets are pricing 100bp of hikes." | DATA_POINT | Quantified reported market expectation |
| "Consensus expects 100bp of hikes." | DATA_POINT | Quantified attributed consensus, not the author's forecast |
| "Markets expect further tightening." | OBSERVATION | Qualitative attributed market expectation |
| "Markets are too hawkish." | VIEW | Analyst evaluation of expectations |
| "USD positioning is excessively crowded." | VIEW | Assessment of market extension |
| "Conditions are unwelcoming for EUR bulls." | VIEW | Qualitative environment judgment |
| "Euro-specific risks are unlikely to fade anytime soon." | VIEW (proposed boundary) | Qualitative judgment of persistent risk environment; review against stricter future-prediction definition |
| "The BoE will hike in November." | FORECAST | Explicit, identifiable predicted policy decision |
| "GBP will appreciate against EUR by year-end." | FORECAST | Identifiable directional future outcome |
| "US midterms could pose a USD risk." | VIEW | Risk assessment, not a predicted USD price outcome |
| "USD is 1.1% overvalued versus G10." | VALUATION | Quantified worth-versus-price assessment; not DATA_POINT |
| "EUR/USD is below our fair-value estimate." | VALUATION | Relative-worth assessment |
| "We expect 100bp of hikes." | FORECAST | Author-endorsed expectation, not attributed data |

**Split mixed propositions before labeling:** "USD positioning reached 24% of OI, leaving the dollar vulnerable to an unwind" yields DATA_POINT (24% of OI) plus VIEW (vulnerability). Do not force one label on a compound proposition.

## Specific prompt/procedure adjustments

- Keep the workflow of reading the whole document, identifying core arguments, extracting self-contained propositions, registering verbatim evidence, assigning roles, and validating textual relationships.
- Explicitly split sentences containing distinct propositions or claim types **before classification**. Do not let the existing instruction to fold concessive clauses into one statement override atomicity.
- Use the six-step decision tree instead of the current `Is it about the future or about unpublished data?` FORECAST test or `Otherwise` VIEW test.
- State that `DATA_POINT` and `OBSERVATION` are both allowed **only in `rationale`**, and cannot be core claims or `supporting` sources. Preserve `RATIONALE` as empirical grounding distinct from `SUPPORTING` as claim-based argumentative support.
- Keep explicit-text-only links, one unique core per argument, and no links based solely on shared subjects.
- Remove `EMPHATIC` from modality enums, prompt text, JSON Schema, example outputs, and validators. Do not otherwise redesign modality here.
- Update the YAML taxonomy, rendered system prompt, output JSON Schema, code validators, and visualisation theme to recognise DATA_POINT. Treat it visually as a factual/rationale component alongside OBSERVATION.
- Ensure existing tests/gold examples are revisited: quantitative historical observations such as USD positioning at 24% OI should become DATA_POINT, while model-reported overvaluation remains VALUATION.

## Open adjudication questions — do not silently settle

1. Should a merely possible future event ("The Fed could cut in December") be FORECAST, or require an author-endorsed expectation? Favor narrow FORECAST to avoid overassignment, but flag for explicit adjudication.
2. Should an estimate of **past but unpublished data** (nowcast) be DATA_POINT or FORECAST? The provisional preference is DATA_POINT for retrospective estimates, with provenance indicating estimate status, but this requires a deliberate rule.
3. A quantitative threshold does not by itself make an evaluative statement factual. E.g., "Positioning is excessively crowded at 24%" may contain separable DATA_POINT and VIEW propositions.

## Acceptance criteria

- Each atomic proposition has at most one primary label.
- Test 4 gates both factual classes; Test 5 only distinguishes them by substantive quantitative content.
- Valuation and forecast retain priority over factual measurement classification.
- Generic outlook judgments no longer automatically become forecasts.
- No VIEW assigned by default; NONE is possible.
- Existing claim/role cardinality and explicit textual-link validation still pass.
