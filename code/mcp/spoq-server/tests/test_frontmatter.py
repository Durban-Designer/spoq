"""Tests for EPIC.md frontmatter parsing, surfacing, coercion, validation, and rooting."""

import json
import os
from pathlib import Path

import pytest

from spoq_server import epic_utils
from spoq_server.epic_utils import (
    VALID_STATUS,
    coerce_status,
    parse_frontmatter,
    read_epic_frontmatter,
    validate_epic_frontmatter,
)
from spoq_server.roadmap_utils import find_entry, save_roadmap, sync_from_disk


# =============================================================================
# Helpers
# =============================================================================

def _epic(tmp_path: Path, tier: str, slug: str, body: str) -> Path:
    """Create epics/<tier>/<slug>/EPIC.md with *body* and return the epic dir."""
    d = tmp_path / "epics" / tier / slug
    d.mkdir(parents=True)
    (d / "EPIC.md").write_text(body, encoding="utf-8")
    return d


def _fm(slug: str, tier: str, status: str = "pending", **extra) -> str:
    lines = ["---", f"slug: {slug}", f"title: 'Epic: {slug.title()}'",
             f"tier: {tier}", f"status: {status}"]
    if "repos" in extra:
        if extra["repos"]:
            lines.append("repos:")
            for r in extra["repos"]:
                lines.append(f"  - {r}")
        else:
            lines.append("repos: []")
    for k in ("completed_date", "map", "feature"):
        if k in extra:
            lines.append(f"{k}: {extra[k]}")
    if "projects" in extra:
        if extra["projects"]:
            lines.append("projects:")
            for p in extra["projects"]:
                lines.append(f"  - {p}")
        else:
            lines.append("projects: []")
    lines.append("---")
    lines.append("")
    lines.append("# Epic: Body")
    lines.append("")
    lines.append("## Overview")
    lines.append("Some text.")
    return "\n".join(lines) + "\n"


# =============================================================================
# parse_frontmatter
# =============================================================================

class TestParseFrontmatter:
    def test_leading_fence_parsed(self):
        fm = parse_frontmatter("---\nslug: a\ntier: active\n---\n# Title\n")
        assert fm == {"slug": "a", "tier": "active"}

    def test_no_fence_returns_empty(self):
        assert parse_frontmatter("# Title\n\nbody\n") == {}

    def test_body_horizontal_rule_not_parsed(self):
        # A --- used as a body rule must NOT be read as frontmatter.
        content = "# Title\n\nIntro\n\n---\n\nSection two: key: value\n"
        assert parse_frontmatter(content) == {}

    def test_empty_string(self):
        assert parse_frontmatter("") == {}

    def test_bom_tolerated(self):
        assert parse_frontmatter("﻿---\nslug: a\n---\n") == {"slug": "a"}

    def test_unclosed_fence_returns_empty(self):
        assert parse_frontmatter("---\nslug: a\nno close here\n") == {}

    def test_non_mapping_returns_empty(self):
        assert parse_frontmatter("---\n- just\n- a list\n---\n") == {}

    def test_malformed_yaml_returns_empty(self):
        assert parse_frontmatter("---\n: : : [bad\n---\n") == {}

    def test_repos_list_round_trips(self):
        fm = parse_frontmatter("---\nslug: a\nrepos:\n  - x\n  - y\n---\n")
        assert fm["repos"] == ["x", "y"]


