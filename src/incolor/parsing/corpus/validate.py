"""Post-condition checks on a rendered document. Errors mean a compiler bug; warnings flag content for review."""

import re
from dataclasses import dataclass

import yaml

from ..core.document import FRONT_MATTER_KEYS, OPTIONAL_FRONT_MATTER_KEYS, CorpusDocument

# Leftovers that should have been stripped or gated: reported as warnings, the document is still written.
CONTENT_CHECKS = {
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "url": r"https?://|www\.",
    "phone": r"\+\d{1,3}[ (\-]\d{2,}[ \-)]\d",
    "control_or_private_use": r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ue000-\uf8ff\ufffd]",
    "mojibake": r"â€|Ã[\x80-\xbf]",
    "unconverted_bullet": r"[•▪■●◼❑◦‣✓]",
    "double_space": r"\S {2,}\S",
    "trailing_whitespace": r"[ \t]+$",
    "space_before_punctuation": r"\w [,.;:!?)](?:\s|$)",
    "empty_bullet": r"^- *$",
    "empty_header": r"^#+ *$",
    "blank_line_run": r"\n\n\n",
    "glued_numbers": r"\d+(?:\.\d+){3,}",
    "lone_n": r"(?<= )n (?=\w)",
    "disclaimer": r"(?i)redistribution|exclusive use|analyst certification|important disclosures",
    "template_text": r"optional cover page|Add author details|SELECT PUBLICATION TYPE|\bXX%",
    "letter_spaced": r"(?<![\w’'-])(?:[A-Z] ){3,}[A-Z](?![\w’'-])",
    "rule_line": r"_{3,}|-{4,}|={4,}",
    "app_promo": r"(?i)\bscan the qr code\b",
}
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Finding:
    """One validation result."""

    code: str
    detail: str


class FormatValidator:
    """Checks a rendered file: structure and round trip (errors), leftover defects in the content (warnings)."""

    def validate(self, rendered: str, expected_content: str | None = None) -> tuple[list[Finding], list[Finding]]:
        """Return ``(errors, warnings)``."""
        errors: list[Finding] = []
        try:
            doc = CorpusDocument.parse(rendered)
        except (ValueError, yaml.YAMLError) as exc:
            return [Finding("structure", str(exc).splitlines()[0])], []
        meta = yaml.safe_load(rendered.split("\n---\n", 1)[0].removeprefix("---\n")) or {}
        keys = list(meta)
        required, optional = keys[: len(FRONT_MATTER_KEYS)], keys[len(FRONT_MATTER_KEYS) :]
        if required != list(FRONT_MATTER_KEYS) or optional not in ([], list(OPTIONAL_FRONT_MATTER_KEYS)):
            errors.append(Finding("front_matter_keys", str(keys)))
        if not doc.title:
            errors.append(Finding("front_matter_empty", "Title"))
        if not _DATE_RE.fullmatch(str(meta.get("Date"))):
            errors.append(Finding("front_matter_date", str(meta.get("Date"))))
        if not doc.content.strip():
            errors.append(Finding("empty_content", "no content left after cleaning"))
        if expected_content is not None and doc.content != expected_content:
            errors.append(Finding("round_trip", "content read back differs from compiled content"))
        if "```yaml ignore" in rendered:
            errors.append(Finding("ignore_block", "stripped text written to the content"))
        return errors, self.content_warnings(doc.content)

    @staticmethod
    def content_warnings(content: str) -> list[Finding]:
        """Leftover formatting defects or boilerplate in the content."""
        warnings = []
        for code, pattern in CONTENT_CHECKS.items():
            for found in re.finditer(pattern, content, re.M):
                warnings.append(Finding(code, content[max(0, found.start() - 60) : found.end() + 60]))
        if '"' in content and any(ch in content for ch in "\u201c\u201d"):
            warnings.append(Finding("mixed_quotes", "straight and curly double quotes in one document"))
        return warnings
