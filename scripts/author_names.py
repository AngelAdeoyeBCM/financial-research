"""Turn the ledger's per-chunk Author_MCP / AuthorRole lists into one {'Name', 'Role'} record per person.

Handles two MCP schemas: older strings ('A; B' with a separate role string) and newer [{Name, Role}] dicts.
Team names, job titles and fragments are filtered out by rules (see ORG_WORDS); run haiku_name_check.check_names
over the distinct names afterwards if you want a second opinion, and pass the approved set as ``keep``.

usage (notebook):
    from author_names import author_records
    df['Author'] = [author_records(a, r, broadcast=True) for a, r in zip(df.Author_MCP, df.AuthorRole)]
"""

import re
from collections import Counter

# Credentials are stripped from names. Word-boundary match, with or without a leading comma.
CRED = re.compile(r"[,\s]*\b(?:CFA|CPA|CAIA|FRM|CMT|Ph\.?D\.?|MBA|Jr\.?|Sr\.?|III|II)\b\.?", re.I)

# Words that only ever mark a team, desk, bank or job title. A candidate name is cut back past these at both ends and
# rejected if any remain inside it.
ORG_WORDS = (
    r"team|teams|desk|group|markets?|research|strategy|strategist|strategists|economics|economic|economist|economists|"
    r"analyst|analysts|quant|quantitative|derivatives|global|bnp|bnpp|paribas|bank|capital|securities|asset|allocation|"
    r"allocations|equity|equities|fx|rates|credit|commodity|commodities|macro|head|chief|senior|director|sales|trading|"
    r"trader|insights?|outlook|weekly|investment|advisory|latam|apac|emea|ceemea|japan|china|asia|europe|european|euro|us|uk|"
    r"eu|em|dm|g10|g4|ficc|mar|qis|gems|fi|jpm|citi|ubs|bofa|bofas|db|deutsche|sachs|barclays|nomura|hsbc|natwest|jefferies|"
    r"branch|north|america|americas|canada|division|product|products|management|securitized|fixed|income|currencies|"
    r"machine|snaps|policy|materials|foundation|systematic|autos|fundamental|corporate|sustainability|staffers|sunday|"
    r"tea|portfolio|public|internet|emerging|volatility|front|end|center|mind|cap|applied"
)
# Words that are also common first names or surnames (Ken Goldman, Hong Li, Stanley Ren). They only count as an
# organisation when the whole string is made of organisation words, e.g. 'Morgan Stanley' or 'State Street'.
AMBIGUOUS_WORDS = r"goldman|morgan|stanley|hong|kong|state|street|london|cross"
ORG = re.compile(rf"\b(?:{ORG_WORDS})\b", re.I)
ORG_FULL = re.compile(rf"(?:{ORG_WORDS})", re.I)
AMBIGUOUS_FULL = re.compile(rf"(?:{AMBIGUOUS_WORDS})", re.I)
JP_MORGAN = re.compile(r"\bJ\.?\s*P\.?\s*Morgan\b|\bJPMorgan\b", re.I)

_PARTICLES = {"de", "da", "del", "di", "van", "von", "der", "la", "le", "dos", "el", "bin", "i"}


def _prep(x):
    x = JP_MORGAN.sub(" ", x)                                           # "J P Morgan Global FX Strategy" -> "Global FX Strategy"
    x = re.sub(r"(?i)\bwith thanks to\b", ";", x)                       # "with thanks to Simran Bedi"
    x = re.sub(r"([^;|]*?)\(([^()]*)\)",                                # "Group (A, B)" -> A, B ; "Amy Gower (Amy S)" -> Amy Gower
               lambda m: m.group(2) if ORG.search(m.group(1)) else m.group(1), x)
    return re.sub(r"[^;|,&/]*:\s*", "", x)                              # "Economics Americas: Jonathan Pingle" -> Jonathan Pingle


def _strip_team_tail(n):
    """'Neill Clark Macro Strategy Team' -> 'Neill Clark'; 'Global Economics Team' -> ''."""
    t = n.split()
    while t and ORG_FULL.fullmatch(t[-1]):
        t.pop()
    while t and ORG_FULL.fullmatch(t[0]):
        t.pop(0)
    return " ".join(t)


def person_names(x, review=None):
    """One author string -> list of person names. Rejected fragments are appended to ``review`` if given."""
    out = []
    for t in re.split(r"[;|,&/]|\band\b", CRED.sub("", _prep(x))):
        n = _strip_team_tail(re.sub(r"\s+", " ", t.replace(".", " ")).strip())
        if not n or re.search(r"\d", n):
            continue
        w = n.split()
        all_org = all(ORG_FULL.fullmatch(k) or AMBIGUOUS_FULL.fullmatch(k) for k in w)          # 'Morgan Stanley', 'State Street'
        if (len(w) < 2 or len(w) > 5 or all(len(k) == 1 for k in w) or any(ORG_FULL.fullmatch(k) for k in w)
                or all_org):
            if review is not None:
                review.append(n)
            continue
        out.append(" ".join(k.title() if k.isupper() and len(k) > 2 else k for k in w))   # LIU -> Liu, keep initials
    return out


def split_roles(x):
    return [t.strip() for t in re.split(r";|\band\b", x) if t.strip()] if isinstance(x, str) else []


def chunk_pairs(author, role, broadcast=False):
    """One chunk -> [(name, [roles])]."""
    if isinstance(author, list) and author and all(isinstance(a, dict) for a in author):      # newer schema
        return [(n, split_roles(a.get("Role"))) for a in author if a.get("Name") for n in person_names(a["Name"])]
    names = [n for a in (author if isinstance(author, list) else [author]) if isinstance(a, str)
             for n in person_names(a)]
    roles = [r for x in (role if isinstance(role, list) else [role]) for r in split_roles(x)]
    if names and len(names) == len(roles):
        return [(n, [r]) for n, r in zip(names, roles)]
    if len(names) == 1:                                   # one person, several roles
        return [(names[0], roles)]
    if broadcast and len(roles) == 1:                     # one role for several people: assumption
        return [(n, roles) for n in names]
    return [(n, []) for n in names]                       # can't pair


def author_records(authors, roles, broadcast=False, keep=None):
    """Per-chunk Author_MCP / AuthorRole lists -> [{'Name':..., 'Role':...}], one per person, roles merged.

    broadcast: give a lone role to every author in a chunk that lists several (an assumption).
    keep:      optional set of names (e.g. those Haiku labelled 'person'); everyone else is dropped.
    Names that differ only by case are merged, keeping the most common spelling.
    """
    merged, spelling = {}, {}
    for a, r in zip(authors or [], roles or []):
        for name, rs in chunk_pairs(a, r, broadcast):
            if keep is not None and name not in keep:
                continue
            k = name.casefold()
            merged.setdefault(k, set()).update(rs)
            spelling.setdefault(k, Counter())[name] += 1
    return [{"Name": spelling[k].most_common(1)[0][0], "Role": "; ".join(sorted(rs)) or None}
            for k, rs in sorted(merged.items())]


def distinct_names(author_col, role_col, broadcast=False):
    """Every distinct name the rules keep, for passing to haiku_name_check.check_names."""
    return sorted({a["Name"] for a_, r_ in zip(author_col, role_col) for a in author_records(a_, r_, broadcast)})
