# Geography, Currency & Market Grouping Ontology

## 1. Architectural Principles

Build a **declarative, composable ontology** that separates taxonomy, relationships, entity instances and inference.

| Component | Technology | Responsibility |
|---|---|---|
| Taxonomy | YAML | Entity classes, subclasses and inheritance |
| Property ontology | YAML | Typed relationships, cardinality and inverses |
| Reference data | YAML → Database | Canonical countries, regions, currencies and relationships |
| Market groupings | YAML | Set-based definitions and compositions |
| Schema validation | Pydantic | Structural and type validation |
| Ontology compiler | Python | Inheritance, traversal, inference and membership resolution |
| Entity registry | Database | Canonical identities, aliases, attributes and relationships |

**Core principle:** Store the most specific authoritative facts and derive broader classifications through explicit rules.

Keep YAML declarative. Implement computational logic in Python.

---

## 2. Taxonomy

Geography and Currency belong to separate taxonomic branches, connected through typed relationships.

```text
Entity
├── Geography
│   ├── Country
│   ├── Territory
│   ├── Region
│   └── GeographicGroup
│
└── FinancialInstrument
    ├── Currency
    ├── CurrencyPair
    └── CurrencyBasket
```

The taxonomy defines **types of objects**, not individual objects.

- `Japan` is an instance of `Country`.
- `EasternAsia` is an instance of `Region`.
- `JPY` is an instance of `Currency`.
- `EUR/USD` is an instance of `CurrencyPair`.
- `APAC` is a defined geographic or market grouping.

Avoid creating subclasses for every country, currency or regional combination.

### YAML taxonomy

`config/ontology/types/geography.yaml`

```yaml
Geography:
  abstract: true

Country:
  parent: Geography

Territory:
  parent: Geography

Region:
  parent: Geography

GeographicGroup:
  parent: Geography
```

`config/ontology/types/financial_instrument.yaml`

```yaml
FinancialInstrument:
  abstract: true

Currency:
  parent: FinancialInstrument

CurrencyPair:
  parent: FinancialInstrument

CurrencyBasket:
  parent: FinancialInstrument
```

Properties defined on a superclass can be inherited by its subclasses.

Taxonomic inheritance (`is-a`) must remain distinct from composition (`has-a` or `member-of`).

---

## 3. Geographic Hierarchy — UN M49

Use **UN M49 as the authoritative geographic reference**, extended with bespoke market-relevant regions.

Assign each country or territory to its most specific M49 subregion. Compile higher-level memberships through the region hierarchy.

```text
Japan
  └── Eastern Asia
        └── Asia
```

Therefore:

```python
country.subregion  # EasternAsia
country.region     # Asia
```

### Reference data

`data/reference/geography/countries.yaml`

```yaml
JP:
  name: Japan
  type: Country
  m49: "392"
  subregion: EasternAsia

FR:
  name: France
  type: Country
  m49: "250"
  subregion: WesternEurope
```

`data/reference/geography/regions.yaml`

```yaml
EasternAsia:
  type: Region
  parent: Asia
  standard: UN_M49

WesternEurope:
  type: Region
  parent: Europe
  standard: UN_M49
```

Maintain the original M49 dataset separately from custom extensions.

A country should have one authoritative subregion assignment within each M49 version. Custom geographic regions may overlap.

---

## 4. Bespoke Geographic Regions

M49 lacks certain classifications commonly used in financial markets, particularly **Middle East** and **Asia-Pacific**.

Define these as explicit or computed geographic sets rather than changing the M49 hierarchy.

| Custom region | Definition |
|---|---|
| Middle East | Curated set of countries |
| APAC | Asia ∪ Oceania, subject to convention |
| MENA | Middle East ∪ Northern Africa |
| EMEA | Europe ∪ Middle East ∪ Africa |
| APAC ex-Japan | APAC − Japan |

Countries may belong to multiple geographic sets. For example, Egypt can belong to both Northern Africa and a bespoke Middle East definition.

