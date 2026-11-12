# samples_v12 / opus: statements → entity states

Hand mapping of all 300 opus statements (4 docs) to entity-state keys. Claim features are ignored: claim_type, modality, attribution and holder (author vs market vs Fed SEP vs model). The only question is whether the **entity** and the **state** resolve.

## 1. Format

| Kind | Key | Example |
|---|---|---|
| Position (TRADE, RATING) | `instrument \| direction \| action` | `fx:chfjpy \| short \| maintain` |
| State | `subject \| variable \| value \| horizon` | `ind:jp:policy_rate \| path \| UP \| 2026` |
| Causal | `state -> state` (`;` joins several states) | `cmdty:crude_oil \| price \| DOWN -> ccy:nok \| value \| DOWN` |

**Slots**
- **instrument / subject**: a registry `entity_id`, lower case. Pairs use `fx:`, single currencies use `ccy:`, so `ccy:CHFJPY` becomes `fx:chfjpy`. Built entities follow the code's key builders:
  - FX cross from `base_id`/`quote_id`: `fx:chfjpy`
  - Indicator as measure × geo: `ind:jp:policy_rate`
  - Instrument from `Instrument.key`: `INS:CURVE[bond:ust]:2y/30y:cash`
  - Event occurrence (notebook gap 3): `event:fomc@2026-09`
  - `?` marks an id that does not exist and cannot be built.
- **direction**: `long | short | neutral`. Pairs are normalised to market convention: "long JPY vs CHF" becomes `fx:chfjpy | short`, and "overweight CAD vs AUD" becomes `fx:audcad | short`. Overweight maps to long and underweight to short.
- **action**: `open | maintain | close | review`. A "switch" is two keys, the old position closed and the new one opened.
- **variable**: from DOC.md §6 and the notebook §6 catalogue. Qualifiers go in brackets: `flows[real_money]`, `risk_premium[geo:fr]`, `allocation[domestic_bonds]`. `priced` (market-implied) is kept as a separate variable from `path` (a forecast), because "underpriced" claims compare the two (`path vs priced`).
- **value**: `UP | DOWN | FLAT`, or a label from the catalogue (hawkish, rich, sticky, two_way…). Magnitude follows a colon (`UP:25bp`), a target follows `to` (`DOWN to 145`), and a reference follows `vs` (`rich vs ind:ea:policy_rate`).
- **horizon**: `near | medium | long`, a period (`2026Q4`, `2027`) or an event occurrence; `-` when the text gives none.

**Status** (the worst component wins)
- ✅ every id is in `config/registries` and the variable is in the vocabulary.
- 🟡 the entity is **built** from registered parts (cross, indicator, instrument, event occurrence), or a qualifier needs a closed list that does not exist yet (participant, allocation bucket).
- ❌ there is no subject in the ontology (theme, strategy, asset class, risk appetite), an id is missing and can't be built, or the statement is **not a state** (communication, procedure, actors' beliefs, model-factor attribution).

## 2. Results

| Doc | n | ✅ | 🟡 | ❌ |
|---|---|---|---|---|
| State Street, Beam yields up | 84 | 41 | 26 | 17 |
| BofA, France risks for EUR | 33 | 17 | 11 | 5 |
| BofA, Sept FOMC | 91 | 27 | 45 | 19 |
| Barclays, Structural JPY weakness | 92 | 30 | 49 | 13 |
| **Total** | **300** | **115 (38%)** | **131 (44%)** | **54 (18%)** |

So 82% of statements resolve to an entity state today or with a built key.

**Why 🟡 (131)**, roughly by frequency
1. **Policy-rate indicators are missing** for the US, JP, NZ, NO, SE, CA and AU. Only `ind:{ea,gb,ch,cn}:policy_rate` exist. `ind:us:policy_rate` is the most-used subject in the FOMC note; the registry has only `rate:fed_funds`, a rate benchmark.
2. **Event occurrences**: `event:fomc@2026-09`, `event:fr_budget@2027`. The registry holds only series.
3. **Participant groups**: real_money, speculative, households, life_insurers, banks, corporates, jp_institutions. Where the participant is registered (`org:gpif`, `geo:jp`) the row is ✅.
4. **Built instruments**: UST 2y/30y outrights and curves, OAT-Bund 10y, SOFR-TONA spread, TONA/SOFR basis.
5. **Unregistered crosses**: `fx:chfjpy`, `fx:audcad`, `fx:cadchf`.
6. **No FX-intervention policy tool**: I fell back to `org:jp_mof | fx_intervention` and `org:us_treasury | fx_intervention`.
7. Unregistered indicators that can be built: `ind:gb:gdp`, `ind:gb:wages`, `ind:nz:*`, `ind:jp:term_premium`, `ind:jp:capital_flows`, `ind:jp:fx_reserves`, `ind:us:term_premium`.

**Why ❌ (54)**
| Reason | n | Examples |
|---|---|---|
| Not a state (communication, procedure, beliefs of actors) | 23 | "Warsh will face questions", "statement wording changes", "Trump won't like the choice", "signal matters more than amount" |
| No subject type: theme, strategy, asset class, risk appetite | 11 | FX carry trade, AI capex/narrative, "risk assets", real-money risk appetite, household allocation |
| Missing registry entry that can't be built | 13 | French legislative election, CAC 40, REER, net interest cost, econ-surprise index, Minister Ueno, ESF, FIMA repo, GPIF board meeting, public-spending measure, hedged foreign yield |
| Model-factor attribution (Boost/Forest drivers) | 5 | "Value drives all Boost trades": the target is a position, not a world state |
| Relation states: correlation and beta | 2 | DXY–yield correlation; USDJPY sensitivity above a 149bp spread |

