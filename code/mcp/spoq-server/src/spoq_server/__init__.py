"""SPOQ — Specialist Orchestrated Queuing for multi-agent AI development.

Provides:
  - SQLite-native Project Plans, Features, Tasks, journals, and collaboration
  - CPU hybrid search and Codex notification adapters
  - Explicit legacy filesystem/API compatibility and lossless migration
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("spoq")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
