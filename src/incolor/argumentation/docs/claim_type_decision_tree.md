# Claim-type decision tree

Apply the tests in order; the first "yes" decides the type (taxonomy v0.8). Colours mirror `config/theme/argument_map.json`.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 22, "rankSpacing": 36}}}%%
flowchart LR
    Q1{Concrete action on a<br/>named exposure?} -- yes --> R[RECOMMENDATION]
    Q1 -- no --> Q2{Worth vs price,<br/>fundamentals or<br/>asset coverage?}
    Q2 -- yes --> V[VALUATION]
    Q2 -- no --> Q3{Measurable quantity<br/>with value and horizon?}
    Q3 -- yes --> F[FORECAST]
    Q3 -- no --> Q4{Identifiable future<br/>event expected?}
    Q4 -- yes --> PR[PREDICTION]
    Q4 -- no --> Q5{Exposure held by<br/>market participants?}
    Q5 -- yes --> P[POSITIONING]
    Q5 -- no --> Q6{Beliefs or mood of<br/>market participants?}
    Q6 -- yes --> S[SENTIMENT]
    Q6 -- no --> Q7{Reported fact with a<br/>substantive number?}
    Q7 -- yes --> D[DATA_POINT]
    Q7 -- no --> Q8{Reported fact<br/>without a number?}
    Q8 -- yes --> O[OBSERVATION]
    Q8 -- no --> W[VIEW]

    classDef question fill:#ffffff,stroke:#333333,stroke-width:1.5px,color:#111111
    classDef rec fill:#f8c9c9,stroke:#8b1a1a,stroke-width:2px,color:#111111
    classDef val fill:#e3d4f5,stroke:#5b2c8f,stroke-width:2px,color:#111111
    classDef fc fill:#c9ecc9,stroke:#1a6b3a,stroke-width:2px,color:#111111
    classDef pred fill:#fff2a8,stroke:#9a7d00,stroke-width:2px,color:#111111
    classDef pos fill:#fdd9b5,stroke:#b35900,stroke-width:2px,color:#111111
    classDef sent fill:#bff0f5,stroke:#00838f,stroke-width:2px,color:#111111
    classDef dp fill:#d4d4d4,stroke:#5f5f5f,stroke-width:2px,color:#111111
    classDef obs fill:#e6e6e6,stroke:#888888,stroke-width:2px,color:#111111
    classDef view fill:#c9dcf8,stroke:#1a3f8b,stroke-width:2px,color:#111111
    class Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8 question
    class R rec
    class V val
    class F fc
    class PR pred
    class P pos
    class S sent
    class D dp
    class O obs
    class W view
    linkStyle default stroke:#333333,stroke-width:1.5px,color:#9a9a9a
```

| Type | Colour | Allowed roles |
|---|---|---|
| RECOMMENDATION | red `#f8c9c9` | core claim, supporting, risks, conditions, catalysts, qualifiers |
| VALUATION | purple `#e3d4f5` | core claim, supporting, risks, conditions, catalysts, qualifiers |
| FORECAST | green `#c9ecc9` | core claim, supporting, risks, conditions, catalysts, qualifiers |
| PREDICTION | yellow `#fff2a8` | core claim, supporting, risks, conditions, catalysts, qualifiers |
| POSITIONING | orange `#fdd9b5` | all roles; rationale when it only reports holdings or flows |
| SENTIMENT | cyan `#bff0f5` | all roles; rationale when it only reports mood |
| VIEW | blue `#c9dcf8` | core claim, supporting, risks, conditions, catalysts, qualifiers |
| DATA_POINT | dark grey `#d4d4d4` | rationale only |
| OBSERVATION | grey `#e6e6e6` | rationale only |
