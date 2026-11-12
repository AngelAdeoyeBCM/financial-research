"""Ontology definitions for reusable research themes."""

from dataclasses import dataclass
from enum import StrEnum

from incolor.utils import require_nonempty


class ThemeStatus(StrEnum):
    ACTIVE = 'active'
    DEPRECATED = 'deprecated'
    PENDING = 'pending'


@dataclass(frozen=True, slots=True)
class Theme:
    """Reusable research theme identified by a stable taxonomy ID."""

    theme_id: str
    name: str

    description: str | None = None
    status: ThemeStatus | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'theme_id',
            require_nonempty(self.theme_id, 'theme_id'),
        )
        object.__setattr__(
            self,
            'name',
            require_nonempty(self.name, 'name'),
        )

        if self.description is not None:
            object.__setattr__(
                self,
                'description',
                require_nonempty(self.description, 'description'),
            )

        if self.status is not None:
            object.__setattr__(
                self,
                'status',
                ThemeStatus(self.status),
            )
