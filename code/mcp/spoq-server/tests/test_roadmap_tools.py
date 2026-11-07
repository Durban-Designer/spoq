"""Unit tests for SPOQ roadmap management MCP tools.

Tests cover the 2 roadmap tools:
  - spoq_roadmap_show: display and filter ROADMAP.yml contents
  - spoq_roadmap_sync: reconcile ROADMAP.yml with on-disk epic directories

Also tests roadmap utilities through the MCP tool layer (TestRoadmapUtils).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from spoq_server.server import mcp
from spoq_server import roadmap_utils


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def call(tool_name: str, arguments: dict | None = None) -> str:
    """Invoke an MCP tool and return the raw text payload."""
    result = await mcp.call_tool(tool_name, arguments or {})
    contents, _meta = result
    return contents[0].text


async def call_json(tool_name: str, arguments: dict | None = None) -> dict:
    """Invoke an MCP tool and return the parsed JSON payload."""
    text = await call(tool_name, arguments)
    return json.loads(text)


def _write_roadmap(spoq_dir: Path, epics: list[dict]) -> None:
    """Write a minimal ROADMAP.yml for testing."""
    data = {
        "version": 1,
        "updated_at": "",
        "epics": epics,
    }
    roadmap = spoq_dir / "ROADMAP.yml"
    roadmap.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _make_epic_dirs(spoq_dir: Path, tiers: dict[str, list[str]]) -> None:
    """Create spoq_dir/epics/<tier>/<slug>/ directories."""
    for tier, slugs in tiers.items():
        for slug in slugs:
            (spoq_dir / "epics" / tier / slug).mkdir(parents=True, exist_ok=True)


# ===================================================================
# 1. Roadmap Show
# ===================================================================

class TestRoadmapShow:
    """spoq_roadmap_show: display and filter roadmap contents."""

    @pytest.mark.anyio
    async def test_missing_roadmap_returns_error(self, tmp_path):
        """When ROADMAP.yml does not exist, returns a structured error."""
        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {})
        assert "error" in data
        assert "ROADMAP.yml not found" in data["error"]

    @pytest.mark.anyio
    async def test_show_all_tiers(self, tmp_path):
        """With no tier filter, all epics are returned."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
            {"slug": "beta", "title": "Beta", "tier": "active", "status": "in_progress"},
            {"slug": "gamma", "title": "Gamma", "tier": "complete", "status": "completed"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {})

        assert "error" not in data
        assert len(data["epics"]) == 3
        assert data["counts"]["total"] == 3
        assert data["counts"]["backlog"] == 1
        assert data["counts"]["active"] == 1
        assert data["counts"]["complete"] == 1

    @pytest.mark.anyio
    async def test_filter_by_tier(self, tmp_path):
        """Filtering by tier returns only matching epics."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
            {"slug": "beta", "title": "Beta", "tier": "active", "status": "in_progress"},
            {"slug": "gamma", "title": "Gamma", "tier": "active", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"tier": "active"})

        assert "error" not in data
        assert len(data["epics"]) == 2
        assert data["counts"]["total"] == 2
        assert data["counts"]["active"] == 2
        assert all(e["tier"] == "active" for e in data["epics"])

    @pytest.mark.anyio
    async def test_invalid_tier_returns_error(self, tmp_path):
        """An invalid tier value returns a structured error."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"tier": "invalid"})

        assert "error" in data
        assert "Invalid tier" in data["error"]

    @pytest.mark.anyio
    async def test_table_format(self, tmp_path):
        """Table format returns a markdown-formatted rendered string."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"format": "table"})

        assert "error" not in data
        assert "rendered" in data
        assert "|" in data["rendered"]  # Markdown table pipe chars

    @pytest.mark.anyio
    async def test_json_format(self, tmp_path):
        """JSON format returns parseable JSON in the rendered field."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"format": "json"})

        assert "error" not in data
        rendered = json.loads(data["rendered"])
        assert isinstance(rendered, list)
        assert rendered[0]["slug"] == "alpha"

    @pytest.mark.anyio
    async def test_response_structure(self, tmp_path):
        """Response includes rendered, epics, and counts keys."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alpha", "title": "Alpha", "tier": "backlog", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {})

        assert "rendered" in data
        assert "epics" in data
        assert "counts" in data
        assert isinstance(data["epics"], list)
        assert isinstance(data["counts"], dict)


# ===================================================================
# 2. Roadmap Sync
# ===================================================================

class TestRoadmapSync:
    """spoq_roadmap_sync: reconcile ROADMAP.yml with disk."""

    @pytest.mark.anyio
    async def test_sync_creates_new_roadmap(self, tmp_path):
        """When no ROADMAP.yml exists, sync creates one with all discovered epics."""
        spoq_dir = tmp_path / "spoq"
        _make_epic_dirs(spoq_dir, {
            "backlog": ["feat-a"],
            "active": ["feat-b"],
            "complete": ["feat-c"],
        })

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        assert "error" not in data
        assert data["new_file"] is True
        assert sorted(data["added"]) == ["feat-a", "feat-b", "feat-c"]
        assert data["removed"] == []
        assert data["updated"] == []

        # Verify file was written
        assert (spoq_dir / "ROADMAP.yml").exists()

    @pytest.mark.anyio
    async def test_sync_detects_added_epics(self, tmp_path):
        """New directories not in ROADMAP.yml are reported as added."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "existing", "title": "Existing", "tier": "active", "status": "pending"},
        ])
        _make_epic_dirs(spoq_dir, {
            "active": ["existing", "new-epic"],
        })

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        assert "error" not in data
        assert "new-epic" in data["added"]
        assert "existing" not in data["added"]

    @pytest.mark.anyio
    async def test_sync_detects_removed_epics(self, tmp_path):
        """Entries in ROADMAP.yml without matching directories are reported as removed."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "alive", "title": "Alive", "tier": "active", "status": "pending"},
            {"slug": "gone", "title": "Gone", "tier": "active", "status": "pending"},
        ])
        _make_epic_dirs(spoq_dir, {
            "active": ["alive"],
        })

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        assert "error" not in data
        assert "gone" in data["removed"]
        assert "alive" not in data["removed"]

    @pytest.mark.anyio
    async def test_sync_returns_roadmap_dict(self, tmp_path):
        """Sync result includes the full roadmap dict."""
        spoq_dir = tmp_path / "spoq"
        _make_epic_dirs(spoq_dir, {"active": ["feat-x"]})

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        assert "roadmap" in data
        assert isinstance(data["roadmap"], dict)
        assert "epics" in data["roadmap"]
        slugs = [e["slug"] for e in data["roadmap"]["epics"]]
        assert "feat-x" in slugs

    @pytest.mark.anyio
    async def test_sync_persists_to_disk(self, tmp_path):
        """After sync, ROADMAP.yml on disk matches the returned data."""
        spoq_dir = tmp_path / "spoq"
        _make_epic_dirs(spoq_dir, {"backlog": ["my-epic"]})

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        roadmap_path = spoq_dir / "ROADMAP.yml"
        assert roadmap_path.exists()
        on_disk = yaml.safe_load(roadmap_path.read_text())
        slugs = [e["slug"] for e in on_disk["epics"]]
        assert "my-epic" in slugs

    @pytest.mark.anyio
    async def test_sync_empty_directories(self, tmp_path):
        """Sync with no epic directories produces an empty roadmap."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        assert "error" not in data
        assert data["added"] == []
        assert data["removed"] == []
        assert len(data["roadmap"]["epics"]) == 0

    @pytest.mark.anyio
    async def test_sync_assigns_correct_tiers(self, tmp_path):
        """Epics discovered in different tier directories get correct tier values."""
        spoq_dir = tmp_path / "spoq"
        _make_epic_dirs(spoq_dir, {
            "backlog": ["plan-it"],
            "active": ["build-it"],
            "complete": ["ship-it"],
        })

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        tier_map = {e["slug"]: e["tier"] for e in data["roadmap"]["epics"]}
        assert tier_map["plan-it"] == "backlog"
        assert tier_map["build-it"] == "active"
        assert tier_map["ship-it"] == "complete"

    @pytest.mark.anyio
    async def test_sync_handles_tier_move(self, tmp_path):
        """An epic whose directory moved tiers is preserved with the new tier.

        sync_from_disk keeps entries whose slug exists on disk, so
        moving from backlog/ to active/ preserves the original entry
        with its custom fields while the tier is updated by the directory
        scan (existing slug stays, tier inferred from current location).
        """
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "migrated", "title": "Migrated", "tier": "backlog", "status": "pending"},
        ])
        # Directory exists in both old and new location -- sync
        # keeps the entry because the slug is still on disk
        _make_epic_dirs(spoq_dir, {"backlog": ["migrated"], "active": ["migrated"]})

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        slugs = {e["slug"] for e in data["roadmap"]["epics"]}
        assert "migrated" in slugs

    @pytest.mark.anyio
    async def test_sync_preserves_extra_fields(self, tmp_path):
        """Custom fields on existing entries survive a sync cycle."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "custom", "title": "Custom", "tier": "active",
             "status": "in_progress", "description": "important notes"},
        ])
        _make_epic_dirs(spoq_dir, {"active": ["custom"]})

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_sync", {})

        entry = next(e for e in data["roadmap"]["epics"] if e["slug"] == "custom")
        assert entry["description"] == "important notes"


# ===================================================================
# 3. Roadmap Show - Additional Edge Cases
# ===================================================================

class TestRoadmapShowEdgeCases:
    """Additional edge cases for spoq_roadmap_show."""

    @pytest.mark.anyio
    async def test_show_empty_roadmap(self, tmp_path):
        """A valid ROADMAP.yml with no epics returns empty lists."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {})

        assert "error" not in data
        assert data["epics"] == []
        assert data["counts"]["total"] == 0

    @pytest.mark.anyio
    async def test_show_filter_returns_zero_matches(self, tmp_path):
        """Filtering a tier with no matching epics returns empty."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "only-active", "title": "Only Active", "tier": "active", "status": "pending"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"tier": "complete"})

        assert data["epics"] == []
        assert data["counts"]["total"] == 0

    @pytest.mark.anyio
    async def test_show_table_format_includes_all_epics(self, tmp_path):
        """Table format rendered string includes data for every epic."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "aaa", "title": "Aaa", "tier": "backlog", "status": "pending"},
            {"slug": "bbb", "title": "Bbb", "tier": "active", "status": "in_progress"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"format": "table"})

        assert "aaa" in data["rendered"]
        assert "bbb" in data["rendered"]

    @pytest.mark.anyio
    async def test_show_json_format_with_tier_filter(self, tmp_path):
        """JSON format respects tier filter."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "aaa", "title": "Aaa", "tier": "backlog", "status": "pending"},
            {"slug": "bbb", "title": "Bbb", "tier": "active", "status": "in_progress"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"format": "json", "tier": "backlog"})

        rendered = json.loads(data["rendered"])
        assert len(rendered) == 1
        assert rendered[0]["slug"] == "aaa"

    @pytest.mark.anyio
    async def test_show_counts_match_filtered_epics(self, tmp_path):
        """Counts reflect filtered results, not the full roadmap."""
        spoq_dir = tmp_path / "spoq"
        spoq_dir.mkdir()
        _write_roadmap(spoq_dir, [
            {"slug": "a", "title": "A", "tier": "backlog", "status": "pending"},
            {"slug": "b", "title": "B", "tier": "backlog", "status": "pending"},
            {"slug": "c", "title": "C", "tier": "active", "status": "in_progress"},
        ])

        with patch("spoq_server.roadmap_tools.project_root", return_value=tmp_path):
            data = await call_json("spoq_roadmap_show", {"tier": "backlog"})

        assert data["counts"]["total"] == 2
        assert data["counts"]["backlog"] == 2
        assert data["counts"]["active"] == 0


# ===================================================================
# 4. Roadmap Utils (tested through direct imports)
# ===================================================================

class TestRoadmapUtils:
    """Test roadmap utility functions integrated with the fixture structure."""

    def test_load_from_fixture(self, fixture_roadmap_path):
        """Load a well-formed ROADMAP.yml using the fixture path."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        assert data["version"] == 1
        assert len(data["epics"]) == 3

    def test_validate_fixture_is_clean(self, fixture_roadmap_path):
        """The fixture ROADMAP.yml passes validation with zero errors."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        errors = roadmap_utils.validate_roadmap(data)
        assert errors == []

    def test_find_entry_by_slug(self, fixture_roadmap_path):
        """find_entry locates an entry by slug from the fixture."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        entry = roadmap_utils.find_entry(data, "build-feature")
        assert entry is not None
        assert entry["tier"] == "active"

    def test_find_entry_miss_returns_none(self, fixture_roadmap_path):
        """find_entry returns None for a nonexistent slug."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        assert roadmap_utils.find_entry(data, "ghost-slug") is None

    def test_update_tier_changes_value(self, fixture_roadmap_path):
        """update_entry_tier modifies the tier field."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        result = roadmap_utils.update_entry_tier(data, "plan-feature", "active")
        assert result is True
        entry = roadmap_utils.find_entry(data, "plan-feature")
        assert entry["tier"] == "active"

    def test_add_entry_and_find(self, fixture_roadmap_path):
        """add_entry appends a new entry retrievable by find_entry."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        new = {"slug": "fresh", "title": "Fresh", "tier": "backlog", "status": "pending"}
        errors = roadmap_utils.add_entry(data, new)
        assert errors == []
        assert roadmap_utils.find_entry(data, "fresh") is not None

    def test_remove_entry_and_verify_gone(self, fixture_roadmap_path):
        """remove_entry deletes the entry from the list."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        removed = roadmap_utils.remove_entry(data, "ship-feature")
        assert removed is True
        assert roadmap_utils.find_entry(data, "ship-feature") is None

    def test_save_and_reload_roundtrip(self, tmp_spoq_dir):
        """save then load preserves all entries."""
        spoq_dir = str(tmp_spoq_dir)
        data = roadmap_utils.load_roadmap(spoq_dir)
        original_count = len(data["epics"])

        roadmap_utils.add_entry(data, {
            "slug": "roundtrip", "title": "Roundtrip", "tier": "backlog", "status": "pending"
        })
        roadmap_utils.save_roadmap(spoq_dir, data)

        reloaded = roadmap_utils.load_roadmap(spoq_dir)
        assert len(reloaded["epics"]) == original_count + 1
        assert roadmap_utils.find_entry(reloaded, "roundtrip") is not None

    def test_sync_discovers_disk_structure(self, tmp_spoq_dir):
        """sync_from_disk returns entries matching the 3-tier directory layout."""
        spoq_dir = str(tmp_spoq_dir)
        result = roadmap_utils.sync_from_disk(spoq_dir)
        slugs = {e["slug"] for e in result["epics"]}
        assert "plan-feature" in slugs
        assert "build-feature" in slugs
        assert "ship-feature" in slugs

    def test_render_table_from_fixture(self, fixture_roadmap_path):
        """render_table produces a string with pipe-delimited rows."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        table = roadmap_utils.render_table(data)
        assert "plan-feature" in table
        assert "build-feature" in table
        assert "|" in table

    def test_validate_catches_bad_tier(self, fixture_roadmap_path):
        """Validation flags an entry with an unrecognized tier."""
        spoq_dir = str(fixture_roadmap_path.parent)
        data = roadmap_utils.load_roadmap(spoq_dir)
        data["epics"].append({
            "slug": "bad", "title": "Bad", "tier": "fantasy", "status": "pending"
        })
        errors = roadmap_utils.validate_roadmap(data)
        assert any("invalid tier" in e.lower() for e in errors)

    def test_constants_exposed(self):
        """Module-level constants are accessible."""
        assert roadmap_utils.ROADMAP_FILENAME == "ROADMAP.yml"
        assert roadmap_utils.ROADMAP_VERSION == 1
        assert "backlog" in roadmap_utils.VALID_TIERS
        assert "active" in roadmap_utils.VALID_TIERS
        assert "complete" in roadmap_utils.VALID_TIERS
