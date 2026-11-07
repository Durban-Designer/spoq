"""Tests for ``spoq export`` (export_cli.py).

Covers the four pillars the task names:

1. Freeze guard — refuses to write into the frozen workspace spoq/ tree
   (and the inverse: a parent that contains it), allows external paths.
2. Frontmatter fidelity — EPIC.md frontmatter conforms to
   EPIC_FRONTMATTER_SCHEMA.md, preserving completed_date and repos and coercing
   the legacy ``complete`` status to ``completed``.
3. On-disk layout + spoq_validate_epic acceptance — the export dir is a valid
   SPOQ tree that the real parser/validator accepts.
4. Round-trip no-op property — export(store) re-read by a fresh FsStore yields
   the same epic/task data (import(export(store)) is a no-op).

A lightweight in-memory ``FakeStore`` stands in for the API/fs store so the
exporter is exercised backend-agnostically without a live Example Product org.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spoq_server import export_cli
from spoq_server.export_cli import (
    build_frontmatter,
    export_store,
    freeze_guard,
    run_export,
    write_epic,
    write_map,
    write_roadmap,
)
from spoq_server.stores.records import Epic, MapDoc, RoadmapEntry, Task


# --- fixtures ----------------------------------------------------------------


def _epic_dict(**over):
    base = {
        "tier": "active",
        "slug": "test-epic-2026-06",
        "title": "Test Epic",
        "status": "completed",
        "completed_date": "2026-06-01",
        "repos": ["example-service"],
        "map": "example-product-board-mvp",
        "tasks": [],
        "body": "# Epic: Test Epic\n\n## Overview\n\nbody text\n",
    }
    base.update(over)
    return base


class FakeStore:
    """In-memory store mirroring the load_epic/list_epics/list_maps surface."""

    def __init__(self, epics, maps=None, roadmap=None):
        # epics: list of dicts keyed by tier+slug
        self._epics = {(e["tier"], e["slug"]): e for e in epics}
        self._maps = maps or []
        self._roadmap = roadmap or []

    def list_epics(self, tier):
        return [s for (t, s) in self._epics if t == tier]

    def load_epic(self, path):
        slug = [p for p in str(path).strip("/").split("/") if p][-1]
        for (t, s), e in self._epics.items():
            if s == slug:
                return e
        raise KeyError(slug)

    def list_maps(self):
        return self._maps

    def load_roadmap(self):
        return self._roadmap


# --- freeze guard ------------------------------------------------------------


def test_freeze_guard_blocks_spoq_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "spoq")
    (tmp_path / "spoq").mkdir()
    with pytest.raises(SystemExit) as exc:
        freeze_guard(tmp_path / "spoq")
    assert "EXPORT REFUSED" in str(exc.value)


def test_freeze_guard_blocks_nested_inside_spoq_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "spoq")
    (tmp_path / "spoq").mkdir()
    with pytest.raises(SystemExit):
        freeze_guard(tmp_path / "spoq" / "epics" / "active")


def test_freeze_guard_blocks_parent_containing_spoq_tree(tmp_path, monkeypatch):
    # --out pointing at the workspace root would let a later step clobber spoq/.
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "ws" / "spoq")
    (tmp_path / "ws" / "spoq").mkdir(parents=True)
    with pytest.raises(SystemExit):
        freeze_guard(tmp_path / "ws")


def test_freeze_guard_allows_external_path(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "spoq")
    (tmp_path / "spoq").mkdir()
    # A sibling that merely shares a name prefix must be allowed.
    freeze_guard(tmp_path / "spoq-export")  # must not raise
    freeze_guard(tmp_path / "my-export")  # must not raise


# --- frontmatter fidelity ----------------------------------------------------


def test_frontmatter_preserves_completed_date_and_repos(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "spoq")
    write_epic(_epic_dict(), tmp_path)
    md = (
        tmp_path / "epics" / "active" / "test-epic-2026-06" / "EPIC.md"
    ).read_text()
    assert md.startswith("---\n")
    fm = yaml.safe_load(md.split("---")[1])
    assert fm["completed_date"] == "2026-06-01"
    assert fm["repos"] == ["example-service"]
    assert fm["map"] == "example-product-board-mvp"
    assert fm["slug"] == "test-epic-2026-06"
    assert fm["tier"] == "active"


def test_frontmatter_emits_feature_and_projects_when_present():
    fm = build_frontmatter(
        {"slug": "x", "tier": "active", "status": "pending",
         "feature": "feat-x", "projects": ["api", "dashboard"]}
    )
    assert fm["feature"] == "feat-x"
    assert fm["projects"] == ["api", "dashboard"]


def test_frontmatter_omits_feature_and_empty_projects_when_absent():
    # Byte-compat: an epic with no feature and an empty projects list serializes
    # exactly as today (no new keys) so the legacy corpus round-trips unchanged.
    fm = build_frontmatter(
        {"slug": "x", "tier": "active", "status": "pending", "projects": []}
    )
    assert "feature" not in fm
    assert "projects" not in fm


def test_write_map_emits_version_and_projects_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    write_map(
        {"slug": "feat-x", "title": "Feature X", "version": "1.2.0",
         "projects": ["api", "dashboard"]},
        tmp_path,
    )
    md = (tmp_path / "maps" / "active" / "feat-x" / "MAP.md").read_text()
    fm = yaml.safe_load(md.split("---")[1])
    assert fm["version"] == "1.2.0"
    assert fm["projects"] == ["api", "dashboard"]


def test_write_map_omits_version_projects_when_absent(tmp_path, monkeypatch):
    # Byte-compat: a plain map (no version/projects) keeps its slug/title-only
    # frontmatter so the ~389-map corpus round-trips unchanged.
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    write_map(MapDoc(id="plain-map", title="Plain"), tmp_path)
    md = (tmp_path / "maps" / "active" / "plain-map" / "MAP.md").read_text()
    fm = yaml.safe_load(md.split("---")[1])
    assert "version" not in fm
    assert "projects" not in fm


def test_round_trip_feature_projects_version_survives(tmp_path, monkeypatch):
    """Exported feature/project/version fields survive generic file parsing."""
    from spoq_server import epic_utils, map_utils

    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    out = tmp_path / "snapshot"

    epic = {
        "tier": "active", "slug": "feat-epic-2026-07", "title": "Feat Epic",
        "status": "pending", "feature": "feat-x",
        "projects": ["api", "dashboard"], "body": _full_epic_body(), "tasks": [],
    }
    write_epic(epic, out)
    write_map(
        {"slug": "feat-x", "title": "Feature X", "version": "1.2.0",
         "projects": ["api", "dashboard"]},
        out,
    )

    epic_file = out / "epics" / "active" / "feat-epic-2026-07" / "EPIC.md"
    normalized = epic_utils.read_epic_frontmatter(epic_file.parent)
    assert normalized["feature"] == "feat-x"
    assert normalized["projects"] == ["api", "dashboard"]
    normalized_map = map_utils.parse_map_md(out / "maps" / "active" / "feat-x")
    assert normalized_map["version"] == "1.2.0"
    assert normalized_map["projects"] == ["api", "dashboard"]


def test_frontmatter_coerces_complete_to_completed():
    fm = build_frontmatter({"slug": "x", "tier": "active", "status": "complete"})
    assert fm["status"] == "completed"


def test_frontmatter_omits_completed_date_when_not_completed():
    fm = build_frontmatter(
        {"slug": "x", "tier": "active", "status": "pending",
         "completed_date": "2026-06-01"}
    )
    assert "completed_date" not in fm


def test_frontmatter_accepts_id_as_slug_alias():
    fm = build_frontmatter({"id": "from-id", "tier": "active", "status": "pending"})
    assert fm["slug"] == "from-id"


# --- task files --------------------------------------------------------------


def test_write_epic_emits_one_yaml_per_task_without_source_marker(tmp_path):
    epic = _epic_dict(
        tasks=[
            Task(id="01-a", title="A", description="da", status="completed",
                 source_file="/some/path/01-a.yml"),
            Task(id="02-b", title="B", description="db"),
        ]
    )
    write_epic(epic, tmp_path)
    tasks_dir = tmp_path / "epics" / "active" / "test-epic-2026-06" / "tasks"
    files = sorted(p.name for p in tasks_dir.glob("*.yml"))
    assert files == ["01-a.yml", "02-b.yml"]
    data = yaml.safe_load((tasks_dir / "01-a.yml").read_text())
    assert data["id"] == "01-a"
    assert data["status"] == "completed"
    assert "_source_file" not in data and "source_file" not in data


# --- roadmap -----------------------------------------------------------------


def test_roadmap_excludes_archive_tier(tmp_path):
    entries = [
        RoadmapEntry(slug="a", title="A", tier="active", status="pending"),
        RoadmapEntry(slug="z", title="Z", tier="archive", status="completed"),
    ]
    write_roadmap(entries, tmp_path)
    data = yaml.safe_load((tmp_path / "ROADMAP.yml").read_text())
    slugs = [e["slug"] for e in data["epics"]]
    assert "a" in slugs
    assert "z" not in slugs


# --- layout + spoq_validate_epic acceptance ----------------------------------


def _full_epic_body():
    return (
        "# Epic: Round Trip\n\n"
        "## Overview\n\nAn epic.\n\n"
        "## Architecture\n\nstuff.\n\n"
        "## Task Dependencies\n\n```\nWave 0: 01-a\n```\n\n"
        "## Dispatch Strategy\n\nwave by wave.\n\n"
        "## Success Criteria\n\n- [ ] done\n"
    )


def test_export_dir_passes_spoq_validate_epic(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    out = tmp_path / "spoq-export"
    epic = {
        "tier": "active", "slug": "round-trip-2026-06", "title": "Round Trip",
        "status": "pending", "repos": [], "body": _full_epic_body(),
        "tasks": [
            {"id": "01-a", "title": "A",
             "description": "## Objective\n\ndo a\n\n## Steps\n\n1. step\n\n"
                            "## Verification\n\nrun the test\n",
             "status": "pending", "phase": 0, "dependencies": []},
        ],
    }
    store = FakeStore([epic])
    export_store(store, out, export_all=True)

    # Validate the exported epic via the real fs-mode validator, rooted at out.
    from spoq_server.stores.fs import FsStore
    from spoq_server import epic_tools

    monkeypatch.setattr(epic_tools, "_store", lambda: FsStore(out / "_root_stub"))
    # Point the validator's store root at `out` by resolving an absolute path.
    epic_dir = out / "epics" / "active" / "round-trip-2026-06"
    import json
    result = json.loads(epic_tools.spoq_validate_epic(str(epic_dir)))
    assert result.get("errors") == [], result


# --- round-trip no-op --------------------------------------------------------


def test_round_trip_noop_via_fs_store(tmp_path, monkeypatch):
    """export(store) re-read by a fresh FsStore reproduces the epic+tasks.

    This is the import(export(store)) == no-op property: the bytes the exporter
    writes parse back into the same logical epic the store held.
    """
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    out = tmp_path / "snapshot"
    epic = {
        "tier": "active", "slug": "round-trip-2026-06", "title": "Round Trip",
        "status": "completed", "completed_date": "2026-06-10",
        "repos": ["example-service", "spoq-platform"], "map": "example-product-board-mvp",
        "body": _full_epic_body(),
        "tasks": [
            {"id": "01-a", "title": "A", "description": "do a",
             "status": "completed", "phase": 0,
             "dependencies": [], "files_to_touch": ["x.py"]},
            {"id": "02-b", "title": "B", "description": "do b",
             "status": "pending", "phase": 1, "dependencies": ["01-a"]},
        ],
    }
    store = FakeStore([epic])
    export_store(store, out, export_all=True)

    # Re-read with a fresh FsStore rooted at the export dir's parent layout.
    from spoq_server.stores.fs import FsStore

    fs = FsStore(out)  # FsStore looks for <root>/spoq/epics; build that layout
    # export_store wrote <out>/epics/... but FsStore expects <root>/spoq/epics;
    # re-resolve by pointing the store at the directory holding epics/.
    reloaded = fs.load_epic(str(out / "epics" / "active" / "round-trip-2026-06"))
    # FsStore.load_epic returns the parse_epic dict; it must parse cleanly.
    assert isinstance(reloaded, dict)
    assert "error" not in reloaded

    # Frontmatter round-trips (read the emitted EPIC.md fence directly).
    fm = _read_fm(out)
    assert fm["status"] == "completed"
    assert fm["completed_date"] == "2026-06-10"
    assert fm["repos"] == ["example-service", "spoq-platform"]
    assert fm["map"] == "example-product-board-mvp"

    # Tasks round-trip: two task files, ids + statuses + deps preserved.
    # FsStore.load_tasks returns parsed dicts (epic_utils.parse_task_yaml).
    tasks = fs.load_tasks(str(out / "epics" / "active" / "round-trip-2026-06"))
    by_id = {t["id"]: t for t in tasks}
    assert sorted(by_id) == ["01-a", "02-b"]
    assert by_id["01-a"]["status"] == "completed"
    assert by_id["02-b"]["status"] == "pending"
    assert by_id["02-b"]["dependencies"] == ["01-a"]


def _read_fm(out: Path) -> dict:
    md = (out / "epics" / "active" / "round-trip-2026-06" / "EPIC.md").read_text()
    return yaml.safe_load(md.split("---")[1])


# --- CLI entry / scope guard -------------------------------------------------


def test_run_export_requires_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    rc = run_export(epic=None, export_all=False, out=str(tmp_path / "out"))
    assert rc == 2


def test_run_export_single_epic_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    out = tmp_path / "out"
    store = FakeStore([_epic_dict()])
    rc = run_export(epic="test-epic-2026-06", export_all=False,
                    out=str(out), store=store)
    assert rc == 0
    assert (out / "epics" / "active" / "test-epic-2026-06" / "EPIC.md").exists()


def test_run_export_freeze_guard_fires_before_store(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "spoq")
    (tmp_path / "spoq").mkdir()
    with pytest.raises(SystemExit):
        run_export(epic=None, export_all=True, out=str(tmp_path / "spoq"))


def test_export_all_writes_maps_and_roadmap(tmp_path, monkeypatch):
    monkeypatch.setattr(export_cli, "WORKSPACE_SPOQ", tmp_path / "frozen-spoq")
    out = tmp_path / "out"
    maps = [MapDoc(id="example-product-board-mvp", title="Example Product Board MVP",
                   vision="ship it")]
    roadmap = [RoadmapEntry(slug="test-epic-2026-06", title="Test Epic",
                            tier="active", status="completed")]
    store = FakeStore([_epic_dict()], maps=maps, roadmap=roadmap)
    summary = export_store(store, out, export_all=True)
    assert summary["epics"] == 1
    assert summary["maps"] == 1
    assert (out / "maps" / "active" / "example-product-board-mvp" / "MAP.md").exists()
    assert (out / "ROADMAP.yml").exists()
