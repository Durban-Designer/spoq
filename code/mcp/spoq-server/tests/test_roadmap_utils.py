"""Unit tests for SPOQ roadmap_utils module."""

from pathlib import Path

import pytest
import yaml

from spoq_server.roadmap_utils import (
    ROADMAP_FILENAME,
    ROADMAP_VERSION,
    VALID_TIERS,
    _parse_md_table_row,
    add_entry,
    find_entry,
    load_roadmap,
    migrate_from_markdown,
    remove_entry,
    render_table,
    save_roadmap,
    sync_from_disk,
    update_entry_tier,
    validate_roadmap,
)


# =============================================================================
# Fixtures
# =============================================================================

def _scaffold(**overrides) -> dict:
    """Build a valid roadmap scaffold with optional overrides."""
    base = {"version": 1, "updated_at": "", "epics": []}
    base.update(overrides)
    return base


def _entry(slug: str = "my-epic", tier: str = "backlog", **kw) -> dict:
    """Build a minimal roadmap entry."""
    e = {"slug": slug, "title": slug.replace("-", " ").title(), "tier": tier, "status": "pending"}
    e.update(kw)
    return e


# =============================================================================
# load_roadmap / save_roadmap Round-Trip
# =============================================================================


class TestLoadSave:
    """Tests for load and save round-trip."""

    def test_load_missing_dir_returns_scaffold(self):
        result = load_roadmap("/nonexistent/path")
        assert result == {"version": 1, "updated_at": "", "epics": []}

    def test_load_missing_file_returns_scaffold(self, tmp_path):
        result = load_roadmap(str(tmp_path))
        assert result["version"] == 1
        assert result["epics"] == []

    def test_round_trip(self, tmp_path):
        data = _scaffold(epics=[_entry("alpha"), _entry("beta", tier="active")])
        save_roadmap(str(tmp_path), data)

        loaded = load_roadmap(str(tmp_path))
        assert len(loaded["epics"]) == 2
        assert loaded["epics"][0]["slug"] == "alpha"
        assert loaded["version"] == 1

    def test_save_sets_timestamp(self, tmp_path):
        data = _scaffold()
        save_roadmap(str(tmp_path), data)
        assert data["updated_at"] != ""

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        save_roadmap(str(nested), _scaffold())
        assert (nested / ROADMAP_FILENAME).exists()

    def test_load_invalid_yaml_returns_scaffold(self, tmp_path):
        (tmp_path / ROADMAP_FILENAME).write_text(": : : bad yaml [")
        result = load_roadmap(str(tmp_path))
        assert result["version"] == 1

    def test_load_non_dict_returns_scaffold(self, tmp_path):
        (tmp_path / ROADMAP_FILENAME).write_text("- just a list\n")
        result = load_roadmap(str(tmp_path))
        assert result == {"version": 1, "updated_at": "", "epics": []}


# =============================================================================
# validate_roadmap
# =============================================================================


class TestValidate:
    """Tests for roadmap validation."""

    def test_empty_dict_returns_errors(self):
        errors = validate_roadmap({})
        assert len(errors) > 0

    def test_valid_data_returns_empty(self):
        data = _scaffold(epics=[_entry("x")])
        assert validate_roadmap(data) == []

    def test_wrong_version(self):
        data = _scaffold(epics=[])
        data["version"] = 99
        errors = validate_roadmap(data)
        assert any("version" in e.lower() for e in errors)

    def test_epics_not_list(self):
        data = {"version": 1, "epics": "oops"}
        errors = validate_roadmap(data)
        assert any("list" in e for e in errors)

    def test_missing_fields(self):
        data = _scaffold(epics=[{"slug": "only-slug"}])
        errors = validate_roadmap(data)
        assert any("missing" in e.lower() for e in errors)

    def test_invalid_tier(self):
        entry = _entry("bad-tier", tier="unknown")
        data = _scaffold(epics=[entry])
        errors = validate_roadmap(data)
        assert any("invalid tier" in e.lower() for e in errors)

    def test_non_dict_data(self):
        errors = validate_roadmap("not a dict")
        assert errors == ["Data must be a dict"]

    def test_entry_not_dict(self):
        data = _scaffold(epics=["not a dict"])
        errors = validate_roadmap(data)
        assert any("not a dict" in e for e in errors)


# =============================================================================
# find_entry
# =============================================================================


