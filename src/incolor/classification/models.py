"""Value objects shared by the classification pipeline."""

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from ..ingestion.corpus import CorpusDocument
from .taxonomy import Taxonomy

_ISO2 = re.compile(r"^[A-Z]{2}$")
_TEXT_QUALITY = ("ok", "empty", "garbled")


class ValidationFailedError(ValueError):
    """Model output broke the schema or used labels outside the taxonomy; ``errors`` feeds the retry prompt."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Document:
    """One source text with its front-matter metadata."""

    path: Path
    sha256: str
    title: str
    date: str
    publisher: str
    publisher_type: str
    body: str

    @classmethod
    def load(cls, path: Path) -> "Document":
        """Read a corpus file (ignore blocks removed) or plain text, and hash the raw bytes."""
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").lstrip("\ufeff")
        try:
            doc = CorpusDocument.parse(text)
        except (ValueError, yaml.YAMLError):
            doc = None
        front = doc.front_matter if doc else None
        return cls(
            path=path,
            sha256=hashlib.sha256(raw).hexdigest(),
            title=(front.title if front else "") or path.stem,
            date=(front.date if front else None) or "",
            publisher=str((front.publisher if front else None) or ""),
            publisher_type=str((front.document_type if front else None) or ""),
            body=(doc.content if doc else text).strip(),
        )

    @property
    def name(self) -> str:
        """File name used as the document key in every output."""
        return self.path.name

    def head(self, max_chars: int) -> str:
        """Opening of the body: title, summary and first headings."""
        return self.body[:max_chars]

    def is_truncated_at(self, max_chars: int) -> bool:
        """True if ``head(max_chars)`` leaves part of the body unread."""
        return len(self.body) > max_chars


@dataclass(frozen=True)
class Label:
    """A category/subcategory pair."""

    category: str
    subcategory: str

    def __str__(self) -> str:
        return f"{self.category} > {self.subcategory}"

    @classmethod
    def parse(cls, raw: Any, taxonomy: Taxonomy, field_name: str, errors: list[str]) -> "Label | None":
        """Build a label from ``{"category", "subcategory"}``, appending to ``errors`` if it is not in the taxonomy."""
        if not isinstance(raw, dict):
            errors.append(f"{field_name} must be an object with category and subcategory")
            return None
        category, subcategory = str(raw.get("category", "")).strip(), str(raw.get("subcategory", "")).strip()
        if problem := taxonomy.check_label(category, subcategory):
            errors.append(f"{field_name}: {problem}")
            return None
        return cls(category, subcategory)


@dataclass(frozen=True)
class Entity:
    """A normalised entity driving a document's argument."""

    name: str
    type: str


