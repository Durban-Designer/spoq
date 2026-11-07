"""Unit tests for team execution MCP tools."""

import json
import pytest


class TestAssignPersonas:
    """Tests for the spoq_assign_personas tool."""

    def test_assigns_personas(self, fixture_epic_path):
        """Verify correct persona assignment based on skills and file patterns."""
        from spoq_server.team_tools import spoq_assign_personas

        result = json.loads(spoq_assign_personas(str(fixture_epic_path)))
        assert "error" not in result
        # Task with react/tailwind skills should be frontend
        assert result["02-core"] == "frontend"
        # Task with jest/pytest should be testing
        assert result["04-tests"] == "testing"

    def test_verbose_mode(self, fixture_epic_path):
        """Verbose output should include persona, score, and per-persona scores."""
        from spoq_server.team_tools import spoq_assign_personas

        result = json.loads(
            spoq_assign_personas(str(fixture_epic_path), verbose=True)
        )
        # Verbose should return dicts with persona, score, scores
        entry = result["02-core"]
        assert "persona" in entry
        assert "score" in entry
        assert "scores" in entry
        assert entry["persona"] == "frontend"
        assert entry["score"] > 0

    def test_invalid_epic(self):
        """Non-existent epic path should return an error."""
        from spoq_server.team_tools import spoq_assign_personas

        result = json.loads(spoq_assign_personas("/nonexistent/path"))
        assert "error" in result


class TestDetectConflicts:
    """Tests for the spoq_detect_conflicts tool."""

    def test_detects_shared_files(self, fixture_epic_path):
        """Wave 0 has tasks 01-setup and 02-core which share no files.

        Tasks 01-setup and 03-api both touch src/config.py, but they
        reside in separate waves so no intra-wave conflict occurs.
        """
        from spoq_server.team_tools import spoq_detect_conflicts

        result = json.loads(spoq_detect_conflicts(str(fixture_epic_path), 0))
        assert "error" not in result
        assert result["wave"] == 0
        # Wave 0 tasks (01-setup, 02-core) do not share files
        assert len(result["conflicts"]) == 0
        assert len(result["safe_tasks"]) == 2

    def test_wave_1_single_task(self, fixture_epic_path):
        """Wave 1 has only task 03-api, so no conflicts are possible."""
        from spoq_server.team_tools import spoq_detect_conflicts

        result = json.loads(spoq_detect_conflicts(str(fixture_epic_path), 1))
        assert len(result["conflicts"]) == 0
        assert "03-api" in result["safe_tasks"]

    def test_invalid_wave(self, fixture_epic_path):
        """Requesting a non-existent wave should return an error."""
        from spoq_server.team_tools import spoq_detect_conflicts

        result = json.loads(spoq_detect_conflicts(str(fixture_epic_path), 99))
        assert "error" in result
        assert "not found" in result["error"]

    def test_invalid_epic(self):
        """Non-existent epic path should return an error."""
        from spoq_server.team_tools import spoq_detect_conflicts

        result = json.loads(spoq_detect_conflicts("/nonexistent/path", 0))
        assert "error" in result
