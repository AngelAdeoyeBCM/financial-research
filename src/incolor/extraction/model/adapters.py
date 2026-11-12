"""Apply and persist per-task LoRA adapters on a GLiNER2 model.

Uses the model's own ``apply_lora`` (PEFT-backed) plus PEFT's native
save/load — the "blessed" API per ``gliner2.training.lora``'s module
docstring. The older ``apply_lora_to_model``/``save_lora_adapter``/
``load_lora_adapter`` functions in that module are deprecated shims kept
only for backwards compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from peft import PeftModel


class LoraCapable(Protocol):
    """Anything exposing GLiNER2's blessed PEFT entry point."""

    def apply_lora(
        self,
        r: int = 8,
        alpha: float = 16.0,
        dropout: float = 0.0,
        targets: list[str] | None = None,
        use_dora: bool = False,
    ) -> PeftModel: ...


def apply_adapter(
    model: LoraCapable,
    *,
    r: int = 8,
    alpha: float = 16.0,
    dropout: float = 0.0,
    targets: list[str] | None = None,
    use_dora: bool = False,
) -> PeftModel:
    """Wrap ``model`` with a fresh, trainable LoRA adapter."""
    return model.apply_lora(r=r, alpha=alpha, dropout=dropout, targets=targets, use_dora=use_dora)


def save_adapter(model: PeftModel, path: Path) -> None:
    """Persist one task's adapter weights to ``path``."""
    model.save_pretrained(str(path))


def load_adapter(model: LoraCapable, path: Path) -> PeftModel:
    """Attach a previously saved per-task adapter to ``model``."""
    from peft import PeftModel

    return PeftModel.from_pretrained(model, str(path))
