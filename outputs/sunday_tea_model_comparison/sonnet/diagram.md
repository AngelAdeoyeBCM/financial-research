```mermaid
%%{init: {"flowchart": {"htmlLabels": true, "nodeSpacing": 20, "rankSpacing": 60}, "themeCSS": ".arg{width:330px;text-align:left;color:#111111} .core,.c{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;margin-top:4px;padding:3px 6px;color:#111111} .core{border:2px solid} .c{border:1.5px solid;border-radius:10px} .rec{background:#f8c9c9;border-color:#8b1a1a} .val{background:#e3d4f5;border-color:#5b2c8f} .fc{background:#c9ecc9;border-color:#1a6b3a} .view{background:#c9dcf8;border-color:#1a3f8b} .dp{background:#d4d4d4;border-color:#5f5f5f} .obs{background:#e6e6e6;border-color:#888888} mark{background:#e6e6e6;color:#111111;padding:0 2px} .edgeLabel,.edgeLabel *{color:#9a9a9a !important;fill:#9a9a9a !important}"}}%%
flowchart LR
    A001["<div class='arg'><b>A001 · FORECAST</b><div class='core fc'><span>FOMC skip in October</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Soft NFP and PCE ease pressure</span><b>[H]</b></div></div>"]
    A002["<div class='arg'><b>A002 · FORECAST</b><div class='core fc'><span>At least two more hikes</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Headline NFP understates strength</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Energy not primary US driver</span><b>[A]</b></div><div class='c view'><span><b>S:</b> Lower energy could mean tighter policy</span><b>[H]</b></div><div class='c dp'><span><b>RA:</b> <mark>Underlying US labour stronger</mark></span><b>[A]</b></div></div>"]
    A003["<div class='arg'><b>A003 · RECOMMENDATION</b><div class='core rec'><span>Not bullish US long end</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> <b>A002 - FORECAST</b></span><b>[A]</b></div></div>"]
    A004["<div class='arg'><b>A004 · FORECAST</b><div class='core fc'><span>ECB one more hike in December</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> ECB fewer hikes than priced</span><b>[H]</b></div><div class='c view'><span><b>S:</b> Energy relief welcome for ECB</span><b>[A]</b></div></div>"]
    A005["<div class='arg'><b>A005 · VIEW</b><div class='core view'><span>OAT move stop-out driven</span><b>[H]</b></div><div class='c view'><span><b>S:</b> High bar for TPI</span><b>[A]</b></div><div class='c dp'><span><b>RA:</b> <mark>OAT-Bund hit 150bp</mark></span><b>[A]</b></div><div class='c view'><span><b>CO:</b> Conditions for OAT rally</span><b>[A]</b></div></div>"]
    A006["<div class='arg'><b>A006 · RECOMMENDATION</b><div class='core rec'><span>Hedge EUR weakness</span><b>[A]</b></div><div class='c fc'><span><b>S:</b> EUR risk premium front-loaded</span><b>[H]</b></div><div class='c view'><span><b>Q:</b> Election risks evenly balanced</span><b>[A]</b></div></div>"]
    A007["<div class='arg'><b>A007 · RECOMMENDATION</b><div class='core rec'><span>Long GBPUSD</span><b>[A]</b></div><div class='c view'><span><b>S:</b> GBP well placed</span><b>[A]</b></div></div>"]
    A008["<div class='arg'><b>A008 · FORECAST</b><div class='core fc'><span>BoJ quarterly hikes likely</span><b>[H]</b></div><div class='c fc'><span><b>S:</b> October BoJ hike unlikely</span><b>[H]</b></div></div>"]

    A002 -- Supporting --> A003

    classDef fc fill:#eef9ee,stroke:#1a6b3a,stroke-width:2px,color:#111111
    classDef rec fill:#fdeeee,stroke:#8b1a1a,stroke-width:2px,color:#111111
    classDef view fill:#eef4fd,stroke:#1a3f8b,stroke-width:2px,color:#111111
    class A001,A002,A004,A008 fc
    class A003,A006,A007 rec
    class A005 view
    linkStyle default stroke:#333333,stroke-width:2px,color:#9a9a9a
```
