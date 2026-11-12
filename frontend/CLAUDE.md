# InColour: project context

InColour (working name was "State explorer") is a front-end mock for exploring what a corpus of documents says about the state of entities (US dollar, The Fed, gold...) and how those states link into narratives. The current deliverable is a single-file HTML mock, `state-explorer.html`, running on dummy data. The goal is to iterate on layout and interaction before building the real app.

## How to work on this

- Keep it a single HTML file with no build step until the design settles. Open it directly in a browser.
- Code style: concise, modular, clear encapsulation, inheritance where it fits (see `View`, `NView`). No clever one-liners that hurt readability when refactoring.
- UI style: wide desktop web interface, Bloomberg-like density, several entities visible at once. Three columns: narrow left and right side panels, and a wide middle column that holds the main view (`.grid` is `1fr 2.4fr 1fr`, with minimum widths on the side panels). Prefer visual, concise output over long text.
- Do not use localStorage for anything important. Put view state in one `Store` object so it can later sync to the URL.
- Check changes with `node --check` on the extracted script, and open the file in a browser. Test both views, both themes (light and dark), and a narrow window.

## Product concepts

- **Entity**: a thing in the world (US dollar, The Fed, FOMC meeting). Has a type.
- **Dimension**: a property of an entity with ordered states (`direction: up | flat | down`, `hike: no | unlikely | likely | yes`).
- **Entity state**: an entity at one state (Dollar, direction, up). Documents assert entity states.
- **State view**: pinned entities as cards. Each property shows a stacked time series of state shares, the leading state, and a Consensus / Debate / Mixed badge.
- **Narrative view**: a graph of entity states linked by claims ("A likely Fed hike lifts the dollar"). Tiers run top to bottom: trigger, 1st, 2nd, 3rd order. Node border shows consensus or debate. Link thickness is the number of documents, dashed amber means contested.
- **Hot topics**: not a view. A short list of states being discussed more than usual (count in window divided by baseline), shown at the top of the left column in both views.
- **Consensus and Debate**: lenses, not top-level views. Shown as dots in the entity list and as tabs in the Narrative states list.
- **Verdict rule** (`kindOf`): top share at least 0.55 is Consensus. Top two shares both at least 0.30 and within 0.15 is Debate. Otherwise Mixed. Thresholds are placeholders to tune.

## Current prototype

Layout: a sticky one-line header (logo, State view / Narrative view toggle, time bar, window buttons; all centred on the dot line `--ky`), then three columns. The middle one is the main view.

| | State view | Narrative view |
|---|---|---|
| Left | Hot topics, entity list with verdict dots | Hot topics, states list (Consensus / Debates / Mixed) |
| Middle | Entity cards (up to 6 pinned, 3 columns by 2 rows; when full, a new pin replaces the most recent one, last in first out) | Claim graph with 1 hop / 2 hops / full chain |
| Right | Document facets and list | Node or claim detail |

Shared time bar:
- Single-day cursor with the date above the dot. Drag, click, or use arrow keys (Shift for a week).
- Window buttons `1W 1M 3M 6M 1Y Max` set the lookback ending at the cursor. `Custom` opens date pickers.
- Double-click the bar to toggle range mode (two dots, start and end). Double-click again for a single date.
- Labels: the dot dates sit above the dots in both modes. The bar's first and last dates (the full data span) are always shown under each end of the bar (`.ticks`).
- In Narrative view the rail shows consensus / debate / mixed history for the focused state.

Document filters (State view): facets for entities, themes, events. The "Apply filters to charts" switch feeds the same filters into the cards (`Corpus.graphOk`).

## Code map (inside the single script)

- `Store`: pub/sub state. Keys: `view, pinned, end, w, custom, filter, fEnt, fTheme, fEvent, facet, more, apply, q, focus, edge, hops, ntab`.
- Time: `N = 546` days, `BASE` = 4 Nov 2026, `end` is a day index, `w` is window length in days.
- Dummy data: `DummyData` (8000 documents, drifting state distributions, themes, events), `Corpus`, `Aggregator`, `Hot`. **These are the parts that move to the backend.**
- Narrative: `NarrModel` (node distributions come from the same corpus; claim links are simulated by `EDGES`).
- Views: `Shell`, `EntityList`, `Workspace`, `Timeline`, `DocList` (State). `NRanking`, `NGraph`, `NDetail` (Narrative). State-only views are listed in `STATE_ONLY`.
- Styling: CSS variables for light and dark, IBM Plex Sans, state colour ramp `--s0..--s3`, verdict colours `--cons`, `--deb`.

## Backend design (decided, not built)

Split by job:
- **Graph database** holds meaning: EntityType, Dimension, State, Entity, EntityState, Alias (tag to entity, versioned), entity relations and hierarchy, and later claim edges (`CAUSES`) with document provenance.
- **Analytics store** (Postgres, ClickHouse or DuckDB) holds documents and assertions, and does the counting. Keep assertion rows keyed by `entity_state_id`.
- Entity hierarchy is materialised as a closure table into the analytics store, so queries never traverse the graph.

Assertions: one document yields many `(doc, entity, dimension, value, weight, confidence, passage_id)` rows. A hedged view splits weight across values (weights per doc, entity, property sum to 1). Document counts are always distinct documents. Dedupe by ancestor when rolling up to parent entities.

API sketch:
- `GET /entities` for the watchlist and verdict dots.
- `GET /states?entity=&from=&to=&themes=&events=&co_entities=` returns fixed-size daily arrays (counts per value, unspecified, mentions). The client does window maths on these. About 25 KB regardless of corpus size.
- `GET /documents` cursor-paginated, with the same filters.
- `GET /facets` top options with counts from rollups.
- Scale target: 100,000s of documents. The browser must never hold the corpus.

## Open questions

- Hot topics ranking: volume above baseline (now) or growth against the previous window?
- Should Narrative view respond to the State view's theme and event filters?
- Replay mode: animate the cursor and show when each node tips into consensus.
- Competing claim paths for contested links (separate edges, not one dashed edge).
- Day-level windows are exact in the mock. Confirm the real pipeline aggregates daily.
- Source weighting and key-voice influence (add a nullable `weight` now).

## Suggested next steps

1. Extract the single file into modules (`data`, `model`, `views/*`) with plain ES modules and no build.
2. Replace `DummyData` with a mock API module returning the response shapes above, including paginated documents and fixed-size `/states` arrays.
3. Sync `Store` to the URL hash so views are shareable and deep-linkable.
4. Add keyboard shortcuts and an entity search command bar.
5. Add a replay mode to the Narrative view.
6. Once the design is stable, port to React + TypeScript + Vite, keeping `Store` as the state contract.
