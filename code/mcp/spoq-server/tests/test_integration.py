"""End-to-end integration tests for the SPOQ MCP server.

These tests exercise every registered tool through FastMCP's call_tool
interface, verifying the complete MCP protocol pipeline from tool
invocation through JSON serialization.

Workflow coverage:
  - Tool discovery (all 29 tools registered)
  - Epic analysis pipeline (parse -> compute_waves -> get_wave_tasks -> assign_personas)
  - Task management lifecycle (get -> update_status -> list_statuses)
  - Utility pipeline (timestamp -> generate_skeleton -> parse_skeleton)
  - Validation & DAG analysis (validate -> analyze_dag -> detect_conflicts)
  - Map coordination pipeline (parse -> validate -> waves -> dag -> status)
  - Roadmap display and lifecycle (roadmap_show, list_epics, promote/demote)
  - Error handling for invalid inputs across all tool categories
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from spoq_server.server import mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def call(tool_name: str, arguments: dict | None = None) -> str:
    """Invoke an MCP tool and return the raw text payload.

    FastMCP.call_tool returns a (contents_list, metadata_dict) tuple.
    Each content object carries a .text attribute with the JSON string.
    """
    result = await mcp.call_tool(tool_name, arguments or {})
    contents, _meta = result
    return contents[0].text


async def call_json(tool_name: str, arguments: dict | None = None) -> dict:
    """Invoke an MCP tool and return the parsed JSON payload."""
    text = await call(tool_name, arguments)
    return json.loads(text)


# ===================================================================
# 1. Tool Discovery
# ===================================================================

EXPECTED_TOOLS = sorted([
    "spoq_ping",
    "spoq_parse_epic",
    "spoq_validate_epic",
    "spoq_compute_waves",
    "spoq_generate_execution_plan",
    "spoq_get_wave_tasks",
    "spoq_analyze_dag",
    "spoq_complete_epic",
    "spoq_get_task",
    "spoq_update_task_status",
    "spoq_list_task_statuses",
    "spoq_assign_personas",
    "spoq_detect_conflicts",
    "spoq_get_timestamp",
    "spoq_generate_skeleton",
    "spoq_parse_map",
    "spoq_validate_map",
    "spoq_compute_epic_waves",
    "spoq_analyze_map_dag",
    "spoq_get_map_status",
    "spoq_list_maps",
    "spoq_generate_map_skeleton",
    "spoq_roadmap_show",
    "spoq_roadmap_sync",
    "spoq_list_epics",
    "spoq_promote",
    "spoq_demote",
    # Feature-aliased tools (thin wrappers over the map verbs, epic
    # spoq-feature-version-support task 05 — added alongside, no map tool removed).
    "spoq_list_features",
    "spoq_parse_feature",
    "spoq_validate_feature",
    "spoq_get_feature_status",
])


@pytest.mark.anyio
async def test_all_tools_discoverable():
    """MCP tool listing must expose exactly 31 registered tools."""
    tools = await mcp.list_tools()
    registered_names = sorted(t.name for t in tools)
    assert registered_names == EXPECTED_TOOLS
    assert len(tools) == 31


@pytest.mark.anyio
async def test_ping_returns_ok():
    """Health-check tool must return status=ok and include version info."""
    data = await call_json("spoq_ping")
    assert data["status"] == "ok"
    assert "version" in data
    assert "project_root" in data
    assert "package" in data


# ===================================================================
# 2. Epic Analysis Workflow
# ===================================================================

class TestEpicAnalysisWorkflow:
    """Parse -> compute_waves -> get_wave_tasks -> assign_personas."""

    @pytest.mark.anyio
    async def test_parse_epic(self, fixture_epic_path):
        """Parsing the fixture epic yields metadata, tasks, and stats."""
        data = await call_json("spoq_parse_epic", {"epic_path": str(fixture_epic_path)})
        assert "error" not in data
        assert "tasks" in data
        assert len(data["tasks"]) == 4
        assert "metadata" in data
        assert "stats" in data
        assert data["epic_name"] == "test-epic"

    @pytest.mark.anyio
    async def test_compute_waves(self, fixture_epic_path):
        """Wave computation produces 3 waves across 4 tasks."""
        data = await call_json("spoq_compute_waves", {"epic_path": str(fixture_epic_path)})
        assert "error" not in data
        assert data["total_waves"] == 3
        assert data["total_tasks"] == 4
        assert len(data["waves"]) == 3

        # Wave 0 should contain the two foundation tasks
        wave0 = data["waves"][0]
        assert wave0["wave"] == 0
        assert wave0["task_count"] == 2
        wave0_ids = {t["id"] for t in wave0["tasks"]}
        assert wave0_ids == {"01-setup", "02-core"}

    @pytest.mark.anyio
    async def test_get_wave_tasks_wave0(self, fixture_epic_path):
        """Fetching wave 0 returns the two independent foundation tasks."""
        data = await call_json("spoq_get_wave_tasks", {
            "epic_path": str(fixture_epic_path),
            "wave": 0,
        })
        assert "error" not in data
        assert data["wave"] == 0
        assert data["task_count"] == 2
        task_ids = {t["id"] for t in data["tasks"]}
        assert task_ids == {"01-setup", "02-core"}

    @pytest.mark.anyio
    async def test_get_wave_tasks_wave1(self, fixture_epic_path):
        """Wave 1 contains the API task that depends on both wave-0 tasks."""
        data = await call_json("spoq_get_wave_tasks", {
            "epic_path": str(fixture_epic_path),
            "wave": 1,
        })
        assert data["task_count"] == 1
        assert data["tasks"][0]["id"] == "03-api"

    @pytest.mark.anyio
    async def test_assign_personas(self, fixture_epic_path):
        """Persona assignment maps every task to a specialist role."""
        data = await call_json("spoq_assign_personas", {
            "epic_path": str(fixture_epic_path),
        })
        assert "error" not in data
        # All 4 tasks must appear in the mapping
        assert len(data) == 4
        assert "01-setup" in data
        assert "02-core" in data
        assert "03-api" in data
        assert "04-tests" in data
        # Each value should be a non-empty persona string
        for task_id, persona in data.items():
            assert isinstance(persona, str)
            assert len(persona) > 0

    @pytest.mark.anyio
    async def test_full_epic_pipeline(self, fixture_epic_path):
        """Chain: parse -> waves -> wave_tasks -> personas -- no step fails."""
        epic = str(fixture_epic_path)

        parsed = await call_json("spoq_parse_epic", {"epic_path": epic})
        assert "error" not in parsed

        waves = await call_json("spoq_compute_waves", {"epic_path": epic})
        assert waves["total_waves"] >= 1

        for wave_num in range(waves["total_waves"]):
            wave_data = await call_json("spoq_get_wave_tasks", {
                "epic_path": epic,
                "wave": wave_num,
            })
            assert wave_data["task_count"] >= 1

        personas = await call_json("spoq_assign_personas", {"epic_path": epic})
        assert len(personas) == parsed["stats"]["total_tasks"]


# ===================================================================
# 2b. Execution Plan (agent-execution / team-execution support)
# ===================================================================

class TestExecutionPlanWorkflow:
    """Execution plan with actionable task filtering for resume support."""

    @pytest.mark.anyio
    async def test_execution_plan_has_actionable_counts(self, fixture_epic_path):
        """Plan includes actionable task counts at top and per-wave level."""
        epic = str(fixture_epic_path)
        data = await call_json("spoq_generate_execution_plan", {"epic_path": epic})
        assert "actionable_tasks" in data
        assert data["actionable_tasks"] == data["total_tasks"]
        for wave in data["waves"]:
            assert "actionable_tasks" in wave

    @pytest.mark.anyio
    async def test_execution_plan_tasks_have_actionable_flag(self, fixture_epic_path):
        """Each task in the plan carries an actionable boolean."""
        epic = str(fixture_epic_path)
        data = await call_json("spoq_generate_execution_plan", {"epic_path": epic})
        for wave in data["waves"]:
            for task in wave["tasks"]:
                assert "actionable" in task
                assert isinstance(task["actionable"], bool)

    @pytest.mark.anyio
    async def test_execution_plan_includes_files_and_skills(self, fixture_epic_path):
        """Tasks include files_to_touch and skills_required for persona assignment."""
        epic = str(fixture_epic_path)
        data = await call_json("spoq_generate_execution_plan", {"epic_path": epic})
        task = data["waves"][0]["tasks"][0]
        assert "files_to_touch" in task
        assert "skills_required" in task

    @pytest.mark.anyio
    async def test_completed_task_not_actionable(self, tmp_epic_copy):
        """After marking a task completed, it should not be actionable."""
        epic = str(tmp_epic_copy)
        # Mark a task completed
        await call_json("spoq_update_task_status", {
            "epic_path": epic, "task_id": "01-setup", "status": "completed"
        })
        data = await call_json("spoq_generate_execution_plan", {"epic_path": epic})
        # Find 01-setup in the plan
        for wave in data["waves"]:
            for task in wave["tasks"]:
                if task["id"] == "01-setup":
                    assert task["actionable"] is False
        assert data["actionable_tasks"] == data["total_tasks"] - 1

    @pytest.mark.anyio
    async def test_execution_plan_includes_critical_path(self, fixture_epic_path):
        """Critical path is included by default with wave numbers."""
        epic = str(fixture_epic_path)
        data = await call_json("spoq_generate_execution_plan", {"epic_path": epic})
        assert "critical_path" in data
        cp_task = data["critical_path"]["tasks"][0]
        assert "wave" in cp_task


# ===================================================================
# 3. Task Management Workflow
# ===================================================================

class TestTaskManagementWorkflow:
    """Get task -> update status -> list statuses (requires mutable copy)."""

    @pytest.mark.anyio
    async def test_get_task(self, tmp_epic_copy):
        """Retrieving a task by ID returns its full YAML payload."""
        data = await call_json("spoq_get_task", {
            "epic_path": str(tmp_epic_copy),
            "task_id": "01-setup",
        })
        assert "error" not in data
        assert data["id"] == "01-setup"
        assert data["status"] == "pending"
        assert data["priority"] == "critical"
        assert "description" in data

    @pytest.mark.anyio
    async def test_update_task_status(self, tmp_epic_copy):
        """Updating status transitions the task and reports both old and new values."""
        data = await call_json("spoq_update_task_status", {
            "epic_path": str(tmp_epic_copy),
            "task_id": "01-setup",
            "status": "in_progress",
        })
        assert data["task_id"] == "01-setup"
        assert data["old_status"] == "pending"
        assert data["new_status"] == "in_progress"
        assert "last_update" in data

    @pytest.mark.anyio
    async def test_update_task_status_with_notes(self, tmp_epic_copy):
        """Providing notes alongside a status change records them."""
        data = await call_json("spoq_update_task_status", {
            "epic_path": str(tmp_epic_copy),
            "task_id": "02-core",
            "status": "in_progress",
            "notes": "Starting frontend work",
        })
        assert data["notes_added"] is True

    @pytest.mark.anyio
    async def test_status_transition_reflected_in_list(self, tmp_epic_copy):
        """After update, list_task_statuses shows the new value."""
        epic = str(tmp_epic_copy)

        # Verify initial state
        before = await call_json("spoq_list_task_statuses", {"epic_path": epic})
        assert before["tasks"]["01-setup"] == "pending"

        # Transition to in_progress
        await call_json("spoq_update_task_status", {
            "epic_path": epic,
            "task_id": "01-setup",
            "status": "in_progress",
        })

        after = await call_json("spoq_list_task_statuses", {"epic_path": epic})
        assert after["tasks"]["01-setup"] == "in_progress"
        assert after["counts"].get("in_progress", 0) >= 1

    @pytest.mark.anyio
    async def test_full_lifecycle(self, tmp_epic_copy):
        """Walk a task through pending -> in_progress -> completed."""
        epic = str(tmp_epic_copy)

        # Fetch initial task
        task = await call_json("spoq_get_task", {
            "epic_path": epic,
            "task_id": "01-setup",
        })
        assert task["status"] == "pending"

        # Move to in_progress
        await call_json("spoq_update_task_status", {
            "epic_path": epic,
            "task_id": "01-setup",
            "status": "in_progress",
        })

        # Move to completed
        update = await call_json("spoq_update_task_status", {
            "epic_path": epic,
            "task_id": "01-setup",
            "status": "completed",
            "notes": "All criteria met",
        })
        assert update["old_status"] == "in_progress"
        assert update["new_status"] == "completed"

        # Confirm via list
        statuses = await call_json("spoq_list_task_statuses", {"epic_path": epic})
        assert statuses["tasks"]["01-setup"] == "completed"


# ===================================================================
# 4. Utility Workflow
# ===================================================================

class TestUtilityWorkflow:
    """Timestamp, skeleton generation, and skeleton round-trip parsing."""

    @pytest.mark.anyio
    async def test_get_timestamp_iso(self):
        """Default ISO timestamp matches YYYY-MM-DDTHH:MM:SSZ pattern."""
        text = await call("spoq_get_timestamp", {})
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text)

    @pytest.mark.anyio
    async def test_get_timestamp_unix(self):
        """Unix timestamp is a numeric string."""
        text = await call("spoq_get_timestamp", {"format": "unix"})
        assert text.isdigit()

    @pytest.mark.anyio
    async def test_get_timestamp_readable(self):
        """Readable timestamp ends with 'UTC'."""
        text = await call("spoq_get_timestamp", {"format": "readable"})
        assert text.endswith("UTC")

    @pytest.mark.anyio
    async def test_generate_skeleton(self, tmp_path):
        """Skeleton generation creates an epic directory with expected files."""
        data = await call_json("spoq_generate_skeleton", {
            "name": "integration-test-epic",
            "task_count": 5,
            "path": str(tmp_path),
        })
        assert "error" not in data
        assert data["task_count"] == 5
        assert "epic_path" in data

        epic_dir = Path(data["epic_path"])
        assert epic_dir.exists()
        assert (epic_dir / "EPIC.md").exists()
        assert (epic_dir / "tasks").is_dir()

        task_files = list((epic_dir / "tasks").glob("*.yml"))
        assert len(task_files) == 5

    @pytest.mark.anyio
    async def test_skeleton_round_trip(self, tmp_path):
        """A generated skeleton can be parsed back through spoq_parse_epic."""
        skeleton = await call_json("spoq_generate_skeleton", {
            "name": "round-trip-test",
            "task_count": 4,
            "path": str(tmp_path),
        })
        assert "error" not in skeleton

        parsed = await call_json("spoq_parse_epic", {
            "epic_path": skeleton["epic_path"],
        })
        assert "error" not in parsed
        assert len(parsed["tasks"]) == 4
        assert parsed["epic_name"] == "round-trip-test"

    @pytest.mark.anyio
    async def test_skeleton_parseable_by_compute_waves(self, tmp_path):
        """Generated skeleton produces valid wave computation results."""
        skeleton = await call_json("spoq_generate_skeleton", {
            "name": "wave-check",
            "task_count": 5,
            "path": str(tmp_path),
        })

        waves = await call_json("spoq_compute_waves", {
            "epic_path": skeleton["epic_path"],
        })
        assert "error" not in waves
        assert waves["total_tasks"] == 5
        assert waves["total_waves"] >= 1


# ===================================================================
# 5. Error Path Tests
# ===================================================================

class TestErrorPaths:
    """Every tool must return structured {error: ...} on bad input."""

    @pytest.mark.anyio
    async def test_parse_epic_invalid_path(self):
        """Nonexistent epic path yields a structured error."""
        data = await call_json("spoq_parse_epic", {
            "epic_path": "/nonexistent/epic/path",
        })
        assert "error" in data

    @pytest.mark.anyio
    async def test_validate_epic_invalid_path(self):
        """Nonexistent path for validation yields a structured error."""
        data = await call_json("spoq_validate_epic", {
            "epic_path": "/nonexistent/epic/path",
        })
        assert "error" in data

    @pytest.mark.anyio
    async def test_get_task_nonexistent_id(self, fixture_epic_path):
        """Requesting a task ID that does not exist yields a clear error."""
        data = await call_json("spoq_get_task", {
            "epic_path": str(fixture_epic_path),
            "task_id": "nonexistent-task-id",
        })
        assert "error" in data
        assert "nonexistent-task-id" in data["error"]

    @pytest.mark.anyio
    async def test_update_task_invalid_status(self, fixture_epic_path):
        """An unrecognized status value is rejected with a descriptive message."""
        data = await call_json("spoq_update_task_status", {
            "epic_path": str(fixture_epic_path),
            "task_id": "01-setup",
            "status": "bananas",
        })
        assert "error" in data
        assert "bananas" in data["error"]
        assert "Must be one of" in data["error"]

    @pytest.mark.anyio
    async def test_get_wave_tasks_invalid_wave(self, fixture_epic_path):
        """A wave number beyond the epic's range returns an error with available waves."""
        data = await call_json("spoq_get_wave_tasks", {
            "epic_path": str(fixture_epic_path),
            "wave": 99,
        })
        assert "error" in data
        assert "99" in data["error"]

    @pytest.mark.anyio
    async def test_detect_conflicts_invalid_wave(self, fixture_epic_path):
        """Out-of-range wave for conflict detection returns available waves."""
        data = await call_json("spoq_detect_conflicts", {
            "epic_path": str(fixture_epic_path),
            "wave": 99,
        })
        assert "error" in data
        assert "99" in data["error"]

    @pytest.mark.anyio
    async def test_compute_waves_invalid_path(self):
        """compute_waves with nonexistent path returns an error."""
        data = await call_json("spoq_compute_waves", {
            "epic_path": "/does/not/exist",
        })
        assert "error" in data

    @pytest.mark.anyio
    async def test_analyze_dag_invalid_path(self):
        """analyze_dag with nonexistent path returns an error."""
        data = await call_json("spoq_analyze_dag", {
            "epic_path": "/does/not/exist",
        })
        assert "error" in data

    @pytest.mark.anyio
    async def test_get_task_invalid_epic_path(self):
        """get_task with nonexistent epic path returns an error."""
        data = await call_json("spoq_get_task", {
            "epic_path": "/does/not/exist",
            "task_id": "01-setup",
        })
        assert "error" in data

    @pytest.mark.anyio
    async def test_generate_skeleton_too_few_tasks(self, tmp_path):
        """Skeleton generation rejects fewer than 3 tasks."""
        data = await call_json("spoq_generate_skeleton", {
            "name": "tiny",
            "task_count": 2,
            "path": str(tmp_path),
        })
        assert "error" in data
        assert "3" in data["error"]

    @pytest.mark.anyio
    async def test_generate_skeleton_duplicate(self, tmp_path):
        """Creating a skeleton twice at the same location is rejected."""
        args = {"name": "duplicate-test", "task_count": 3, "path": str(tmp_path)}
        first = await call_json("spoq_generate_skeleton", args)
        assert "error" not in first

        second = await call_json("spoq_generate_skeleton", args)
        assert "error" in second
        assert "already exists" in second["error"]


