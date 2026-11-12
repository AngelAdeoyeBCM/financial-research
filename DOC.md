# ColourKG: Entities and States

## 1. Ontology

ColourKG separates two layers: what research **says** (discourse) and what it says it **about** (the world). The **state** is where the two layers meet.

![Ontology: discourse layer and world layer](entity_state_ontology.svg)

- **Documents** contain **arguments**.
- **Arguments** consist of **claims**.
- **Claims** assert propositions about **entity states**.
- **State → state** edges (causes, implies) form the narrative graph.

---

## 2. Entity versus state

| | Entity | State |
|---|---|---|
| Question it answers | *What* is it? | *What condition* is it in, or will it be in? |
| Persistence | Exists regardless of what anyone says | Exists only because a claim asserts it |
| Changes over time? | No. Its identity is fixed. | Yes. That's the point. |
| Example | 10y OAT-Bund spread | Spread widening by Q1 |
| How it's logged | Registry entry, or built from a spec | Extracted from claims, merged by key |

### Rule for attributes

- **If it defines identity, it's an entity property.** Examples: tenor `10Y`, family, issuer.
- **If it varies over time and someone could make a claim about it, it's a state variable.** Examples: spread level, implied vol, France's credit rating.

---

## 3. Anatomy of a state

Example: *"10y OAT-Bund spread widening by Q1"*

| Component | Value | Notes |
|---|---|---|
| **Entity** | `INS:SPREAD[OAT-BUND]:10Y` | Resolved through the entity resolution pipeline |
| **Variable** | `level` | Which aspect of the entity. "OAT vol rising" and "OAT yield rising" are different states. |
| **Change** | `UP` | Normalised direction, not the word "widening" |
| **Magnitude** | +15bp, or none | Optional |
| **Horizon** | `2026Q1` | Bucketed, so similar states merge |

### What stays on the claim, not the state

| On the claim | Examples |
|---|---|
| Modality | observed / expected / conditional |
| Confidence | hedged, high-conviction |
| Provenance | author, document, date |
| Claim kind | view versus trade recommendation |

**Why this split matters:** if five analysts say "OAT-Bund wider by Q1" and two say "tighter", that gives **two state nodes** with five and two claims attached. Agreement and disagreement become countable.

---

## 4. State keys

States are **built, like instruments**. Each gets a deterministic key, so identical propositions from different documents land on the same node:

```
STATE[<entity_id> | <variable> | <change> | <horizon>]

STATE[INS:SPREAD[OAT-BUND]:10Y | level | UP | 2026Q1]
```

---

## 5. Direction vocabularies

Direction words depend on the instrument shape. **"Tightening" means opposite things for a spread and for a policy rate.**

| Shape | Canonical variable | Up | Down |
|---|---|---|---|
| Spread | level | widen | tighten |
| Curve spread (2s10s) | slope | steepen | flatten |
| Bond | yield | sell off / cheapen | rally / richen |
| FX pair (EURUSD) | spot | EUR strengthens | USD strengthens |
| Option / vol | implied vol | richen / vol up | cheapen / vol down |
| Policy rate | rate | hike / tighten | cut / ease |
| Indicator | print | accelerate / beat | slow / miss |

### Implementation notes

- Each shape class carries its own vocabulary, e.g.

  ```python
  class Spread(Instrument):
      DIRECTIONS = {"widen": UP, "tighten": DOWN}
  ```

- **Bond inversion:** "Treasuries rally" means the yield goes down. Pick one canonical variable per shape (yield, not price) and convert into it.
- **FX inversion:** a claim on JPY/USD flips sign when normalised to USDJPY. This reuses the `inverted` flag from instrument resolution.
- **Trade expressions split in two:** "5s20s flattener" becomes the instrument (5s20s spread) plus a direction (DOWN on slope). The direction goes on the state, and the recommendation goes on the claim.

---

## 6. Default variables by entity type

| Entity type | Default variable | Other variables |
|---|---|---|
| Instrument | level, yield or spot (depends on shape) | vol, positioning, carry |
| PolicyTool | setting (rate or size) | status (announced, active, ended) |
| Indicator | print | surprise vs consensus, trend |
| Actor | stance | rating, reaction function |
| Index | level | |

---

## 7. Hierarchy carries over to states

A state on a child entity counts as evidence for the same state on its family:

```
OAT-Bund wider  ─┐
BTP-Bund wider  ─┼──►  EGB spreads wider
SPGB-Bund wider ─┘
```

This is how narrative-level views come out of instrument-level claims.

---

## 8. Stage 1 actions

Keep logging entities as now. Add two things, because they're cheap and everything later depends on them:

1. **A variable list per entity type** (section 6).
2. **A direction vocabulary per shape** (section 5).

States themselves arrive with claim extraction in stage 2.
