```mermaid
%%{init: {"flowchart": {"htmlLabels": true, "nodeSpacing": 20, "rankSpacing": 60}, "themeCSS": ".arg{width:330px;text-align:left;color:#111111} .core,.c{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;margin-top:4px;padding:3px 6px;color:#111111} .core{border:2px solid} .c{border:1.5px solid;border-radius:10px} .rec{background:#f8c9c9;border-color:#8b1a1a} .val{background:#e3d4f5;border-color:#5b2c8f} .fc{background:#c9ecc9;border-color:#1a6b3a} .view{background:#c9dcf8;border-color:#1a3f8b} .dp{background:#d4d4d4;border-color:#5f5f5f} .obs{background:#e6e6e6;border-color:#888888} mark{background:#e6e6e6;color:#111111;padding:0 2px} .edgeLabel,.edgeLabel *{color:#9a9a9a !important;fill:#9a9a9a !important}"}}%%
flowchart LR
    A001["<div class='arg'><b>A001 · FORECAST</b><div class='core fc'><span>FOMC skips October, still two more hikes</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Soft NFP and PCE ease pressure</span><b>[H]</b></div><div class='c dp'><span><b>RA:</b> <mark>Household survey, hours, participation</mark></span><b>[A]</b></div></div>"]
    A002["<div class='arg'><b>A002 · FORECAST</b><div class='core fc'><span>At least two more Fed hikes</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Energy not main driver of US inflation</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Lower energy could necessitate tighter policy</span><b>[S]</b></div></div>"]
    A003["<div class='arg'><b>A003 · VIEW</b><div class='core view'><span>Not bullish on US long end</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> <b>A002 - FORECAST</b></span><b>[A]</b></div></div>"]
    A004["<div class='arg'><b>A004 · FORECAST</b><div class='core fc'><span>One more ECB hike in December</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Energy decline helps ECB more</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> No ECB hike in October</span><b>[A]</b></div></div>"]
    A005["<div class='arg'><b>A005 · VIEW</b><div class='core view'><span>OAT move stop-out driven, not fundamentals</span><b>[H]</b></div><div class='c val'><span><b>S:</b> 150bp consistent with BBB+ pricing</span><b>[A]</b></div><div class='c dp'><span><b>RA:</b> <mark>OAT-Bund hit 150bp</mark></span><b>[A]</b></div><div class='c view'><span><b>CO:</b> Conditions for sustained OAT rally</span><b>[A]</b></div></div>"]
    A006["<div class='arg'><b>A006 · VIEW</b><div class='core view'><span>High bar for ECB TPI use</span><b>[A]</b></div><div class='c view'><span><b>S:</b> TPI moral hazard</span><b>[S]</b></div></div>"]
    A007["<div class='arg'><b>A007 · FORECAST</b><div class='core fc'><span>Front-loaded EUR weakness, risk to 1.14</span><b>[A]</b></div><div class='c view'><span><b>S:</b> <b>A005 - VIEW</b></span><b>[H]</b></div></div>"]
    A008["<div class='arg'><b>A008 · RECOMMENDATION</b><div class='core rec'><span>Short EURAUD and EURMXN put spread</span><b>[A]</b></div><div class='c rec'><span><b>S:</b> Hedge further EUR weakness</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> <b>A007 - FORECAST</b></span><b>[A]</b></div><div class='c rec'><span><b>Q:</b> Hedge further EUR weakness</span><b>[A]</b></div></div>"]
    A009["<div class='arg'><b>A009 · RECOMMENDATION</b><div class='core rec'><span>Long GBPUSD</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> GBP well placed</span><b>[A]</b></div><div class='c view'><span><b>S:</b> UK reforms phased, limited budget impact</span><b>[A]</b></div></div>"]
    A010["<div class='arg'><b>A010 · VIEW</b><div class='core view'><span>BoJ quarterly hiking cycle likelier</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> Consecutive October BoJ hike limited</span><b>[H]</b></div><div class='c fc'><span><b>S:</b> Ueda non-committal</span><b>[A]</b></div></div>"]
    A011["<div class='arg'><b>A011 · FORECAST</b><div class='core fc'><span>Brazil neutral scenario implies runoff tie</span><b>[H]</b></div><div class='c dp'><span><b>RA:</b> <mark>Poll aggregator shows Lula 3pp ahead</mark></span><b>[A]</b></div></div>"]
    A012["<div class='arg'><b>A012 · RECOMMENDATION</b><div class='core rec'><span>Short MXNCOP, Coltes receiver, COP payer</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> Another Banrep hike likelier</span><b>[H]</b></div><div class='c dp'><span><b>RA:</b> <mark>Banrep hiked 25bp vs pause expected</mark></span><b>[A]</b></div></div>"]
    A013["<div class='arg'><b>A013 · FORECAST</b><div class='core fc'><span>Czech hike in November</span><b>[A]</b></div><div class='c view'><span><b>S:</b> CEE outlook revised on energy</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> NBH on hold, one Q4 cut removed</span><b>[H]</b></div></div>"]
    A014["<div class='arg'><b>A014 · FORECAST</b><div class='core fc'><span>Poland hikes may shift to next year</span><b>[S]</b></div><div class='c fc'><span><b>S:</b> Polish fuel subsidies improve inflation</span><b>[H]</b></div></div>"]

    A002 -- Supporting --> A003
    A005 -- Supporting --> A007
    A007 -- Supporting --> A008

    classDef fc fill:#eef9ee,stroke:#1a6b3a,stroke-width:2px,color:#111111
    classDef rec fill:#fdeeee,stroke:#8b1a1a,stroke-width:2px,color:#111111
    classDef view fill:#eef4fd,stroke:#1a3f8b,stroke-width:2px,color:#111111
    class A001,A002,A004,A007,A011,A013,A014 fc
    class A008,A009,A012 rec
    class A003,A005,A006,A010 view
    linkStyle default stroke:#333333,stroke-width:2px,color:#9a9a9a
```