# ===================================================================
# 6. Validation Workflow
# ===================================================================

class TestValidationWorkflow:
    """Validate -> analyze_dag -> detect_conflicts."""

    @pytest.mark.anyio
    async def test_validate_epic_passes(self, fixture_epic_path):
        """The fixture epic passes validation with zero errors."""
        data = await call_json("spoq_validate_epic", {
            "epic_path": str(fixture_epic_path),
        })
        assert "error" not in data
        assert data["summary"]["valid"] is True
        assert data["summary"]["error_count"] == 0
        assert data["summary"]["total_tasks"] == 4

    @pytest.mark.anyio
    async def test_analyze_dag_critical_path(self, fixture_epic_path):
        """DAG analysis returns critical path and parallelism metrics."""
        data = await call_json("spoq_analyze_dag", {
            "epic_path": str(fixture_epic_path),
        })
        assert "error" not in data
        assert "critical_path" in data
        assert "parallelism" in data
        assert "effort" not in data

        cp = data["critical_path"]
        assert "tasks" in cp
        assert "length" in cp
        assert len(cp["tasks"]) >= 2  # at least 2 tasks on critical path

        parallelism = data["parallelism"]
        assert parallelism["wave_count"] >= 1
        assert parallelism["max_parallelism"] >= 1

    @pytest.mark.anyio
    async def test_detect_conflicts_wave0(self, fixture_epic_path):
        """Wave 0 conflict detection returns safe_tasks and empty conflicts."""
        data = await call_json("spoq_detect_conflicts", {
            "epic_path": str(fixture_epic_path),
            "wave": 0,
        })
        assert "error" not in data
        assert data["wave"] == 0
        assert isinstance(data["conflicts"], list)
        assert isinstance(data["safe_tasks"], list)
        assert isinstance(data["conflicting_tasks"], list)
        # Wave 0 tasks (01-setup, 02-core) touch different files, so no conflicts
        assert len(data["conflicts"]) == 0
        assert set(data["safe_tasks"]) == {"01-setup", "02-core"}

    @pytest.mark.anyio
    async def test_full_validation_pipeline(self, fixture_epic_path):
        """Chain: validate -> analyze_dag -> detect_conflicts."""
        epic = str(fixture_epic_path)

        # Step 1: Validate
        validation = await call_json("spoq_validate_epic", {"epic_path": epic})
        assert validation["summary"]["valid"] is True

        # Step 2: Analyze DAG
        dag = await call_json("spoq_analyze_dag", {"epic_path": epic})
        assert "critical_path" in dag

        # Step 3: Check conflicts for each wave
        waves = await call_json("spoq_compute_waves", {"epic_path": epic})
        for wave_num in range(waves["total_waves"]):
            conflicts = await call_json("spoq_detect_conflicts", {
                "epic_path": epic,
                "wave": wave_num,
            })
            assert "error" not in conflicts
            assert conflicts["wave"] == wave_num


