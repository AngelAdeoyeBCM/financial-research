from __future__ import annotations

import re

UPPER = 'A-ZÀ-ÖØ-Þ'
LETTER = "A-Za-zÀ-ÖØ-öø-ÿĀ-ž"
WORD = rf"[{UPPER}][{LETTER}.'’-]+"


def _ci(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
PHONE = re.compile(r'(?:\+\d{1,3}[\s.-]?\(?\d{1,5}\)?[\s.-]?\d{3,5}[\s.-]?\d{3,5}|\(\d{3}\)\s?\d{3}[\s.-]\d{4})')
CONTACT_LABEL = re.compile(r'\b(?:Tel|Phone|Mobile|Email|E-mail|T|M|Direct)\b[:\s]*', re.I)

# Whole lines that are navigation chrome, banners or boilerplate; removed wherever they appear.
LINE_DROP = _ci(
    r'^\[?This message originated from an external source\]?$',
    r'^\[The REPLY TO address does not match the SENDER.*\]$',
    r'^(?:Please address )?[Qq]uestions to\b.{0,200}@[\w.-]+\.\w+',
    r'^.{0,120}\b(?:please )?(?:contact|email) \S+@[\w.-]+\.\w+.{0,60}$',
    r'^[_=\-–—*~·.#\s]{3,}$',
    r'^Classification:\s*\w+$',
    r'^.{0,80}(?:Not a product of [\w ]{1,30}Research|FOR INSTITUTIONAL USE ONLY).{0,80}$',
    r'^\(?(?:PDF:\s*)?\d+\s*(?:pdf )?pages?\s*\)?$',
    r'^(?:Read Full Report|Read the Report|Read report\b.*|Read more\.{0,3}|Read more on\b.*|Continue Reading|'
    r'Full Report|View Report(?: Online)?|View Document|View full report|Download(?: the)? pdf\b.*|'
    r'DOWNLOAD THE PDF\s*>?|Print PDF.*|Request a meeting|Bloomberg chat|Symphony|Send email|Email|'
    r'View this email in (?:your )?browser|View in browser|To view this in a browser.*|VIEW ANALYST.S PAGE.*|'
    r'Scan code to view the report|Link: View on .*|Ask the editor.*|Back to contents|Link to source|'
    r'Data Download|Open in browser|Forward to a friend|Share this email|Subscribe|Subscribe I Unsubscribe|'
    r'Unsubscribe|Subscribe to .{1,40}research|Learn more|Click here)$',
    r'^This report is intended (?:exclusively )?for\b.*$',
    r'^This e-?mail is intended for .{1,80} only\b.*$',
    rf'^Hello,? [{LETTER}]+,?$',
    r'^(?:Prepared|This was prepared) for\b.*$',
    r'^Your Goldman Sachs [Aa]lert .*$',
    r'^Recipient:\s.*$',
    r'^https?://\S+$',
    r'^Visit J\.P\. Morgan Markets\b.*$',
    r'^Click here for the full document and disclaimers.*$',
    r'^\+\d[\d\s()\-]{8,}$',
    r'^BofA GLOBAL RESEARCH$',
    r'^\(\d{2,3} \d{2,3}\) \d{3,4}-\d{4}$',
    r'^.{0,60}Morgan Stanley Asia Limited.{0,60}$',
    r'^Barclays, UK$',
    r'^Once registered, you will receive an email\b.*$',
    r'^Pre-Registration required\b.*$',
    r'^This document is intended for institutional investors and is not subject to all of the independence\b.*$',
    r'^Go to My Research\b.*$',
    r'^\(\d{1,4}[- ]?\d{0,4}\)\s?\d{3,4}[- ]?\d{4}$',
    r'^Bookmark \| Read$',
    r'^The 20\d\d .{0,80}\bSurvey is now open\b.*$',
    r'^\(Continued on the next page\)$',
    r'^.{1,120}\.pdf$',
    r'^The full press report can be seen here:?$',
    r'^Citigroup\.com$',
    r'^(?:Inversiones J\.P\. Morgan|Banco J\.P\. Morgan|J\.P\. Morgan Corredores).*$',
    rf'^Hi [{LETTER}]+,?$',
    r'^(?:Global Markets Strategy|Global Research|Europe Credit Research|EM,? Economic and Policy Research|Research|'
    r'Deutsche Bank|Viewpoint \| Citi Research|CITI[\'’]S TAKE|Macro and Strategy Research|Date & Time|Register|'
    r'YOU[\'’]RE INVITED!?)$',
)
# Research-analyst accreditation lines such as "Jane Doe AC" (case-sensitive "AC").
ANALYST_ACCREDITATION = re.compile(rf'^(?:{WORD} ){{1,3}}AC\b.*$')

# First line of a footer / disclaimer; everything from here on is dropped.
FOOTER_START = _ci(
    r'^Subscription (?:details|changes)\b',
    r'^Unsubscribe\b',
    r'^Manage (?:your )?(?:subscriptions?|preferences)\b',
    r'^You (?:have )?(?:been )?received this (?:e-?mail|message)\b',
    r'^You are receiving this\b',
    r'^If you (?:no longer wish|do not wish|don.t wish|would like to (?:stop|unsubscribe|change))\b',
    r'^To (?:unsubscribe|stop receiving)\b',
    r'^Update your (?:subscription|preferences)\b',
    r'^Click here to (?:un)?subscribe\b',
    r'^(?:Important |Legal )?Disclaimers?\b',
    r'^(?:Important )?Disclosures?\b',
    r'^Analyst Certification\b',
    r'^For (?:important information|analyst certification|Reg AC|important disclosures)\b',
    r'^Please refer to research report\b',
    r'^Please see (?:the )?(?:important )?disclosures?\b',
    r'^Read the research report for complete information\b',
    r'^[*•\s-]*Read the research report(?:\(s\)|s)?\b.{0,160}\b(?:disclosures?|certifications?)\b',
    r'^SEE THE DISCLOSURES APPENDIX\b',
    r'^Please refer to the disclaimer\b',
    r'^To discontinue receiving reports\b',
    r'^This synopsis, the research reports\b',
    r'^No Liability:',
    r'^No redistribution or reproduction:',
    r'^Questions to\b.{0,200}@',
    r'^This (?:e-?mail|email|message|publication|document|communication|material|report)\b.{0,200}\b'
    r'(?:confidential|privileged|solely for|intended (?:solely|only|exclusively)|prepared by|'
    r'for information purposes|not (?:an )?(?:offer|investment advice))',
    r'^IMPORTANT:?\s+This (?:e-?mail|email)\b',
    r'^This information has been obtained or derived from sources believed to be reliable',
    r'^(?:©|\(c\)|Copyright\b)',
    r'^Sent from my\b',
    r'^View how we use personal information',
    r'^Morgan Stanley will make certain research products',
    r'^-?\s*SAVE PAPER\b',
    r'^Please consider the environment',
    r'^Stay connected to our\b',
    r'^Download the .{1,60} app\b',
    r'^Click here to subscribe to similar content',
    r'^Publication:\s',
    r'^Vanda Research$',
    r'^Completed:\s.*Released:',
    r'^Barclays Events Terms of Service',
    r'^Notice to (?:Australian|Brazilian|Investors)\b',
    r'^Deutsche Bank Research \|',
    r'^This publication contains non-objective material',
    r'^If you would like to know more about\b',
    r'^If you have any queries to access this content\b',
    r'^For more information, please contact:?$',
    r'^(?:Follow us|Connect with us|Find us on)\b',
    r'^Registered (?:office|in)\b',
    r'^Sponsored\b',
    r'^J\.P\. Morgan Securities (?:plc|LLC|India Private Limited)\b',
    r'^All of J\.P\. Morgan.s published research',
    r'^Private Bank Clients:',
    r'^[“"]JPMC[”"] means',
    r'^Modify Your Subscriptions',
    r'^To manage your subscriptions',
    r'^UBS does and seeks to do business',
    r'^The message is subject to the Global Research Disclaimer',
    r'^As detailed in the UBS Neo Platform',
    r'^For analyst certifications',
    r'^Written by EmergingMarketWatch',
    r'^For important Morgan Stanley\b',
    r'^Terms and Conditions\b.*Privacy',
    r'^Barclays Capital Inc\. and/or one of its affiliates',
    r'^These events are intended for Barclays\b',
    r'^If your firm is in-scope for research unbundling\b',
    r'^Global Banking & Markets$',
    r'^\(GS\)',
    r'^Published \d{1,2} [A-Z][a-z]{2}, \d{4}',
    r'^For a list of all Goldman Sachs\b',
)

# Lines that open an author block / sign-off; the lines that follow are kept as the signature.
SIGNATURE_START = _ci(
    r'^(?:Authors?|Author contacts|Contributors?|Editors?|Contacts?|Analyst contacts?)$',
    r'^(?:(?:Best|Kind|Warm|Many) )?(?:regards|wishes)[,!.\s]*$',
    r'^(?:Sincerely|Cheers|Thank you!?|Thanks)[,!.\s]*$',
    r'^--\s*$',
)

DATE_ONLY = re.compile(
    r'^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?(?:\d{1,2}(?:st|nd|rd|th)?[\s-]+'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?(?:,?[\s-]+\d{2,4})?|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+\d{4})?)'
    r'(?:[\s,|]+\d{1,2}[:.]\d{2}(?::\d{2})?(?:\s*(?:am|pm|GMT|BST|CET|UTC|EST|ET))*)?$',
    re.I,
)
REGION_LABEL = re.compile(
    r'^(?:North America|Asia Pacific|APAC|Europe|EMEA|CEEMEA|Global|Americas|Latin America|LatAm|'
    r'Middle East(?: & | and )?(?:North )?Africa|Asia|Japan|United States|US|UK)$',
    re.I,
)
DATED_LINE = re.compile(r'\|\s*\d{1,2}-[A-Za-z]{3}-\d{2}$')