class TestFindEntry:
    """Tests for entry lookup."""

    def test_hit(self):
        data = _scaffold(epics=[_entry("alpha"), _entry("beta")])
        result = find_entry(data, "beta")
        assert result is not None
        assert result["slug"] == "beta"

    def test_miss(self):
        data = _scaffold(epics=[_entry("alpha")])
        assert find_entry(data, "nonexistent") is None

    def test_empty_epics(self):
        assert find_entry(_scaffold(), "anything") is None


# =============================================================================
# update_entry_tier
# =============================================================================


class TestUpdateEntryTier:
    """Tests for tier promotion/demotion."""

    def test_promote_to_active(self):
        data = _scaffold(epics=[_entry("x", tier="backlog")])
        assert update_entry_tier(data, "x", "active") is True
        assert data["epics"][0]["tier"] == "active"
        assert data["epics"][0]["completed_date"] is None

    def test_promote_to_complete_sets_date(self):
        data = _scaffold(epics=[_entry("x", tier="active")])
        assert update_entry_tier(data, "x", "complete") is True
        assert data["epics"][0]["tier"] == "complete"
        assert data["epics"][0]["completed_date"] is not None

    def test_demote_clears_completed_date(self):
        entry = _entry("x", tier="complete", completed_date="2026-01-01")
        data = _scaffold(epics=[entry])
        update_entry_tier(data, "x", "active")
        assert data["epics"][0]["completed_date"] is None

    def test_not_found_returns_false(self):
        data = _scaffold(epics=[])
        assert update_entry_tier(data, "ghost", "active") is False


# =============================================================================
# add_entry
# =============================================================================


class TestAddEntry:
    """Tests for adding entries."""

    def test_success(self):
        data = _scaffold()
        errors = add_entry(data, _entry("new-one"))
        assert errors == []
        assert len(data["epics"]) == 1

    def test_duplicate_slug(self):
        data = _scaffold(epics=[_entry("dup")])
        errors = add_entry(data, _entry("dup"))
        assert any("duplicate" in e.lower() for e in errors)
        assert len(data["epics"]) == 1

    def test_missing_required_fields(self):
        data = _scaffold()
        errors = add_entry(data, {"slug": "only"})
        assert len(errors) > 0
        assert len(data["epics"]) == 0


# =============================================================================
# remove_entry
# =============================================================================


class TestRemoveEntry:
    """Tests for removing entries."""

    def test_present(self):
        data = _scaffold(epics=[_entry("a"), _entry("b")])
        assert remove_entry(data, "a") is True
        assert len(data["epics"]) == 1
        assert data["epics"][0]["slug"] == "b"

    def test_absent(self):
        data = _scaffold(epics=[_entry("a")])
        assert remove_entry(data, "nope") is False
        assert len(data["epics"]) == 1


# =============================================================================
# sync_from_disk
# =============================================================================