# ===================================================================
# 7. Map Workflow
# ===================================================================

class TestMapWorkflow:
    """parse_map -> validate_map -> compute_epic_waves -> analyze_map_dag -> status."""

    @pytest.mark.anyio
    async def test_full_map_pipeline(
        self, fixture_map_path, fixture_map_epics_path
    ):
        """Chain map tools end-to-end without any step failing."""
        map_dir = str(fixture_map_path)
        epics_dir = str(fixture_map_epics_path)

        # Step 1: Parse
        parsed = await call_json("spoq_parse_map", {
            "map_path": map_dir,
            "epics_base": epics_dir,
        })
        assert "error" not in parsed
        assert parsed["stats"]["total_epics"] == 3

        # Step 2: Validate
        validated = await call_json("spoq_validate_map", {
            "map_path": map_dir,
        })
        assert validated["summary"]["valid"] is True

        # Step 3: Compute waves
        waves = await call_json("spoq_compute_epic_waves", {
            "map_path": map_dir,
            "critical_path": True,
        })
        assert waves["total_waves"] == 3
        assert "critical_path" in waves

        # Step 4: Analyze DAG
        dag = await call_json("spoq_analyze_map_dag", {
            "map_path": map_dir,
        })
        assert "critical_path" in dag
        assert dag["critical_path"]["length"] >= 2

        # Step 5: Status rollup
        status = await call_json("spoq_get_map_status", {
            "map_path": map_dir,
            "epics_base": epics_dir,
        })
        assert len(status["epics"]) == 3
        assert status["progress"] == 0  # all pending