PARTICLES = 'de|van|von|di|da|del|la|bin'
NAME = re.compile(rf'^{WORD}(?: (?:{WORD}|{PARTICLES})){{1,3}}(?:,? (?:CFA|PhD|FRM|CAIA))?$')
NAME_WITH_CREDENTIAL = re.compile(rf'^{WORD}(?: {WORD}){{1,2}},? (?:CFA|PhD|FRM|CAIA)$')
BYLINE = re.compile(rf'^(?i:By) {WORD}(?: {WORD}){{1,3}}(?:,.*)?$')
TITLE = re.compile(
    r'\b(?:Economist|Strategist|Analyst|Head of|Director|Managing Director|Chief|Editor|Researcher|Research|'
    r'Sales|Trader|Specialist|Associate|Vice President|Partner|Co-?Head|Senior|Global|Equity Strategy|Economics)\b',
    re.I,
)
ENTITY = re.compile(
    r'^(?:BofAS|BofAS Japan|BofA Europe.*|BofA Securities.*|MLI \(UK\)|MLPF&S|Merrill Lynch.*|Morgan Stanley.*|'
    r'Goldman Sachs.*|Barclays.*|BCI, US|HSBC.*|Deutsche Bank.*|J\.P\. Morgan.*|Citi.*|UBS.*|ING.*|UniCredit.*)$',
    re.I,
)
CONTACT_LEAD = re.compile(r'^(?:Tel|Phone|Mobile|Email|E-mail|T|M|Direct)\b[:\s]', re.I)
