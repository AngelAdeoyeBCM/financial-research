"""Thin orchestration around GLiNER2's trainer for a single training run."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gliner2.training.trainer import TrainingConfig

if TYPE_CHECKING:
    from gliner2.inference.engine import GLiNER2
    from gliner2.training.data import TrainDataInput


class TrainingPipeline:
    """Configure and run one ``ExtractorTrainer`` training arrangement.

    Kept deliberately thin: ``config`` carries every knob worth varying
    between experiments (LoRA on/off, learning rates, schedule, ...), so a
    new arrangement is a new ``TrainingConfig``, not new code here.
    """

    def __init__(self, model: GLiNER2, config: TrainingConfig) -> None:
        self._model = model
        self._config = config

    def run(
        self, train_data: TrainDataInput, eval_data: TrainDataInput | None = None
    ) -> dict[str, Any]:
        from gliner2.training.trainer import ExtractorTrainer

        trainer = ExtractorTrainer(model=self._model, config=self._config)
        return trainer.train(train_data=train_data, eval_data=eval_data)