# ===================================================================
# 8. Roadmap & Lifecycle Workflows
# ===================================================================

class TestRoadmapShowWorkflow:
    """Verify spoq_roadmap_show returns structured output."""

    @pytest.mark.anyio
    async def test_roadmap_show_returns_structure(self):
        """spoq_roadmap_show returns rendered text, epics list, and counts."""
        data = await call_json("spoq_roadmap_show")
        # If ROADMAP.yml exists we get full data; otherwise an error key
        if "error" not in data:
            assert "rendered" in data
            assert "epics" in data
            assert isinstance(data["epics"], list)
            assert "counts" in data
            assert "total" in data["counts"]
        else:
            # Acceptable: file may not exist in CI environments
            assert "ROADMAP.yml" in data["error"]

    @pytest.mark.anyio
    async def test_roadmap_show_json_format(self):
        """Requesting JSON format returns a parseable rendered field."""
        data = await call_json("spoq_roadmap_show", {"format": "json"})
        if "error" not in data:
            assert "rendered" in data
            # Rendered field should itself be valid JSON
            parsed = json.loads(data["rendered"])
            assert isinstance(parsed, list)

    @pytest.mark.anyio
    async def test_roadmap_show_invalid_tier(self):
        """Passing an invalid tier returns a structured error."""
        data = await call_json("spoq_roadmap_show", {"tier": "imaginary"})
        assert "error" in data
        # Either the tier is rejected or ROADMAP.yml is missing (both are valid errors)
        assert "imaginary" in data["error"] or "ROADMAP.yml" in data["error"]


