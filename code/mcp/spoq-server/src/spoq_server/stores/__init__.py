"""SPOQ storage layer — public surface.

ABCs (:class:`EpicStore`, :class:`MapStore`, :class:`RoadmapStore`) plus the
typed records (:class:`Epic`, :class:`Task`, :class:`MapDoc`,
:class:`RoadmapEntry`) that backends implement and tool modules consume.

Two backend-agnostic exceptions live here so storage backends —
and the config/selection layer — raise a single shared type:

* :class:`ConfigurationError` — a backend cannot be constructed because its
  required configuration (env vars) is absent or invalid. Raised at
  construction time, before any I/O.
* :class:`StoreError` — a storage operation failed at runtime (a missing
  record, an auth rejection, a conflict). Tool modules surface its message
  verbatim as a tool-level error.
"""


class StoreError(Exception):
    """A storage operation failed (not-found, auth, conflict, transport).

    Backends raise this with a human-readable, tool-surfaceable message; the
    MCP tool handlers relay ``str(exc)`` to the caller. It deliberately sits
    above any backend-specific exception (``httpx.HTTPError``,
    ``FileNotFoundError``) so tool code never imports a backend's library.
    """


class ConfigurationError(StoreError):
    """A backend could not be constructed from the current configuration.

    Subclasses :class:`StoreError` so a broad ``except StoreError`` still
    catches misconfiguration, while callers that care can distinguish a
    construction-time config fault from a runtime operation failure.
    """


from .base import EpicStore, MapStore, RoadmapStore
from .records import Epic, MapDoc, RoadmapEntry, Task

__all__ = [
    "EpicStore",
    "MapStore",
    "RoadmapStore",
    "Epic",
    "Task",
    "MapDoc",
    "RoadmapEntry",
    "StoreError",
    "ConfigurationError",
]