@dataclass(frozen=True)
class Classification:
    """Validated classification of one document."""

    primary: Label
    secondary: tuple[Label, ...]
    countries: tuple[str, ...]
    document_type: str
    confidence: float
    rationale: str
    runner_up: Label
    runner_up_reason: str
    runner_up_close: bool
    text_quality: str
    entities: tuple[Entity, ...]

    @classmethod
    def from_payload(cls, payload: Any, taxonomy: Taxonomy, max_entities: int = 15) -> "Classification":
        """Validate a model JSON payload against the taxonomy.

        Raises:
            ValidationFailedError: Listing every problem found so the model can fix them in one retry.
        """
        errors: list[str] = []
        if not isinstance(payload, dict):
            raise ValidationFailedError(["top-level JSON value must be an object"])

        primary = Label.parse(payload.get("primary"), taxonomy, "primary", errors)
        runner_up = Label.parse(payload.get("runner_up"), taxonomy, "runner_up", errors)
        if primary and runner_up and primary == runner_up:
            errors.append("runner_up must differ from primary")

        raw_secondary = payload.get("secondary") or []
        secondary: list[Label] = []
        if not isinstance(raw_secondary, list) or len(raw_secondary) > 2:
            errors.append("secondary must be a list of at most 2 labels")
        else:
            for i, raw in enumerate(raw_secondary):
                if label := Label.parse(raw, taxonomy, f"secondary[{i}]", errors):
                    if label == primary or label in secondary:
                        errors.append(f"secondary[{i}] duplicates another label")
                    else:
                        secondary.append(label)
        if primary and primary.category == taxonomy.fallback_category and secondary:
            errors.append(f"secondary must be empty when primary is {taxonomy.fallback_category}")

        raw_countries = payload.get("countries") or []
        countries: list[str] = []
        if not isinstance(raw_countries, list):
            errors.append("countries must be a list of ISO 3166-1 alpha-2 codes")
        else:
            for code in (str(c).strip().upper() for c in raw_countries):
                if not _ISO2.match(code):
                    errors.append(f"countries: {code!r} is not a 2-letter ISO code")
                elif code not in countries:
                    countries.append(code)

        document_type = str(payload.get("document_type", "")).strip().lower()
        if document_type not in taxonomy.document_types:
            errors.append(f"document_type {document_type!r} must be one of {list(taxonomy.document_types)}")

        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            errors.append("confidence must be a number between 0 and 1")
            confidence = 0.0

        rationale = str(payload.get("rationale", "")).strip()
        if not rationale:
            errors.append("rationale is required")
        reason = str((payload.get("runner_up") or {}).get("reason", "")).strip() if runner_up else ""
        if runner_up and not reason:
            errors.append("runner_up.reason is required")

        quality = str(payload.get("text_quality", "ok")).strip().lower()
        if quality not in _TEXT_QUALITY:
            errors.append(f"text_quality must be one of {list(_TEXT_QUALITY)}")

        entities = cls._parse_entities(payload.get("entities"), taxonomy, max_entities, errors)

        if errors or primary is None or runner_up is None:
            raise ValidationFailedError(errors)
        return cls(
            primary=primary,
            secondary=tuple(secondary),
            countries=tuple(countries),
            document_type=document_type,
            confidence=float(confidence),
            rationale=rationale,
            runner_up=runner_up,
            runner_up_reason=reason,
            runner_up_close=bool(payload["runner_up"].get("close_call", False)),
            text_quality=quality,
            entities=entities,
        )

    @staticmethod
    def _parse_entities(raw: Any, taxonomy: Taxonomy, cap: int, errors: list[str]) -> tuple[Entity, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            errors.append("entities must be a list of {name, type}")
            return ()
        seen: dict[tuple[str, str], Entity] = {}
        for i, item in enumerate(raw):
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                errors.append(f"entities[{i}] needs a non-empty name")
                continue
            kind = str(item.get("type", "")).strip()
            if kind not in taxonomy.entity_types:
                errors.append(f"entities[{i}].type {kind!r} must be one of {list(taxonomy.entity_types)}")
                continue
            name = taxonomy.normalise_entity(str(item["name"]))
            seen.setdefault((name, kind), Entity(name, kind))
        return tuple(seen.values())[:cap]


@dataclass(frozen=True)
class DocumentResult:
    """Classification plus the document metadata that reporters need."""

    file: str
    title: str
    date: str
    classification: Classification
    needs_review: bool
    read_full_text: bool = False

    def to_json(self) -> dict[str, Any]:
        """Plain-dict form for the cache and the HTML report."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DocumentResult":
        """Rebuild from ``to_json`` output (cache read)."""
        c = data["classification"]
        classification = Classification(
            primary=Label(**c["primary"]),
            secondary=tuple(Label(**s) for s in c["secondary"]),
            countries=tuple(c["countries"]),
            document_type=c["document_type"],
            confidence=c["confidence"],
            rationale=c["rationale"],
            runner_up=Label(**c["runner_up"]),
            runner_up_reason=c["runner_up_reason"],
            runner_up_close=c["runner_up_close"],
            text_quality=c["text_quality"],
            entities=tuple(Entity(**e) for e in c["entities"]),
        )
        return cls(
            file=data["file"],
            title=data["title"],
            date=data["date"],
            classification=classification,
            needs_review=data["needs_review"],
            read_full_text=data.get("read_full_text", False),
        )
