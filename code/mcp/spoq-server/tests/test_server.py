"""Unit tests for SPOQ MCP server core."""

import json
import os
import re
from pathlib import Path

import pytest


def test_server_imports():
    """Verify server module imports without error."""
    from spoq_server.server import mcp, project_root
    assert mcp is not None
    assert mcp.name == "spoq"


def test_project_root_exists(tmp_path, monkeypatch):
    """Resolve an actual test project without depending on the test runner CWD."""
    (tmp_path/'.git').mkdir()
    monkeypatch.chdir(tmp_path)
    from spoq_server.server import project_root
    root = project_root()
    assert root.exists()
    assert (root / ".git").exists()


def test_project_root_prefers_cwd(tmp_path: Path, monkeypatch):
    """When CWD has a spoq/ dir, project_root() should return CWD."""
    (tmp_path / "spoq").mkdir()
    monkeypatch.chdir(tmp_path)
    # Re-import to pick up new CWD
    from spoq_server import server
    root = server.project_root()
    assert root == tmp_path


def test_project_root_walks_up_from_cwd(tmp_path: Path, monkeypatch):
    """When CWD is a subdirectory, project_root() walks up to find .git."""
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "code" / "apps"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    from spoq_server import server
    root = server.project_root()
    assert root == tmp_path


def test_bundled_utils_importable():
    """Verify bundled epic_utils and map_utils import without error."""
    from spoq_server import epic_utils, map_utils
    assert hasattr(epic_utils, "parse_epic")
    assert hasattr(map_utils, "parse_map_md")


def test_spoq_ping():
    """Verify spoq_ping returns valid JSON with expected keys."""
    from spoq_server.server import spoq_ping
    result = json.loads(spoq_ping())
    assert result["status"] == "ok"
    assert "version" in result
    assert "project_root" in result
    assert "package" in result


def test_version():
    """Verify package version is derived from installed metadata."""
    from spoq_server import __version__
    assert __version__
    assert re.match(r"^\d+\.\d+\.\d+", __version__) or __version__ == "0.0.0-dev"