class TestReadEpicFrontmatter:
    def test_reads_from_dir(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", _fm("feat-a", "active"))
        fm = read_epic_frontmatter(d)
        assert fm["slug"] == "feat-a"

    def test_missing_epic_md_returns_empty(self, tmp_path):
        d = tmp_path / "epics" / "active" / "ghost"
        d.mkdir(parents=True)
        assert read_epic_frontmatter(d) == {}


# =============================================================================
# coerce_status
# =============================================================================

class TestCoerceStatus:
    def test_complete_becomes_completed(self):
        assert coerce_status("complete") == "completed"

    def test_hyphen_to_underscore(self):
        assert coerce_status("in-progress") == "in_progress"

    def test_passthrough_valid(self):
        for s in VALID_STATUS:
            assert coerce_status(s) == s

    def test_non_string_unchanged(self):
        assert coerce_status(None) is None
        assert coerce_status(3) == 3


# =============================================================================
# sync_from_disk surfacing
# =============================================================================

class TestSyncSurfacing:
    def test_surfaces_repos_status_title(self, tmp_path):
        _epic(tmp_path, "active", "feat-a",
              _fm("feat-a", "active", status="in_progress",
                  repos=["example-service", "example-app-docs"]))
        result = sync_from_disk(str(tmp_path))
        e = find_entry(result, "feat-a")
        assert e["repos"] == ["example-service", "example-app-docs"]
        assert e["status"] == "in_progress"
        assert e["title"] == "Epic: Feat-A"

    def test_complete_status_coerced_on_emit(self, tmp_path):
        _epic(tmp_path, "active", "feat-c", _fm("feat-c", "active", status="complete"))
        result = sync_from_disk(str(tmp_path))
        assert find_entry(result, "feat-c")["status"] == "completed"

    def test_empty_repos_list_emitted(self, tmp_path):
        _epic(tmp_path, "active", "feat-e", _fm("feat-e", "active", repos=[]))
        result = sync_from_disk(str(tmp_path))
        assert find_entry(result, "feat-e")["repos"] == []

    def test_tier_disagreement_warns_but_keeps_disk(self, tmp_path):
        # Frontmatter says backlog, but the dir is under active.
        _epic(tmp_path, "active", "feat-d", _fm("feat-d", "backlog"))
        warnings = []
        result = sync_from_disk(str(tmp_path), warnings=warnings)
        assert find_entry(result, "feat-d")["tier"] == "active"
        assert any("disagrees" in w for w in warnings)

    def test_slug_disagreement_warns(self, tmp_path):
        _epic(tmp_path, "active", "feat-x", _fm("wrong-slug", "active"))
        warnings = []
        result = sync_from_disk(str(tmp_path), warnings=warnings)
        # Keyed by directory name, not frontmatter slug.
        assert find_entry(result, "feat-x") is not None
        assert any("does not" in w for w in warnings)

    def test_optional_passthrough_fields(self, tmp_path):
        _epic(tmp_path, "complete", "feat-done",
              _fm("feat-done", "complete", status="completed",
                  completed_date="2026-06-15", map="post-split-cleanup-2026-06"))
        result = sync_from_disk(str(tmp_path))
        e = find_entry(result, "feat-done")
        assert e["completed_date"] == "2026-06-15"
        assert e["map"] == "post-split-cleanup-2026-06"

    def test_preserves_unrelated_existing_fields(self, tmp_path):
        _epic(tmp_path, "active", "feat-p", _fm("feat-p", "active"))
        save_roadmap(str(tmp_path), {
            "version": 1, "updated_at": "",
            "epics": [{"slug": "feat-p", "title": "Old", "tier": "active",
                       "status": "pending", "priority": 1, "owner": "royce"}],
        })
        result = sync_from_disk(str(tmp_path))
        e = find_entry(result, "feat-p")
        assert e["priority"] == 1
        assert e["owner"] == "royce"

    def test_no_frontmatter_falls_back_to_defaults(self, tmp_path):
        d = tmp_path / "epics" / "backlog" / "bare"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text("# Epic: Bare\n\n## Overview\nx\n")
        result = sync_from_disk(str(tmp_path))
        e = find_entry(result, "bare")
        assert e["tier"] == "backlog"
        assert e["status"] == "pending"
        assert e["title"] == "Bare"

    def test_archive_tier_never_scanned(self, tmp_path):
        _epic(tmp_path, "active", "live", _fm("live", "active"))
        # An archive tier on disk must not surface into the roadmap.
        arch = tmp_path / "epics" / "archive" / "old"
        arch.mkdir(parents=True)
        (arch / "EPIC.md").write_text(_fm("old", "archive"))
        result = sync_from_disk(str(tmp_path))
        slugs = {e["slug"] for e in result["epics"]}
        assert slugs == {"live"}


# =============================================================================
# validate_epic_frontmatter
# =============================================================================

class TestValidateFrontmatter:
    def test_valid_passes(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", _fm("feat-a", "active"))
        errors, warnings = validate_epic_frontmatter(d)
        assert errors == []

    def test_slug_mismatch_errors(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", _fm("not-feat-a", "active"))
        errors, _ = validate_epic_frontmatter(d)
        assert any("slug" in e for e in errors)

    def test_tier_mismatch_errors(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", _fm("feat-a", "backlog"))
        errors, _ = validate_epic_frontmatter(d)
        assert any("tier" in e for e in errors)

    def test_missing_required_field_errors(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", "---\nslug: feat-a\ntier: active\n---\n# X\n")
        errors, _ = validate_epic_frontmatter(d)
        assert any("missing required field" in e for e in errors)

    def test_invalid_status_errors(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a", _fm("feat-a", "active", status="wat"))
        errors, _ = validate_epic_frontmatter(d)
        assert any("status" in e for e in errors)

    def test_absent_warns_by_default(self, tmp_path):
        d = tmp_path / "epics" / "active" / "bare"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text("# Epic: Bare\n")
        errors, warnings = validate_epic_frontmatter(d)
        assert errors == []
        assert any("no leading frontmatter" in w for w in warnings)

    def test_absent_errors_when_required(self, tmp_path):
        d = tmp_path / "epics" / "active" / "bare"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text("# Epic: Bare\n")
        errors, warnings = validate_epic_frontmatter(d, require_present=True)
        assert any("no leading frontmatter" in e for e in errors)

    def test_feature_equal_map_is_valid(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a",
                  _fm("feat-a", "active", map="owner-map", feature="owner-map"))
        errors, _ = validate_epic_frontmatter(d)
        assert errors == []

    def test_feature_not_equal_map_errors(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a",
                  _fm("feat-a", "active", map="owner-map", feature="other-feat"))
        errors, _ = validate_epic_frontmatter(d)
        assert any("disagree" in e for e in errors)

    def test_lone_feature_is_valid(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a",
                  _fm("feat-a", "active", feature="owner-feat"))
        errors, _ = validate_epic_frontmatter(d)
        assert errors == []

    def test_lone_map_is_valid(self, tmp_path):
        d = _epic(tmp_path, "active", "feat-a",
                  _fm("feat-a", "active", map="owner-map"))
        errors, _ = validate_epic_frontmatter(d)
        assert errors == []


# =============================================================================
# records: feature/projects/version + Product/Version dataclasses
# =============================================================================

class TestRecordFields:
    def test_epic_carries_feature_projects(self):
        from spoq_server.stores.records import Epic
        e = Epic(id="x", title="X", feature="f-2026", projects=["api"])
        assert e.feature == "f-2026"
        assert e.projects == ["api"]

    def test_epic_defaults_are_empty(self):
        from spoq_server.stores.records import Epic
        e = Epic(id="x", title="X")
        assert e.feature is None
        assert e.projects == []

    def test_roadmap_entry_omits_absent_feature_projects(self):
        from spoq_server.stores.records import RoadmapEntry
        r = RoadmapEntry(slug="s", title="t", tier="active", status="pending")
        d = r.to_dict()
        assert "feature" not in d
        assert "projects" not in d

    def test_roadmap_entry_emits_feature_projects_when_set(self):
        from spoq_server.stores.records import RoadmapEntry
        r = RoadmapEntry(slug="s", title="t", tier="active", status="pending",
                         feature="f", projects=["api"])
        d = r.to_dict()
        assert d["feature"] == "f"
        assert d["projects"] == ["api"]

    def test_roadmap_entry_from_dict_round_trip(self):
        from spoq_server.stores.records import RoadmapEntry
        src = {"slug": "s", "title": "t", "tier": "active", "status": "pending",
               "feature": "f", "projects": ["api", "dash"]}
        assert RoadmapEntry.from_dict(src).to_dict() == src

    def test_mapdoc_carries_frontmatter_fields(self):
        from spoq_server.stores.records import MapDoc
        m = MapDoc.from_dict("slug-x", {
            "slug": "slug-x", "title": "T", "tier": "active",
            "version": "0.1.0", "projects": ["api"]})
        assert m.id == "slug-x"
        assert m.slug == "slug-x"
        assert m.version == "0.1.0"
        assert m.projects == ["api"]
        assert m.tier == "active"

    def test_mapdoc_defaults_when_no_frontmatter(self):
        from spoq_server.stores.records import MapDoc
        m = MapDoc.from_dict("slug-x", {"title": "Only body"})
        assert m.version is None
        assert m.projects == []
        assert m.slug == ""

    def test_product_record_nests_version_records(self):
        from spoq_server.stores.records import ProductRecord, VersionRecord
        p = ProductRecord.from_dict({
            "slug": "example-product", "name": "Example Product",
            "versions": [{"semver": "0.1.0", "status": "planned"}]})
        assert p.slug == "example-product"
        assert isinstance(p.versions[0], VersionRecord)
        assert p.versions[0].semver == "0.1.0"
        assert p.versions[0].status == "planned"
        assert p.versions[0].released_date is None

    def test_product_record_empty_versions(self):
        from spoq_server.stores.records import ProductRecord
        p = ProductRecord.from_dict({"slug": "p", "name": "P"})
        assert p.versions == []

    def test_version_record_released_fields(self):
        from spoq_server.stores.records import VersionRecord
        v = VersionRecord.from_dict({
            "semver": "1.0.0", "status": "released",
            "released_date": "2026-06-15", "notes_md": "cut",
            "features": ["feat-a"]})
        assert v.released_date == "2026-06-15"
        assert v.features == ["feat-a"]


# =============================================================================
# Project-root override
# =============================================================================

class TestProjectRootOverride:
    def test_override_takes_precedence(self, tmp_path, monkeypatch):
        from spoq_server import server
        monkeypatch.delenv("SPOQ_PROJECT_ROOT", raising=False)
        server.set_project_root_override(str(tmp_path))
        try:
            assert server.project_root() == tmp_path.resolve()
        finally:
            server.set_project_root_override(None)

    def test_env_var_used_when_no_override(self, tmp_path, monkeypatch):
        from spoq_server import server
        server.set_project_root_override(None)
        monkeypatch.setenv("SPOQ_PROJECT_ROOT", str(tmp_path))
        assert server.project_root() == tmp_path.resolve()