class TestListEpicsWorkflow:
    """Verify spoq_list_epics returns grouped epic lists."""

    @pytest.mark.anyio
    async def test_list_epics_returns_tiers(self):
        """spoq_list_epics returns backlog, active, complete keys and counts."""
        data = await call_json("spoq_list_epics")
        assert "error" not in data
        assert "backlog" in data
        assert "active" in data
        assert "complete" in data
        assert "counts" in data
        assert isinstance(data["backlog"], list)
        assert isinstance(data["active"], list)
        assert isinstance(data["complete"], list)
        assert data["counts"]["total"] == (
            data["counts"]["backlog"]
            + data["counts"]["active"]
            + data["counts"]["complete"]
        )

    @pytest.mark.anyio
    async def test_list_epics_filter_by_tier(self):
        """Filtering by a single tier only populates that tier's list."""
        data = await call_json("spoq_list_epics", {"tier": "active"})
        assert "error" not in data
        # Backlog and complete should be empty when filtering to active
        assert data["backlog"] == []
        assert data["complete"] == []

    @pytest.mark.anyio
    async def test_list_epics_invalid_tier(self):
        """Requesting an invalid tier returns a structured error."""
        data = await call_json("spoq_list_epics", {"tier": "nonexistent"})
        assert "error" in data
        assert "nonexistent" in data["error"]


