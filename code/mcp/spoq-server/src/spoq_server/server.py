"""
SPOQ MCP Server entry point.

Registers all SPOQ tools and runs the FastMCP server via stdio transport.
On startup, checks for newer versions published at spoqpaper.com and warns
the user if an update is available.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from spoq_server import __version__
from spoq_server.config import ServerConfig, build_store, load_config
from spoq_server.version_check import (
    VersionCheckResult,
    check_version,
    check_project_structure,
    warn_if_outdated,
)


# An explicit project-root override, set via `spoq mcp --root <path>` before
# the server starts. Takes precedence over every autodetection heuristic.
_project_root_override: Path | None = None


def set_project_root_override(path: str | os.PathLike | None) -> None:
    """Pin the project root to an explicit path (or clear it with None)."""
    global _project_root_override
    _project_root_override = Path(path).expanduser().resolve() if path else None


def project_root() -> Path:
    """Return the project root where SPOQ is being used.

    Strategy:
    0. An explicit override (`spoq mcp --root`) or the SPOQ_PROJECT_ROOT
       environment variable, which fix the root regardless of launch CWD.
    1. Use CWD if it looks like a SPOQ project (has .git or spoq/ dir).
       MCP clients like Claude Code launch servers with the project as CWD.
    2. Walk up from CWD to find a .git directory.
    3. Walk up from __file__ (works when running from source inside the repo).
    4. Fall back to CWD as a last resort.
    """
    if _project_root_override is not None:
        return _project_root_override

    env_root = os.environ.get("SPOQ_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    cwd = Path.cwd().resolve()

    # CWD is the project root (most common case for pipx installs)
    if (cwd / ".git").exists() or (cwd / "spoq").is_dir():
        return cwd

    # Walk up from CWD
    for parent in cwd.parents:
        if (parent / ".git").exists():
            return parent

    # Walk up from __file__ (works when running from source)
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent

    # Last resort: assume CWD is the project
    return cwd


# Module-level state populated by the lifespan hook.
_version_check_result: VersionCheckResult | None = None
_project_check_result: dict | None = None


# ---------------------------------------------------------------------------
# Legacy filesystem storage, resolved once at startup.
_config: ServerConfig = load_config()
_store = build_store(_config)


def active_backend() -> str:
    """Return the active storage backend name ("fs")."""
    return _config.store_backend


def get_store(root_resolver=None):
    """Return the cached filesystem store for the resolved project root."""
    from spoq_server.stores.fs import get_fs_store

    resolver = root_resolver if root_resolver is not None else project_root
    return get_fs_store(resolver())


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Run startup tasks (version check, project structure check) and yield server context."""
    global _version_check_result, _project_check_result
    _version_check_result = check_version()
    warn_if_outdated(_version_check_result)
    _project_check_result = check_project_structure(project_root())
    if _project_check_result.get("needs_upgrade"):
        print(
            "[spoq] Project structure outdated. Run: spoq init --upgrade",
            file=sys.stderr,
        )
    yield {}


# Create FastMCP server instance with lifespan
mcp = FastMCP("spoq", lifespan=lifespan)


@mcp.tool()
def spoq_ping() -> str:
    """Health check - returns server version and project root path."""
    result = {
        "version": __version__,
        "package": "spoq",
        "status": "ok",
        "active_backend": _config.store_backend,
    }
    result["project_root"] = str(project_root())
    if _version_check_result and _version_check_result.is_outdated:
        result["update_available"] = _version_check_result.remote_version
        result["update_notice"] = (
            f"Update available: {_version_check_result.local_version} → "
            f"{_version_check_result.remote_version}. Run: pipx upgrade spoq"
        )
        result["package_update_command"] = "pipx upgrade spoq"
    if _project_check_result and _project_check_result.get("needs_upgrade"):
        result["project_needs_upgrade"] = True
        result["missing_structure"] = _project_check_result["missing"]
        result["upgrade_command"] = "spoq init --upgrade --target ."
        result["upgrade_instructions"] = (
            "Project structure is outdated. Missing: "
            + ", ".join(_project_check_result["missing"])
            + ". Run `spoq init --upgrade` to update."
        )
    return json.dumps(result)


# Import tool modules to register their tools with the mcp instance
import spoq_server.epic_tools  # noqa: F401, E402
import spoq_server.task_tools  # noqa: F401, E402
import spoq_server.team_tools  # noqa: F401, E402
import spoq_server.util_tools  # noqa: F401, E402
import spoq_server.map_tools  # noqa: F401, E402
import spoq_server.roadmap_tools  # noqa: F401, E402


def main():
    """Run the SPOQ MCP server."""
    # Startup banner on stderr (stdout is reserved for the stdio MCP protocol).
    # Reports the active storage backend so operators can confirm fs vs api at
    # a glance: `store=fs` for this explicit legacy server.
    print(
        f"[spoq] starting MCP server v{__version__} store={_config.store_backend}",
        file=sys.stderr,
        flush=True,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
