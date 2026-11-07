"""Non-blocking version check against the published version on spoqpaper.com."""

import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version

from spoq_server import __version__

VERSION_URL = "https://spoqpaper.com/mcp-version.json"
TIMEOUT_SECONDS = 3


@dataclass
class VersionCheckResult:
    """Comparison of the local version against the published version."""

    is_outdated: bool
    local_version: str
    remote_version: str | None
    error: str | None = None


def check_version() -> VersionCheckResult:
    """Fetch the remote version and compare against ``__version__``.

    Never raises — all failures are captured in the *error* field so the
    MCP server can start regardless of network conditions.
    """
    try:
        req = urllib.request.Request(VERSION_URL, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            remote = data.get("version", "")
            is_outdated = remote != "" and Version(remote) > Version(__version__)
            return VersionCheckResult(
                is_outdated=is_outdated,
                local_version=__version__,
                remote_version=remote,
            )
    except Exception as exc:
        return VersionCheckResult(
            is_outdated=False,
            local_version=__version__,
            remote_version=None,
            error=str(exc),
        )


def check_project_structure(root: Path) -> dict:
    """Check if the project has current SPOQ structure. Never raises."""
    missing = []
    try:
        spoq = root / "spoq"
        if not (spoq / "epics" / "backlog").is_dir():
            missing.append("spoq/epics/backlog/")
        if not (spoq / "maps" / "backlog").is_dir():
            missing.append("spoq/maps/backlog/")
        if not (spoq / "ROADMAP.yml").is_file():
            missing.append("spoq/ROADMAP.yml")
    except OSError:
        pass
    return {"needs_upgrade": len(missing) > 0, "missing": missing}


def warn_if_outdated(result: VersionCheckResult) -> None:
    """Print a warning to stderr if the local version is outdated."""
    if result.is_outdated:
        print(
            f"[spoq] Update available: {result.local_version} → "
            f"{result.remote_version}. Run: pipx upgrade spoq",
            file=sys.stderr,
        )