**Design observations**
- **Normalised keys merge**: "short AUDCAD" (S003), "overweight CAD vs AUD" (S033) and Forest's "short AUDCAD" (S080) all become `fx:audcad | short | maintain`.
- **Stripping the holder makes disagreement countable**: BofA's "+75bp in 2026" (S009) and the Fed's "median dot +50bp" (S002) sit on the same slot, `ind:us:policy_rate | path | · | 2026`, with different values.
- **"Constructive" on a spread has no direction** (FOMC S073, long-end UST asset-swap spreads). The position key can't be filled.
- **6m3m forward vol can't be built**: `Outright` rejects a forward-start tenor on options (France S017).
- **Basis "widening"** (Barclays S042) has no entry in the DOC.md §5 direction table, so its sign is ambiguous.
- **Revisions** ("SEP inflation −0.3pp vs June") need `vs prior_sep` as a reference. Otherwise a revision and a level look the same.

---

## 3. State Street, DM FX Weekly "Beam yields up, Scotty?" (2026-08-26)

- **S001** Buyback turned focus to debt: `policy:ust_buybacks | size | UP:4bn | - -> ?theme:us_debt_sustainability | salience | UP | -` ❌ theme (no theme registry)
- **S002** Underweight USD: `ccy:usd | short | maintain` ✅
- **S003** Short AUDCAD: `fx:audcad | short | maintain` 🟡 cross
- **S004** Room for trade U-turns: `event:us_canada_trade_war | outcome_prob[sanctions] | DOWN | 2027-01` ✅
- **S005** CAD reaction overdone: `ccy:cad | valuation | cheap | near` ✅
- **S006** Long EURGBP: `fx:eurgbp | long | maintain` ✅
- **S007** Short CHFJPY: `fx:chfjpy | short | maintain` 🟡 cross
- **S008** Long EURUSD: `fx:eurusd | long | maintain` ✅
- **S009** Yield rise a drift: `bond:ust | yield | UP | 2026Q3 ; INS:CURVE[bond:ust]:2y/10y:cash | slope | UP:24bp | 2026Q3` 🟡 built curve; "not stress" has no slot
- **S010** Debt interest a huge problem: `?ind:us:net_interest | level | UP | -` ❌ no interest-cost measure
- **S011** US duration unattractive: `bond:ust | valuation | rich | -` ✅
- **S012** Buybacks won't stem yields: `INS:OUTRIGHT[bond:ust]:30y:cash | yield | UP | 2026Q3` 🟡 "long end" taken as 30y
- **S013** Won't accept $32bn: `policy:ust_buybacks | accepted_size | below:32bn | 2026Q3` ✅
- **S014** Drop in the ocean: `policy:ust_buybacks | size vs bond:ust supply[10y+] | small | 2026Q3` ✅
- **S015** Not the only game in town: `bond:ust | demand_share | DOWN | -` ✅ lossy
- **S016** AI drives corporate issuance: `?theme:ai_capex -> ?credit:us_corporate | supply | UP | 2026` ❌ no theme or corporate-credit entity
- **S017** Japanese flows less supportive: `bond:ust | flows[geo:jp] | DOWN | -` ✅
- **S018** JGB yields draw flows home: `bond:jgb | yield | UP -> ind:jp:capital_flows | net_inflow | UP` 🟡 built indicator
- **S019** Yields support USD for now: `bond:ust | yield | UP -> ccy:usd | value | UP | near` ✅
- **S020** Yield support may fade: `?CORR[index:dxy|bond:ust:30y] | level | DOWN` ❌ correlation needs a pair subject
- **S021** Growth vs deficit yields: `ind:us:gdp | trend | UP -> ccy:usd | value | UP ; ind:us:budget_balance | level | DOWN -> ccy:usd | value | FLAT` 🟡 built indicator; mediating yield state dropped
- **S022** Bessent hurt confidence: `person:scott_bessent | credibility | DOWN | -` ✅
- **S023** Fallout weighs on USD: `person:scott_bessent | credibility | DOWN -> ccy:usd | value | DOWN | near` ✅
- **S024** Warsh has a needle to thread: ❌ not a state
- **S025** Little on reaction function: `org:fed | reaction_function | unclear | event:jackson_hole@2026-08` ✅
- **S026** Balance-sheet aims vs buybacks: `person:kevin_warsh | stance[balance_sheet] | shrink | -` ✅ the clash with `policy:ust_buybacks` is a relation and is lost
- **S027** Yields up, carry less compelling: `bond:ust | yield | UP -> ?strategy:fx_carry | attractiveness | DOWN` ❌ no strategy entity
- **S028** Real money overweight carry: `?strategy:fx_carry | positioning[real_money] | long` ❌
- **S029** Risk appetite positive: `?risk_appetite[real_money] | level | positive` ❌
- **S030** Yields rise again: `bond:ust | yield | UP | -` ✅
- **S031** Carry a loser: `?strategy:fx_carry | performance | DOWN` ❌
- **S032** BoC/market ignore strong data: `?ind:ca:econ_surprise | level | UP ; org:boc | stance | FLAT ; ind:ca:policy_rate | priced | FLAT` ❌ no surprise-index measure
- **S033** Overweight CAD vs AUD: `fx:audcad | short | maintain` 🟡 same key as S003
- **S034** Intervention changed JPY dynamic: `org:jp_mof | fx_intervention | BUY_JPY | 2026-07 -> ccy:jpy | regime | changed | near` 🟡 no intervention tool, fell back to the org
- **S035** BoJ hikes underpriced: `ind:jp:policy_rate | path vs priced | above | 2026` 🟡
- **S036** Real money buying EUR: `ccy:eur | flows[real_money] | BUY | -` 🟡 participant
- **S037** Market reads ECB hawkish: `org:ecb | stance | hawkish | -` ✅
- **S038** BoE pricing too high vs ECB: `ind:gb:policy_rate | priced vs ind:ea:policy_rate | rich | -` ✅
- **S039** Tone/surprises favour EUR: `fx:eurgbp | spot | UP | - ; fx:eurusd | spot | UP | -` ✅
- **S040** NZ troughed, CPI above target: `ind:nz:gdp | trend | UP ; ind:nz:cpi | target_gap | above` 🟡
- **S041** A lot expected of RBNZ: `ind:nz:policy_rate | priced | UP | medium` 🟡
- **S042** Neutral NZD: `ccy:nzd | neutral | maintain` ✅
- **S043** SEK vulnerable in shocks: `?risk_appetite | level | DOWN -> ccy:sek | value | DOWN ; cmdty:crude_oil | price | DOWN -> ccy:sek | value | DOWN` ❌ risk-on/off has no subject (oil leg ✅)
- **S044** Conflict and oil recede: `event:middle_east_conflict | escalation_risk | DOWN ; cmdty:crude_oil | price | DOWN` ✅
- **S045** SEK can recover: `ccy:sek | value | UP | -` ✅
- **S046** Neutral SEK: `ccy:sek | neutral | maintain` ✅
- **S047** NOK vs energy: `cmdty:crude_oil | price | DOWN -> ccy:nok | value | DOWN` ✅
- **S048** Limited escalation appetite: `event:middle_east_conflict | escalation_risk | low | -` ✅
- **S049** NOK uncertain: `ccy:nok | risk_balance | two_way | -` ✅
- **S050** Neutral NOK: `ccy:nok | neutral | maintain` ✅
- **S051** High bar for Sept hike: `ind:us:policy_rate | decision | hold | event:fomc@2026-09` 🟡
- **S052** USD vulnerable: `ccy:usd | value | DOWN | near` ✅
- **S053** SNB most dovish: `org:snb | stance | dovish (rank 1 vs geo:g10) | -` ✅
- **S054** Risk appetite / geopolitics: `?risk_appetite | level | positive ; geo:global | political_risk | elevated, FLAT` ❌ risk appetite
- **S055** CHF ideal funder: `ccy:chf | funding_role | ideal | -` ✅ new variable
- **S056** Sterling stubborn: `ccy:gbp | value | FLAT ; ccy:gbp | flows[real_money] | BUY ; ind:gb:gdp | trend | weak` 🟡 participant; built indicator
- **S057** Iran hit to AU labour: `event:middle_east_conflict | escalation | UP -> ind:au:gdp | trend | DOWN ; ind:au:labour_force | condition | loosening` 🟡
- **S058** AUD most overweight: `ccy:aud | positioning[real_money] | long (extreme) | -` 🟡 participant
- **S059** Uncomfortable Fed backdrop: `ind:us:pce | target_gap | above ; ind:us:unemployment_rate | condition | fragile` ✅ "uncomfortable for the Fed" itself is not a state
- **S060** ECB pricing steady: `ind:ea:policy_rate | priced | FLAT | -` ✅
- **S061** BoJ more hawkish: `org:boj | stance | UP ; ind:jp:cpi | target_gap | above` ✅
- **S062** More BoJ hikes: `ind:jp:policy_rate | path | UP | 2026` 🟡
- **S063** UK growth potential < EZ: `ind:gb:gdp | potential vs ind:ea:gdp | below | -` 🟡
- **S064** UK inflation sticky: `ind:gb:cpi | condition | sticky | -` ✅
- **S065** UK wages slowing: `ind:gb:wages | trend | DOWN | -` 🟡
- **S066** UK pricing a maximum: `ind:gb:policy_rate | priced | rich (ceiling) | -` ✅
- **S067** SNB little room: `ind:ch:policy_rate | level | 0% ; org:snb | policy_space | limited` ✅
- **S068** CHF expensive: `ccy:chf | valuation | rich (moderate) | -` ✅
- **S069** SNB on hold: `ind:ch:policy_rate | path | FLAT | 2026` ✅
- **S070** More RBNZ hikes: `ind:nz:policy_rate | path | UP | 12m` 🟡
- **S071** Norges shallow: `ind:no:policy_rate | path | UP (shallow) | -` 🟡
- **S072** Riksbank low inflation: `ind:se:cpif | level | low vs geo:g10 | -` ✅
- **S073** Riksbank lags ECB: `ind:se:policy_rate | path vs ind:ea:policy_rate | later | -` 🟡
- **S074** Boost short CHFJPY: `fx:chfjpy | short | maintain` 🟡 same key as S007
- **S075** Boost long USDCHF: `fx:usdchf | long | maintain` ✅
- **S076** Boost switch: `fx:cadchf | long | open ; fx:audcad | short | close` 🟡
- **S077** Value drives Boost: ❌ model-factor attribution
- **S078** Rate diffs drive Boost: ❌ same
- **S079** Growth diffs drive Boost: ❌ same
- **S080** Forest short AUDCAD: `fx:audcad | short | maintain` 🟡
- **S081** Forest long USDCHF: `fx:usdchf | long | maintain` ✅
- **S082** Forest switch: `fx:cadchf | long | open ; fx:chfjpy | short | close` 🟡
- **S083** Growth/momentum drive Forest: ❌ model-factor attribution
- **S084** Value/rates drive Forest: ❌ same