class TestSyncFromDisk:
    """Tests for disk reconciliation."""

    def test_discovers_new_epics(self, tmp_path):
        # Create tier directories with epic folders
        (tmp_path / "epics" / "backlog" / "feat-a").mkdir(parents=True)
        (tmp_path / "epics" / "active" / "feat-b").mkdir(parents=True)
        (tmp_path / "epics" / "complete" / "feat-c").mkdir(parents=True)

        result = sync_from_disk(str(tmp_path))
        slugs = {e["slug"] for e in result["epics"]}
        assert slugs == {"feat-a", "feat-b", "feat-c"}

    def test_preserves_existing_entries(self, tmp_path):
        (tmp_path / "epics" / "active" / "feat-x").mkdir(parents=True)
        # Pre-populate ROADMAP.yml with custom fields
        data = _scaffold(epics=[
            _entry("feat-x", tier="active", status="in_progress", description="custom")
        ])
        save_roadmap(str(tmp_path), data)

        result = sync_from_disk(str(tmp_path))
        entry = find_entry(result, "feat-x")
        assert entry is not None
        assert entry["description"] == "custom"

    def test_removes_stale_entries(self, tmp_path):
        (tmp_path / "epics" / "active" / "still-here").mkdir(parents=True)
        data = _scaffold(epics=[
            _entry("still-here", tier="active"),
            _entry("gone-now", tier="backlog"),
        ])
        save_roadmap(str(tmp_path), data)

        result = sync_from_disk(str(tmp_path))
        assert find_entry(result, "gone-now") is None
        assert find_entry(result, "still-here") is not None

    def test_empty_spoq_dir(self, tmp_path):
        result = sync_from_disk(str(tmp_path))
        assert result["epics"] == []

    def test_infers_tier_from_directory(self, tmp_path):
        (tmp_path / "epics" / "complete" / "old-work").mkdir(parents=True)
        result = sync_from_disk(str(tmp_path))
        entry = find_entry(result, "old-work")
        assert entry["tier"] == "complete"
        assert entry["status"] == "completed"

    def test_surfaces_feature_and_projects(self, tmp_path):
        d = tmp_path / "epics" / "active" / "with-feat"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text(
            "---\nslug: with-feat\ntitle: With Feat\ntier: active\n"
            "status: pending\nfeature: my-feat\nprojects:\n  - api\n  - dashboard\n"
            "---\n\n# Epic\n",
            encoding="utf-8",
        )
        result = sync_from_disk(str(tmp_path))
        entry = find_entry(result, "with-feat")
        assert entry["feature"] == "my-feat"
        assert entry["projects"] == ["api", "dashboard"]

    def test_no_feature_projects_keys_when_absent(self, tmp_path):
        d = tmp_path / "epics" / "active" / "no-feat"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text(
            "---\nslug: no-feat\ntitle: No Feat\ntier: active\nstatus: pending\n"
            "---\n\n# Epic\n",
            encoding="utf-8",
        )
        result = sync_from_disk(str(tmp_path))
        entry = find_entry(result, "no-feat")
        assert "feature" not in entry
        assert "projects" not in entry

    def test_projects_must_be_list(self, tmp_path):
        # A non-list `projects` scalar is ignored (mirrors repos list-check).
        d = tmp_path / "epics" / "active" / "scalar-proj"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text(
            "---\nslug: scalar-proj\ntitle: Scalar\ntier: active\n"
            "status: pending\nprojects: not-a-list\n---\n\n# Epic\n",
            encoding="utf-8",
        )
        result = sync_from_disk(str(tmp_path))
        entry = find_entry(result, "scalar-proj")
        assert "projects" not in entry


# =============================================================================
# render_table
# =============================================================================


class TestRenderTable:
    """Tests for markdown table rendering."""

    def test_grouped_output(self):
        data = _scaffold(epics=[
            _entry("b", tier="backlog"),
            _entry("a", tier="active"),
            _entry("c", tier="complete"),
        ])
        table = render_table(data)
        lines = table.strip().split("\n")
        # Header + separator + 3 data rows
        assert len(lines) == 5
        assert "backlog" in lines[2]
        assert "active" in lines[3]
        assert "complete" in lines[4]

    def test_max_complete_cap(self):
        entries = [_entry(f"done-{i}", tier="complete") for i in range(20)]
        data = _scaffold(epics=entries)
        table = render_table(data, max_complete=3)
        complete_rows = [l for l in table.split("\n") if "complete" in l]
        assert len(complete_rows) == 3

    def test_empty_data(self):
        table = render_table(_scaffold())
        lines = table.strip().split("\n")
        # Header + separator only
        assert len(lines) == 2


# =============================================================================
# migrate_from_markdown
# =============================================================================


