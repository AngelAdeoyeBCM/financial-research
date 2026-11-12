"""Local model backend: Ollama, with the JSON Schema passed as the constrained-decoding format."""

from typing import Any

from .base import BackendUnavailableError


class OllamaBackend:
    """Call a local Ollama server. Requires the ``ollama`` package and a running server."""

    name = "local"

    def __init__(self, model: str, host: str, num_ctx: int, temperature: float) -> None:
        try:
            import ollama
        except ImportError as exc:
            raise BackendUnavailableError("The local backend requires ollama: pip install 'ollama>=0.4'") from exc
        self._ollama = ollama
        self._client = ollama.Client(host=host)
        self._model = model
        self._options: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx}

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the assistant message text for one chat request.

        Raises:
            BackendUnavailableError: If the server is unreachable or rejects the request.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = self._client.chat(
                model=self._model,
                messages=messages,
                format=json_schema,
                options=self._options,
            )
        except ConnectionError as exc:
            raise BackendUnavailableError(f"Ollama server is not reachable: {exc}") from exc
        except self._ollama.ResponseError as exc:
            raise BackendUnavailableError(f"Ollama rejected the request for model {self._model!r}: {exc}") from exc
        return response.message.content or ""