class TestPromoteDemoteRoundTrip:
    """Create a temp epic in backlog, promote to active, demote back."""

    @pytest.mark.anyio
    async def test_promote_demote_lifecycle(self, tmp_path):
        """Round-trip: generate skeleton in backlog -> promote -> demote -> verify."""
        from spoq_server.server import project_root

        backlog_dir = project_root() / "spoq" / "epics" / "backlog"
        active_dir = project_root() / "spoq" / "epics" / "active"
        slug = "integration-promote-test"
        backlog_path = backlog_dir / slug
        active_path = active_dir / slug

        try:
            # Generate a skeleton directly in backlog
            skeleton = await call_json("spoq_generate_skeleton", {
                "name": slug,
                "task_count": 3,
                "path": str(backlog_dir),
            })
            assert "error" not in skeleton
            assert Path(skeleton["epic_path"]).exists()

            # Promote backlog -> active
            promote_result = await call_json("spoq_promote", {
                "path": str(backlog_path),
            })
            assert "error" not in promote_result
            assert promote_result["old_tier"] == "backlog"
            assert promote_result["new_tier"] == "active"
            assert promote_result["slug"] == slug
            assert active_path.exists()
            assert not backlog_path.exists()

            # Demote active -> backlog
            demote_result = await call_json("spoq_demote", {
                "path": str(active_path),
            })
            assert "error" not in demote_result
            assert demote_result["old_tier"] == "active"
            assert demote_result["new_tier"] == "backlog"
            assert demote_result["slug"] == slug
            assert backlog_path.exists()
            assert not active_path.exists()
        finally:
            # Cleanup: remove the temp epic from whichever tier it ended up in
            for cleanup_path in (backlog_path, active_path):
                if cleanup_path.exists():
                    shutil.rmtree(cleanup_path)

    @pytest.mark.anyio
    async def test_promote_nonexistent_path(self):
        """Promoting a nonexistent path returns a structured error."""
        data = await call_json("spoq_promote", {
            "path": "/nonexistent/epic/path",
        })
        assert "error" in data
        assert "not found" in data["error"].lower()

    @pytest.mark.anyio
    async def test_demote_at_lowest_tier(self, tmp_path):
        """Demoting an epic already at backlog tier returns an error."""
        from spoq_server.server import project_root

        backlog_dir = project_root() / "spoq" / "epics" / "backlog"
        slug = "integration-demote-floor-test"
        backlog_path = backlog_dir / slug

        try:
            skeleton = await call_json("spoq_generate_skeleton", {
                "name": slug,
                "task_count": 3,
                "path": str(backlog_dir),
            })
            assert "error" not in skeleton

            data = await call_json("spoq_demote", {
                "path": str(backlog_path),
            })
            assert "error" in data
            assert "lowest tier" in data["error"].lower()
        finally:
            if backlog_path.exists():
                shutil.rmtree(backlog_path)