class TestMigrateFromMarkdown:
    """Tests for ROADMAP.md -> ROADMAP.yml migration."""

    def test_parses_active_table(self, tmp_path):
        md = tmp_path / "ROADMAP.md"
        md.write_text(
            "## Active Epics\n\n"
            "| Priority | Epic | Status | Tasks | Est. Hours | Dependencies |\n"
            "|----------|------|--------|-------|------------||--------------|\n"
            "| 1 | [my-epic](epics/active/my-epic/) | pending | 5 | 10h | none |\n"
        )
        result = migrate_from_markdown(str(md), str(tmp_path))
        assert len(result["epics"]) == 1
        entry = result["epics"][0]
        assert entry["slug"] == "my-epic"
        assert entry["tier"] == "active"

    def test_parses_completed_table(self, tmp_path):
        md = tmp_path / "ROADMAP.md"
        md.write_text(
            "## Completed Epics\n\n"
            "| Epic | Completed | Tasks |\n"
            "|------|-----------|-------|\n"
            "| [old-work](epics/complete/old-work/) | 2026-01-15 | 8 |\n"
        )
        result = migrate_from_markdown(str(md), str(tmp_path))
        assert len(result["epics"]) == 1
        entry = result["epics"][0]
        assert entry["slug"] == "old-work"
        assert entry["tier"] == "complete"
        assert entry["status"] == "completed"

    def test_missing_file_returns_scaffold(self, tmp_path):
        result = migrate_from_markdown(str(tmp_path / "nope.md"), str(tmp_path))
        assert result["version"] == 1
        assert result["epics"] == []

    def test_real_roadmap_format(self, tmp_path):
        """Parse a table matching the actual SPOQ ROADMAP.md format."""
        md = tmp_path / "ROADMAP.md"
        md.write_text(
            "# SPOQ Epic Roadmap\n\n"
            "## Active Epics (Priority Order)\n\n"
            "| Priority | Epic | Status | Tasks | Est. Hours | Dependencies |\n"
            "|----------|------|--------|-------|------------||--------------|\n"
            "| 1 | [spoq-paper-revision](epics/active/spoq-paper-revision/) | pending | 10 | 4h | none |\n"
            "| 2 | [website-audit](epics/active/website-audit/) | pending | 16 | 32h | none |\n"
            "\n"
            "## Completed Epics\n\n"
            "| Epic | Completed | Tasks |\n"
            "|------|-----------|-------|\n"
            "| [spoq-mcp-server](epics/complete/spoq-mcp-server/) | 2026-02-23 | 9 |\n"
        )
        result = migrate_from_markdown(str(md), str(tmp_path))
        assert len(result["epics"]) == 3
        active_slugs = [e["slug"] for e in result["epics"] if e["tier"] == "active"]
        assert "spoq-paper-revision" in active_slugs
        complete_slugs = [e["slug"] for e in result["epics"] if e["tier"] == "complete"]
        assert "spoq-mcp-server" in complete_slugs


# =============================================================================
# Parser Edge Cases (_parse_md_table_row)
# =============================================================================


class TestParserEdgeCases:
    """Tests for enhanced _parse_md_table_row handling of edge-case formats."""

    def test_bare_slug_extraction(self):
        """Bare kebab-case slugs (no markdown link) should be recognised."""
        cells = ["2", "case-study-adrata", "pending", "0/6", "~12", "None"]
        entry = _parse_md_table_row(cells, tier="active")
        assert entry["slug"] == "case-study-adrata"

    def test_task_count_fraction(self):
        """0/6 format should capture the total (denominator) as tasks."""
        cells = ["2", "case-study-adrata", "pending", "0/6", "~12", "None"]
        entry = _parse_md_table_row(cells, tier="active")
        assert entry["tasks"] == 6

    def test_strikethrough_stripping(self):
        """Tildes wrapping a slug should be stripped before extraction."""
        cells = ["3", "~~email-deliverability-fix~~", "pending", "5", "~8"]
        entry = _parse_md_table_row(cells, tier="active")
        assert entry["slug"] == "email-deliverability-fix"

    def test_bold_status_stripping(self):
        """Double-asterisk bold wrapping a status should be stripped."""
        cells = ["1", "my-feature", "**complete**", "4", "~6"]
        entry = _parse_md_table_row(cells, tier="active")
        assert entry["status"] == "complete"

    def test_separator_detection(self, tmp_path):
        """migrate_from_markdown should skip separator rows like |---|---|."""
        md = tmp_path / "ROADMAP.md"
        md.write_text(
            "## Active Epics\n\n"
            "| Priority | Epic | Status |\n"
            "|---|---|---|\n"
            "| 1 | [alpha](epics/active/alpha/) | pending |\n"
        )
        result = migrate_from_markdown(str(md), str(tmp_path))
        # Only the data row should produce an entry, not the separator
        assert len(result["epics"]) == 1
        assert result["epics"][0]["slug"] == "alpha"

    def test_mixed_format_row(self):
        """Row combining bare slug, strikethrough, bold status, and 0/N tasks."""
        cells = ["1", "~~infra-overhaul~~", "**in-progress**", "3/10", "~24"]
        entry = _parse_md_table_row(cells, tier="active")
        assert entry["slug"] == "infra-overhaul"
        assert entry["status"] == "in_progress"
        assert entry["tasks"] == 10
        # Legacy hour-estimate cells are skipped: the estimate concept was removed
        assert "estimated_hours" not in entry
