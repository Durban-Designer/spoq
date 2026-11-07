"""Tests for init_cmd.py — fresh init and upgrade paths."""

from __future__ import annotations

import yaml
import pytest
from pathlib import Path

from spoq_server.init_cmd import (
    run_init,
    DIRECTORIES,
    TODO_YML_TEMPLATE,
)


class TestFreshInit:
    """Test the _fresh_init path via run_init()."""

    def test_creates_all_directories(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        for d in DIRECTORIES:
            assert (tmp_path / d).is_dir(), f"Missing directory: {d}"

    def test_creates_backlog_dirs(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        assert (tmp_path / "spoq" / "epics" / "backlog").is_dir()
        assert (tmp_path / "spoq" / "maps" / "backlog").is_dir()

    def test_creates_roadmap_yml(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        roadmap = tmp_path / "spoq" / "ROADMAP.yml"
        assert roadmap.exists()
        data = yaml.safe_load(roadmap.read_text())
        assert data["version"] == 1
        assert data["epics"] == []
        assert "updated_at" in data

    def test_no_roadmap_md_created(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        assert not (tmp_path / "spoq" / "ROADMAP.md").exists()

    def test_creates_todo_yml(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        todo = tmp_path / "TODO.yml"
        assert todo.exists()
        data = yaml.safe_load(todo.read_text())
        assert data["version"] == "1"
        assert data["sections"] == []
        assert data["standalone"] == []
        assert data["maps"] == []

    def test_creates_claude_md(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        claude = tmp_path / "CLAUDE.md"
        assert claude.exists()
        content = claude.read_text()
        assert "SPOQ" in content

    def test_creates_journal_md(self, tmp_path: Path) -> None:
        run_init(target=str(tmp_path))
        journal = tmp_path / "journal.md"
        assert journal.exists()

    def test_idempotent_no_clobber(self, tmp_path: Path) -> None:
        """Running init twice should not overwrite existing files."""
        run_init(target=str(tmp_path))
        # Write custom content to CLAUDE.md
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("custom content")
        # Re-run init
        run_init(target=str(tmp_path))
        assert claude.read_text() == "custom content"

    def test_idempotent_todo_no_clobber(self, tmp_path: Path) -> None:
        """Running init twice should not overwrite existing TODO.yml."""
        run_init(target=str(tmp_path))
        todo = tmp_path / "TODO.yml"
        todo.write_text("custom: true")
        run_init(target=str(tmp_path))
        assert todo.read_text() == "custom: true"

    def test_fresh_init_full_with_mcp(self, tmp_path: Path) -> None:
        """--full --with-mcp creates directories, files, example epic, and .mcp.json."""
        run_init(target=str(tmp_path), full=True, with_mcp=True)

        # All standard directories exist
        for d in DIRECTORIES:
            assert (tmp_path / d).is_dir(), f"Missing directory: {d}"

        # Core files
        assert (tmp_path / "spoq" / "ROADMAP.yml").exists()
        assert (tmp_path / "TODO.yml").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "journal.md").exists()

        # MCP configuration
        mcp_json = tmp_path / ".mcp.json"
        assert mcp_json.exists()
        import json
        mcp_data = json.loads(mcp_json.read_text())
        assert "spoq" in mcp_data.get("mcpServers", {})

        # Example epic from --full flag
        example_epic = tmp_path / "spoq" / "epics" / "active" / "example-config-validator"
        assert example_epic.is_dir()
        assert (example_epic / "EPIC.md").exists()


class TestUpgrade:
    """Test the _upgrade path via run_init(upgrade=True)."""

    def test_creates_missing_backlog_dirs(self, tmp_path: Path) -> None:
        # Create minimal structure without backlog dirs
        (tmp_path / "spoq" / "epics" / "active").mkdir(parents=True)
        (tmp_path / "spoq" / "maps" / "active").mkdir(parents=True)
        run_init(target=str(tmp_path), upgrade=True)
        assert (tmp_path / "spoq" / "epics" / "backlog").is_dir()
        assert (tmp_path / "spoq" / "maps" / "backlog").is_dir()

    def test_creates_roadmap_yml_on_upgrade(self, tmp_path: Path) -> None:
        (tmp_path / "spoq" / "epics" / "active").mkdir(parents=True)
        run_init(target=str(tmp_path), upgrade=True)
        roadmap = tmp_path / "spoq" / "ROADMAP.yml"
        assert roadmap.exists()
        data = yaml.safe_load(roadmap.read_text())
        assert data["version"] == 1

    def test_does_not_overwrite_existing_roadmap_yml(self, tmp_path: Path) -> None:
        (tmp_path / "spoq").mkdir(parents=True)
        roadmap = tmp_path / "spoq" / "ROADMAP.yml"
        roadmap.write_text("version: 1\nepics: [{slug: existing}]\n")
        run_init(target=str(tmp_path), upgrade=True)
        data = yaml.safe_load(roadmap.read_text())
        assert len(data["epics"]) == 1
        assert data["epics"][0]["slug"] == "existing"

    def test_migration_notice_when_md_exists(self, tmp_path: Path, capsys) -> None:
        (tmp_path / "spoq").mkdir(parents=True)
        (tmp_path / "spoq" / "ROADMAP.md").write_text("# Old roadmap")
        run_init(target=str(tmp_path), upgrade=True)
        captured = capsys.readouterr()
        assert "ROADMAP.md detected" in captured.out

    def test_creates_todo_yml_on_upgrade(self, tmp_path: Path) -> None:
        (tmp_path / "spoq" / "epics" / "active").mkdir(parents=True)
        run_init(target=str(tmp_path), upgrade=True)
        todo = tmp_path / "TODO.yml"
        assert todo.exists()

    def test_does_not_overwrite_existing_todo_yml(self, tmp_path: Path) -> None:
        (tmp_path / "spoq" / "epics" / "active").mkdir(parents=True)
        todo = tmp_path / "TODO.yml"
        todo.write_text("custom: true")
        run_init(target=str(tmp_path), upgrade=True)
        assert todo.read_text() == "custom: true"

    def test_upgrade_already_up_to_date(self, tmp_path: Path, capsys) -> None:
        """Running upgrade on a fully-initialized project reports up to date."""
        run_init(target=str(tmp_path))
        run_init(target=str(tmp_path), upgrade=True)
        captured = capsys.readouterr()
        assert "up to date" in captured.out


class TestClaudeSettings:
    """Test _setup_claude_settings creates MCP permissions."""

    def test_creates_settings_with_spoq_permissions(self, tmp_path: Path) -> None:
        import json
        run_init(target=str(tmp_path))
        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "mcp__spoq__*" in data["permissions"]["allow"]

    def test_merges_into_existing_settings(self, tmp_path: Path) -> None:
        import json
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        settings = settings_dir / "settings.json"
        settings.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
        run_init(target=str(tmp_path))
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["env"]["FOO"] == "bar"
        assert "mcp__spoq__*" in data["permissions"]["allow"]

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        import json
        run_init(target=str(tmp_path))
        run_init(target=str(tmp_path))
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        count = data["permissions"]["allow"].count("mcp__spoq__*")
        assert count == 1

    def test_preserves_existing_permissions(self, tmp_path: Path) -> None:
        import json
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        settings = settings_dir / "settings.json"
        existing = {"permissions": {"allow": ["Bash(npm *)"]}}
        settings.write_text(json.dumps(existing), encoding="utf-8")
        run_init(target=str(tmp_path))
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "Bash(npm *)" in data["permissions"]["allow"]
        assert "mcp__spoq__*" in data["permissions"]["allow"]

    def test_upgrade_also_sets_permissions(self, tmp_path: Path) -> None:
        import json
        (tmp_path / "spoq" / "epics" / "active").mkdir(parents=True)
        run_init(target=str(tmp_path), upgrade=True)
        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "mcp__spoq__*" in data["permissions"]["allow"]


class TestTodoYmlTemplate:
    """Test the TODO_YML_TEMPLATE constant."""

    def test_template_is_valid_yaml(self) -> None:
        data = yaml.safe_load(TODO_YML_TEMPLATE)
        assert data["version"] == "1"
        assert data["sections"] == []
        assert data["standalone"] == []
        assert data["maps"] == []

    def test_template_has_all_required_keys(self) -> None:
        data = yaml.safe_load(TODO_YML_TEMPLATE)
        for key in ("version", "updated", "sections", "standalone", "maps"):
            assert key in data, f"Missing key: {key}"