## 4. BofA Liquid Insight, "France risks for EUR"

- **S001** France risk partly priced in FX: `ccy:eur | risk_premium[geo:fr] | partly_priced | -` ✅
- **S002** Constructive EUR: `ccy:eur | value | UP | medium` ✅
- **S003** France a downside risk: `geo:fr | political_risk | elevated -> ccy:eur | risk_balance | downside | medium` ✅
- **S004** No budget disruption: `event:fr_budget@2027 | outcome | orderly | -` 🟡 occurrence
- **S005** Election is the next catalyst: `event:fr_presidential_2027 | timing | early (2027Q1) | -` ✅ the ranking against the budget is lost
- **S006** Weak French macro: `ind:fr:gdp | trend | weak | -` ✅
- **S007** Fiscal slippage, Moody's: `ind:fr:budget_balance | path | DOWN ; bond:oat | credit_rating[org:moodys] | downgrade_risk | 2026-10-23` 🟡 built indicator
- **S008** EU-integration risk: `event:fr_presidential_2027 | outcome | anti_integration -> ccy:eur | risk_balance | downside | medium` 🟡 theme carried as an outcome label
- **S009** Parliamentary fragmentation: `?event:fr_legislative_2027 | outcome | fragmented -> ccy:eur | risk_balance | downside` ❌ no legislative-election series
- **S010** Budget stability risk: `event:fr_budget@2027 | political_risk | elevated -> ccy:eur | risk_balance | downside | near` 🟡
- **S011** Budget passes, deficit flat: `event:fr_budget@2027 | outcome | passed ; ind:fr:budget_balance | level | FLAT vs 2026 | 2027` 🟡
- **S012** Needs c60bp of measures: `geo:fr | fiscal_stance | tighten:0.6pp GDP | 2027` ✅
- **S013** President could dissolve parliament: `?event:fr_legislative_2027 | timing | 2027` ❌ same gap as S009
- **S014** France drove EUR sentiment/RR lows: `geo:fr | political_risk | UP -> ccy:eur | sentiment | DOWN ; fx:eurusd | rr_25d | DOWN` ✅
- **S015** Low REER reflects low inflation: `ind:fr:cpi | level | low -> ?ind:fr:reer | level | low` ❌ no REER measure
- **S016** Election risk in options: `fx:eur* | implied_vol[event:fr_presidential_2027] | priced` 🟡 "EUR crosses" is a family
- **S017** 6m3m forward-vol peak: `fx:eur* | implied_vol | UP | 2027-04..06` 🟡 the 6m3m instrument can't be built
- **S018** Premium in EURGBP, EURCHF: `fx:eurgbp | implied_vol[event:fr_presidential_2027] | rich ; fx:eurchf | … | rich` ✅
- **S019** Historically large premium: `fx:eur* | implied_vol[event:fr_presidential_2027] | rich vs history` 🟡
- **S020** EURUSD sentiment drop not France: `fx:eurusd | sentiment | DOWN | -` ✅ the negated driver has no slot
- **S021** EURUSD sentiment neutral: `fx:eurusd | sentiment | neutral | -` ✅
- **S022** EUR positioning unremarkable: `ccy:eur | positioning | neutral | -` ✅
- **S023** Higher stakes: `event:fr_presidential_2027 | impact[ccy:eur] | high vs prior | -` ✅
- **S024** Competitive race: `event:fr_presidential_2027 | outcome_distribution | competitive` ✅
- **S025** Other markets partly price it: `INS:SPREAD[bond:oat|bond:bund]:10y:cash | risk_premium[geo:fr] | partly_priced` 🟡 "other markets" taken as OAT-Bund
- **S026** 10bp OAT-Bund ≈ −0.4% EURUSD: `INS:SPREAD[bond:oat|bond:bund]:10y:cash | level | UP:10bp -> fx:eurusd | spot | DOWN:0.4%` 🟡
- **S027** Neutral French equities: `?index:cac40 | neutral | maintain` ❌ no French equity index
- **S028** Non-EA investors sold French equities: `?index:cac40 | flows[non_ea] | SELL` ❌
- **S029** EUR downside dominates: `ccy:eur | risk_balance | downside | medium` ✅
- **S030** More relevant once field is clear: `event:fr_presidential_2027 | candidate_field | clarified -> ccy:eur | risk_premium[geo:fr] | UP` ✅
- **S031** Hedge via CHF: `fx:eurchf | short | open` ✅
- **S032** Hedge via GBP: `fx:eurgbp | short | open` ✅
- **S033** EURUSD more US-driven: `fx:eurusd | sensitivity[geo:us] | high vs fx:eurchf, fx:eurgbp` 🟡 a beta is a relation

