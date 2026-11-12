"""Extension point for an external supervisor reviewing training runs.

Not wired into ``ExtractorTrainer`` — it has no callback/hook mechanism to
attach to (confirmed by reading ``gliner2.training.trainer``). A supervisor
therefore sits one level up, driving a loop of ``TrainingPipeline.run()``
calls and deciding what to change between them from each run's returned
metrics. Left unimplemented until a concrete supervisor (e.g. a Claude
agent) is ready to consume this contract.
"""

from __future__ import annotations

from typing import Protocol


class TrainingSupervisor(Protocol):
    """Reviews one run's results and decides what the next arrangement should be."""

    def review(self, metrics: dict[str, float]) -> str | None:
        """Return guidance for the next run, or None to accept this run as final."""
        ...
