"""The compiled document file: YAML front matter, ``# Title`` and the cleaned content.

Text removed during cleaning is not written to the file; the extract manifest records it by section.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FRONT_MATTER_KEYS = ("Title", "Publisher", "Document type", "Date", "Authors")
# Written only when a document was compiled with warnings (e.g. ``FIGURE_CAPTION``), so it can be filtered on.
OPTIONAL_FRONT_MATTER_KEYS = ("Warnings",)
_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_YAML_RESERVED = frozenset({"true", "false", "yes", "no", "on", "off", "null", "~"})


@dataclass(frozen=True)
class FrontMatter:
    """Document metadata written as YAML front matter."""

    title: str
    publisher: str | None
    document_type: str | None
    date: str | None
    authors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "FrontMatter":
        """Parse loaded YAML front matter."""
        authors = data.get("Authors") or []
        warnings = data.get("Warnings") or []
        return cls(
            title=str(data.get("Title") or ""),
            publisher=data.get("Publisher"),
            document_type=data.get("Document type"),
            date=str(data["Date"]) if data.get("Date") else None,
            authors=tuple(str(a) for a in authors) if isinstance(authors, list) else (str(authors),),
            warnings=tuple(str(w) for w in warnings) if isinstance(warnings, list) else (str(warnings),),
        )

    def render(self) -> str:
        """The ``---`` delimited block, plain scalars quoted only where YAML would misread them."""
        lines = [
            "---",
            f"Title: {_yaml_scalar(self.title)}",
            f"Publisher: {_yaml_scalar(self.publisher)}",
            f"Document type: {_yaml_scalar(self.document_type)}",
            f"Date: {_yaml_scalar(self.date)}",
            "Authors:",
            *(f"  - {_yaml_scalar(a)}" for a in self.authors),
        ]
        if self.warnings:
            lines += ["Warnings:", *(f"  - {_yaml_scalar(w)}" for w in self.warnings)]
        lines.append("---")
        return "\n".join(line.rstrip() for line in lines)


@dataclass
class CorpusDocument:
    """A compiled document: front matter and cleaned content."""

    front_matter: FrontMatter
    content: str

    @property
    def title(self) -> str:
        """Document title (front matter)."""
        return self.front_matter.title

    def render(self) -> str:
        """The full file text."""
        heading = " ".join(self.title.split())
        return f"{self.front_matter.render()}\n\n# {heading}\n\n{self.content}\n"

    @classmethod
    def load(cls, path: Path) -> "CorpusDocument":
        """Read a compiled file."""
        return cls.parse(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))

    @classmethod
    def parse(cls, text: str) -> "CorpusDocument":
        """Parse file text into front matter and content.

        Raises:
            ValueError: If the text has no front matter.
        """
        match = _FRONT_MATTER_RE.match(text)
        if not match:
            raise ValueError("missing YAML front matter")
        meta = yaml.safe_load(match.group(1)) or {}
        front = FrontMatter.from_mapping(meta if isinstance(meta, dict) else {})
        body = text[match.end() :].lstrip("\n")
        first, _, rest = body.partition("\n")
        if first.startswith("# "):
            body = rest
        return cls(front, body.strip("\n"))


def _yaml_scalar(value: str | None) -> str:
    if not value:
        return ""
    needs_quotes = (
        ": " in value
        or " #" in value
        or value.endswith(":")
        or value[0] in "-?:,[]{}#&*!|>'\"%@`"
        or value != value.strip()
        or value.lower() in _YAML_RESERVED
    )
    return json.dumps(value, ensure_ascii=False) if needs_quotes else value
