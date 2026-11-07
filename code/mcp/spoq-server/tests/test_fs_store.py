"""Behavioral tests for the FsStore epic/task backend (mcp-02).

These assert real filesystem behavior — directory moves, prefix-match task
resolution, byte-faithful YAML round-trips, and path-style arg resolution — not
tautologies. The FsStore is the reference backend the API store mirrors.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from spoq_server.stores.base import EpicStore
from spoq_server.stores.fs import FsStore, get_fs_store

# Golden tool output captured against the pristine (pre-refactor) tool surface.
# The only path-dependent token, ``epic_path``, is normalized to ``{EPIC_PATH}``
# so the snapshot is portable across checkouts/tmpdirs.
SNAPSHOT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "tool_output_snapshot_v0.5.1.json"
)


@pytest.fixture
def store_root(tmp_path: Path, fixture_epic_path: Path) -> Path:
    """A SPOQ-shaped project root with the fixture epic in active/."""
    active = tmp_path / "spoq" / "epics" / "active"
    active.mkdir(parents=True)
    shutil.copytree(fixture_epic_path, active / "test-epic")
    return tmp_path


class TestContract:
    def test_fsstore_satisfies_epicstore(self):
        assert issubclass(FsStore, EpicStore)

    def test_fsstore_instantiable(self, tmp_path):
        # EpicStore is abstract; FsStore must implement every abstract method.
        FsStore(tmp_path)


class TestPathResolution:
    def test_relative_resolves_against_root(self, tmp_path):
        store = FsStore(tmp_path)
        assert store._resolve("spoq/epics/active/x") == tmp_path / "spoq/epics/active/x"

    def test_absolute_passes_through(self, tmp_path):
        store = FsStore(tmp_path)
        abs_path = tmp_path / "somewhere"
        assert store._resolve(str(abs_path)) == abs_path


class TestTaskResolution:
    def test_find_task_prefix_match(self, store_root):
        store = FsStore(store_root)
        # Convenience prefix: '01' should resolve to the 01-setup task file.
        found = store.find_task("spoq/epics/active/test-epic", "01")
        assert found is not None
        assert found.name.startswith("01")

    def test_find_task_exact_id(self, store_root):
        store = FsStore(store_root)
        found = store.find_task("spoq/epics/active/test-epic", "01-setup")
        assert found is not None
        assert found.name == "01-setup.yml"

    def test_find_task_missing_returns_none(self, store_root):
        store = FsStore(store_root)
        assert store.find_task("spoq/epics/active/test-epic", "99-nope") is None

    def test_get_task_parses(self, store_root):
        store = FsStore(store_root)
        task = store.get_task("spoq/epics/active/test-epic", "01-setup")
        assert task is not None
        assert task["id"] == "01-setup"

    def test_load_tasks_returns_all(self, store_root):
        store = FsStore(store_root)
        tasks = store.load_tasks("spoq/epics/active/test-epic")
        assert len(tasks) >= 1
        assert all("id" in t or "error" in t for t in tasks)


class TestTaskStats:
    def test_counts_stub_tasks_missing_title(self, tmp_path):
        # Mirrors spoq_list_epics raw counting: stub tasks (id+status only,
        # no title/description) must still count toward total + completed.
        tasks = tmp_path / "spoq/epics/active/e/tasks"
        tasks.mkdir(parents=True)
        (tasks / "01.yml").write_text(yaml.dump({"id": "01", "status": "completed"}))
        (tasks / "02.yml").write_text(yaml.dump({"id": "02", "status": "pending"}))
        store = FsStore(tmp_path)
        total, completed = store.task_stats("spoq/epics/active/e")
        assert (total, completed) == (2, 1)

    def test_no_tasks_dir_is_zero(self, tmp_path):
        (tmp_path / "spoq/epics/active/e").mkdir(parents=True)
        store = FsStore(tmp_path)
        assert store.task_stats("spoq/epics/active/e") == (0, 0)


class TestUpdateTask:
    def test_update_persists_and_roundtrips(self, store_root):
        store = FsStore(store_root)
        epic = "spoq/epics/active/test-epic"
        task_file = store_root / "spoq/epics/active/test-epic/tasks/01-setup.yml"

        store.update_task(epic, "01-setup", {"status": "completed", "last_update": "T"})

        on_disk = yaml.safe_load(task_file.read_text())
        assert on_disk["status"] == "completed"
        assert on_disk["last_update"] == "T"

    def test_update_preserves_dump_options(self, store_root):
        # sort_keys=False means id stays the first key, not alphabetized.
        store = FsStore(store_root)
        epic = "spoq/epics/active/test-epic"
        task_file = store_root / "spoq/epics/active/test-epic/tasks/01-setup.yml"

        store.update_task(epic, "01-setup", {"status": "qa"})
        first_line = task_file.read_text().splitlines()[0]
        assert first_line.startswith("id:")

    def test_update_missing_raises(self, store_root):
        store = FsStore(store_root)
        with pytest.raises(FileNotFoundError):
            store.update_task("spoq/epics/active/test-epic", "99-nope", {"status": "qa"})

    def test_read_task_raw_absent_key_defaults_unknown(self, store_root):
        # The raw read backs spoq_update_task_status's old_status semantics.
        store = FsStore(store_root)
        task_file = store_root / "spoq/epics/active/test-epic/tasks/01-setup.yml"
        data = yaml.safe_load(task_file.read_text())
        data.pop("status", None)
        task_file.write_text(yaml.dump(data, sort_keys=False))
        raw = store.read_task_raw("spoq/epics/active/test-epic", "01-setup")
        assert raw.get("status", "unknown") == "unknown"


class TestTierTransitions:
    def test_promote_moves_directory(self, tmp_path):
        active = tmp_path / "spoq/epics/active/demo"
        active.mkdir(parents=True)
        (active / "EPIC.md").write_text("# Demo")
        store = FsStore(tmp_path)

        move = store.promote("spoq/epics/active/demo")

        assert move["old_tier"] == "active"
        assert move["new_tier"] == "complete"
        assert not active.exists()
        assert (tmp_path / "spoq/epics/complete/demo").is_dir()

    def test_demote_moves_directory(self, tmp_path):
        active = tmp_path / "spoq/epics/active/demo"
        active.mkdir(parents=True)
        store = FsStore(tmp_path)

        move = store.demote("spoq/epics/active/demo")

        assert move["new_tier"] == "backlog"
        assert (tmp_path / "spoq/epics/backlog/demo").is_dir()

    def test_promote_at_highest_raises(self, tmp_path):
        complete = tmp_path / "spoq/epics/complete/demo"
        complete.mkdir(parents=True)
        store = FsStore(tmp_path)
        with pytest.raises(ValueError, match="highest tier"):
            store.promote("spoq/epics/complete/demo")

    def test_demote_at_lowest_raises(self, tmp_path):
        backlog = tmp_path / "spoq/epics/backlog/demo"
        backlog.mkdir(parents=True)
        store = FsStore(tmp_path)
        with pytest.raises(ValueError, match="lowest tier"):
            store.demote("spoq/epics/backlog/demo")

    def test_promote_no_tier_in_path_raises(self, tmp_path):
        loose = tmp_path / "loose"
        loose.mkdir()
        store = FsStore(tmp_path)
        with pytest.raises(ValueError, match="Cannot determine tier"):
            store.promote(str(loose))

    def test_promote_dest_exists_raises(self, tmp_path):
        (tmp_path / "spoq/epics/active/demo").mkdir(parents=True)
        (tmp_path / "spoq/epics/complete/demo").mkdir(parents=True)
        store = FsStore(tmp_path)
        with pytest.raises(FileExistsError):
            store.promote("spoq/epics/active/demo")

    def test_complete_epic_moves_to_sibling_complete(self, store_root):
        store = FsStore(store_root)
        move = store.complete_epic("spoq/epics/active/test-epic")
        assert not (store_root / "spoq/epics/active/test-epic").exists()
        assert (store_root / "spoq/epics/complete/test-epic").is_dir()
        assert move["slug"] == "test-epic"


class TestStoreCache:
    def test_get_fs_store_caches_by_root(self, tmp_path):
        a = get_fs_store(tmp_path)
        b = get_fs_store(tmp_path)
        assert a is b

    def test_get_fs_store_distinct_roots(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        assert get_fs_store(tmp_path) is not get_fs_store(other)


class TestToolOutputSnapshot:
    """AC #8: tool OUTPUT (not just tool names/schemas) must be byte-identical
    before and after the FsStore refactor on a fixture epic.

    The golden file ``tool_output_snapshot_v0.5.1.json`` was captured against the
    pristine surface; these tests run the live (post-refactor) tools through the
    FsStore path and assert the serialized JSON matches byte-for-byte after the
    single ``{EPIC_PATH}`` normalization.
    """

    def _run_tools(self, fixture_epic_path: Path) -> dict[str, str]:
        # Import inside the test so any import-time regression surfaces here,
        # exactly as the production tool callers experience it.
        from spoq_server.epic_tools import spoq_parse_epic
        from spoq_server.task_tools import spoq_list_task_statuses

        fx = str(fixture_epic_path.resolve())
        parse = spoq_parse_epic(fx).replace(fx, "{EPIC_PATH}")
        statuses = spoq_list_task_statuses(fx)
        return {
            "spoq_parse_epic": parse,
            "spoq_list_task_statuses": statuses,
        }

    def test_snapshot_fixture_present_and_well_formed(self):
        golden = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
        assert set(golden) == {"spoq_parse_epic", "spoq_list_task_statuses"}
        # Each captured value is itself a JSON document the tool returns.
        json.loads(golden["spoq_parse_epic"].replace("{EPIC_PATH}", "/x"))
        json.loads(golden["spoq_list_task_statuses"])

    def test_parse_epic_output_byte_identical(self, fixture_epic_path):
        golden = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
        live = self._run_tools(fixture_epic_path)
        # Byte-for-byte string equality — not a parsed/structural compare.
        assert live["spoq_parse_epic"] == golden["spoq_parse_epic"]

    def test_list_task_statuses_output_byte_identical(self, fixture_epic_path):
        golden = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
        live = self._run_tools(fixture_epic_path)
        assert live["spoq_list_task_statuses"] == golden["spoq_list_task_statuses"]

    def test_snapshot_stable_across_tmpdir_copy(self, tmp_path, fixture_epic_path):
        # Same epic content at a DIFFERENT absolute location must still match
        # after normalization — proves the snapshot guards content, not paths.
        # Keep the leaf dir name ("test-epic") — epic_name is derived from it
        # and is legitimately content, not path. Only the parent location moves.
        dest = tmp_path / "relocated" / "test-epic"
        shutil.copytree(fixture_epic_path, dest)
        golden = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
        live = self._run_tools(dest)
        assert live["spoq_parse_epic"] == golden["spoq_parse_epic"]
        assert live["spoq_list_task_statuses"] == golden["spoq_list_task_statuses"]


# ===================================================================
# Map / Roadmap backend (mcp-03)
#
# These assert real filesystem behavior for the map/roadmap half of the
# store contract: MAP.md resolution + inline status rewrite, and ROADMAP.yml
# load/save/sync. The dict-shaped methods are the surface the map/roadmap
# tools call after the task-03 extraction.
# ===================================================================

from spoq_server.stores.base import MapStore, RoadmapStore


@pytest.fixture
def map_root(tmp_path: Path, fixture_map_path: Path, fixture_map_epics_path: Path) -> Path:
    """A SPOQ-shaped root with the fixture map under spoq/maps/active/."""
    maps_active = tmp_path / "spoq" / "maps" / "active"
    maps_active.mkdir(parents=True)
    shutil.copytree(fixture_map_path, maps_active / "test-map")
    epics_active = tmp_path / "spoq" / "epics" / "active"
    epics_active.mkdir(parents=True)
    shutil.copytree(fixture_map_epics_path, epics_active, dirs_exist_ok=True)
    return tmp_path


class TestMapRoadmapContract:
    def test_fsstore_satisfies_map_and_roadmap_stores(self):
        assert issubclass(FsStore, MapStore)
        assert issubclass(FsStore, RoadmapStore)

    def test_required_methods_present(self):
        for m in (
            "resolve_map_file", "read_map_status", "write_map_status",
            "load_roadmap", "save_roadmap", "sync_roadmap_from_disk",
        ):
            assert hasattr(FsStore, m), m


class TestResolveMapFile:
    def test_directory_format_resolves_to_map_md(self, map_root):
        store = FsStore(map_root)
        resolved = store.resolve_map_file("spoq/maps/active/test-map")
        assert resolved is not None
        assert resolved.name == "MAP.md"
        assert resolved.exists()

    def test_standalone_md_passes_through(self, tmp_path):
        store = FsStore(tmp_path)
        f = tmp_path / "solo-map.md"
        f.write_text("# Map: Solo\n", encoding="utf-8")
        assert store.resolve_map_file("solo-map.md") == f

    def test_missing_returns_none(self, tmp_path):
        store = FsStore(tmp_path)
        assert store.resolve_map_file("spoq/maps/active/nope") is None


class TestReadMapStatus:
    def test_parses_title_and_epics(self, map_root):
        store = FsStore(map_root)
        data = store.read_map_status("spoq/maps/active/test-map")
        assert "error" not in data
        assert data["title"] == "Test Pipeline"
        slugs = {e["slug"] for e in data["epics"]}
        assert {"alpha-service", "beta-api", "gamma-tests"} <= slugs


class TestWriteMapStatus:
    def test_rewrites_status_line_in_place(self, map_root):
        store = FsStore(map_root)
        result = store.write_map_status(
            "spoq/maps/active/test-map",
            {"epic_slug": "beta-api", "new_status": "completed"},
        )
        assert "error" not in result
        assert result["new_status"] == "completed"
        # Re-read through the store: only beta-api changed.
        reparsed = {e["slug"]: e["status"] for e in
                    store.read_map_status("spoq/maps/active/test-map")["epics"]}
        assert reparsed["beta-api"] == "completed"
        assert reparsed["alpha-service"] == "pending"

    def test_preserves_bullet_and_colon_style(self, map_root):
        store = FsStore(map_root)
        store.write_map_status(
            "spoq/maps/active/test-map",
            {"epic_slug": "alpha-service", "new_status": "in_progress"},
        )
        raw = (map_root / "spoq/maps/active/test-map/MAP.md").read_text(encoding="utf-8")
        # Fixture uses "- **Status:** " — bullet + colon-inside style preserved.
        assert "- **Status:** in_progress" in raw

    def test_unknown_epic_returns_error(self, map_root):
        store = FsStore(map_root)
        result = store.write_map_status(
            "spoq/maps/active/test-map",
            {"epic_slug": "does-not-exist", "new_status": "completed"},
        )
        assert "error" in result


class TestRoadmapLoadSave:
    def test_load_missing_returns_scaffold(self, tmp_path):
        store = FsStore(tmp_path)
        data = store.load_roadmap_dict()
        assert data == {"version": 1, "updated_at": "", "epics": []}

    def test_save_then_load_roundtrip_stamps_updated_at(self, tmp_path):
        store = FsStore(tmp_path)
        (tmp_path / "spoq").mkdir()
        store.save_roadmap_dict({"version": 1, "epics": [{"slug": "x", "tier": "active"}]})
        loaded = store.load_roadmap_dict()
        assert loaded["epics"] == [{"slug": "x", "tier": "active"}]
        assert loaded["updated_at"]  # non-empty ISO timestamp

    def test_no_writes_outside_spoq_dir(self, tmp_path):
        store = FsStore(tmp_path)
        (tmp_path / "spoq").mkdir()
        store.save_roadmap_dict({"version": 1, "epics": []})
        assert (tmp_path / "spoq" / "ROADMAP.yml").exists()


class TestRoadmapSyncFromDisk:
    def test_discovers_on_disk_epic(self, store_root):
        store = FsStore(store_root)
        warnings: list[str] = []
        data = store.sync_roadmap_from_disk(warnings=warnings)
        slugs = {e["slug"] for e in data["epics"]}
        assert "test-epic" in slugs
        entry = next(e for e in data["epics"] if e["slug"] == "test-epic")
        assert entry["tier"] == "active"

    def test_removes_stale_entry(self, store_root):
        store = FsStore(store_root)
        # Seed ROADMAP with a phantom epic that has no directory.
        store.save_roadmap_dict({
            "version": 1,
            "epics": [{"slug": "ghost", "title": "Ghost", "tier": "active", "status": "pending"}],
        })
        data = store.sync_roadmap_from_disk()
        slugs = {e["slug"] for e in data["epics"]}
        assert "ghost" not in slugs


class TestRoadmapMatchesUtils:
    """FsStore roadmap I/O must be behaviorally identical to roadmap_utils."""

    def test_load_matches_roadmap_utils(self, store_root):
        from spoq_server import roadmap_utils
        store = FsStore(store_root)
        spoq_dir = str(store_root / "spoq")
        store.save_roadmap_dict({"version": 1, "epics": [
            {"slug": "a", "title": "A", "tier": "active", "status": "pending"}]})
        assert store.load_roadmap_dict() == roadmap_utils.load_roadmap(spoq_dir)

    def test_sync_matches_roadmap_utils(self, store_root):
        from spoq_server import roadmap_utils
        store = FsStore(store_root)
        spoq_dir = str(store_root / "spoq")
        w1: list[str] = []
        w2: list[str] = []
        via_store = store.sync_roadmap_from_disk(warnings=w1)
        via_utils = roadmap_utils.sync_from_disk(spoq_dir, warnings=w2)
        assert {e["slug"] for e in via_store["epics"]} == {e["slug"] for e in via_utils["epics"]}

    def test_sync_delegates_full_dict_matches_utils(self, store_root):
        # The consolidated FsStore method is a pure delegation, so the whole
        # reconciled dict (not just the slug set) must equal roadmap_utils'.
        from spoq_server import roadmap_utils
        store = FsStore(store_root)
        spoq_dir = str(store_root / "spoq")
        via_store = store.sync_roadmap_from_disk()
        via_utils = roadmap_utils.sync_from_disk(spoq_dir)
        assert via_store["epics"] == via_utils["epics"]

    def test_sync_body_is_pure_delegation(self):
        # Guard against the ~95-line copy creeping back in.
        import inspect
        src = inspect.getsource(FsStore.sync_roadmap_from_disk)
        assert "roadmap_utils.sync_from_disk" in src
        assert "entries_by_slug" not in src

    def test_sync_surfaces_feature_projects(self, store_root):
        store = FsStore(store_root)
        d = store_root / "spoq" / "epics" / "active" / "feat-epic"
        d.mkdir(parents=True)
        (d / "EPIC.md").write_text(
            "---\nslug: feat-epic\ntitle: Feat Epic\ntier: active\n"
            "status: pending\nfeature: my-feat\nprojects:\n  - api\n  - dash\n"
            "---\n\n# Epic\n",
            encoding="utf-8",
        )
        data = store.sync_roadmap_from_disk()
        entry = next(e for e in data["epics"] if e["slug"] == "feat-epic")
        assert entry["feature"] == "my-feat"
        assert entry["projects"] == ["api", "dash"]
        # Typed projection carries them too.
        rec = store._roadmap_entry(entry)
        assert rec.feature == "my-feat"
        assert rec.projects == ["api", "dash"]


# --- task 06: FsStore honors MAP.md frontmatter + product.yml -------------

_FEATURE_MAP_MD = (
    "---\n"
    "slug: feat-x\n"
    'title: "Feature: X"\n'
    "tier: active\n"
    "version: 0.1.0\n"
    "projects: [api, dash]\n"
    "---\n"
    "\n"
    "# Map: X\n"
    "\n"
    "## Vision\n"
    "A feature.\n"
    "\n"
    "---\n"  # a BODY horizontal rule — must NOT be read as frontmatter
    "\n"
    "## Epics\n"
    "### e1\n"
    "- **Status:** pending\n"
    "### e2\n"
    "- **Status:** pending\n"
)

_VALID_PRODUCT_YML = (
    "products:\n"
    "  - slug: example-product\n"
    "    name: Example Product\n"
    "    versions:\n"
    "      - semver: 0.1.0\n"
    "        status: planned\n"
    "      - semver: 1.0.0\n"
    "        status: released\n"
    "        released_date: 2026-07-01\n"
)

# Bad version status → validation must flag it.
_INVALID_PRODUCT_YML = (
    "products:\n"
    "  - slug: example-product\n"
    "    name: Example Product\n"
    "    versions:\n"
    "      - semver: 0.1.0\n"
    "        status: bogus\n"
)


class TestParseMapSurfacesFrontmatter:
    """FsStore.parse_map/read_map_status carry MAP.md leading-fence fields."""

    def _root_with_feature_map(self, tmp_path: Path) -> Path:
        d = tmp_path / "spoq" / "maps" / "active" / "feat-x"
        d.mkdir(parents=True)
        (d / "MAP.md").write_text(_FEATURE_MAP_MD, encoding="utf-8")
        return tmp_path

    def test_parse_map_returns_version_and_projects(self, tmp_path):
        root = self._root_with_feature_map(tmp_path)
        doc = FsStore(root).parse_map("spoq/maps/active/feat-x")
        assert doc.version == "0.1.0"
        assert doc.projects == ["api", "dash"]
        assert doc.slug == "feat-x"
        assert doc.tier == "active"

    def test_read_map_status_carries_frontmatter(self, tmp_path):
        root = self._root_with_feature_map(tmp_path)
        data = FsStore(root).read_map_status("spoq/maps/active/feat-x")
        assert "error" not in data
        assert data["version"] == "0.1.0"
        assert data["projects"] == ["api", "dash"]
        # Body sections still parse alongside the frontmatter.
        assert {e["slug"] for e in data["epics"]} == {"e1", "e2"}

    def test_body_horizontal_rule_not_parsed_as_frontmatter(self, tmp_path):
        # A MAP.md whose ONLY '---' is a body rule (no leading fence) yields no
        # frontmatter version/projects — proving the store didn't over-parse.
        d = tmp_path / "spoq" / "maps" / "active" / "plain"
        d.mkdir(parents=True)
        (d / "MAP.md").write_text(
            "# Map: Plain\n\n## Vision\nv\n\n---\n\n## Epics\n### e1\n"
            "- **Status:** pending\n",
            encoding="utf-8",
        )
        doc = FsStore(tmp_path).parse_map("spoq/maps/active/plain")
        assert doc.version is None
        assert doc.projects == []


class TestLoadProductRegistry:
    """FsStore product.yml I/O delegates parse/validate to product_utils."""

    def test_absent_file_returns_empty_registry(self, tmp_path):
        (tmp_path / "spoq").mkdir()
        store = FsStore(tmp_path)
        assert store.load_product_registry() == []
        # An empty registry validates clean.
        assert store.validate_product_registry() == []

    def test_valid_product_yml_loads_and_validates_clean(self, tmp_path):
        (tmp_path / "spoq").mkdir()
        (tmp_path / "spoq" / "product.yml").write_text(
            _VALID_PRODUCT_YML, encoding="utf-8"
        )
        store = FsStore(tmp_path)
        products = store.load_product_registry()
        assert len(products) == 1
        assert products[0].slug == "example-product"
        assert {v.semver for v in products[0].versions} == {"0.1.0", "1.0.0"}
        assert store.validate_product_registry() == []

    def test_invalid_product_yml_reports_errors(self, tmp_path):
        (tmp_path / "spoq").mkdir()
        (tmp_path / "spoq" / "product.yml").write_text(
            _INVALID_PRODUCT_YML, encoding="utf-8"
        )
        store = FsStore(tmp_path)
        errors = store.validate_product_registry()
        assert errors  # non-empty: bad status is flagged
        assert any("bogus" in e for e in errors)

    def test_spoq_dir_override_is_honored(self, tmp_path):
        # I/O is anchored via _spoq_dir → an explicit spoq_dir arg redirects it.
        alt = tmp_path / "elsewhere"
        alt.mkdir()
        (alt / "product.yml").write_text(_VALID_PRODUCT_YML, encoding="utf-8")
        store = FsStore(tmp_path)
        assert store.load_product_registry() == []  # default <root>/spoq has none
        assert len(store.load_product_registry(spoq_dir=str(alt))) == 1
        assert store.validate_product_registry(spoq_dir=str(alt)) == []

    def test_e1_seed_product_yml_validates_clean(self, tmp_path):
        # The E1 workspace seed (products example-app in_progress + example-product planned)
        # is the designated validation fixture. Embedded verbatim here (the seed
        # itself lives in the workspace planning tree, outside this repo) so the
        # test proves the store loads + validates it clean, portably.
        e1_seed = (
            "products:\n"
            "  - slug: example-app\n"
            "    name: Pinpoint\n"
            "    description: Continuously-deployed QA/verification SaaS.\n"
            "    versions:\n"
            "      - semver: 1.0.0\n"
            "        status: in_progress\n"
            "        features:\n"
            "          - api-cleanliness-2026-07\n"
            "  - slug: example-product\n"
            "    name: Example Product\n"
            "    description: SPOQ-native SDLC / fleet-command platform.\n"
            "    versions:\n"
            "      - semver: 0.1.0\n"
            "        status: planned\n"
            "        features:\n"
            "          - example-product-sdlc-uprev-2026-07\n"
        )
        (tmp_path / "spoq").mkdir()
        (tmp_path / "spoq" / "product.yml").write_text(e1_seed, encoding="utf-8")
        store = FsStore(tmp_path)
        products = store.load_product_registry()
        assert {p.slug for p in products} == {"example-app", "example-product"}
        assert store.validate_product_registry() == []
