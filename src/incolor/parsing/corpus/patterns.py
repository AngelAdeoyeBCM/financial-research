"""Regex tables and thresholds recovered from the original ``compile_samples.py`` (compiled 2026-10-23)."""

import re

# --- Corruption gate thresholds -------------------------------------------------------------------------------------
MAX_AXIS_RUN = 8
MAX_NUMERIC_SHARE = 0.4
MIN_TOKENS_FOR_SHARE = 30
MIN_STOPWORD_SHARE = 0.08
MIN_WORDS_FOR_LANGUAGE = 40
MIN_FOREIGN_STOPWORDS = 8
MIN_FOREIGN_SCRIPT_LETTERS = 2
MAX_GLUED_WORDS = 3
MIN_TABLE_ROWS = 4

TEMPLATE_RE = re.compile(
    r"optional cover page|Add author details|macro function|SELECT PUBLICATION TYPE|guidance notes|\bXX%"
)

BULLET_CHARS = "•▪■●◼❑◦‣✓\uf0a7\x98"
NON_LATIN_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "CYRILLIC", "ARABIC", "HEBREW", "THAI", "DEVANAGARI")
# fmt: off
ENGLISH_STOPWORDS = frozenset({
    "the", "of", "and", "to", "in", "a", "is", "that", "for", "on", "with", "as", "by", "at", "from", "be", "are",
    "was", "it", "this", "an", "or", "have", "has", "not", "will", "we", "our", "but", "which", "can", "would",
    "should", "may", "been", "than", "its", "their", "they", "also", "more", "if", "into", "over", "after", "while",
})
FOREIGN_STOPWORDS = frozenset({
    "der", "das", "und", "ist", "nicht", "mit", "auf", "für", "von", "dem", "eine", "sich", "auch",
    "le", "la", "les", "des", "est", "et", "une", "pour", "dans", "qui", "sur", "pas", "du", "aux", "avec", "sont",
    "el", "los", "las", "del", "por", "para", "como", "más", "una", "il", "che", "della", "gli", "nel", "sono",
    "os", "uma", "não",
})
CURRENCIES = frozenset({
    "USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK", "CNY", "CNH", "HKD", "SGD",
    "KRW", "TWD", "INR", "IDR", "MYR", "THB", "PHP", "BRL", "MXN", "CLP", "COP", "PEN", "ZAR", "TRY", "PLN",
    "HUF", "CZK", "ILS", "RUB", "SAR", "AED", "XAU",
})
# fmt: on

MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?"
    r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_TOKEN = (
    rf"{MONTH}(?:[-'’]?\d{{2,4}})?,?|(?:[1-4]Q|Q[1-4])(?:[-'’]?\d{{2,4}})?|['’]\d{{2}}"
    rf"|\(?\d{{1,2}}-{MONTH}-\d{{2,4}}\)?"
)
AXIS_TOKEN_RE = re.compile(
    rf"[(\-+−]?[$€£¥]?\d[\d.,:/]*(?:%|[a-zA-Z]{{1,3}})?\)?[,;]?|{DATE_TOKEN}|[-–—]{{1,2}}|n/?a|N/?A|nm"
)
DATE_TOKEN_RE = re.compile(DATE_TOKEN)
NUMBER_RE = re.compile(r"[-+−]?\d+(?:\.\d+)?")
GLUED_NUMBERS_RE = re.compile(r"\d+(?:\.\d+){3,}|\d+(?:[-−]\d+){4,}|\d+(?:%[-−]?\d+){2,}")
GLUED_WORDS_RE = re.compile(r"[a-z]{3,}[A-Z][a-z]{2,}")
WORD_RE = re.compile(r"[^\W\d_]+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://\s?\S+")
SPLIT_WORDS_RE = re.compile(r"[\W_]+")
DOC_ID_RE = re.compile(r"--\d+$")
SOURCE_PREFIX_RE = re.compile(r"^(?:BC|BNP|BofA|Citi|DB|GS|JPM|MS|SSGA|UBS)_")

# --- Figure captions and source lines (now a skip signal: the chart itself was not extracted) -----------------------
SOURCE_WORDS = (
    "Bloomberg|Macrobond|Haver|Analytics|Finance|LP|Research|Markets|Street|State|BNP|Paribas|Citi|Citigroup|Deutsche"
    "|Bank|Goldman|Sachs|Global|Investment|Morgan|Stanley|UBS|Barclays|BofA|Federal|Reserve|Fed|Atlanta|New|York"
    "|Eurostat|European|Commission|Central|Ministry|Treasury|Department|Bureau|Labor|Statistics|Economic|Analysis"
    "|Census|National|Office|Institute|Cabinet|Refinitiv|LSEG|Datastream|FactSet|Kpler|Tradeweb|CEIC|EPFR|Markit|S&P"
    "|Moody’s|Fitch|Reuters|Thomson|Company|Board|Governors|Japan|China|Wind|Insights|Strategy|Economics|estimates"
    "|calculations|data|analysis|staff|projections|forecasts|reports|websites|the|of|and|&"
)
SOURCE_ITEM = rf"(?:[A-Z]{{2,}}\w*|{SOURCE_WORDS})(?:[ /](?:[A-Z]{{2,}}\w*|{SOURCE_WORDS}))*"
SOURCE_RE = re.compile(rf"\bSources?:(?: ?{SOURCE_ITEM}(?:[,;] ?{SOURCE_ITEM})*)?\.?")
FIGURE_LABEL = r"(?:Fig(?:ure)?\.?|Exhibit|Chart|Table) ?\d+[a-z]?:"
FIGURE_LABEL_RE = re.compile(
    rf"{FIGURE_LABEL}|(?:Fig(?:ure)?\.?|FIGURE|Exhibit|EXHIBIT|Chart|CHART|Table|TABLE) ?\d+[a-z]?\.(?!\d)"
)

