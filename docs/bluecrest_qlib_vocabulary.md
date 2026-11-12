# BlueCrest market vocabulary (QLib): summary for ontology alignment

## 1. Source of truth

| Item | Location |
|---|---|
| Master QLib source | SVN `https://risksvn/svn/QR/Qlib/trunk/src/`. Read-only copies are pulled into each repo as SVN externals. |
| Newest local copy | `C:\src\QXL\src\BlueCrest.QR.QLib.Core.Src\` (dated 22/09/2025) |
| **Grammar and all type keywords** | `...\QLib.Core.Src\Identifiable\IdentityTypes.cs` (about 1,000 lines) |
| Enum value lists | `...\QLib.Core.Src\Market\Enums\*.cs` and `...\Market\Instrument\{CurrencyCode,ReferenceIndex}.cs` |
| Definition classes | `...\QLib.Core.Src\Market\Instrument\*` (e.g. `CurrencyDefinition.cs`) and `...\Market\Definitions\*` |
| Definition data (values) | **Use `C:\Temp\QCL\5.4.528\cfg\market\definitions\`** (`ccy\` 110 files, `inst\` 866 files, plus `*.yml`). It is shipped with the production QCL build that pyQCL loads, and is the largest set. Upstream: SVN `QR/Qlib/trunk/cfg` (QXL/QNL checkouts, ~906 files). The Junko repos use a different upstream, `Shared/BlueCrest.Market.Environment/trunk/cfg`, with a different layout (`currency\`, `instrument\`); avoid unless you need server-specific config. |
| Design notes | `C:\src\FO_2\MarketApps\JunkoPosition\trunk\cfg\readme.txt` |

The same vocabulary is used by every consumer: the Junko servers (JunkoMarket, JunkoPosition), QXL (Excel), QNL (.NET) and QCL/pyQCL (Python). Each one passes ID strings to QLib, which parses them with `IdentityTypes.Parser`.

## 2. Identifier grammar

```
keyword[arg1, arg2, ..., key:value, ...]      e.g. flt[USD,CMS,60M]
```

- **Keyword:** a short lowercase code that names the structure type (`ccy`, `idx`, `flt`, `zc`, `crv`).
- **Positional arguments:** declared per type, in a fixed order. Each one is an enum value, a property or another identifier.
- **Nesting:** an argument can itself be an identifier, e.g. `crv[inst[idx[USD,SOFR]]]` or `bsw[flt[EUR,EURIBOR,3M],flt[USD,LIBOR,3M]]`.
- **Qualifiers:** extra `key:value` pairs refine an ID. Examples seen: `ref:SOFR`, `maturity:1D`, `crv-type:derived`, `srfc-type:vol`, `model:dsabr`, `riskStyle:none`, `obs-start:2006-01-05`. Bare enum values also appear as qualifiers, e.g. `ois` in `zc[USD,LIBOR,ois]`. They appear to be matched to their enum type by value; this was inferred from examples, not from the parser code.
- **Wildcards:** `*` is used in factory patterns, e.g. `irs[flt[*,*,*]]` or `srf[inst[swpo[*]]]`. The most specific pattern must come first.
- **Timestamped instances:** in query results an ID can carry `@<datetime>`, e.g. `crv[inst[eto[if,SFR]]]@2025-03-13 23:59:59`.
- **Kinds of ID type in `IdentityTypes.cs`:**
  - 203 structure types (the keywords)
  - 123 enum types
  - 69 property types (`key:value`)

## 3. Core structure keywords, grouped by domain

**Conventions and reference objects**

| Keyword | Arguments | Meaning |
|---|---|---|
| `ccy` | CurrencyCode | Currency definition |
| `cntry` | CountryCode | Country |
| `idx` | Ccy, ReferenceIndex | Rate, inflation or commodity index |
| `idx-cfg` | Ccy, ReferenceIndex | Index configuration |
| `flt` | Ccy, ReferenceIndex, maturity | Floating leg convention |
| `fix` | Ccy, ReferenceIndex | Fixed leg convention |
| `fxng` | Ccy, ReferenceIndex | Fixing |
| `bnd` | Country, BondFamily, Ccy | Bond index or family |
| `et`, `eto` | AssetType, ChainIdentifier | Exchange-traded family or option chain |
| `spec` | idx, ParameterType | Pricing spec |
| `hols` | — | Holidays |
| `chain` | ChainName | Chain |
| `dsc` | — | Discounting override |
| `leg`, `beta` | Ccy | Leg, beta |

**Instruments.** Most take Ccy as the only positional argument; exceptions are shown in brackets.

- **Rates:** `swp`, `irs[flt]`, `bsw[flt]`, `ffs[fix,fix]`, `xcs[leg,leg]`, `fra`, `ois`-style `cbs`, `onswp`, `swpo`, `mcswpo`, `fswpo`, `cswpo`, `xswpo`, `cap`, `cmscap`, `dcap`, `cmsspo`, `spcf`, `rf`, `irfo[Ccy,Chain]`, `swpf`, `bswp[Ccy,maturity]`, `frasprd`, `sprdfut`, `fly`, `ss`, `swp-spd`, `aswp`, `repo`
- **Benchmark curve instruments:** `irf[Ccy,Ref,maturity]`, `csh[Ccy,Ref,maturity]`, `hyb[InstCat,Ccy,Ref,maturity]`, `hyb-x[InstCat,Ccy,Ref,maturity]`, `hyb-b[InstCat,Ccy,Country,BondFamily]`, `pay`
- **Bonds:** `bnd-ins[BondClass,BondSubCat,Country,Ccy]`, `bond[isin]`, `bf`, `bfo[Ccy,Chain]`, `ctd[inst]`, `bndfwd`, `bndtrs`, `bndcfd`, `bond-opt`, `cbond[isin]`, `bndcnv[Country,BondClass,Ccy]`
- **Inflation:** `ins`, `insf`, `inf`, `inb`, `inbswp`, each `[Ccy,Ref]`
- **FX:** `fx`, `fxf`, `fxswp`, `fxfut`, `ofxfut`, `fxcorr-swap`, `fxo[fx]`, `cfxo[fx]`, `fxfo[fx]`
- **Credit:** `cds-inst[redcode,Ccy,Seniority]`, `cds[redcode,tenor,coupon]`, `cdsidx[CdsIdx,Series]`, `crdcds`, `crdidx`, `crdidx-opt`, `tranche`, `cmbx`, `refentity[redcode]`
- **Equity:**
  - Exchange-traded options: `eqo`, `eio`, `eifo`, `eivo`
  - OTC options: `oeqo`, `oeio`, `oeifo`, `oeivo`
  - Futures: `ef`, `eif`, `edf`, `eivf`
  - Instruments: `eqty`, `eqtyidx`, `eqcfd`, `eqidxcfd`, `eq[isin]`, `eqidx[IndexId]`
  - Variance, volatility and correlation swaps: `varswp`, `volswp`, `corswp`
- **Commodities:** `cf`, `csf`, `cfo`, `cmdtyfwd`, `cmdtyswp`, `cmdtysprd` (the last three `[Ccy,Ref]`), `cidx`, `cfc[Ref]`
- **Generic:** `fut[ticker]`, `opt[AssetType,ticker]`, `etfo`, `etc[fut]`

**Market structures (curves, surfaces, data)**

| Keyword | Arguments | Meaning |
|---|---|---|
| `zc` | Ccy | Zero curve |
| `zcf` | Ccy | Zero curve family |
| `fc` | Ccy | FX forward curve |
| `ic` | Ccy, Ref | Inflation curve |
| `bc` | Country, BondFamily, Ccy | Bond curve |
| `parbc`, `infparbc`, `intbc`, `intinfbc` | — | Par and interpolated bond curves |
| `crv` | inst | Instrument curve, refined with `crv-type:` |
| `srf` | inst | Surface, refined with `srfc-type:` |
| `cs` | inst, Model | Calibrated surface |
| `params`, `mdef`, `p` | inst, Model | Model parameters and definitions |
| `inst` | — | Instrument wrapper |
| `ticks` | inst, interval | Intraday ticks |
| `ts` | chain | Time series |
| `quote` | QuoteType | Quote |
| `pca`, `stats` | — | PCA and statistics matrices |
| `grp` | MarketType, Ccy | Curve group |
| `tweak` | struct, TweakMethod | Risk tweak |
| `template` | — | Calibration template |
| `schedule` | — | Schedule |
| `data` | — | Generic data |
| `src-info` | — | Source information |

## 4. Enum types: argument keys and known values

| Enum | Key | Values (hard-coded) |
|---|---|---|
| CurrencyCode | `cc` | 67 values: USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF, SEK, NOK, DKK, CNY, CNH, BRL, MXN, ZAR… Also metals: XAU, XAG, XPT, XPD |
| CountryCode | `cn` | 39 values: US, GB, DE, FR, IT, ES, JP, AU, CA, EU, NZ… Also pseudo-codes SNAT, MULT, ZZ, M1. More are loaded at runtime from the Junko service (`cntry[...]`). |
| ReferenceIndex | `ref` | 118 values, mixing three kinds: IBORs/RFRs (EURIBOR, LIBOR, SOFR, SONIA, ESTR, TONAROIS, SARON, FF, OIS, CMS, CMT…); inflation indices using Bloomberg tickers (CPURNSA, UKRPI, CPTFEMU, FRCPXTOB…); commodities (NG, TTF, NBP, WTI, BRENT…) |
| CurveType | `crv-type` | benchmark, implied, transform, derived, published, fixing, fwd, spread, vol, turn, seasonality… (48) |
| SurfaceType | `srfc-type` | vol, sabr, shiftedsabr, published, chain, quote, generate… (35) |
| AssetType | `at` | b (bond), bf (bond future), if (interest rate future), ff (fed funds), fxf, ei, eif, cf, irs, credit… (21) |
| BondFamily | `bt` | default, otr, offtr… |
| BondClassification | `bnd-clss` | Govt, Corp, Muni, Mtge, Infl, Floater… |
| MktType | `mkt-typ` | ois, lib, inf, basis, on, off… |
| MarketType | `mkt` | rates, fx, hyb |
| Model | `model` | sabr, dsabr, zeta, svi-*, copula… (59) |
| IndexIdentifier | `idx-id` | SPX, NDX, VIX, NKY, SX5E… |
| ChainIdentifier | `cn-id` | Small hard-coded set, but other values such as `TY` are used in practice |
| Others | | 209 enum keys in total (full list in `Market\Enums`). Includes `tenor`/`term`, `bdc`, `dcc`, `seniority`, `sector`, `issr-name`, `tz`, `xccy`, `col`… |

**Common property keys** (`key:value`): `maturity`, `tenor`, `fix-freq`, `flt-freq`, `start`, `end`, `startDt`, `endDt`, `obs-start`, `ival`, `history`, `offset`, `ticker`, `isin`, `name`, `strike`, `coupon`, `calendar`, `otr`, `src`, `label`.

## 5. Definition layer: how an ID becomes an object

- **Two kinds of object:**
  - **Definitions** are shared and don't change: currencies, indexes, instrument conventions.
  - **Structures** belong to one environment and hold data that changes: curves, surfaces, market data.
- **Routing:** `market_definitions.cfg` lists factory entries, each with `AssemblyName`, `FactoryClass` and `WildCard`. The first factory whose wildcard matches the ID builds the definition.
- **Definition file format:** the first line is the .NET assembly-qualified class name. YAML-like properties follow, written by the `IArchivable` read/write methods. Example: `ccy[USD]` →

  ```
  BlueCrest.QR.QLib.Core.Market.Instrument.CurrencyDefinition,BlueCrest.QR.QLib.Core
  &0:
    CurrencyCode: USD
    RateIndexes: [idx[USD,CMS], idx[USD,SOFR], ...]
    InflationIndexes: [idx[USD,CPURNSA]]
    CommodityIndexes: [idx[USD,WTI], ...]
    DefaultOisRateIndex: idx[USD,OIS]
    CentralBankCode: FED
    ReformIndex: idx[USD,SOFR]
    ...
  ```

- **Relationships are stored as properties that hold IDs, not as a graph.** For example, a currency lists its indexes, and `flt` points to `idx` through its arguments.

## 6. What the vocabulary covers and what it doesn't

- **Covered:** currencies, countries, indexes (rates, inflation, commodity, equity), leg and instrument conventions, instruments across rates, FX, credit, equity, commodities and bonds, plus curves, surfaces, models and market data.
- **Not covered as first-class types:**
  - Organisations
  - People
  - Macro indicators and economic data releases
  - Events
  - Themes
  - Research documents
- **Central banks appear only as a property:** `CentralBankCode: FED` on a currency definition, plus meeting settings. There is no central-bank ID type.
- **Inflation measures are reference indices named by Bloomberg ticker** (e.g. CPURNSA), not economic concepts.

## 7. Alignment with Bloomberg

The two are aligned on identifiers and classification values, but not on structure. BlueCrest uses Bloomberg's identifiers and copies Bloomberg's category values, but arranges them in its own pricing-oriented grammar.

**Where it lines up with Bloomberg** (all seen in the QLib source):

| QLib item | Bloomberg equivalent | Evidence |
|---|---|---|
| `YellowKey` enum (`yel`) | Yellow keys (market sectors) | Exact values: `Mtge, Equity, Govt, Corp, Muni, Pfd, Comdty, Index, Curncy, Port` |
| `BondClassification` (`bnd-clss`) | Yellow keys | `Govt, Corp, Muni, Mtge, Pfd, Comdty…` |
| `SecurityType` (`sec-typ`) | Bloomberg security type values | `"Financial commodity future."`, `"Physical index future."` (Bloomberg's trailing full stop is kept) |
| `FutureClassification` | Bloomberg futures categories | `Base Metal, Crude Oil, Precious Metal, Livestock, Soy, Weather…` |
| `BondSubCategory` | Bloomberg mortgage and bond types | `MBS, CMO, TBA, ABS, CMBS, Pool, Whole Loan…` |
| Inflation `ReferenceIndex` values | Bloomberg index tickers | `CPURNSA, UKRPI, CPTFEMU, FRCPXTOB, JCPNJGBI` |
| `fut[...]` IDs | FIGI (Bloomberg's open identifier) | `fut[BBG01Z2DZJF4]` in the QCL notebooks |
| Ticker IDs | Ticker plus yellow key | `ctd[inst[fut[TYM4 Comdty]]]`, `et[b,USD SOV]` |
| `QuoteType` field names | Bloomberg reference fields | `figi`, `ticker`, `isin`, `cusip`, `YellowKey` |

About 60 QLib source files mention Bloomberg, BBG or FIGI, mostly under `Market\Structures`, `Market\Instrument` and `Market\Definitions`.

**Where it doesn't line up:**

| BlueCrest | Bloomberg |
|---|---|
| A grammar of nested keywords (`flt[USD,SOFR,3M]`, `crv[inst[swp[...]]]`) | Flat security IDs plus field names (e.g. `PX_LAST`) |
| Pricing objects: conventions, legs, zero curves, surfaces, models | Mainly securities and their fields, so no direct equivalent of `zc`, `flt`, `crv` or `cs` |
| Generic index-based instruments (`swp[USD]`, `irs[flt]`) | Specific tickers (e.g. `USOSFR10 Curncy`) |
| Own short codes: `cc`, `ref`, `at`, `crv-type` | Field names such as `CRNCY` and `SECURITY_TYP` |

**Taken together:**

- **Ties to Bloomberg are strongest at the edges.** These are the ID formats (FIGI, ticker plus yellow key, ISIN) and the security classifications.
- **The core vocabulary is BlueCrest's own.** Currencies, reference indexes and curve or instrument structures are QLib's design.
- **Bloomberg doesn't publish one formal ontology.** "Bloomberg ontology" in practice means FIGI and its security-type scheme, yellow keys and field names. So "aligned with Bloomberg" can only mean it reuses those standards.

## 8. Caveats

- **Copies can differ.** There are two cfg lineages: QLib (`QR/Qlib/trunk/cfg`: QXL, QNL, QCL bundle; layout `ccy\`, `inst\`) and Market.Environment (`Shared/BlueCrest.Market.Environment/trunk/cfg`: JunkoMarket, JunkoPosition; layout `currency\`, `instrument\`). The keywords are shared, but file layout and definition content drift. The QCL 5.4.528 bundle is the reference copy.
- **Hard-coded enum lists aren't complete.** Chain identifiers and countries take values beyond the hard-coded sets.
- **Naming is inconsistent in places.** `swap` and `swp` coexist; the source comments that they should be merged. Keywords are terse (`cs`, `ms`, `es`, `n`, `f`, `l`, `s`). Legacy values like LIBOR are still present.
- **Not every type keyword is a market concept.** Some are internal or technical, e.g. `conf`, `clear`, `monitor`, `user`, `i-id`, `calc-req`.
