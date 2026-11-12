# Temporal Relationship Semantics

## Purpose

Temporal relationship semantics define **when a relationship is valid**, **when the registry knew or recorded it**, and how time propagates through **inverse relationships, inference, grouping and classification**.

For the entity ontology and financial narrative graph, use a **bitemporal relationship model** with explicit valid time and transaction (record) time.

## 1. Two temporal dimensions

| Dimension | Meaning | Example |
|---|---|---|
| **Valid time** | When the relationship was true in the modelled world | Country X was a member of Group Y from 2010 to 2020 |
| **Transaction time** | When the registry recorded or maintained the assertion | The registry learned about the membership in 2022 |

Use **half-open intervals** `[from, to)`: inclusive start, exclusive end. A `null` endpoint is unbounded; it does not necessarily imply permanence.

```yaml
subject: country_X
predicate: memberOf
object: group_Y

valid_from: 2010-01-01
valid_to: 2020-01-01

recorded_from: 2022-03-15T10:00:00Z
recorded_to: null
```

## 2. Temporal policy by relationship type

The **property schema** should declare how relationships are treated temporally, without hard-coding dates in each property definition.

| Property | Recommended treatment | Illustration |
|---|---|---|
| `subclassOf` | Ontology-version scoped | `CurrencyPair` is a `FinancialInstrument` |
| `assignedSubregion` | Classification-version scoped | Japan → Eastern Asia under a specific UN M49 edition |
| `parentRegion` | Classification-version scoped | Eastern Asia → Asia |
| `usesCurrency` | Valid-time scoped | France → EUR |
| `memberOf` | Valid-time or group-definition-version scoped | UK → EU |
| `employedBy` | Valid-time scoped | Person → Organisation |
| `issuedBy` | Usually a stable historical fact | Bond → Issuer |
| `baseCurrency` | Usually intrinsic/immutable for the instrument identity | EUR/USD → EUR |
| `classifiedAs` | Source-, context- and time-dependent | Country → Emerging Market |
| `aliasOf` | Lexical, potentially temporal | Former organisational name → Entity |

Three useful policies:

1. **`immutable`** — intrinsic under the chosen entity identity rules; corrections are still possible.
2. **`valid_time`** — may change in the world over historical time.
3. **`versioned`** — depends on an external classification/ontology edition or a named definition.

All three can retain transaction-time audit history. **Static is not the same as timeless.**

### Example property declarations

```yaml
usesCurrency:
  domain: Country
  range: Currency
  cardinality: many
  temporal:
    mode: valid_time
    precision: date
    allow_open_interval: true

assignedSubregion:
  domain: Country
  range: Region
  cardinality: one
  temporal:
    mode: versioned
    version_source: UN_M49

baseCurrency:
  domain: CurrencyPair
  range: Currency
  cardinality: one
  temporal:
    mode: immutable
```

## 3. Temporal inference and compilation

A derived relationship can be valid only at times when **all required premises are simultaneously valid**.

Example:

```text
Country X ─memberOf──────→ Group Y       [2010, 2020)
Group Y   ─classifiedAs──→ EconomicBloc  [2015, 2025)

Derived relation                         [2015, 2020)
```

For a rule requiring all premises:

\[
V_{\text{derived}} = \bigcap_{i=1}^{n} V_i
\]

If the intersection is empty, emit no derived assertion. Exact inverse edges retain the same validity interval as their source assertion.

For **unions**, preserve the union of valid membership intervals; only coalesce adjacent intervals when their definitions and provenance are compatible. For **differences**, evaluate the included and excluded memberships over time, not just against a present-day snapshot.

### Example: group compilation

`APAC_EX_JAPAN = APAC − Japan` describes a set-valued grouping. The compiler should evaluate APAC membership and then exclude Japan from the output at each requested date, using the applicable group-definition version.

Keep **asserted**, **inferred**, and **materialised** relationships distinguishable. Derived assertions should retain the rule identifier and supporting assertion IDs so they can be recomputed or invalidated.

## 4. Temporal cardinality

Cardinality constraints apply **within the appropriate temporal and classification context**, not necessarily across an entity's entire history.

For example:

```yaml
assignedSubregion:
  cardinality: one
  temporal:
    mode: versioned
```

A country may have one assigned M49 subregion in one edition and a different assignment in another without violating the rule. Likewise, an organisation can have successive headquarters; a `max_one` rule might prohibit overlapping active assignments only if exclusivity is genuinely part of the relationship semantics.

Do not impose singular cardinality on naturally concurrent relationships, such as countries using multiple currencies.

## 5. Assertion provenance, corrections and audit history

Keep validity, recording history, source evidence and classification-version metadata separate.

```yaml
assertion_id: rel_123

subject: country_X
predicate: memberOf
object: group_Y

valid_time:
  from: 2010-01-01
  to: 2020-01-01

transaction_time:
  from: 2022-03-15T10:00:00Z
  to: null

source_id: source_456
definition_version: "2022"
status: asserted
```

When correcting an assertion, **close its previous transaction-time interval** and create a replacement record. Do not silently overwrite the old state. This preserves what the system previously believed.

### Two distinct historical queries

```python
registry.relationships(
    entity="country_X",
    valid_at="2018-01-01",
)
# Relationships valid in 2018 according to current registry knowledge.

registry.relationships(
    entity="country_X",
    valid_at="2018-01-01",
    known_at="2022-06-01",
)
# What the registry believed in June 2022 about 2018.
```

When using an externally defined taxonomy such as UN M49 or a provider-defined EM classification, specify which edition or effective definition the query is evaluating.

## 6. Pydantic and Python implementation

Define temporal data shapes in Pydantic; declare **property-specific policies** in YAML; enforce cross-entity and temporal consistency in the Python semantic validator.

```python
from datetime import date, datetime
from enum import StrEnum
from pydantic import BaseModel


class TemporalMode(StrEnum):
    IMMUTABLE = "immutable"
    VALID_TIME = "valid_time"
    VERSIONED = "versioned"


class TemporalPolicy(BaseModel):
    mode: TemporalMode
    precision: str = "date"


class RelationshipAssertion(BaseModel):
    subject: str
    predicate: str
    object: str

    valid_from: date | None = None
    valid_to: date | None = None

    recorded_from: datetime
    recorded_to: datetime | None = None

    source_id: str | None = None
    definition_version: str | None = None
```

Add semantic validation for:

- Interval ordering, half-open boundary semantics and timestamp consistency.
- Invalid overlaps where cardinality requires exclusivity.
- Version compatibility and definition changes.
- Domain/range constraints and relationship references.
- Temporal intersection for inferred property chains.
- Traceable dependencies for inverse and derived edges.

## 7. Distinguish narrative time from registry fact time

A research note published in 2026 could **predict** that a country will join an economic grouping in 2028.

These are separate facts:

| Field | Meaning |
|---|---|
| Claim publication time | 2026 |
| Predicted event time | 2028 |
| Claim modality | Prediction |
| Registry membership validity | Unchanged until independently established |

Never promote a predicted or hypothetical relationship from a narrative directly into an **asserted registry relationship**.

## 8. Implementation principle

> Every relationship assertion supports bitemporal bookkeeping, while its property schema declares whether the relationship is immutable, valid-time-dependent or classification-version-dependent. Derived relationships are valid over the temporal intersection of their premises and retain full provenance and rule dependencies.

This enables historically correct geographic and market-group compilation while separating observed facts, classification changes, historical corrections and narrative predictions.
