"""The text Stage 1 works on: a sample file's body, without YAML front matter, with LF line endings, stripped.

Runs store only the sample's path; every offset in ``edits.jsonl`` indexes the body ``load_body`` returns for it.
"""

import re
from pathlib import Path

FRONT_MATTER = re.compile(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)


def front_matter(source: str) -> tuple[int, str | None]:
    """Return the offset where the body starts after any YAML front matter, and the front-matter ``Title``."""
    m = FRONT_MATTER.match(source)
    if not m:
        return 0, None
    title = re.search(r"^Title:[ \t]*[\"']?(.*?)[\"']?[ \t\r]*$", m.group(1), re.M)
    return m.end(), title.group(1) if title else None


def load_body(path: Path) -> tuple[str, str | None]:
    """Return the body of the sample at ``path`` and its front-matter ``Date``."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        source = f.read()
    start, _ = front_matter(source)
    date = re.search(r"^Date:[ \t]*[\"']?([^\"'\r\n]+)", source[:start], re.M)
    body = source[start:].replace("\r\n", "\n").strip()
    return body, date.group(1).strip() if date else None