## 5. BofA, "Sept FOMC: hike or bond spike"

- **S001** Hike 25bp in Sept: `ind:us:policy_rate | decision | hike:25bp | event:fomc@2026-09` 🟡
- **S002** 2026 dot +50bp: `ind:us:policy_rate | path | UP:50bp | 2026` 🟡 same slot as S009
- **S003** Hike or bond spike: `ind:us:policy_rate | decision | hold | event:fomc@2026-09 -> INS:OUTRIGHT[bond:ust]:30y:cash | yield | UP (sharp)` 🟡
- **S004** Orthodoxy anchors the long end: `ind:us:policy_rate | path | UP -> INS:OUTRIGHT[bond:ust]:30y:cash | yield | DOWN ; policy:ust_buybacks | size | UP -> … | FLAT` 🟡
- **S005** Hawkish hike: `event:fomc@2026-09 | tone | hawkish` 🟡
- **S006** Front end up, twist flatten: `INS:OUTRIGHT[bond:ust]:2y:cash | yield | UP ; INS:CURVE[bond:ust]:2y/30y:cash | slope | DOWN` 🟡
- **S007** USD depends on out-hawking: `ind:us:policy_rate | path vs priced | above -> ccy:usd | value | UP` 🟡 the "vs G10 CBs" basket has no entity
- **S008** JH + data repriced hikes: `event:jackson_hole@2026-08 | tone | hawkish ; ind:us:core_pce, ind:us:payrolls | surprise | UP -> ind:us:policy_rate | priced | UP` 🟡
- **S009** Oct + Dec hikes, 75bp: `ind:us:policy_rate | path | UP:75bp | 2026` 🟡
- **S010** Fed holds: `ind:us:policy_rate | decision | hold | event:fomc@2026-09` 🟡
- **S011** 30y to 5.75%: `INS:OUTRIGHT[bond:ust]:30y:cash | yield | UP to 5.75% | near` 🟡
- **S012** Buybacks futile: `policy:ust_buybacks | effectiveness | none | -` ✅
- **S013** Waller dovish dissent: `person:christopher_waller | vote | dissent:dovish | event:fomc@2026-09` ✅
- **S014** Bond market drives hawkishness: `bond:ust | market_condition | fragile -> person:kevin_warsh | stance | hawkish` ✅
- **S015** USD supported: `ccy:usd | value | UP | near` ✅
- **S016** Risk assets pressured: `?asset_class:risk | performance | DOWN` ❌ no asset-class entity
- **S017** Dovish presser: `event:fomc@2026-09 | tone | dovish` 🟡
- **S018** Bigger Bessent "house": `policy:ust_buybacks | size | UP (needed) | -` ✅ the metaphor read as more Treasury support
- **S019** Cost of disappointing raised: ❌ payoff asymmetry, not a state
- **S020** Flattening = credibility: `INS:CURVE[bond:ust]:2y/30y:cash | slope | DOWN -> org:fed | credibility | UP` 🟡
- **S021** Path after Sept uncertain: `ind:us:policy_rate | risk_balance | two_way | 2026Q4` 🟡
- **S022** Data soften / dovish turn: `ind:us:* | surprise | DOWN ; org:fed | stance | dovish` 🟡 indicator family
- **S023** Fed hikes in Sept: `ind:us:policy_rate | decision | hike | event:fomc@2026-09` 🟡 same slot as S001
- **S024** Inflation wording changes: ❌ wording of a communication
- **S025** Productivity wording: ❌ wording (`ind:us:productivity | trend | soft` would be 🟡)
- **S026** SEP discontinued: `event:fed_sep | status | discontinued | -` ✅
- **S027** 2029 dots ≈ longer run: `ind:us:policy_rate | level | ≈ meas:neutral_rate | 2029` 🟡
- **S028** 2027 dot: one cut to 3.875%: `ind:us:policy_rate | path | DOWN:25bp to 3.875% | 2027` 🟡
- **S029** Pencil in a 2027 cut: `ind:us:policy_rate | path | DOWN | 2027` 🟡
- **S030** Officials: hikes quell inflation: `ind:us:policy_rate | level | UP -> ind:us:pce | trend | DOWN` 🟡
- **S031** Fed adopts PCE methodology change: `ind:us:pce | data_quality | methodology_change | 2026-09-30` 🟡 only the methodology change resolves; the Fed's choice is not a state
- **S032** Easier after the fact: ❌ procedural judgement
- **S033** 2026 inflation −30bp: `ind:us:pce, ind:us:core_pce | value vs prior_sep | DOWN:0.3pp | 2026` ✅
- **S034** Growth −0.1pp: `ind:us:gdp | value vs prior_sep | DOWN:0.1pp to 2.2% | 2027 ; … to 2.1% | 2028` ✅
- **S035** Higher path lowers growth: `ind:us:policy_rate | path | UP -> ind:us:gdp | value | DOWN` 🟡
- **S036** 2027 inflation −0.1pp: `ind:us:pce, ind:us:core_pce | value vs prior_sep | DOWN:0.1pp | 2027` ✅
- **S037** Unemployment projections lower: `ind:us:unemployment_rate | value vs prior_sep | DOWN | 2026Q4, 2027Q4` ✅
- **S038** Other SEP changes modest: ❌ no subject
- **S039** Questions on the path: ❌ not a state
- **S040** Balancing act: ❌ not a state
- **S041** Impatient Warsh: `person:kevin_warsh | stance | hawkish | event:fomc@2026-09 ; ind:us:policy_rate | path | UP (series)` 🟡
- **S042** ≥100bp priced: `ind:us:policy_rate | priced | UP to ≥100bp | -` 🟡
- **S043** Market doubts 2% commitment: `org:fed | credibility | DOWN | -` ✅
- **S044** Why no July hike: ❌ not a state
- **S045** Underlying inflation progress insufficient: `ind:us:core_pce | trend vs target | above | -` ✅ "underlying" taken as core PCE
- **S046** Oil an upside risk: `cmdty:crude_oil | price | UP -> ind:us:pce | risk_balance | upside` ✅
- **S047** Contradicts earlier oil stance: ❌ consistency between speeches
- **S048** Trimmed mean = dovish signal: `org:fed | reaction_function[gauge] | trimmed_mean_pce -> event:fomc@2026-09 | tone | dovish` 🟡 needs a trimmed-mean basket on `meas:pce`
- **S049** JH more transparent: `org:fed | guidance | transparent | event:jackson_hole@2026-08` ✅
- **S050** Transparency cuts miscommunication: `org:fed | guidance | transparent -> org:fed | miscommunication_risk | DOWN` 🟡 the consequent variable is ad hoc
- **S051** Back to no substance: `org:fed | guidance | opaque | event:fomc@2026-09` ✅
- **S052** Fewer questions: ❌ not a state
- **S053** Pricing supports a hike: `ind:us:policy_rate | priced | hike (high prob) | event:fomc@2026-09` 🟡
- **S054** Dovish outcome = bigger move: ❌ compares move sizes across scenarios
- **S055** Reaction depends on comms: ❌ dependency with no direction
- **S056** ~100bp priced: `ind:us:policy_rate | priced | UP to 100bp (60-65bp by 2026Q4)` 🟡
- **S057** 2y +5-10, 30y −5-10: `INS:OUTRIGHT[bond:ust]:2y:cash | yield | UP:5-10bp ; INS:OUTRIGHT[bond:ust]:30y:cash | yield | DOWN:5-10bp` 🟡
- **S058** Credible Fed, lower yields: `org:fed | credibility | UP -> bond:ust | yield | DOWN` ✅
- **S059** Peak lowered: `ind:us:policy_rate | priced | DOWN` 🟡
- **S060** ~85bp priced: `ind:us:policy_rate | priced | DOWN to 85bp (40-45bp by 2026Q4)` 🟡
- **S061** 2y −5, 30y +5: `INS:OUTRIGHT[bond:ust]:2y:cash | yield | DOWN:5bp ; …:30y:cash | yield | UP:5bp` 🟡
- **S062** Confusion lifts yields: `org:fed | reaction_function | unclear -> bond:ust | yield | UP` ✅
- **S063** Front end down, twist steepen: `INS:OUTRIGHT[bond:ust]:2y:cash | yield | DOWN ; INS:CURVE[bond:ust]:2y/30y:cash | slope | UP` 🟡
- **S064** 65-75bp priced: `ind:us:policy_rate | priced | DOWN to 65-75bp (30-35bp by 2026Q4)` 🟡
- **S065** 2y −15-20, 30y +10-15: same pattern as S061 🟡
- **S066** Steepening sources: `ind:us:policy_rate | path | DOWN -> INS:CURVE[bond:ust]:2y/30y:cash | slope | UP ; org:fed | credibility | DOWN -> ind:us:term_premium | level | UP` 🟡
- **S067** Officials understand the risk: ❌ beliefs of actors
- **S068** Admin's choice: ❌ restates S003 as a dilemma
- **S069** Bessent/Warsh explain to Trump: ❌
- **S070** Trump won't like it: ❌
- **S071** Trump should understand: ❌
- **S072** Challenges belly bias: `INS:OUTRIGHT[bond:ust]:5y:cash | long | review` 🟡 "belly" taken as 5y
- **S073** Constructive long-end ASW: `INS:SPREAD[bond:ust|rate:sofr]:30y:cash | ? | maintain` 🟡 "constructive" has no direction
- **S074** Credibility supports demand: `org:fed | credibility | UP -> bond:ust | demand | UP` ✅
- **S075** Record dovish hold: `event:fomc@2026-09 | surprise | dovish (record)` 🟡
- **S076** IORB/ON RRP +25bp: `ind:us:iorb | decision | UP:25bp ; policy:fed_on_rrp | rate | UP:25bp | event:fomc@2026-09` ✅
- **S077** No balance-sheet change: `policy:fed_qt | status | unchanged | event:fomc@2026-09` ✅
- **S078** July presser soured USD: `event:fomc@2026-07 | tone | muddled -> org:fed | credibility | DOWN -> ccy:usd | sentiment | DOWN` 🟡
- **S079** Energy up, USD up: `cmdty:crude_oil | price | UP -> ccy:usd | value | UP` ✅
- **S080** Global repricing cut USD support: `geo:global | policy_stance | hawkish -> ccy:usd | value | DOWN` 🟡 the US-vs-G10 rate-differential mediator was dropped
- **S081** >3 hikes priced: `ind:us:policy_rate | priced | UP:>75bp` 🟡
- **S082** USD sideways except JPY: `ccy:usd | value | FLAT | 2026Q4 ; fx:usdjpy | spot | DOWN | 2026Q4` ✅
- **S083** Two-way USD risk: `ccy:usd | risk_balance | two_way | event:fomc@2026-09` ✅
- **S084** Broader dot support: `ind:us:policy_rate | path vs prior_sep | UP | 2026` 🟡 dot dispersion flattened to a direction
- **S085** Forecasts stay elevated: `ind:us:gdp | value | elevated ; ind:us:pce | value | elevated` ✅
- **S086** No guidance caps USD: `org:fed | guidance | none -> ccy:usd | value | UP (unlikely)` ✅
- **S087** USD drops sharply: `ccy:usd | value | DOWN (large) | near` ✅
- **S088** USD softens despite hike: `ccy:usd | value | DOWN | near` ✅
- **S089** No patience for one-and-done: ❌ market tolerance for a message
- **S090** Muddied messaging, USD down: `org:fed | reaction_function | unclear ; INS:OUTRIGHT[bond:ust]:30y:cash | yield | UP -> ccy:usd | value | DOWN` 🟡
- **S091** Restrained dots weigh on USD: `ind:us:policy_rate | path vs priced | below -> ccy:usd | value | DOWN` 🟡

