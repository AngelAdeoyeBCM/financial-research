"""Classifiers: an abstract interface and a Claude implementation with validate-and-retry."""

import hashlib
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol

from .models import Classification, Document, DocumentResult, ValidationFailedError
from .taxonomy import Taxonomy

DEFAULT_PROMPT = Path(__file__).parents[3] / "prompts" / "classify_document.md"
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ClassificationError(RuntimeError):
    """A document could not be classified after all attempts."""


class TextGenerator(Protocol):
    """The slice of a model backend the classifier needs."""

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the model's text reply."""


class Classifier(ABC):
    """Turns a ``Document`` into a validated ``DocumentResult``."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy

    @property
    @abstractmethod
    def fingerprint(self) -> str:
        """Identifies everything that changes results (model, prompt, taxonomy) for cache keys."""

    @abstractmethod
    def classify(self, document: Document) -> DocumentResult:
        """Classify one document.

        Raises:
            ClassificationError: If no valid result could be produced.
        """

    def needs_review(self, document: Document, result: Classification) -> bool:
        """Apply the review rules: low confidence, close runner-up, or empty/garbled text."""
        return (
            result.confidence < self.taxonomy.confidence_threshold
            or result.runner_up_close
            or result.text_quality != "ok"
            or len(document.body) < self.taxonomy.min_body_chars
        )


class ClaudeClassifier(Classifier):
    """Classifies with Claude. Reads the opening first and rereads the full text only if confidence is low."""

    def __init__(
        self,
        taxonomy: Taxonomy,
        backend: TextGenerator,
        model: str = "sonnet",
        prompt_path: Path = DEFAULT_PROMPT,
        head_chars: int = 6000,
        max_attempts: int = 3,
        max_entities: int = 15,
    ) -> None:
        super().__init__(taxonomy)
        self._backend = backend
        self._model = model
        self._head_chars = head_chars
        self._max_attempts = max_attempts
        self._max_entities = max_entities
        self._system_prompt = self._render_prompt(prompt_path.read_text(encoding="utf-8"))
        self._prompt_digest = hashlib.sha256(self._system_prompt.encode("utf-8")).hexdigest()[:12]

    @property
    def fingerprint(self) -> str:
        """Model, prompt, taxonomy digest and head size."""
        parts = (self._model, self._prompt_digest, self.taxonomy.digest, self._head_chars, self._max_entities)
        return "claude:" + ":".join(map(str, parts))

    def classify(self, document: Document) -> DocumentResult:
        """Classify from the opening; escalate to the full text when confidence is below the review threshold."""
        truncated = document.is_truncated_at(self._head_chars)
        read_full = False
        result = self._classify_text(document, document.head(self._head_chars), partial=truncated)
        if result.confidence < self.taxonomy.confidence_threshold and truncated:
            result = self._classify_text(document, document.body, partial=False)
            read_full = True
        return DocumentResult(
            file=document.name,
            title=document.title,
            date=document.date,
            classification=result,
            needs_review=self.needs_review(document, result),
            read_full_text=read_full,
        )

    def _classify_text(self, document: Document, text: str, partial: bool) -> Classification:
        user_prompt = self._user_prompt(document, text, partial)
        problems: list[str] = []
        reply = ""
        for attempt in range(1, self._max_attempts + 1):
            prompt = user_prompt if not problems else self._retry_prompt(user_prompt, reply, problems)
            try:
                reply = self._backend.generate(self._system_prompt, prompt, {})
                return Classification.from_payload(self._parse_json(reply), self.taxonomy, self._max_entities)
            except ValidationFailedError as exc:
                problems = exc.errors
            except Exception as exc:
                problems = [f"previous attempt failed: {type(exc).__name__}: {exc}"]
                reply = ""
            if attempt == self._max_attempts:
                raise ClassificationError(f"{self._max_attempts} attempts failed: {'; '.join(problems)}")
        raise ClassificationError("no attempts were made")

    def _render_prompt(self, template: str) -> str:
        tax = self.taxonomy
        values = {
            "taxonomy": tax.render_for_prompt(),
            "fallback": tax.fallback_category,
            "document_types": ", ".join(tax.document_types),
            "entity_types": ", ".join(tax.entity_types),
            "max_entities": str(self._max_entities),
            "aliases": ", ".join(tax.canonical_entities),
        }
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", value)
        return template

    @staticmethod
    def _user_prompt(document: Document, text: str, partial: bool) -> str:
        note = "\nOnly the opening of the document is shown." if partial else ""
        return (
            f"Title: {document.title}\nPublisher: {document.publisher}\n"
            f"Publisher's document type: {document.publisher_type}\nDate: {document.date}{note}\n\n"
            f"<document>\n{text}\n</document>"
        )

    @staticmethod
    def _retry_prompt(user_prompt: str, reply: str, problems: list[str]) -> str:
        listed = "\n".join(f"- {p}" for p in problems)
        return (
            f"{user_prompt}\n\nYour previous reply was rejected:\n{reply}\n\n"
            f"Fix these problems and reply with the full JSON again:\n{listed}"
        )

    @staticmethod
    def _parse_json(reply: str) -> Any:
        candidate = fenced.group(1) if (fenced := _FENCE.search(reply)) else reply
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end < start:
            raise ValidationFailedError(["reply contained no JSON object"])
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValidationFailedError([f"invalid JSON: {exc}"]) from exc
