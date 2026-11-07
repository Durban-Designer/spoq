"""Unit tests for utility MCP tools."""

import json
import re
import pytest
from pathlib import Path


class TestGetTimestamp:
    def test_iso_format(self):
        from spoq_server.util_tools import spoq_get_timestamp
        result = spoq_get_timestamp("iso")
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result)

    def test_default_is_iso(self):
        from spoq_server.util_tools import spoq_get_timestamp
        result = spoq_get_timestamp()
        assert result.endswith("Z")
        assert "T" in result

    def test_unix_format(self):
        from spoq_server.util_tools import spoq_get_timestamp
        result = spoq_get_timestamp("unix")
        assert result.isdigit()
        assert int(result) > 1700000000  # After 2023

    def test_readable_format(self):
        from spoq_server.util_tools import spoq_get_timestamp
        result = spoq_get_timestamp("readable")
        assert "UTC" in result
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", result)

    def test_invalid_format(self):
        from spoq_server.util_tools import spoq_get_timestamp
        result = spoq_get_timestamp("invalid")
        assert "Unknown format" in result


class TestGenerateSkeleton:
    def test_creates_structure(self, tmp_path):
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton("My Test Epic", 6, str(tmp_path)))
        assert "error" not in result
        assert result["task_count"] == 6

        epic_path = Path(result["epic_path"])
        assert epic_path.exists()
        assert (epic_path / "EPIC.md").exists()
        assert (epic_path / "tasks").exists()

    def test_correct_task_count(self, tmp_path):
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton("Test Epic", 8, str(tmp_path)))
        epic_path = Path(result["epic_path"])
        yml_files = list((epic_path / "tasks").glob("*.yml"))
        assert len(yml_files) == 8

    def test_wave_distribution(self, tmp_path):
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton("Wave Test", 10, str(tmp_path)))
        dist = result["wave_distribution"]
        assert dist["wave_0"] + dist["wave_1"] + dist["later"] == 10
        assert dist["wave_0"] >= 1
        assert dist["wave_1"] >= 1

    def test_slug_generation(self, tmp_path):
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton("My Cool Feature", 3, str(tmp_path)))
        assert "my-cool-feature" in result["epic_path"]

    def test_minimum_tasks(self):
        from spoq_server.util_tools import spoq_generate_skeleton
        result = json.loads(spoq_generate_skeleton("Tiny", 2, "/tmp/test"))
        assert "error" in result
        assert "Minimum 3" in result["error"]

    def test_existing_epic_error(self, tmp_path):
        from spoq_server.util_tools import spoq_generate_skeleton
        # Create first
        spoq_generate_skeleton("Dupe Test", 3, str(tmp_path))
        # Try to create again
        result = json.loads(spoq_generate_skeleton("Dupe Test", 3, str(tmp_path)))
        assert "error" in result
        assert "already exists" in result["error"]
