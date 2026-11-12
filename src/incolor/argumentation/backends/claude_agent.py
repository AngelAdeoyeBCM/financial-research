"""Claude backend: Claude Agent SDK, single turn, no tools. Needs ANTHROPIC_API_KEY or a Claude Code login."""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from .base import BackendUnavailableError

try:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, CLINotFoundError, ResultMessage, TextBlock, query
except ImportError as exc:
    raise BackendUnavailableError("The claude backend requires: pip install 'claude-agent-sdk'") from exc


def _has_claude_login() -> bool:
    """Return True if Claude Code has stored login credentials the SDK's CLI can use."""
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return (config_dir / ".credentials.json").is_file()


class ClaudeAgentBackend:
    """Send one prompt pair to Claude with no tools and return the concatenated text blocks.

    ``usage`` collects one record per call (cost, tokens, duration, resolved model ids) for run summaries.
    """

    name = "claude"

    def __init__(self, model: str | None) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY") and not _has_claude_login():
            raise BackendUnavailableError(
                "Neither ANTHROPIC_API_KEY nor a Claude Code login was found; the claude backend cannot run."
            )
        self._model = model
        self.usage: list[dict[str, Any]] = []

    def generate(self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]) -> str:
        """Return the assistant text for one turn. The JSON Schema is enforced by validation, not by the SDK.

        Raises:
            BackendUnavailableError: If the Claude Code CLI is missing or the SDK reports an error.
        """
        del json_schema  # Schema is embedded in the system prompt; validation enforces it.
        try:
            return asyncio.run(self._collect(system_prompt, user_prompt))
        except CLINotFoundError as exc:
            raise BackendUnavailableError(
                "The Claude Code CLI was not found. Install it, or use --backend local."
            ) from exc

    async def _collect(self, system_prompt: str, user_prompt: str) -> str:
        # A file avoids the Windows 32,767-character command-line limit that a long --system-prompt hits.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
            f.write(system_prompt)
        prompt_path = Path(f.name)
        try:
            options = ClaudeAgentOptions(
                system_prompt={"type": "file", "path": str(prompt_path)},
                model=self._model,
                max_turns=1,
                tools=[],
                allowed_tools=[],
            )
            chunks: list[str] = []
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    chunks.extend(block.text for block in message.content if isinstance(block, TextBlock))
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        raise BackendUnavailableError(f"Claude Agent SDK returned an error: {message.result}")
                    self.usage.append(
                        {
                            "cost_usd": message.total_cost_usd,
                            "duration_ms": message.duration_ms,
                            "usage": message.usage,
                            "models": sorted(message.model_usage or {}),
                        }
                    )
            return "".join(chunks)
        finally:
            prompt_path.unlink(missing_ok=True)