Set operations eliminate duplicate memberships automatically.

---

## 5. Market Groupings

Market groupings are **compositions of geographic regions, market classifications or explicit entity sets**, not subclasses of countries or regions.

Support five operations:

| Operator | Meaning |
|---|---|
| `union` | Combine memberships |
| `difference` | Exclude memberships |
| `intersection` | Retain shared memberships |
| `explicit` | Manually define members |
| `filter` | Select using classification properties |

### YAML definitions

`config/ontology/groups/market.yaml`

```yaml
MiddleEast:
  member_type: Country
  definition:
    difference:
      - union:
          - WesternAsia
          - Egypt
      - Cyprus

APAC:
  member_type: Country
  definition:
    union:
      - Asia
      - Oceania

EMEA:
  member_type: Country
  definition:
    union:
      - Europe
      - MiddleEast
      - Africa

APAC_EX_JAPAN:
  member_type: Country
  definition:
    difference:
      - APAC
      - Japan
```

These definitions are illustrative: the precise Middle East and APAC membership conventions should be curated.

### Important market groupings

- **Regional:** Americas, LATAM, EMEA, APAC, CEE, CEEMEA, MENA.
- **Market classifications:** DM, EM, FM, EM Asia, EM Europe, EM LATAM.
- **Currency universes:** G10 FX, EM FX.
- **Institutional groups:** G7, G20, GCC, BRICS, Euro Area.

Distinguish geographic groupings from market classifications and institutional memberships.

Market classifications should retain their source, asset-class scope and validity period where relevant. For example, an MSCI emerging-market equity universe may differ from a macro or FX desk's EM universe.

---

## 6. Currency Ontology

Currencies belong to the Financial Instrument ontology but maintain relationships with geographic and organisational entities.

```text
Japan ──usesCurrency──→ JPY

France ──usesCurrency──→ EUR

EUR/USD
  ├──baseCurrency──→ EUR
  └──quoteCurrency─→ USD
```

### Currency registry

`data/reference/currencies.yaml`

```yaml
JPY:
  type: Currency
  name: Japanese yen
  iso_code: JPY

EUR:
  type: Currency
  name: Euro
  iso_code: EUR

USD:
  type: Currency
  name: US dollar
  iso_code: USD
```

Do not encode currency usage through taxonomic inheritance. Currency usage is a relationship that may be many-to-many and time-dependent.

Currency market groupings, such as G10 FX, should refer directly to currencies rather than automatically inheriting memberships from country groups.

---

## 7. Property Ontology

Define relationships centrally, with explicit domain, range, cardinality and inverse semantics.

`config/ontology/properties/geography.yaml`

```yaml
parentRegion:
  domain: Region
  range: Region
  inverse: hasSubregion

assignedSubregion:
  domain: [Country, Territory]
  range: Region
  cardinality: one
  inverse: containsGeography

usesCurrency:
  domain: [Country, Territory]
  range: Currency
  cardinality: many
  inverse: usedIn

baseCurrency:
  domain: CurrencyPair
  range: Currency
  cardinality: one

quoteCurrency:
  domain: CurrencyPair
  range: Currency
  cardinality: one
```

### Relationship semantics

Distinguish:

1. **Direct relationships:** Explicitly stored facts.
2. **Exact inverses:** Logically equivalent reverse relationships.
3. **Derived relationships:** Computed through property chains.
4. **Related relationships:** Conceptually associated but not logically equivalent.

For example:

```text
Japan → assignedSubregion → EasternAsia
EasternAsia → parentRegion → Asia
```

Derive:

```text
Japan → belongsToRegion → Asia
```

Do not confuse derived membership with an exact inverse.

---

## 8. Canonical Entity Registry & Aliases

Each entity has one stable canonical identifier. Aliases are separate lexical records pointing to possible canonical entities.

```yaml
entity_id: currency_usd
canonical_name: US dollar

aliases:
  - USD
  - US dollar
  - Greenback
```