# --- Boilerplate stripping -----------------------------------------------------------------------------------------
# ``{series}`` is replaced by the escaped publication series (e.g. "Fixed Income Blog") of the document.
BOILERPLATE_TEMPLATES = (
    r"(?:(?<!\w)a ?s ?a ?s )?Please ref ?er to important inf ?ormation at the end of the report and MAR disclosures"
    r"(?: \d{1,2} \w+ \d{4}| \d{2}/\d{2}/\d{4})?(?: \d{1,3}\b)?",
    r"TRADE IDEA (?:T ?R ?A ?D ?E ?I ?D ?E ?A )?\d{2}/\d{2}/\d{4}(?: \d{1,3}\b)?",
    r"(?:keep page (?:margin|gutter) clear ?)+",
    r"\b(?:TRADE IDEA|DESKNOTE|SUNDAY TEA WITH BNP PARIBAS|RESEARCH NOTE|OUTLOOK) \d{1,2} [A-Z]+ \d{4}\b",
    r"‹#›",
    r"Use “Add author details” macro function to save time",
    r"\b(?=\w*\d)(?=\w*[a-z])(?=\w*[A-Z])[0-9A-Za-z]{16}\b",
    r"Distributed on: \d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} GMT",
    r"Deutsche Bank Research Deutsche Bank (?:AG|Securities Inc\.)",
    r"(?:Deutsche Bank AG )?IMPORTANT RESEARCH DISCLOSURES AND ANALYST CERTIFICATIONS LOCATED IN APPENDIX 1\."
    r"(?: UNTIL 19th MARCH 2021.*?FOR FURTHER DETAILS\.)?",
    r"Note to U\.S\. investors: US regulators have not approved most foreign listed stock index futures and options"
    r" for US investors\.?",
    r"Provided for the exclusive use of \S+ on \S+?\.?(?= |$)",
    r"DO NOT REDISTRIBUTE",
    r"\d{1,2} \w+ \d{4} [^.]{0,60}?Deutsche Bank (?:AG|Securities Inc\.) Page \d+",
    r"See Appendix A-1 for Analyst Certification, Important Disclosures and Research Analyst Affiliations\.?",
    r"(?:\b\w+ \| )?\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} ET │ \d+ pages?",
    r"Prepared for [A-Z][\w’'-]+ [A-Z][\w’'-]+",
    r"© ?\d{4} Citigroup Inc\. No redistribution without Citigroup[’']s written permission\.",
    r"(?:{series} )?\d{1,2} \w+ \d{4} Citi Research \d+",
    r"-? ?Vi e w p o i n? ?t\b",
    r"(?:BofA Securities|Goldman Sachs) does and seeks to do business with (?:issuers|companies) covered in its"
    r" research reports\..*?(?:making their investment decision|affect the objectivity of this report)\.",
    r"Trading ideas and investment strategies discussed herein may give rise to significant risk.*?applying these"
    r" ideas or strategies\.",
    r"Refer to important disclosures on pages? \d+(?: to \d+)?\.(?: \d{8}\b)?",
    r"Accessible version",
    r"Timestamp: \d{1,2} \w+ \d{4} \d{1,2}:\d{2}[AP]M [A-Z]{3}",
    r"Unauthorized redistribution of this report is prohibited\.",
    r"This report is intended for \S+",
    r"See Team Page for List of Analysts",
    r"(?:{series} )?\| \d{1,2} \w+ \d{4} \d{1,3}\b",
    r"For the exclusive use of \S+(?: [0-9a-f]{32})?",
    r"\d{1,2} \w+ \d{4} \d{1,3} Goldman Sachs(?: {series})?",
    r"Investors should consider this report as only a single factor in making their investment decision\.",
    r"For Reg AC certification and other important disclosures, see the Disclosure Appendix, or go to"
    r"(?: Economics Research)?",
    r"Analysts employed by non-US affiliates are not registered/qualified as research analysts with FINRA in the"
    r" U\.S\.",
    r"^\s*& Co\. LLC",
    r"(?:Goldman Sachs )?\(Asia\) L\.L\.C\.",
    r"For important disclosures, refer to the Disclosure Section, located at the end of this report\.",
    r"(?:\w+ \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M GMT )?Downloaded by \S+ Not for redistribution without written"
    r" consent of Morgan Stanley\.?",
    r"^\s*M (?:Update|Idea|Foundation|Blueprint)\b",
    r"This report has been prepared by UBS [^.]+?\. ANALYST CERTIFICATION AND REQUIRED DISCLOSURES, including"
    r" information on the Quantitative Research Review published by UBS, begin on page \d+\.",
    r"^\s*ab \d{1,2} \w+ \d{4}(?: Global Research)?",
    r"(?:{series} ?)?\d{1,2} \w+ \d{4} ab \d{1,3}\b",
    r"\bS\d{13}\b",
    r"Please see analyst certifications and important disclosures beginning on page \d+\.",
    r"This is a Special Report that is not an equity or a debt research report.*?FINRA Rule 2242\.",
    r"This document is intended for institutional investors and is not subject to all of the independence.*?"
    r"contrary to the recommendations offered in this report\.",
    r"Completed: \d{1,2}-\w{3}-\d{2}, \d{2}:\d{2} GMT(?: Released: \d{1,2}-\w{3}-\d{2}, \d{2}:\d{2} GMT)?"
    r"(?: Restricted - External)?",
    r"\d{1,2} \w+ \d{4} \d{1,3} Barclays \|(?: {series})?",
    r"FICC Research \w+ \d{1,2} \w+ \d{4}",
    r"(?:Special Report )?(?:Macro|FICC|Equity) Research \d{1,2} \w+ \d{4}(?: SIGNATURE [^()]{0,60}?\(i{1,3}\))?",
    r"(?:Information )?Classification: General(?:, Complimentary Material)?",
    r"\b\d{1,2} Insights\b",
    r"J P M O R G A N",
    r"www\.\S+",
    r"To register for the call, please contact your DB sales rep or go to the following URL: ?(?:https?://)? ?\S*",
)

