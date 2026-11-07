"""Tests for the version check module."""

import json
import socket
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from spoq_server.version_check import (
    VersionCheckResult,
    check_version,
    check_project_structure,
    warn_if_outdated,
)


# ---------------------------------------------------------------------------
# check_version
# ---------------------------------------------------------------------------

def _mock_urlopen(payload: dict):
    """Return a MagicMock that behaves like a urlopen context manager."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_detects_outdated_version():
    """A newer remote version should produce an update notice."""
    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        return_value=_mock_urlopen({"version": "99.0.0"}),
    ):
        result = check_version()
    assert result.is_outdated is True
    assert result.remote_version == "99.0.0"
    assert result.error is None


@pytest.mark.parametrize(
    ("local", "remote", "outdated"),
    [
        ("0.7.0", "0.5.1", False),
        ("0.7.0", "0.7.0", False),
        ("0.7.0", "0.7.1", True),
        ("0.7.0", "0.10.0", True),
        ("0.10.0", "0.9.0", False),
        ("0.7.0rc1", "0.7.0", True),
        ("0.7.0", "0.7.0rc1", False),
    ],
)
def test_update_notice_requires_a_newer_version(local, remote, outdated):
    """Compare release ordering rather than string inequality or lexical order."""
    with (
        patch("spoq_server.version_check.__version__", local),
        patch(
            "spoq_server.version_check.urllib.request.urlopen",
            return_value=_mock_urlopen({"version": remote}),
        ),
    ):
        result = check_version()
    assert result.is_outdated is outdated
    assert result.remote_version == remote
    assert result.error is None


def test_invalid_remote_version_does_not_recommend_an_update():
    """A malformed release value must not disrupt startup or prompt an upgrade."""
    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        return_value=_mock_urlopen({"version": "not-a-version"}),
    ):
        result = check_version()
    assert result.is_outdated is False
    assert result.error is not None


def test_detects_current_version():
    """Remote version matches local — is_outdated should be False."""
    from spoq_server import __version__

    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        return_value=_mock_urlopen({"version": __version__}),
    ):
        result = check_version()
    assert result.is_outdated is False
    assert result.remote_version == __version__
    assert result.error is None


def test_handles_network_failure():
    """Network errors are captured, not raised."""
    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        side_effect=ConnectionError("no network"),
    ):
        result = check_version()
    assert result.is_outdated is False
    assert result.error is not None
    assert "no network" in result.error


def test_handles_timeout():
    """Socket timeout is captured, not raised."""
    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        side_effect=socket.timeout("timed out"),
    ):
        result = check_version()
    assert result.is_outdated is False
    assert result.error is not None


def test_handles_malformed_json():
    """Invalid JSON from the remote is captured."""
    resp = MagicMock()
    resp.read.return_value = b"not json"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch(
        "spoq_server.version_check.urllib.request.urlopen",
        return_value=resp,
    ):
        result = check_version()
    assert result.is_outdated is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# warn_if_outdated
# ---------------------------------------------------------------------------

def test_warns_on_stderr_when_outdated(capsys):
    """Outdated version prints a warning to stderr."""
    result = VersionCheckResult(
        is_outdated=True,
        local_version="0.1.0",
        remote_version="0.2.0",
    )
    warn_if_outdated(result)
    captured = capsys.readouterr()
    assert "Update available" in captured.err
    assert "0.2.0" in captured.err
    assert "pipx upgrade spoq" in captured.err


def test_silent_when_current(capsys):
    """Current version produces no output."""
    result = VersionCheckResult(
        is_outdated=False,
        local_version="0.2.0",
        remote_version="0.2.0",
    )
    warn_if_outdated(result)
    captured = capsys.readouterr()
    assert captured.err == ""


# ---------------------------------------------------------------------------
# spoq_ping integration
# ---------------------------------------------------------------------------

def test_ping_includes_update_notice_when_outdated():
    """spoq_ping includes update fields when a newer version exists."""
    from spoq_server import server

    old = server._version_check_result
    try:
        server._version_check_result = VersionCheckResult(
            is_outdated=True,
            local_version="0.1.0",
            remote_version="0.2.0",
        )
        ping = json.loads(server.spoq_ping())
        assert ping["update_available"] == "0.2.0"
        assert "Update available" in ping["update_notice"]
    finally:
        server._version_check_result = old


def test_ping_omits_update_fields_when_current():
    """spoq_ping has no update fields when version is current."""
    from spoq_server import server

    old = server._version_check_result
    old_proj = server._project_check_result
    try:
        server._version_check_result = VersionCheckResult(
            is_outdated=False,
            local_version="0.2.0",
            remote_version="0.2.0",
        )
        server._project_check_result = None
        ping = json.loads(server.spoq_ping())
        assert "update_available" not in ping
        assert "update_notice" not in ping
        assert "project_needs_upgrade" not in ping
    finally:
        server._version_check_result = old
        server._project_check_result = old_proj


# ---------------------------------------------------------------------------
# check_project_structure
# ---------------------------------------------------------------------------

def _build_spoq_structure(root: Path, *, backlog_epics=True, backlog_maps=True, roadmap=True):
    """Helper to create SPOQ directory structure in a tmp_path."""
    spoq = root / "spoq"
    (spoq / "epics" / "active").mkdir(parents=True)
    (spoq / "epics" / "complete").mkdir(parents=True)
    (spoq / "maps" / "active").mkdir(parents=True)
    (spoq / "maps" / "complete").mkdir(parents=True)
    if backlog_epics:
        (spoq / "epics" / "backlog").mkdir(parents=True)
    if backlog_maps:
        (spoq / "maps" / "backlog").mkdir(parents=True)
    if roadmap:
        (spoq / "ROADMAP.yml").write_text("version: 1\n")


def test_check_project_structure_all_present(tmp_path):
    """Full structure present — needs_upgrade should be False."""
    _build_spoq_structure(tmp_path)
    result = check_project_structure(tmp_path)
    assert result["needs_upgrade"] is False
    assert result["missing"] == []


def test_check_project_structure_missing_backlog(tmp_path):
    """Missing backlog dirs — needs_upgrade should be True."""
    _build_spoq_structure(tmp_path, backlog_epics=False, backlog_maps=False)
    result = check_project_structure(tmp_path)
    assert result["needs_upgrade"] is True
    assert "spoq/epics/backlog/" in result["missing"]
    assert "spoq/maps/backlog/" in result["missing"]


def test_check_project_structure_missing_roadmap_yml(tmp_path):
    """Missing ROADMAP.yml — needs_upgrade should be True."""
    _build_spoq_structure(tmp_path, roadmap=False)
    result = check_project_structure(tmp_path)
    assert result["needs_upgrade"] is True
    assert "spoq/ROADMAP.yml" in result["missing"]
    assert len(result["missing"]) == 1


def test_check_project_structure_no_spoq_dir(tmp_path):
    """Empty project with no spoq/ dir — all items missing."""
    result = check_project_structure(tmp_path)
    assert result["needs_upgrade"] is True
    assert len(result["missing"]) == 3


# ---------------------------------------------------------------------------
# spoq_ping with project structure
# ---------------------------------------------------------------------------

def test_ping_includes_upgrade_when_project_outdated():
    """spoq_ping includes upgrade fields when project structure is outdated."""
    from spoq_server import server

    old_ver = server._version_check_result
    old_proj = server._project_check_result
    try:
        server._version_check_result = VersionCheckResult(
            is_outdated=False,
            local_version="0.2.0",
            remote_version="0.2.0",
        )
        server._project_check_result = {
            "needs_upgrade": True,
            "missing": ["spoq/epics/backlog/", "spoq/ROADMAP.yml"],
        }
        ping = json.loads(server.spoq_ping())
        assert ping["project_needs_upgrade"] is True
        assert "spoq/epics/backlog/" in ping["missing_structure"]
        assert ping["upgrade_command"] == "spoq init --upgrade --target ."
        assert "spoq init --upgrade" in ping["upgrade_instructions"]
        # No version update fields
        assert "update_available" not in ping
    finally:
        server._version_check_result = old_ver
        server._project_check_result = old_proj


def test_ping_includes_both_when_version_and_project_outdated():
    """spoq_ping includes both version and project upgrade fields."""
    from spoq_server import server

    old_ver = server._version_check_result
    old_proj = server._project_check_result
    try:
        server._version_check_result = VersionCheckResult(
            is_outdated=True,
            local_version="0.1.0",
            remote_version="0.2.0",
        )
        server._project_check_result = {
            "needs_upgrade": True,
            "missing": ["spoq/maps/backlog/"],
        }
        ping = json.loads(server.spoq_ping())
        # Version update fields
        assert ping["update_available"] == "0.2.0"
        assert ping["package_update_command"] == "pipx upgrade spoq"
        # Project upgrade fields
        assert ping["project_needs_upgrade"] is True
        assert ping["upgrade_command"] == "spoq init --upgrade --target ."
        assert "spoq/maps/backlog/" in ping["upgrade_instructions"]
    finally:
        server._version_check_result = old_ver
        server._project_check_result = old_proj
