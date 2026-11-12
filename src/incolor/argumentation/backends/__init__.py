"""Model backends. Backend modules are imported lazily so optional SDKs are only needed when selected."""

from typing import TYPE_CHECKING

from .base import BackendUnavailableError, ModelBackend

if TYPE_CHECKING:
    from ..pipeline import PipelineConfig

__all__ = ["BackendUnavailableError", "ModelBackend", "get_backend"]


def get_backend(config: "PipelineConfig") -> ModelBackend:
    """Return the backend selected by ``config.backend``.

    Raises:
        BackendUnavailableError: If the selected backend's SDK or settings are missing.
        ValueError: If ``config.backend`` is not a known backend.
    """
    if config.backend == "claude":
        from .claude_agent import ClaudeAgentBackend

        return ClaudeAgentBackend(model=config.claude.model)
    if config.backend == "local":
        from .ollama_local import OllamaBackend

        return OllamaBackend(
            model=config.local.model,
            host=config.local.host,
            num_ctx=config.local.num_ctx,
            temperature=config.temperature,
        )
    raise ValueError(f"Unknown backend: {config.backend!r}")
