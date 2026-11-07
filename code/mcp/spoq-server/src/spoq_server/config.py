"""Configuration for the optional legacy filesystem server.

SPOQ 1.x uses SQLite through spoq_server.v1. The explicit legacy launcher
keeps filesystem compatibility for projects that have not converted yet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

VALID_STORES = ("fs",)

@dataclass(frozen=True)
class ServerConfig:
    store_backend: Literal["fs"] = "fs"

def load_config() -> ServerConfig:
    backend = os.environ.get("SPOQ_STORE", "fs").strip().lower()
    if backend != "fs":
        raise SystemExit(f"Invalid legacy SPOQ_STORE={backend!r}. Use fs for legacy files, or the default SQLite CLI.")
    return ServerConfig()

def build_store(cfg: ServerConfig, root: Path | None = None):
    from spoq_server.stores.fs import get_fs_store
    if root is None:
        from spoq_server.server import project_root
        root = project_root()
    return get_fs_store(Path(root))
