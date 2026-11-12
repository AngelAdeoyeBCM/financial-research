"""Backend protocol and the error raised when a backend cannot run."""

from typing import Any, Protocol


class BackendUnavailableError(RuntimeError):
    """Raised when a model backend is not installed, not configured, or not reachable."""


class ModelBackend(Protocol):
    """A text-in, text-out model call. Implementations must not use tools."""

    name: str

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the model's raw text response for one prompt pair."""
        ...
