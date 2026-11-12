"""Persistence repositories for research emails and entities."""

from .entities import EntityRepository

__all__ = ['EmailRepository', 'EntityRepository']


def __getattr__(name: str):
    # Entity storage does not need to load email parsing models.
    if name == 'EmailRepository':
        from .emails import EmailRepository

        return EmailRepository
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