Canonicalisation should use:

1. Exact identifiers and aliases.
2. Normalised and fuzzy lexical matching.
3. Entity-type constraints.
4. Contextual disambiguation.
5. Registry linking or provisional entity creation.

A shared alias does not imply identical entities.

The registry should support entity merges, redirects, provenance and historical validity.

---

## 9. Pydantic Validation

Pydantic defines the structure of YAML declarations, rather than hardcoding each country or currency into Python classes.

```python
from pydantic import BaseModel, Field

class EntityTypeDefinition(BaseModel):
    parent: str | None = None
    abstract: bool = False

class PropertyDefinition(BaseModel):
    domain: str | list[str]
    range: str
    cardinality: str = "many"
    inverse: str | None = None

class CountryRecord(BaseModel):
    name: str
    type: str = "Country"
    m49: str
    subregion: str

class CurrencyRecord(BaseModel):
    name: str
    type: str = "Currency"
    iso_code: str
```

Pydantic validates structural correctness. A separate semantic validator checks:

- All referenced classes and entities exist.
- Parent-class relationships are valid and acyclic.
- Property domains and ranges are compatible.
- Inverse properties are consistently defined.
- Group expressions resolve to the required entity types.
- Geographic hierarchies and group definitions contain no circular dependencies.
- Membership constraints and temporal validity are respected.

---

## 10. Ontology Compilation

Compile the ontology once at startup or whenever its version changes.

```text
YAML definitions
      ↓
Pydantic validation
      ↓
Semantic validation
      ↓
Ontology compilation
      ├── Class inheritance
      ├── Property resolution
      ├── Inverse relationships
      ├── Geographic ancestry
      └── Group expressions
      ↓
Indexed compiled ontology
      ↓
Entity registry enrichment
```

The compiler should support:

```python
registry.get_region("Japan")
# Asia

registry.members("APAC_EX_JAPAN")
# Compiled geographic membership

registry.get_groups("Japan")
# Relevant geographic and market groups
```

### Performance

- Build ancestry and reverse-relationship indexes.
- Cache frequently requested group memberships.
- Resolve compositions recursively.
- Detect circular references.
- Invalidate cached results when dependencies change.
- Preserve provenance for derived relationships.
- Support `as_of` queries for historical classification.

Avoid materialising every possible relationship. Cache only frequently used derived views.

---

## 11. Project Structure

```text
config/
  ontology/
    types/
      geography.yaml
      financial_instrument.yaml
      organization.yaml
      indicator.yaml
      person.yaml

    properties/
      geography.yaml
      financial_instrument.yaml

    groups/
      geographic.yaml
      market.yaml
      currency.yaml

data/
  reference/
    geography/
      countries.yaml
      regions.yaml
    currencies.yaml

src/
  ontology/
    schemas.py
    loader.py
    validator.py
    compiler.py

  registry/
    models.py
    repository.py

  resolution/
    alias_index.py
    canonicalizer.py

  geography/
    hierarchy.py
    grouping.py
```

---

## 12. Final Design Principles

1. **Separate types from instances.** `Country` is a class; `Japan` is an entity.
2. **Use M49 as the geographic backbone.** Assign leaf-level subregions and derive higher-level geography.
3. **Keep custom regions as overlays.** Do not modify the authoritative M49 hierarchy.
4. **Build market groups compositionally.** Use explicit sets, unions, differences, intersections and filters.
5. **Keep currencies separate from geography.** Connect them through typed relationships.
6. **Define properties centrally.** Specify domain, range, cardinality and inverse behaviour.
7. **Separate exact inverses from inferred relationships.**
8. **Treat aliases as lexical mappings, not identity assertions.**
9. **Use YAML for declarations, Pydantic for validation and Python for computation.**
10. **Compile once, query many times.** Index and cache common results.

**Overall objective:** Maintain a minimal, canonical set of authoritative entity facts, then derive geographic, market and financial relationships through a validated, compositional ontology.
