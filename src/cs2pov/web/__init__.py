"""Local-only Web/API surface for the current-version application."""

from .app import CurrentJobWebApplication
from .query import CurrentJobWebQueryError, CurrentJobWebQueryService

__all__ = [
    "CurrentJobWebApplication",
    "CurrentJobWebQueryError",
    "CurrentJobWebQueryService",
]