## 6. Barclays FX Views, "Structural JPY weakness unchanged"

- **S001** Intervention cut JPY selling: `org:jp_mof | fx_intervention | BUY_JPY -> ccy:jpy | flows[net] | SELL DOWN | near` 🟡 org fallback
- **S002** BoJ pricing lifted JPY: `ind:jp:policy_rate | priced | UP -> fx:usdjpy | spot | DOWN:3 ; ccy:jpy | risk_premium[person:sanae_takaichi] | DOWN` 🟡
- **S003** USDJPY technically vulnerable: `fx:usdjpy | spot | DOWN | near` ✅
- **S004** No sustained JPY rally: `ccy:jpy | value | not UP | medium` ✅
- **S005** Rate gap still wide: `INS:SPREAD[rate:sofr|rate:tona]:2y:swap | level | wide` 🟡 tenor assumed
- **S006** Low ERP a headwind: `index:spx | equity_risk_premium | low -> ccy:jpy | value | DOWN` ✅
- **S007** Takaichi policy a headwind: `person:sanae_takaichi | policy_stance | reflationary -> ccy:jpy | value | DOWN` ✅
- **S008** Drivers of JPY rally: `ind:jp:policy_rate | priced | UP ; org:gpif | allocation[domestic] | UP -> ccy:jpy | value | UP` 🟡
- **S009** Takata lifted pricing: `person:hajime_takata | stance | hawkish -> ind:jp:policy_rate | priced | UP | 2026Q4` 🟡
- **S010** Break of 155: `fx:usdjpy | spot | below 155 -> fx:usdjpy | spot | DOWN` ✅
- **S011** GPIF board meeting: `?event:gpif_board@2026-08 -> org:gpif | allocation[domestic] | UP` ❌ no GPIF meeting series
- **S012** 155 resistance: `fx:usdjpy | resistance | 155 | near` ✅
- **S013** 158 resistance: `fx:usdjpy | resistance | 158 | near` ✅
- **S014** 152/150 support: `fx:usdjpy | support | 152, 150 | -` ✅
- **S015** Down to 145: `fx:usdjpy | spot | DOWN to 145 | -` ✅
- **S016** Below 150: `fx:usdjpy | spot | below 150 | -` ✅
- **S017** BoJ pricing fades: `ind:jp:policy_rate | priced | DOWN` 🟡
- **S018** Back to upper 150s: `fx:usdjpy | spot | UP to 157-159 | -` ✅
- **S019** Neither materialises: `ind:jp:policy_rate | path vs priced | below ; org:gpif | allocation | FLAT` 🟡
- **S020** Needs hawkish surprise: `ind:jp:policy_rate | surprise vs priced | hawkish -> ccy:jpy | value | UP` 🟡
- **S021** Pricing above Barclays: `ind:jp:policy_rate | priced vs author_path | above` 🟡
- **S022** Sep/Jan/Jul to 1.75%: `ind:jp:policy_rate | path | UP to 1.75% | 2027-07` 🟡
- **S023** No quarterly signal: `org:boj | guidance | no_quarterly_signal | -` ✅
- **S024** Gains limited: `ccy:jpy | value | UP (limited) | near` ✅
- **S025** Beyond-2% fuels JPY: `ind:jp:policy_rate | path | above 2% -> ccy:jpy | value | UP` 🟡
- **S026** 2% = neutral midpoint: `ind:jp:policy_rate | priced | 2% vs ind:jp:neutral_rate | at` 🟡
- **S027** Beyond-2% unlikely: `org:boj | guidance | above_2pct (unlikely) | -` ✅
- **S028** Pricing reversal amplifies: `ind:jp:policy_rate | priced | DOWN -> ccy:jpy | value | DOWN (amplified)` 🟡
- **S029** Ueno's reservations: `?person:ueno | stance[gpif_reallocation] | reserved` ❌ not in people registry
- **S030** Hits superlong JGBs: `org:gpif | allocation[domestic_bonds] | UP -> INS:OUTRIGHT[bond:jgb]:30y:cash | yield | DOWN` 🟡
- **S031** Avoid a Fed repricing: `ind:us:policy_rate | priced | UP (sharp) -> ccy:jpy | value | DOWN` 🟡
- **S032** GPIF gains reverse: `ccy:jpy | value | DOWN | -` ✅
- **S033** No reallocation: `org:gpif | allocation | FLAT | -` ✅
- **S034** Impact overstated: `org:gpif | allocation | UP -> ccy:jpy | value | UP (small)` ✅
- **S035** Change unclear: `org:gpif | allocation | uncertain | -` ✅
- **S036** No prior disclosure: ❌ procedure
- **S037** Yields justify 5-10pp: `bond:jgb | yield | high -> org:gpif | allocation[domestic_bonds] | UP:5-10pp` 🟡 allocation bucket
- **S038** JPY16-32trn buying: `ccy:jpy | flows[org:gpif] | BUY:16-32trn | -` ✅
- **S039** Less than intervention: `ccy:jpy | flows[org:gpif] | BUY -> ccy:jpy | value | UP (small)` ✅
- **S040** Regime beta above 149bp: ❌ threshold-dependent sensitivity
- **S041** Via hedged bonds: `org:gpif | allocation[hedged_foreign_bonds] | UP` 🟡
- **S042** Basis widening: `INS:BASIS[rate:tona|rate:sofr] | level | wider | near` 🟡 sign convention undefined
- **S043** Hedged shift buys JPY: `org:gpif | allocation[hedged_foreign_bonds] | UP -> ccy:jpy | flows[org:gpif] | BUY` 🟡
- **S044** Hedged yields low: `?hedged_yield[bond:ust, JPY] | level | low` ❌ derived quantity, no entity
- **S045** Hedged shift unlikely: `org:gpif | allocation[hedged_foreign_bonds] | UP (unlikely)` 🟡
- **S046** Others won't follow: `ccy:jpy | flows[jp_institutions] | BUY (none)` 🟡 participant
- **S047** Lifer sales small: `ccy:jpy | flows[life_insurers] | BUY (small)` 🟡
- **S048** JGBs attract lifers: `bond:jgb | yield | UP -> bond:jgb | flows[life_insurers] | BUY` 🟡
- **S049** Lifers see headwinds unchanged: `ccy:jpy | value | DOWN (structural)` ✅ the holder (lifers) is stripped
- **S050** Lifers resume selling: `ccy:jpy | flows[life_insurers] | SELL | near` 🟡
- **S051** Banks via repo: `ccy:jpy | flows[banks] | BUY (small)` 🟡
- **S052** Two-way USDJPY: `fx:usdjpy | risk_balance | two_way | near` ✅
- **S053** Headwinds unchanged: `ccy:jpy | value | DOWN (structural) | long` ✅
- **S054** 100 to 160 drivers: `INS:SPREAD[rate:sofr|rate:tona] | level | UP ; index:spx | equity_risk_premium | DOWN ; ccy:jpy | risk_premium[person:sanae_takaichi] | UP -> fx:usdjpy | spot | UP:100 to 160 | 5y` 🟡
- **S055** Term premium explains JPY: `ccy:jpy | risk_premium[person:sanae_takaichi] | UP ; ind:jp:term_premium | level | UP -> ccy:jpy | value | DOWN` 🟡
- **S056** BoJ more hawkish: `org:boj | stance | UP | -` ✅
- **S057** Below fair value 157: `fx:usdjpy | valuation | cheap vs fair_value:157 | -` ✅
- **S058** Spec positioning: `fx:usdjpy | positioning[speculative] | short` 🟡
- **S059** Fiscal expansion: `geo:jp | fiscal_stance | loose | -` ✅
- **S060** FY27 requests rise: `?ind:jp:govt_spending | budget_request | UP | FY2027` ❌ no public-spending measure
- **S061** Fiscal → term premia & JPY: `geo:jp | fiscal_stance | loose -> ind:jp:term_premium | level | UP ; ccy:jpy | value | DOWN` 🟡
- **S062** Structural selling persists: `ccy:jpy | flows[net] | SELL | long` ✅
- **S063** No fresh highs: `fx:usdjpy | spot | new_high (unlikely) | -` ✅
- **S064** Intervention concerns: `org:jp_mof | fx_intervention | risk elevated` 🟡
- **S065** What sustained gains need: `ind:us:policy_rate | path | DOWN ; index:spx | equity_risk_premium | UP ; person:sanae_takaichi | policy_stance | less_reflationary -> ccy:jpy | value | UP (sustained)` 🟡 the AI narrative behind the ERP leg is lost
- **S066** ~JPY7trn net buying in Q3: `ccy:jpy | flows[net] | BUY:7trn | 2026Q3` ✅
- **S067** Specs absorbed intervention: `ccy:jpy | positioning[speculative] | short (reduced)` 🟡
- **S068** Inward FDI eases selling: `ind:jp:fdi_inward | level | UP -> ccy:jpy | flows[net] | SELL DOWN` 🟡 needs an inward-FDI basket
- **S069** Not immediate: same subject 🟡
- **S070** NISA selling persists: `ccy:jpy | flows[households] | SELL` 🟡
- **S071** AI narrative unchanged: `?theme:ai_equity | salience | FLAT` ❌
- **S072** NISA accelerating: `ccy:jpy | flows[households] | SELL UP | 2026H2` 🟡
- **S073** Weak JPY drew FDI: `ccy:jpy | value | DOWN -> ind:jp:fdi_inward | level | UP` 🟡
- **S074** FDI income flows sell JPY: `ccy:jpy | flows[fdi_income] | SELL` 🟡
- **S075** Outflows > CA surplus: `ind:jp:capital_flows | outflow vs ind:jp:current_account | above` 🟡
- **S076** Households shift to investment: `?household_allocation[geo:jp] | risk_assets | UP` ❌ no household balance-sheet measure
- **S077** Household investing weakened JPY: `ccy:jpy | flows[households] | SELL -> ccy:jpy | value | DOWN` 🟡
- **S078** No shift back: `ccy:jpy | flows[households] | BUY (none)` 🟡
- **S079** Corporate ODI selling: `ccy:jpy | flows[corporates] | SELL, FLAT` 🟡
- **S080** M&A pace steady: `ccy:jpy | flows[corporates] | SELL, FLAT | 2026` 🟡
- **S081** M&A pressure: same 🟡
- **S082** FDI dividends weigh: `ind:jp:fdi_inward | level | UP -> ccy:jpy | flows[fdi_income] | SELL -> ccy:jpy | value | DOWN | long` 🟡
- **S083** US share small: `org:us_treasury | fx_intervention[fx:usdjpy] | size <5bn | 2026-07` 🟡
- **S084** Signal over amount: ❌ general principle
- **S085** US signalling role: ❌
- **S086** Funded by ESF: ❌ ESF not registered; a funding source is not a state
- **S087** Japan funded most: `org:jp_mof | fx_intervention | size large | 2026-07` 🟡
- **S088** Ample capacity: `ind:jp:fx_reserves | level | ample` 🟡
- **S089** Less need for intervention: `ccy:jpy | value | UP -> org:jp_mof | fx_intervention | prob DOWN` 🟡
- **S090** Initiative rests with Japan: ❌
- **S091** FIMA repo: `?policy:fed_fima_repo` ❌ not registered
- **S092** Depreciation pressure returns: `ccy:jpy | value | DOWN | -` ✅