# fmt: off
CONTACT_CONNECTORS = frozenset({
    "|", "-", "–", "&", "and", "of", "de", "da", "di", "del", "der", "van", "von", "le", "plc",
})
CONTACT_ABBREVIATIONS = frozenset({
    "Inc.", "Ltd.", "Co.", "Corp.", "LLC.", "L.L.C.", "N.A.", "S.E.", "AG.", "SA.", "plc.", "Jr.", "St.",
})
CONTACT_ORG_WORDS = frozenset({
    "AG", "Bank", "Branch", "BCI", "BofAS", "BofASE", "BSJL", "Corp.", "Europe", "Goldman", "Inc.", "International",
    "Japan", "LLC", "London", "Ltd.", "Paris", "plc", "Sachs", "SE", "Securities", "Singapore", "UK", "US",
})
PROVIDER_WORDS = frozenset({
    "BofA", "Barclays", "BNP", "Paribas", "Citi", "Deutsche", "Goldman", "JPMorgan", "Morgan", "Street", "UBS",
})
# fmt: on
CONTACT_TOKEN_RE = re.compile(r"\|?\(?[A-Z][\w’'.,\-]*\)?[,|]?")
PHONE_PART_RE = re.compile(r"[+(]?\d[\d()\-./]*\)?,?")
MIN_PHONE_DIGITS = 8
MAX_CONTACT_SPAN = 25
REPEAT_NGRAM = 6
REPEAT_PHRASE = 8
MAX_HEADER_REPEATS = 3

# --- Formatting ----------------------------------------------------------------------------------------------------
BULLET_RE = re.compile(rf"\s*[{BULLET_CHARS}]+\s*")
HEADER_RE = re.compile(r"(?<![\w’'])(?:[A-Z][A-Z0-9’'&/\-]*|&)(?:[ ]+(?:[A-Z][A-Z0-9’'&/\-]*|&|\d{1,4}))+(?![\w’'])")
ENUM_RE = re.compile(
    r"(?:(?<=\s)|^)(?P<marker>\((?P<paren>\d{1,2}|[a-h]|[ivx]{1,4})\)|(?P<digit>\d{1,2})[.)]|(?P<bare>[a-h]|[ivx]{1,4})\))"
    r"\s+(?=\S)"
)
# Spaced-out banners ("B N P P ...", "T R A D E") and rule lines ("____") left by PDF extraction.
LETTER_SPACED_RE = re.compile(r"(?<![\w’'-])(?:[A-Z] ){3,}[A-Z](?![\w’'-])")
RULE_LINE_RE = re.compile(r"_{3,}|-{4,}|={4,}")
# Mobile app call-to-action; any spaced-out banner before it is removed by LETTER_SPACED_RE first.
APP_PROMO_RE = re.compile(
    r"(?i)(?:BNP PARIBAS (?:GLOBAL MARKETS )?)?(?:APP)?:? ?Scan the QR code\b[^.]{0,80}?\bmobile app\.?"
)
ENUM_BLOCKERS = frozenset(
    {"section", "fig", "figure", "page", "exhibit", "box", "no", "phase", "note", "appendix", "chart", "step", "table"}
)
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
MAX_ENUM_GAP = 2000
TITLE_SEARCH_CHARS = 1000
