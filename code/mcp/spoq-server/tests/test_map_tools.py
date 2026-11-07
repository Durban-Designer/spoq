"""Unit tests for SPOQ map management MCP tools.

Tests cover the 7 map tools:
  - spoq_parse_map: metadata extraction and epic resolution
  - spoq_validate_map: structural validation and dependency checking
  - spoq_compute_epic_waves: inter-epic wave computation
  - spoq_analyze_map_dag: critical path and parallelism metrics
  - spoq_get_map_status: per-epic status rollup
  - spoq_list_maps: directory scanning for active/complete maps
  - spoq_generate_map_skeleton: templated MAP.md generation

Both map storage formats are tested:
  - Directory format: map-slug/MAP.md
  - Single-file format: map-slug.md
"""

import json
from pathlib import Path

import pytest

from spoq_server.server import mcp


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


# ===================================================================
# 1. Parse Map
# ===================================================================

class TestParseMap:
    """spoq_parse_map: metadata extraction and epic resolution."""

    @pytest.mark.anyio
    async def test_parse_map_returns_valid_json(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Parsing a valid map returns structured JSON without errors."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        assert "error" not in data
        assert "title" in data
        assert "epics" in data
        assert "stats" in data

    @pytest.mark.anyio
    async def test_parse_map_metadata(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Parsed metadata includes title, vision, and correct epic count."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        assert data["title"] == "Test Pipeline"
        assert len(data["epics"]) == 3
        assert data["stats"]["total_epics"] == 3

    @pytest.mark.anyio
    async def test_parse_map_epic_resolution(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Epics with directories on disk are marked as resolved."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        resolved = {e["slug"]: e["resolved"] for e in data["epics"]}
        assert resolved["alpha-service"] is True
        assert resolved["beta-api"] is True
        assert resolved["gamma-tests"] is True

    @pytest.mark.anyio
    async def test_parse_map_unresolved_epics(
        self, fixture_map_path, tmp_path
    ):
        """Epics without directories on disk are marked unresolved."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_path),
            "epics_base": str(tmp_path),  # empty directory
        })
        for epic in data["epics"]:
            assert epic["resolved"] is False

    @pytest.mark.anyio
    async def test_parse_map_stats(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Stats include wave count, critical path, and parallelism."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        stats = data["stats"]
        assert stats["wave_count"] == 3
        assert stats["critical_path_length"] > 0
        assert stats["max_parallelism"] >= 1

    @pytest.mark.anyio
    async def test_parse_map_nonexistent(self):
        """Nonexistent map path returns a structured error."""
        data = await call_json("spoq_parse_map", {
            "map_path": "/nonexistent/map/path",
        })
        assert "error" in data


# ===================================================================
# 2. Validate Map
# ===================================================================

class TestValidateMap:
    """spoq_validate_map: structural and dependency validation."""

    @pytest.mark.anyio
    async def test_validate_map_passes(self, fixture_map_path):
        """The fixture map passes validation with zero errors."""
        data = await call_json("spoq_validate_map", {
            "map_path": str(fixture_map_path),
        })
        assert "error" not in data
        assert data["summary"]["valid"] is True
        assert data["summary"]["error_count"] == 0

    @pytest.mark.anyio
    async def test_validate_map_has_required_keys(self, fixture_map_path):
        """Validation response includes errors, warnings, and summary."""
        data = await call_json("spoq_validate_map", {
            "map_path": str(fixture_map_path),
        })
        assert "errors" in data
        assert "warnings" in data
        assert "summary" in data
        assert "total_epics" in data["summary"]

    @pytest.mark.anyio
    async def test_validate_map_nonexistent(self):
        """Nonexistent path returns a structured error."""
        data = await call_json("spoq_validate_map", {
            "map_path": "/nonexistent/map/path",
        })
        assert "error" in data


# ===================================================================
# 3. Compute Epic Waves
# ===================================================================

class TestComputeEpicWaves:
    """spoq_compute_epic_waves: wave assignment from dependency graph."""

    @pytest.mark.anyio
    async def test_three_waves(self, fixture_map_path):
        """The fixture map produces exactly 3 waves."""
        data = await call_json("spoq_compute_epic_waves", {
            "map_path": str(fixture_map_path),
        })
        assert "error" not in data
        assert data["total_waves"] == 3
        assert data["total_epics"] == 3

    @pytest.mark.anyio
    async def test_wave_structure(self, fixture_map_path):
        """Wave 0 contains alpha-service, wave 1 beta-api, wave 2 gamma-tests."""
        data = await call_json("spoq_compute_epic_waves", {
            "map_path": str(fixture_map_path),
        })
        wave0_slugs = {e["slug"] for e in data["waves"][0]["epics"]}
        wave1_slugs = {e["slug"] for e in data["waves"][1]["epics"]}
        wave2_slugs = {e["slug"] for e in data["waves"][2]["epics"]}

        assert wave0_slugs == {"alpha-service"}
        assert wave1_slugs == {"beta-api"}
        assert wave2_slugs == {"gamma-tests"}

    @pytest.mark.anyio
    async def test_critical_path_option(self, fixture_map_path):
        """Passing critical_path=True includes critical path details."""
        data = await call_json("spoq_compute_epic_waves", {
            "map_path": str(fixture_map_path),
            "critical_path": True,
        })
        assert "critical_path" in data
        assert len(data["critical_path"]["epics"]) >= 2
        assert data["critical_path"]["length"] == len(data["critical_path"]["epics"])


# ===================================================================
# 4. Analyze Map DAG
# ===================================================================

class TestAnalyzeMapDag:
    """spoq_analyze_map_dag: critical path and parallelism."""

    @pytest.mark.anyio
    async def test_critical_path(self, fixture_map_path):
        """DAG analysis returns a non-empty critical path."""
        data = await call_json("spoq_analyze_map_dag", {
            "map_path": str(fixture_map_path),
        })
        assert "error" not in data
        assert "critical_path" in data
        cp = data["critical_path"]
        assert len(cp["epics"]) >= 2
        assert cp["length"] == len(cp["epics"])

    @pytest.mark.anyio
    async def test_parallelism_metrics(self, fixture_map_path):
        """Parallelism section includes wave count and max parallelism."""
        data = await call_json("spoq_analyze_map_dag", {
            "map_path": str(fixture_map_path),
        })
        parallelism = data["parallelism"]
        assert parallelism["wave_count"] == 3
        assert parallelism["max_parallelism"] >= 1

    @pytest.mark.anyio
    async def test_no_effort_section(self, fixture_map_path):
        """Effort estimation was removed from SPOQ — analyze_map_dag must not emit it."""
        data = await call_json("spoq_analyze_map_dag", {
            "map_path": str(fixture_map_path),
        })
        assert "effort" not in data

    @pytest.mark.anyio
    async def test_invalid_path(self):
        """Nonexistent path returns a structured error."""
        data = await call_json("spoq_analyze_map_dag", {
            "map_path": "/does/not/exist",
        })
        assert "error" in data


# ===================================================================
# 6. Get Map Status
# ===================================================================

class TestGetMapStatus:
    """spoq_get_map_status: per-epic status rollup."""

    @pytest.mark.anyio
    async def test_rollup_structure(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Status rollup includes all epics and progress percentage."""
        data = await call_json("spoq_get_map_status", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        assert "error" not in data
        assert "epics" in data
        assert "progress" in data
        assert len(data["epics"]) == 3

    @pytest.mark.anyio
    async def test_all_pending_fixture(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Fixture epics with all tasks pending show pending status."""
        data = await call_json("spoq_get_map_status", {
            "map_path": str(fixture_map_path),
            "epics_base": str(fixture_map_epics_path),
        })
        for slug, status_data in data["epics"].items():
            assert status_data["status"] == "pending"
            assert status_data["resolved"] is True

    @pytest.mark.anyio
    async def test_unresolved_status(self, fixture_map_path, tmp_path):
        """Unresolved epics report status from MAP.md."""
        data = await call_json("spoq_get_map_status", {
            "map_path": str(fixture_map_path),
            "epics_base": str(tmp_path),
        })
        for slug, status_data in data["epics"].items():
            assert status_data["resolved"] is False

    @pytest.mark.anyio
    async def test_nonexistent_path(self):
        """Nonexistent map path returns an error."""
        data = await call_json("spoq_get_map_status", {
            "map_path": "/nonexistent/map",
        })
        assert "error" in data


# ===================================================================
# 7. List Maps
# ===================================================================

class TestListMaps:
    """spoq_list_maps: directory scanning for backlog/active/complete."""

    @pytest.mark.anyio
    async def test_returns_list_structure(self, tmp_path):
        """Result includes backlog, active, and complete lists even if empty."""
        data = await call_json("spoq_list_maps", {
            "base_path": str(tmp_path),
        })
        assert "error" not in data
        assert "backlog" in data
        assert "active" in data
        assert "complete" in data
        assert isinstance(data["backlog"], list)
        assert isinstance(data["active"], list)
        assert isinstance(data["complete"], list)
        assert data["total_backlog"] == 0
        assert data["total_active"] == 0
        assert data["total_complete"] == 0

    @pytest.mark.anyio
    async def test_discovers_map(self, tmp_path, fixture_map_path):
        """A map copied into active/ is discovered by list_maps."""
        import shutil
        active_dir = tmp_path / "active"
        active_dir.mkdir()
        shutil.copytree(fixture_map_path, active_dir / "test-map")

        data = await call_json("spoq_list_maps", {
            "base_path": str(tmp_path),
        })
        assert len(data["active"]) == 1
        assert data["active"][0]["slug"] == "test-map"
        assert data["active"][0]["epic_count"] == 3

    @pytest.mark.anyio
    async def test_discovers_backlog_map(self, tmp_path, fixture_map_path):
        """A map in backlog/ is discovered and counted separately."""
        import shutil
        backlog_dir = tmp_path / "backlog"
        backlog_dir.mkdir()
        shutil.copytree(fixture_map_path, backlog_dir / "future-map")

        data = await call_json("spoq_list_maps", {
            "base_path": str(tmp_path),
        })
        assert len(data["backlog"]) == 1
        assert data["backlog"][0]["slug"] == "future-map"
        assert data["backlog"][0]["epic_count"] == 3
        assert data["total_backlog"] == 1
        assert data["total_active"] == 0
        assert data["total_complete"] == 0


# ===================================================================
# 8. Generate Map Skeleton
# ===================================================================

class TestGenerateMapSkeleton:
    """spoq_generate_map_skeleton: templated MAP.md generation."""

    @pytest.mark.anyio
    async def test_creates_map_directory(self, tmp_path):
        """Skeleton creates a map directory with MAP.md."""
        data = await call_json("spoq_generate_map_skeleton", {
            "name": "test-pipeline",
            "epic_count": 3,
            "path": str(tmp_path),
        })
        assert "error" not in data
        assert "map_path" in data
        map_dir = Path(data["map_path"])
        assert map_dir.exists()
        assert (map_dir / "MAP.md").exists()

    @pytest.mark.anyio
    async def test_correct_epic_count(self, tmp_path):
        """Generated MAP.md contains the requested number of epics."""
        data = await call_json("spoq_generate_map_skeleton", {
            "name": "multi-epic",
            "epic_count": 5,
            "path": str(tmp_path),
        })
        assert data["epic_count"] == 5
        assert data["wave_distribution"]["wave_0"] >= 1
        assert data["wave_distribution"]["wave_1"] >= 1

    @pytest.mark.anyio
    async def test_parseable_by_validate(self, tmp_path):
        """Generated skeleton passes spoq_validate_map."""
        skeleton = await call_json("spoq_generate_map_skeleton", {
            "name": "validate-check",
            "epic_count": 4,
            "path": str(tmp_path),
        })
        assert "error" not in skeleton

        validated = await call_json("spoq_validate_map", {
            "map_path": skeleton["map_path"],
        })
        assert validated["summary"]["valid"] is True
        assert validated["summary"]["error_count"] == 0

    @pytest.mark.anyio
    async def test_parseable_by_compute_waves(self, tmp_path):
        """Generated skeleton produces valid wave computation."""
        skeleton = await call_json("spoq_generate_map_skeleton", {
            "name": "wave-check",
            "epic_count": 6,
            "path": str(tmp_path),
        })
        waves = await call_json("spoq_compute_epic_waves", {
            "map_path": skeleton["map_path"],
        })
        assert "error" not in waves
        assert waves["total_epics"] == 6
        assert waves["total_waves"] >= 2

    @pytest.mark.anyio
    async def test_minimum_epics(self, tmp_path):
        """Fewer than 2 epics is rejected."""
        data = await call_json("spoq_generate_map_skeleton", {
            "name": "tiny",
            "epic_count": 1,
            "path": str(tmp_path),
        })
        assert "error" in data
        assert "2" in data["error"]

    @pytest.mark.anyio
    async def test_duplicate_rejected(self, tmp_path):
        """Creating a skeleton twice at the same path is rejected."""
        args = {"name": "dup-test", "epic_count": 3, "path": str(tmp_path)}
        first = await call_json("spoq_generate_map_skeleton", args)
        assert "error" not in first

        second = await call_json("spoq_generate_map_skeleton", args)
        assert "error" in second
        assert "already exists" in second["error"]

    @pytest.mark.anyio
    async def test_round_trip_analyze(self, tmp_path):
        """Generated skeleton round-trips through analyze_map_dag."""
        skeleton = await call_json("spoq_generate_map_skeleton", {
            "name": "round-trip",
            "epic_count": 4,
            "path": str(tmp_path),
        })
        dag = await call_json("spoq_analyze_map_dag", {
            "map_path": skeleton["map_path"],
        })
        assert "error" not in dag
        assert dag["critical_path"]["length"] >= 2
        assert dag["parallelism"]["wave_count"] >= 2


# ===================================================================
# 9. Single-File Map Format
# ===================================================================

class TestSingleFileMapFormat:
    """All map tools work with standalone .md files (not just directories)."""

    @pytest.mark.anyio
    async def test_parse_single_file(
        self, fixture_map_file_path, fixture_map_epics_path
    ):
        """spoq_parse_map works with a standalone .md file path."""
        data = await call_json("spoq_parse_map", {
            "map_path": str(fixture_map_file_path),
            "epics_base": str(fixture_map_epics_path),
        })
        assert "error" not in data
        assert data["title"] == "Test Pipeline"
        assert len(data["epics"]) == 3

    @pytest.mark.anyio
    async def test_validate_single_file(self, fixture_map_file_path):
        """spoq_validate_map works with a standalone .md file path."""
        data = await call_json("spoq_validate_map", {
            "map_path": str(fixture_map_file_path),
        })
        assert "error" not in data
        assert data["summary"]["valid"] is True
        assert data["summary"]["error_count"] == 0

    @pytest.mark.anyio
    async def test_compute_waves_single_file(self, fixture_map_file_path):
        """spoq_compute_epic_waves works with a standalone .md file path."""
        data = await call_json("spoq_compute_epic_waves", {
            "map_path": str(fixture_map_file_path),
        })
        assert "error" not in data
        assert data["total_waves"] == 3

    @pytest.mark.anyio
    async def test_analyze_dag_single_file(self, fixture_map_file_path):
        """spoq_analyze_map_dag works with a standalone .md file path."""
        data = await call_json("spoq_analyze_map_dag", {
            "map_path": str(fixture_map_file_path),
        })
        assert "error" not in data
        assert data["critical_path"]["length"] >= 2

    @pytest.mark.anyio
    async def test_get_status_single_file(
        self, fixture_map_file_path, fixture_map_epics_path
    ):
        """spoq_get_map_status works with a standalone .md file path."""
        data = await call_json("spoq_get_map_status", {
            "map_path": str(fixture_map_file_path),
            "epics_base": str(fixture_map_epics_path),
        })
        assert "error" not in data
        assert len(data["epics"]) == 3

    @pytest.mark.anyio
    async def test_list_maps_discovers_single_files(self, tmp_path):
        """spoq_list_maps discovers standalone .md map files."""
        import shutil
        from pathlib import Path

        active_dir = tmp_path / "active"
        active_dir.mkdir()

        # Copy the single-file fixture into the active directory
        fixtures = Path(__file__).parent / "fixtures"
        shutil.copy(fixtures / "test-map-file.md", active_dir / "pipeline.md")

        data = await call_json("spoq_list_maps", {
            "base_path": str(tmp_path),
        })
        assert len(data["active"]) == 1
        assert data["active"][0]["slug"] == "pipeline"
        assert data["active"][0]["title"] == "Test Pipeline"
        assert data["active"][0]["epic_count"] == 3

    @pytest.mark.anyio
    async def test_list_maps_mixed_formats(self, tmp_path, fixture_map_path):
        """spoq_list_maps discovers both directory and single-file maps."""
        import shutil
        from pathlib import Path

        active_dir = tmp_path / "active"
        active_dir.mkdir()

        # Directory-format map
        shutil.copytree(fixture_map_path, active_dir / "dir-map")

        # Single-file-format map
        fixtures = Path(__file__).parent / "fixtures"
        shutil.copy(fixtures / "test-map-file.md", active_dir / "file-map.md")

        data = await call_json("spoq_list_maps", {
            "base_path": str(tmp_path),
        })
        slugs = {m["slug"] for m in data["active"]}
        assert slugs == {"dir-map", "file-map"}
        assert data["total_active"] == 2


# ===================================================================
# 10. Update Epic Status in Map
# ===================================================================

class TestUpdateEpicStatusInMap:
    """map_utils.update_epic_status_in_map: rewrite status lines."""

    def test_updates_status_in_directory_map(self, tmp_map_copy):
        """Updates the **Status:** line for a named epic in a directory map."""
        from spoq_server.map_utils import update_epic_status_in_map

        map_dir, _ = tmp_map_copy
        result = update_epic_status_in_map(
            map_dir, "alpha-service", "Complete (4/4 tasks, 2026-03-27)",
        )
        assert "error" not in result
        assert "Complete" in result["new_status"]

        content = (map_dir / "MAP.md").read_text()
        # The alpha-service section should now say Complete
        section = content.split("### alpha-service")[1].split("###")[0]
        assert "Complete (4/4 tasks, 2026-03-27)" in section

    def test_updates_status_in_single_file_map(self, tmp_path):
        """Updates status in a standalone .md map file."""
        import shutil
        from pathlib import Path
        from spoq_server.map_utils import update_epic_status_in_map

        fixtures = Path(__file__).parent / "fixtures"
        map_file = tmp_path / "pipeline.md"
        shutil.copy(fixtures / "test-map-file.md", map_file)

        result = update_epic_status_in_map(
            map_file, "beta-api", "Complete (6/6 tasks, 2026-03-27)",
        )
        assert "error" not in result

        content = map_file.read_text()
        section = content.split("### beta-api")[1].split("###")[0]
        assert "Complete (6/6 tasks, 2026-03-27)" in section

    def test_preserves_other_epics(self, tmp_map_copy):
        """Updating one epic leaves others unchanged."""
        from spoq_server.map_utils import update_epic_status_in_map

        map_dir, _ = tmp_map_copy
        update_epic_status_in_map(
            map_dir, "alpha-service", "Complete",
        )

        content = (map_dir / "MAP.md").read_text()
        beta_section = content.split("### beta-api")[1].split("###")[0]
        assert "pending" in beta_section.lower()

    def test_missing_epic_returns_error(self, tmp_map_copy):
        """Updating a non-existent epic slug returns an error."""
        from spoq_server.map_utils import update_epic_status_in_map

        map_dir, _ = tmp_map_copy
        result = update_epic_status_in_map(
            map_dir, "nonexistent-epic", "Complete",
        )
        assert "error" in result

    def test_missing_map_returns_error(self):
        """Non-existent map path returns an error."""
        from pathlib import Path
        from spoq_server.map_utils import update_epic_status_in_map

        result = update_epic_status_in_map(
            Path("/nonexistent"), "alpha-service", "Complete",
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# MAP.md leading-fence frontmatter (Feature descriptor)
# ---------------------------------------------------------------------------

class TestMapFrontmatter:
    """parse_map_md leading-``---``-fence parsing (FEATURE_FRONTMATTER_SCHEMA)."""

    def _body(self) -> str:
        # A body ``---`` horizontal rule appears between Vision and Epics.
        return (
            "\n# Map: X\n\n## Vision\nv\n\n---\n\n"
            "## Epics\n### e1\n- **Status:** pending\n"
            "### e2\n- **Status:** pending\n"
        )

    def test_map_frontmatter_leading_fence(self, tmp_path):
        """A leading fence yields slug/title/tier/version/projects."""
        from spoq_server.map_utils import parse_map_md

        (tmp_path / "MAP.md").write_text(
            '---\nslug: feat-x\ntitle: "Feature: X"\ntier: active\n'
            'version: 0.1.0\nprojects: [api, dashboard]\n---\n' + self._body()
        )
        m = parse_map_md(tmp_path)
        assert m["slug"] == "feat-x"
        assert m["title"] == "Feature: X"
        assert m["tier"] == "active"
        assert m["version"] == "0.1.0"
        assert m["projects"] == ["api", "dashboard"]
        # Section membership still parses (two epics from the body).
        assert [e["slug"] for e in m["epics"]] == ["e1", "e2"]

    def test_map_body_rule_not_frontmatter(self, tmp_path):
        """A body ``---`` rule is never mistaken for a frontmatter fence."""
        from spoq_server.map_utils import parse_map_md

        (tmp_path / "MAP.md").write_text(self._body().lstrip("\n"))
        m = parse_map_md(tmp_path)
        assert m["title"] == "X"          # heading-derived, not a fence
        assert m["version"] is None       # no fence → no version
        assert m["projects"] == []        # no fence → empty list
        assert m["slug"] == tmp_path.name  # falls back to dir name

    def test_map_frontmatter_title_precedence(self, tmp_path):
        """Frontmatter title overrides the ``# Heading`` title."""
        from spoq_server.map_utils import parse_map_md

        (tmp_path / "MAP.md").write_text(
            '---\nslug: feat-y\ntitle: "Feature: Y from fence"\ntier: active\n'
            '---\n' + self._body()
        )
        m = parse_map_md(tmp_path)
        assert m["title"] == "Feature: Y from fence"

    def test_map_frontmatter_tolerates_epics_key(self, tmp_path):
        """A derived ``epics: [...]`` fence key never corrupts section epics."""
        from spoq_server.map_utils import parse_map_md

        (tmp_path / "MAP.md").write_text(
            '---\nslug: feat-z\ntitle: "Feature: Z"\ntier: active\n'
            'epics: [ghost-a, ghost-b]\n---\n' + self._body()
        )
        m = parse_map_md(tmp_path)
        # Section-parsed membership is authoritative — fence epics are passed
        # through untouched under a distinct key, not merged into ``epics``.
        assert [e["slug"] for e in m["epics"]] == ["e1", "e2"]
        assert m["frontmatter_epics"] == ["ghost-a", "ghost-b"]

    def test_map_frontmatter_feeds_mapdoc(self, tmp_path):
        """MapDoc.from_dict stores version/projects from the parsed dict."""
        from spoq_server.map_utils import parse_map_md
        from spoq_server.stores.records import MapDoc

        (tmp_path / "MAP.md").write_text(
            '---\nslug: feat-w\ntitle: "Feature: W"\ntier: active\n'
            'version: 1.2.3\nprojects: [core]\n---\n' + self._body()
        )
        doc = MapDoc.from_dict("feat-w", parse_map_md(tmp_path))
        assert doc.version == "1.2.3"
        assert doc.projects == ["core"]
        assert doc.tier == "active"

    def test_frontmatter_dependencies_stay_separate_from_body_epics(self, tmp_path):
        from spoq_server.map_utils import parse_map_md
        document = tmp_path / "sample-plan.md"
        document.write_text("---\nslug: sample-plan\ntier: backlog\nepics:\n  - feature-a\n  - feature-b\n---\n# Map: Sample Plan\n\n## Vision\nExample.\n\n## Epics\n### feature-a\n- **Status:** pending\n### feature-b\n- **Status:** pending\n")
        parsed = parse_map_md(document)
        assert parsed["slug"] == "sample-plan"
        assert parsed["tier"] == "backlog"
        assert parsed["frontmatter_epics"] == ["feature-a", "feature-b"]
        assert parsed["version"] is None
        assert parsed["projects"] == []
        assert parsed["title"] == "Sample Plan"

    def test_map_malformed_fence_graceful_fallback(self, tmp_path):
        """A malformed leading fence degrades to no-frontmatter defaults.

        Exercises the fallback through ``parse_map_md`` itself (not just
        ``epic_utils.parse_frontmatter``): an unclosed fence and a non-mapping
        (list) fence both yield version None, projects [], slug from dir name,
        and a heading-derived title — never a crash.
        """
        from spoq_server.map_utils import parse_map_md

        body = (
            "\n# Map: Malformed\n\n## Vision\nv\n\n"
            "## Epics\n### e1\n- **Status:** pending\n"
            "### e2\n- **Status:** pending\n"
        )

        # Case 1: opening fence never closes.
        unclosed = tmp_path / "unclosed"
        unclosed.mkdir()
        (unclosed / "MAP.md").write_text("---\nslug: a\nno close here\n" + body)
        m1 = parse_map_md(unclosed)
        assert m1["version"] is None
        assert m1["projects"] == []
        assert m1["slug"] == "unclosed"       # fence ignored → dir-name fallback
        assert m1["title"] == "Malformed"     # heading-derived

        # Case 2: fence body is a YAML list, not a mapping.
        listfence = tmp_path / "listfence"
        listfence.mkdir()
        (listfence / "MAP.md").write_text("---\n- one\n- two\n---\n" + body)
        m2 = parse_map_md(listfence)
        assert m2["version"] is None
        assert m2["projects"] == []
        assert m2["slug"] == "listfence"
        assert m2["title"] == "Malformed"
        assert "frontmatter_epics" not in m2  # non-mapping fence exposes nothing


# ---------------------------------------------------------------------------
# Feature-aliased MCP tools (SDLC-hierarchy uprev, design §4.2)
# ---------------------------------------------------------------------------

class TestFeatureAliasTools:
    """spoq_*_feature tools are thin, payload-identical wrappers over map verbs.

    A "Feature" IS a map on disk (same dir, same MAP.md, same MapDoc). Each
    feature tool must delegate 1:1 to its ``spoq_*_map`` counterpart and return
    a byte-identical payload for the same input — no logic fork.
    """

    def _make_feature_map(self, parent) -> Path:
        d = parent / "feat-parity"
        d.mkdir()
        (d / "MAP.md").write_text(
            '---\nslug: feat-parity\ntitle: "Feature: Parity"\ntier: active\n'
            'version: 0.3.0\nprojects: [api, dashboard]\n---\n'
            "\n# Map: Parity\n\n## Vision\nv\n\n---\n\n"
            "## Epics\n### e1\n- **Status:** pending\n- **Dependencies:** none\n"
            "### e2\n- **Status:** pending\n- **Dependencies:** [e1]\n"
        )
        return d

    def test_parse_feature_matches_parse_map(self, tmp_path):
        """spoq_parse_feature returns the SAME payload as spoq_parse_map."""
        from spoq_server.map_tools import spoq_parse_feature, spoq_parse_map

        d = self._make_feature_map(tmp_path)
        eb = tmp_path / "epics"
        eb.mkdir()
        assert spoq_parse_feature(str(d), str(eb)) == spoq_parse_map(str(d), str(eb))

    def test_parse_feature_surfaces_frontmatter(self, tmp_path):
        """spoq_parse_feature surfaces the MAP.md frontmatter (task 02 fields)."""
        from spoq_server.map_tools import spoq_parse_feature

        d = self._make_feature_map(tmp_path)
        data = json.loads(spoq_parse_feature(str(d)))
        assert "error" not in data
        assert data["slug"] == "feat-parity"
        assert data["title"] == "Feature: Parity"
        assert data["tier"] == "active"
        assert data["version"] == "0.3.0"
        assert data["projects"] == ["api", "dashboard"]
        assert [e["slug"] for e in data["epics"]] == ["e1", "e2"]

    def test_validate_feature_matches_validate_map(self, tmp_path):
        """spoq_validate_feature returns the SAME payload as spoq_validate_map."""
        from spoq_server.map_tools import spoq_validate_feature, spoq_validate_map

        d = self._make_feature_map(tmp_path)
        assert spoq_validate_feature(str(d)) == spoq_validate_map(str(d))

    def test_get_feature_status_matches_get_map_status(self, tmp_path):
        """spoq_get_feature_status returns the SAME payload as spoq_get_map_status."""
        from spoq_server.map_tools import (
            spoq_get_feature_status,
            spoq_get_map_status,
        )

        d = self._make_feature_map(tmp_path)
        eb = tmp_path / "epics"
        eb.mkdir()
        assert spoq_get_feature_status(str(d), str(eb)) == spoq_get_map_status(
            str(d), str(eb)
        )

    def test_list_features_matches_list_maps(self, tmp_path):
        """spoq_list_features returns the SAME payload as spoq_list_maps."""
        from spoq_server.map_tools import spoq_list_features, spoq_list_maps

        active = tmp_path / "active"
        active.mkdir()
        self._make_feature_map(active)  # active/feat-parity
        result = spoq_list_features(str(tmp_path))
        assert result == spoq_list_maps(str(tmp_path))
        data = json.loads(result)
        assert data["active"][0]["slug"] == "feat-parity"

    @pytest.mark.anyio
    async def test_feature_tools_reachable_via_mcp(self):
        """The four feature aliases are dispatchable through the MCP surface."""
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert {
            "spoq_list_features",
            "spoq_parse_feature",
            "spoq_validate_feature",
            "spoq_get_feature_status",
        } <= names


# ---------------------------------------------------------------------------
# resource_type="feature" on promote/demote (normalized to "map" at tool layer)
# ---------------------------------------------------------------------------

class TestPromoteDemoteFeatureAlias:
    """resource_type='feature' routes to spoq/maps identically to 'map'."""

    def test_promote_feature_moves_map_dir(self, tmp_path, monkeypatch):
        """A feature promote moves a spoq/maps/<tier>/<slug> dir forward."""
        import spoq_server.epic_tools as et
        from spoq_server.epic_tools import spoq_promote

        maps_base = tmp_path / "spoq" / "maps"
        src = maps_base / "backlog" / "my-feature"
        src.mkdir(parents=True)
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src), resource_type="feature"))
        assert "error" not in data
        assert data["old_tier"] == "backlog"
        assert data["new_tier"] == "active"
        assert data["slug"] == "my-feature"
        assert not src.exists()
        assert (maps_base / "active" / "my-feature").exists()

    def test_promote_feature_equals_promote_map(self, tmp_path, monkeypatch):
        """feature and map promotes produce the same tier transition."""
        import spoq_server.epic_tools as et
        from spoq_server.epic_tools import spoq_promote

        maps_base = tmp_path / "spoq" / "maps"
        (maps_base / "backlog" / "feat-a").mkdir(parents=True)
        (maps_base / "backlog" / "map-a").mkdir(parents=True)
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        fdata = json.loads(spoq_promote(str(maps_base / "backlog" / "feat-a"),
                                        resource_type="feature"))
        mdata = json.loads(spoq_promote(str(maps_base / "backlog" / "map-a"),
                                        resource_type="map"))
        assert "error" not in fdata and "error" not in mdata
        assert fdata["old_tier"] == mdata["old_tier"] == "backlog"
        assert fdata["new_tier"] == mdata["new_tier"] == "active"

    def test_demote_feature_moves_map_dir(self, tmp_path, monkeypatch):
        """A feature demote moves a spoq/maps/<tier>/<slug> dir backward."""
        import spoq_server.epic_tools as et
        from spoq_server.epic_tools import spoq_demote

        maps_base = tmp_path / "spoq" / "maps"
        src = maps_base / "complete" / "my-feature"
        src.mkdir(parents=True)
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src), resource_type="feature"))
        assert "error" not in data
        assert data["old_tier"] == "complete"
        assert data["new_tier"] == "active"
        assert not src.exists()
        assert (maps_base / "active" / "my-feature").exists()
