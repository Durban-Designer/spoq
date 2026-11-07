"""Unit tests for SPOQ epic management MCP tools."""

import json
from pathlib import Path

import pytest

from spoq_server.epic_tools import (
    spoq_analyze_dag,
    spoq_complete_epic,
    spoq_compute_waves,
    spoq_demote,
    spoq_generate_execution_plan,
    spoq_get_wave_tasks,
    spoq_list_epics,
    spoq_parse_epic,
    spoq_promote,
    spoq_validate_epic,
)


# =============================================================================
# spoq_parse_epic
# =============================================================================


class TestParseEpic:
    """Tests for the spoq_parse_epic tool."""

    def test_parse_epic_returns_valid_json(self, fixture_epic_path):
        raw = spoq_parse_epic(str(fixture_epic_path))
        data = json.loads(raw)
        assert "error" not in data

    def test_parse_epic_contains_metadata(self, fixture_epic_path):
        data = json.loads(spoq_parse_epic(str(fixture_epic_path)))
        assert "metadata" in data
        assert "title" in data["metadata"]
        assert data["metadata"]["title"] == "Config Validator Service"

    def test_parse_epic_contains_tasks(self, fixture_epic_path):
        data = json.loads(spoq_parse_epic(str(fixture_epic_path)))
        assert "tasks" in data
        assert len(data["tasks"]) == 4

    def test_parse_epic_contains_stats(self, fixture_epic_path):
        data = json.loads(spoq_parse_epic(str(fixture_epic_path)))
        assert "stats" in data
        stats = data["stats"]
        assert stats["total_tasks"] == 4
        assert stats["valid_tasks"] == 4
        assert stats["pending"] == 4

    def test_parse_epic_strips_source_file(self, fixture_epic_path):
        data = json.loads(spoq_parse_epic(str(fixture_epic_path)))
        for task in data["tasks"]:
            assert "_source_file" not in task

    def test_parse_epic_contains_epic_name(self, fixture_epic_path):
        data = json.loads(spoq_parse_epic(str(fixture_epic_path)))
        assert data["epic_name"] == "test-epic"

    def test_parse_epic_nonexistent_path(self):
        raw = spoq_parse_epic("/nonexistent/path/to/epic")
        data = json.loads(raw)
        assert "error" in data
        assert "not found" in data["error"].lower() or "not a directory" in data["error"].lower()

    def test_parse_epic_relative_path(self, fixture_epic_path):
        """Verify relative paths are resolved against project root."""
        # Use a path that definitely does not exist relative to project root
        raw = spoq_parse_epic("nonexistent/relative/epic")
        data = json.loads(raw)
        assert "error" in data


# =============================================================================
# spoq_validate_epic
# =============================================================================


class TestValidateEpic:
    """Tests for the spoq_validate_epic tool."""

    def test_validate_returns_valid_json(self, fixture_epic_path):
        raw = spoq_validate_epic(str(fixture_epic_path))
        data = json.loads(raw)
        assert "error" not in data

    def test_validate_has_required_keys(self, fixture_epic_path):
        data = json.loads(spoq_validate_epic(str(fixture_epic_path)))
        assert "errors" in data
        assert "warnings" in data
        assert "summary" in data

    def test_validate_summary_structure(self, fixture_epic_path):
        data = json.loads(spoq_validate_epic(str(fixture_epic_path)))
        summary = data["summary"]
        assert "valid" in summary
        assert "total_tasks" in summary
        assert "valid_tasks" in summary
        assert "error_count" in summary
        assert "warning_count" in summary

    def test_validate_fixture_epic_is_valid(self, fixture_epic_path):
        data = json.loads(spoq_validate_epic(str(fixture_epic_path)))
        assert data["summary"]["valid"] is True
        assert data["summary"]["error_count"] == 0

    def test_validate_fixture_no_warnings_above_threshold(self, fixture_epic_path):
        """The fixture epic has 7 success criteria (above the 5 threshold), so no warnings."""
        data = json.loads(spoq_validate_epic(str(fixture_epic_path)))
        # The fixture has 7 checkboxes which is >= 5, so no recommend warning
        recommend_warnings = [
            w for w in data["warnings"] if "recommend" in w.lower()
        ]
        assert len(recommend_warnings) == 0

    def test_validate_strict_mode_with_valid_epic(self, fixture_epic_path):
        """In strict mode, phase warnings become errors but fixture phases are consistent."""
        data_normal = json.loads(spoq_validate_epic(str(fixture_epic_path), strict=False))
        data_strict = json.loads(spoq_validate_epic(str(fixture_epic_path), strict=True))
        # Strict should have at least as many errors as normal mode
        assert data_strict["summary"]["error_count"] >= data_normal["summary"]["error_count"]
        # Phase warnings in normal mode should move to errors in strict mode
        phase_warnings_normal = len([w for w in data_normal["warnings"] if "phase" in w.lower()])
        phase_errors_strict = len([e for e in data_strict["errors"] if "phase" in e.lower()])
        assert phase_errors_strict >= phase_warnings_normal

    def test_validate_nonexistent_path(self):
        raw = spoq_validate_epic("/nonexistent/epic/path")
        data = json.loads(raw)
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_validate_task_count_matches(self, fixture_epic_path):
        data = json.loads(spoq_validate_epic(str(fixture_epic_path)))
        assert data["summary"]["total_tasks"] == 4
        assert data["summary"]["valid_tasks"] == 4


# =============================================================================
# spoq_compute_waves
# =============================================================================


class TestComputeWaves:
    """Tests for the spoq_compute_waves tool."""

    def test_compute_waves_returns_valid_json(self, fixture_epic_path):
        raw = spoq_compute_waves(str(fixture_epic_path))
        data = json.loads(raw)
        assert "error" not in data

    def test_compute_waves_has_required_keys(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        assert "epic_name" in data
        assert "total_waves" in data
        assert "total_tasks" in data
        assert "waves" in data

    def test_compute_waves_fixture_produces_three_waves(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        assert data["total_waves"] == 3
        assert data["total_tasks"] == 4

    def test_compute_waves_wave_structure(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        for wave in data["waves"]:
            assert "wave" in wave
            assert "task_count" in wave
            assert "tasks" in wave
            for task in wave["tasks"]:
                assert "id" in task
                assert "title" in task
                assert "status" in task
                assert "priority" in task
                assert "dependencies" in task

    def test_compute_waves_wave0_has_two_tasks(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        wave0 = data["waves"][0]
        assert wave0["wave"] == 0
        assert wave0["task_count"] == 2
        task_ids = [t["id"] for t in wave0["tasks"]]
        assert "01-setup" in task_ids
        assert "02-core" in task_ids

    def test_compute_waves_wave1_has_api(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        wave1 = data["waves"][1]
        assert wave1["wave"] == 1
        assert wave1["task_count"] == 1
        assert wave1["tasks"][0]["id"] == "03-api"

    def test_compute_waves_wave2_has_tests(self, fixture_epic_path):
        data = json.loads(spoq_compute_waves(str(fixture_epic_path)))
        wave2 = data["waves"][2]
        assert wave2["wave"] == 2
        assert wave2["task_count"] == 1
        assert wave2["tasks"][0]["id"] == "04-tests"

    def test_compute_waves_with_critical_path(self, fixture_epic_path):
        data = json.loads(
            spoq_compute_waves(str(fixture_epic_path), critical_path=True)
        )
        assert "critical_path" in data
        cp = data["critical_path"]
        assert "tasks" in cp
        assert "length" in cp
        assert len(cp["tasks"]) >= 2

    def test_compute_waves_without_critical_path(self, fixture_epic_path):
        data = json.loads(
            spoq_compute_waves(str(fixture_epic_path), critical_path=False)
        )
        assert "critical_path" not in data

    def test_compute_waves_nonexistent_path(self):
        raw = spoq_compute_waves("/nonexistent/epic/path")
        data = json.loads(raw)
        assert "error" in data


# =============================================================================
# spoq_generate_execution_plan
# =============================================================================


class TestGenerateExecutionPlan:
    """Tests for the spoq_generate_execution_plan tool."""

    def test_returns_valid_json(self, fixture_epic_path):
        raw = spoq_generate_execution_plan(str(fixture_epic_path))
        data = json.loads(raw)
        assert "error" not in data

    def test_has_required_keys(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        assert "epic_name" in data
        assert "total_waves" in data
        assert "total_tasks" in data
        assert "actionable_tasks" in data
        assert "waves" in data

    def test_all_pending_tasks_are_actionable(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        # Fixture has all tasks pending, so all should be actionable
        assert data["actionable_tasks"] == data["total_tasks"]

    def test_wave_has_actionable_count(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        wave0 = data["waves"][0]
        assert "actionable_tasks" in wave0
        assert "total_tasks" in wave0
        assert wave0["actionable_tasks"] == wave0["total_tasks"]

    def test_task_has_actionable_flag(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        task = data["waves"][0]["tasks"][0]
        assert "actionable" in task
        assert task["actionable"] is True

    def test_task_includes_files_and_skills(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        task = data["waves"][0]["tasks"][0]
        assert "files_to_touch" in task
        assert "skills_required" in task

    def test_completed_task_not_actionable(self, tmp_epic_copy):
        """After marking a task completed, it should not be actionable."""
        import yaml

        # Mark 01-setup as completed
        task_file = tmp_epic_copy / "tasks" / "01-setup.yml"
        task_data = yaml.safe_load(task_file.read_text())
        task_data["status"] = "completed"
        task_file.write_text(yaml.dump(task_data, default_flow_style=False, sort_keys=False))

        data = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy)))
        # Find the completed task
        for wave in data["waves"]:
            for task in wave["tasks"]:
                if task["id"] == "01-setup":
                    assert task["actionable"] is False
                    break
        # Total actionable should be total - 1
        assert data["actionable_tasks"] == data["total_tasks"] - 1

    def test_includes_critical_path_by_default(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        assert "critical_path" in data
        cp = data["critical_path"]
        assert "tasks" in cp
        assert "length" in cp

    def test_critical_path_task_has_wave(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        cp_task = data["critical_path"]["tasks"][0]
        assert "wave" in cp_task
        assert "id" in cp_task
        assert "title" in cp_task

    def test_without_critical_path(self, fixture_epic_path):
        data = json.loads(
            spoq_generate_execution_plan(str(fixture_epic_path), include_critical_path=False)
        )
        assert "critical_path" not in data

    def test_nonexistent_path(self):
        data = json.loads(spoq_generate_execution_plan("/nonexistent/path"))
        assert "error" in data

    def test_task_includes_retry_count(self, fixture_epic_path):
        data = json.loads(spoq_generate_execution_plan(str(fixture_epic_path)))
        task = data["waves"][0]["tasks"][0]
        assert "retry_count" in task
        assert isinstance(task["retry_count"], int)


class TestExecutionPlanResume:
    """resume=True re-actions qa/failed carryover so all three executors
    (agent-, team-, workflow-execute) attempt failed tasks up to the 3-attempt
    cap before escalating to a human. Without resume, qa/failed are skipped."""

    @staticmethod
    def _set_status(epic_dir, task_filename, status, retry_count=None):
        import yaml

        task_file = epic_dir / "tasks" / task_filename
        task_data = yaml.safe_load(task_file.read_text())
        task_data["status"] = status
        if retry_count is not None:
            task_data["retry_count"] = retry_count
        task_file.write_text(yaml.dump(task_data, default_flow_style=False, sort_keys=False))

    @staticmethod
    def _find_task(data, task_id):
        for wave in data["waves"]:
            for task in wave["tasks"]:
                if task["id"] == task_id:
                    return task
        raise AssertionError(f"task {task_id} not found in plan")

    def test_failed_not_actionable_without_resume(self, tmp_epic_copy):
        self._set_status(tmp_epic_copy, "01-setup.yml", "failed", retry_count=3)
        data = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy)))
        assert self._find_task(data, "01-setup")["actionable"] is False

    def test_failed_actionable_with_resume(self, tmp_epic_copy):
        self._set_status(tmp_epic_copy, "01-setup.yml", "failed", retry_count=1)
        data = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy), resume=True))
        task = self._find_task(data, "01-setup")
        assert task["actionable"] is True
        # retry_count surfaces so the executor can enforce the 3-attempt cap.
        assert task["retry_count"] == 1

    def test_qa_actionable_only_with_resume(self, tmp_epic_copy):
        self._set_status(tmp_epic_copy, "01-setup.yml", "qa")
        plain = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy)))
        resumed = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy), resume=True))
        assert self._find_task(plain, "01-setup")["actionable"] is False
        assert self._find_task(resumed, "01-setup")["actionable"] is True

    def test_completed_never_actionable_even_with_resume(self, tmp_epic_copy):
        self._set_status(tmp_epic_copy, "01-setup.yml", "completed")
        data = json.loads(spoq_generate_execution_plan(str(tmp_epic_copy), resume=True))
        assert self._find_task(data, "01-setup")["actionable"] is False


# =============================================================================
# spoq_get_wave_tasks
# =============================================================================


class TestGetWaveTasks:
    """Tests for the spoq_get_wave_tasks tool."""

    def test_get_wave_0_returns_valid_json(self, fixture_epic_path):
        raw = spoq_get_wave_tasks(str(fixture_epic_path), wave=0)
        data = json.loads(raw)
        assert "error" not in data

    def test_get_wave_0_has_required_keys(self, fixture_epic_path):
        data = json.loads(spoq_get_wave_tasks(str(fixture_epic_path), wave=0))
        assert "wave" in data
        assert "task_count" in data
        assert "tasks" in data

    def test_get_wave_0_task_details(self, fixture_epic_path):
        data = json.loads(spoq_get_wave_tasks(str(fixture_epic_path), wave=0))
        assert data["wave"] == 0
        assert data["task_count"] == 2
        for task in data["tasks"]:
            assert "id" in task
            assert "title" in task
            assert "status" in task
            assert "dependencies" in task
            assert "files_to_touch" in task
            assert "skills_required" in task

    def test_get_wave_1_has_api_task(self, fixture_epic_path):
        data = json.loads(spoq_get_wave_tasks(str(fixture_epic_path), wave=1))
        assert data["task_count"] == 1
        task = data["tasks"][0]
        assert task["id"] == "03-api"
        assert "01-setup" in task["dependencies"]
        assert "02-core" in task["dependencies"]

    def test_get_wave_2_has_test_task(self, fixture_epic_path):
        data = json.loads(spoq_get_wave_tasks(str(fixture_epic_path), wave=2))
        assert data["task_count"] == 1
        assert data["tasks"][0]["id"] == "04-tests"

    def test_get_wave_invalid_number(self, fixture_epic_path):
        raw = spoq_get_wave_tasks(str(fixture_epic_path), wave=99)
        data = json.loads(raw)
        assert "error" in data
        assert "99" in data["error"]
        assert "Available waves" in data["error"]

    def test_get_wave_nonexistent_path(self):
        raw = spoq_get_wave_tasks("/nonexistent/epic/path", wave=0)
        data = json.loads(raw)
        assert "error" in data

    def test_get_wave_skills_and_files(self, fixture_epic_path):
        """Wave 0 tasks should include skills and files_to_touch."""
        data = json.loads(spoq_get_wave_tasks(str(fixture_epic_path), wave=0))
        task_ids = {t["id"]: t for t in data["tasks"]}
        setup = task_ids["01-setup"]
        assert "python" in setup["skills_required"]
        assert "src/config.py" in setup["files_to_touch"]


# =============================================================================
# spoq_analyze_dag
# =============================================================================


class TestAnalyzeDag:
    """Tests for the spoq_analyze_dag tool."""

    def test_analyze_dag_returns_valid_json(self, fixture_epic_path):
        raw = spoq_analyze_dag(str(fixture_epic_path))
        data = json.loads(raw)
        assert "error" not in data

    def test_analyze_dag_has_required_keys(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        assert "epic_name" in data
        assert "total_tasks" in data
        assert "critical_path" in data
        assert "parallelism" in data

    def test_analyze_dag_critical_path_structure(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        cp = data["critical_path"]
        assert "tasks" in cp
        assert "length" in cp
        assert "task_details" in cp
        assert len(cp["tasks"]) >= 2
        assert cp["length"] == len(cp["tasks"])

    def test_analyze_dag_critical_path_details(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        cp = data["critical_path"]
        for detail in cp["task_details"]:
            assert "id" in detail
            assert "title" in detail
            assert "wave" in detail

    def test_analyze_dag_parallelism_structure(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        par = data["parallelism"]
        assert "wave_count" in par
        assert "max_parallelism" in par
        assert "wave0_tasks" in par
        assert "wave0_ratio" in par
        assert "waves" in par

    def test_analyze_dag_parallelism_values(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        par = data["parallelism"]
        assert par["wave_count"] == 3
        assert par["max_parallelism"] == 2
        assert par["wave0_tasks"] == 2
        assert par["wave0_ratio"] == 0.5

    def test_analyze_dag_has_no_effort_section(self, fixture_epic_path):
        """Effort estimation was removed from SPOQ — analyze_dag must not emit it."""
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        assert "effort" not in data

    def test_analyze_dag_nonexistent_path(self):
        raw = spoq_analyze_dag("/nonexistent/epic/path")
        data = json.loads(raw)
        assert "error" in data

    def test_analyze_dag_total_tasks(self, fixture_epic_path):
        data = json.loads(spoq_analyze_dag(str(fixture_epic_path)))
        assert data["total_tasks"] == 4


# =============================================================================
# spoq_complete_epic
# =============================================================================


def _complete_all_tasks(epic_dir: Path) -> None:
    """Set every task in an epic to 'completed' status."""
    import yaml

    for yml in sorted((epic_dir / "tasks").glob("*.yml")):
        data = yaml.safe_load(yml.read_text())
        data["status"] = "completed"
        yml.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


class TestCompleteEpic:
    """Tests for the spoq_complete_epic tool."""

    def test_moves_epic_to_complete(self, tmp_epic_copy):
        _complete_all_tasks(tmp_epic_copy)
        # Set up active/complete directory structure
        active_dir = tmp_epic_copy.parent  # tmp_path/test-epic -> tmp_path
        epics_dir = active_dir
        complete_dir = epics_dir / "complete"

        # Rearrange so epic is inside an active/ directory
        import shutil
        proper_active = epics_dir / "active"
        proper_active.mkdir()
        dest = proper_active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        data = json.loads(spoq_complete_epic(str(dest)))
        assert "error" not in data
        assert data["tasks_completed"] == 4
        assert data["tasks_total"] == 4
        assert not dest.exists(), "Original should be gone"
        assert Path(data["new_path"]).exists(), "Should exist at new location"
        assert "complete" in data["new_path"]

    def test_rejects_incomplete_epic(self, tmp_epic_copy):
        """Refuses to archive when tasks remain incomplete."""
        data = json.loads(spoq_complete_epic(str(tmp_epic_copy)))
        assert "error" in data
        assert "not completed" in data["error"]
        assert "incomplete_tasks" in data
        assert tmp_epic_copy.exists(), "Epic should not have been moved"

    def test_force_moves_incomplete_epic(self, tmp_epic_copy):
        """Force flag allows archiving incomplete epics."""
        active = tmp_epic_copy.parent / "active"
        active.mkdir()
        import shutil
        dest = active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        data = json.loads(spoq_complete_epic(str(dest), force=True))
        assert "error" not in data
        assert data["tasks_completed"] == 0
        assert data["tasks_total"] == 4
        assert not dest.exists()

    def test_rejects_duplicate_destination(self, tmp_epic_copy):
        """Rejects move when complete/ already has a directory with same name."""
        _complete_all_tasks(tmp_epic_copy)
        import shutil
        active = tmp_epic_copy.parent / "active"
        complete = tmp_epic_copy.parent / "complete"
        active.mkdir()
        complete.mkdir()
        (complete / tmp_epic_copy.name).mkdir()  # pre-existing
        dest = active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        data = json.loads(spoq_complete_epic(str(dest)))
        assert "error" in data
        assert "already exists" in data["error"]

    def test_nonexistent_path(self):
        data = json.loads(spoq_complete_epic("/nonexistent/epic"))
        assert "error" in data

    def test_updates_map_on_completion(self, tmp_map_copy):
        """Completing an epic also updates the map file status."""
        map_dir, epics_dir = tmp_map_copy
        epic_dir = epics_dir / "alpha-service"

        _complete_all_tasks(epic_dir)

        # Move epic into active/complete structure
        import shutil
        active = epic_dir.parent / "active"
        active.mkdir(exist_ok=True)
        dest = active / epic_dir.name
        shutil.move(str(epic_dir), str(dest))

        data = json.loads(spoq_complete_epic(
            str(dest),
            map_path=str(map_dir),
        ))
        assert "error" not in data
        assert data["map_update"] is not None
        assert "error" not in data["map_update"]
        assert "Complete" in data["map_update"]["new_status"]

        # Verify map file was actually changed
        map_md = map_dir / "MAP.md"
        content = map_md.read_text()
        assert "pending" not in content.split("### alpha-service")[1].split("###")[0].lower() or \
               "Complete" in content.split("### alpha-service")[1].split("###")[0]

    def test_updates_roadmap_on_completion(self, tmp_epic_copy, monkeypatch):
        """Completing an epic updates ROADMAP.yml tier to complete."""
        import yaml

        _complete_all_tasks(tmp_epic_copy)
        import shutil
        active = tmp_epic_copy.parent / "active"
        active.mkdir()
        dest = active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        # Create spoq dir with ROADMAP.yml containing the epic slug
        spoq_dir = dest.parent.parent / "spoq"
        spoq_dir.mkdir(parents=True)
        roadmap_data = {
            "version": 1,
            "updated_at": "",
            "epics": [
                {"slug": "test-epic", "title": "Test Epic", "tier": "active", "status": "in_progress"},
            ],
        }
        (spoq_dir / "ROADMAP.yml").write_text(
            yaml.dump(roadmap_data, default_flow_style=False, sort_keys=False)
        )

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: dest.parent.parent)

        data = json.loads(spoq_complete_epic(str(dest)))
        assert "error" not in data
        assert data["roadmap_updated"] is True

        # Verify ROADMAP.yml was persisted with tier=complete and completed_date
        saved = yaml.safe_load((spoq_dir / "ROADMAP.yml").read_text())
        entry = next(e for e in saved["epics"] if e["slug"] == "test-epic")
        assert entry["tier"] == "complete"
        assert entry["completed_date"] is not None

    def test_roadmap_missing_no_error(self, tmp_epic_copy, monkeypatch):
        """When ROADMAP.yml does not exist, completion succeeds with roadmap_updated=False."""
        _complete_all_tasks(tmp_epic_copy)
        import shutil
        active = tmp_epic_copy.parent / "active"
        active.mkdir()
        dest = active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        # Point project_root at a directory with no spoq/ROADMAP.yml
        fake_root = dest.parent.parent
        (fake_root / "spoq").mkdir(parents=True, exist_ok=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: fake_root)

        data = json.loads(spoq_complete_epic(str(dest)))
        assert "error" not in data
        assert data["roadmap_updated"] is False

    def test_roadmap_slug_not_found(self, tmp_epic_copy, monkeypatch):
        """When epic slug is not in ROADMAP.yml, roadmap_updated is False."""
        import yaml

        _complete_all_tasks(tmp_epic_copy)
        import shutil
        active = tmp_epic_copy.parent / "active"
        active.mkdir()
        dest = active / tmp_epic_copy.name
        shutil.move(str(tmp_epic_copy), str(dest))

        spoq_dir = dest.parent.parent / "spoq"
        spoq_dir.mkdir(parents=True)
        roadmap_data = {
            "version": 1,
            "updated_at": "",
            "epics": [
                {"slug": "other-epic", "title": "Other", "tier": "active", "status": "pending"},
            ],
        }
        (spoq_dir / "ROADMAP.yml").write_text(
            yaml.dump(roadmap_data, default_flow_style=False, sort_keys=False)
        )

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: dest.parent.parent)

        data = json.loads(spoq_complete_epic(str(dest)))
        assert "error" not in data
        assert data["roadmap_updated"] is False

        # Verify original entry was not modified
        saved = yaml.safe_load((spoq_dir / "ROADMAP.yml").read_text())
        entry = next(e for e in saved["epics"] if e["slug"] == "other-epic")
        assert entry["tier"] == "active"


# =============================================================================
# spoq_list_epics
# =============================================================================


class TestListEpics:
    """Tests for the spoq_list_epics tool."""

    def test_list_returns_valid_json(self, tmp_path, monkeypatch):
        """List returns well-formed JSON with all tier keys."""
        epics_base = tmp_path / "spoq" / "epics"
        (epics_base / "backlog" / "epic-a").mkdir(parents=True)
        (epics_base / "active" / "epic-b").mkdir(parents=True)
        (epics_base / "complete" / "epic-c").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics())
        assert "error" not in data
        assert "backlog" in data
        assert "active" in data
        assert "complete" in data
        assert "counts" in data

    def test_list_counts_are_correct(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        (epics_base / "backlog" / "b1").mkdir(parents=True)
        (epics_base / "backlog" / "b2").mkdir(parents=True)
        (epics_base / "active" / "a1").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics())
        assert data["counts"]["backlog"] == 2
        assert data["counts"]["active"] == 1
        assert data["counts"]["complete"] == 0
        assert data["counts"]["total"] == 3

    def test_list_filter_by_tier(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        (epics_base / "backlog" / "b1").mkdir(parents=True)
        (epics_base / "active" / "a1").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics(tier="backlog"))
        assert data["backlog"] == ["b1"]
        assert data["active"] == []
        assert data["counts"]["backlog"] == 1
        assert data["counts"]["active"] == 0

    def test_list_invalid_tier(self, tmp_path, monkeypatch):
        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics(tier="invalid"))
        assert "error" in data

    def test_list_include_stats(self, tmp_path, monkeypatch):
        import yaml

        epics_base = tmp_path / "spoq" / "epics"
        tasks_dir = epics_base / "active" / "my-epic" / "tasks"
        tasks_dir.mkdir(parents=True)

        # Two tasks: one completed, one pending
        (tasks_dir / "01.yml").write_text(yaml.dump({"id": "01", "status": "completed"}))
        (tasks_dir / "02.yml").write_text(yaml.dump({"id": "02", "status": "pending"}))

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics(include_stats=True))
        assert len(data["active"]) == 1
        entry = data["active"][0]
        assert entry["slug"] == "my-epic"
        assert entry["tasks_total"] == 2
        assert entry["tasks_completed"] == 1
        assert entry["progress"] == 0.5

    def test_list_empty_dirs(self, tmp_path, monkeypatch):
        """No epic directories exist at all."""
        (tmp_path / "spoq" / "epics").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics())
        assert data["counts"]["total"] == 0

    def test_list_skips_files(self, tmp_path, monkeypatch):
        """Non-directory entries in tier dirs are ignored."""
        epics_base = tmp_path / "spoq" / "epics"
        (epics_base / "active").mkdir(parents=True)
        (epics_base / "active" / "not-a-dir.txt").write_text("hello")
        (epics_base / "active" / "real-epic").mkdir()

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_list_epics())
        assert data["active"] == ["real-epic"]


# =============================================================================
# spoq_promote
# =============================================================================


class TestPromote:
    """Tests for the spoq_promote tool."""

    def test_promote_backlog_to_active(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "my-epic"
        src.mkdir(parents=True)
        (src / "EPIC.md").write_text("# Test")

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" not in data
        assert data["old_tier"] == "backlog"
        assert data["new_tier"] == "active"
        assert data["slug"] == "my-epic"
        assert not src.exists()
        assert Path(data["new_path"]).exists()

    def test_promote_active_to_complete_warns(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" not in data
        assert data["new_tier"] == "complete"
        assert "warnings" in data
        assert any("spoq_complete_epic" in w for w in data["warnings"])

    def test_promote_already_at_highest(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "complete" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" in data
        assert "highest" in data["error"].lower()

    def test_promote_destination_exists(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "my-epic"
        src.mkdir(parents=True)
        (epics_base / "active" / "my-epic").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" in data
        assert "already exists" in data["error"].lower()

    def test_promote_nonexistent_path(self, tmp_path, monkeypatch):
        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote("/nonexistent/backlog/my-epic"))
        assert "error" in data

    def test_promote_map_resource_type(self, tmp_path, monkeypatch):
        maps_base = tmp_path / "spoq" / "maps"
        src = maps_base / "backlog" / "my-map"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src), resource_type="map"))
        assert "error" not in data
        assert data["new_tier"] == "active"
        assert not src.exists()
        dest = maps_base / "active" / "my-map"
        assert dest.exists()

    def test_promote_no_tier_in_path(self, tmp_path, monkeypatch):
        src = tmp_path / "no-tier-here" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" in data
        assert "determine tier" in data["error"].lower()


# =============================================================================
# spoq_demote
# =============================================================================


class TestDemote:
    """Tests for the spoq_demote tool."""

    def test_demote_active_to_backlog(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "my-epic"
        src.mkdir(parents=True)
        (src / "EPIC.md").write_text("# Test")

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" not in data
        assert data["old_tier"] == "active"
        assert data["new_tier"] == "backlog"
        assert data["slug"] == "my-epic"
        assert not src.exists()
        assert Path(data["new_path"]).exists()

    def test_demote_complete_to_active(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "complete" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" not in data
        assert data["old_tier"] == "complete"
        assert data["new_tier"] == "active"

    def test_demote_already_at_lowest(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" in data
        assert "lowest" in data["error"].lower()

    def test_demote_destination_exists(self, tmp_path, monkeypatch):
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "my-epic"
        src.mkdir(parents=True)
        (epics_base / "backlog" / "my-epic").mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" in data
        assert "already exists" in data["error"].lower()

    def test_demote_nonexistent_path(self, tmp_path, monkeypatch):
        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote("/nonexistent/active/my-epic"))
        assert "error" in data

    def test_demote_map_resource_type(self, tmp_path, monkeypatch):
        maps_base = tmp_path / "spoq" / "maps"
        src = maps_base / "active" / "my-map"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src), resource_type="map"))
        assert "error" not in data
        assert data["new_tier"] == "backlog"
        assert not src.exists()
        dest = maps_base / "backlog" / "my-map"
        assert dest.exists()

    def test_demote_no_tier_in_path(self, tmp_path, monkeypatch):
        src = tmp_path / "no-tier-here" / "my-epic"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" in data
        assert "determine tier" in data["error"].lower()

    def test_promote_then_demote_roundtrip(self, tmp_path, monkeypatch):
        """Promote and demote return to original location."""
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "roundtrip-epic"
        src.mkdir(parents=True)
        (src / "EPIC.md").write_text("# Roundtrip")

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        # Promote backlog -> active
        promo = json.loads(spoq_promote(str(src)))
        assert promo["new_tier"] == "active"

        # Demote active -> backlog
        demo = json.loads(spoq_demote(promo["new_path"]))
        assert demo["new_tier"] == "backlog"
        assert Path(demo["new_path"]).exists()
        assert (Path(demo["new_path"]) / "EPIC.md").exists()

    def test_promote_demote_preserves_contents(self, tmp_path, monkeypatch):
        """Full promote/demote cycle preserves every file and its content."""
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "content-check"
        tasks_dir = src / "tasks"
        tasks_dir.mkdir(parents=True)

        epic_content = "# Content Check\n\nThis text must survive the round-trip."
        task_content = "id: 01-thing\ntitle: Thing\nstatus: pending\n"
        (src / "EPIC.md").write_text(epic_content)
        (tasks_dir / "01-thing.yml").write_text(task_content)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        # Promote backlog -> active
        promo = json.loads(spoq_promote(str(src)))
        assert "error" not in promo
        promoted_path = Path(promo["new_path"])
        assert (promoted_path / "EPIC.md").read_text() == epic_content
        assert (promoted_path / "tasks" / "01-thing.yml").read_text() == task_content

        # Demote active -> backlog
        demo = json.loads(spoq_demote(promo["new_path"]))
        assert "error" not in demo
        demoted_path = Path(demo["new_path"])
        assert (demoted_path / "EPIC.md").read_text() == epic_content
        assert (demoted_path / "tasks" / "01-thing.yml").read_text() == task_content


# =============================================================================
# Promote/Demote with ROADMAP.yml integration
# =============================================================================


class TestPromoteRoadmapIntegration:
    """Tests that promote updates ROADMAP.yml tier."""

    def test_promote_updates_roadmap(self, tmp_path, monkeypatch):
        """Promoting an epic also updates its tier in ROADMAP.yml."""
        import yaml

        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "my-epic"
        src.mkdir(parents=True)

        spoq_dir = tmp_path / "spoq"
        roadmap = {
            "version": 1, "updated_at": "",
            "epics": [{"slug": "my-epic", "title": "My Epic", "tier": "backlog", "status": "pending"}],
        }
        (spoq_dir / "ROADMAP.yml").write_text(yaml.dump(roadmap, default_flow_style=False, sort_keys=False))

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" not in data
        assert data["roadmap_updated"] is True

        saved = yaml.safe_load((spoq_dir / "ROADMAP.yml").read_text())
        entry = next(e for e in saved["epics"] if e["slug"] == "my-epic")
        assert entry["tier"] == "active"

    def test_promote_without_roadmap_succeeds(self, tmp_path, monkeypatch):
        """Promotion works when no ROADMAP.yml exists."""
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "backlog" / "no-roadmap"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_promote(str(src)))
        assert "error" not in data
        assert data["roadmap_updated"] is False


class TestDemoteRoadmapIntegration:
    """Tests that demote updates ROADMAP.yml tier."""

    def test_demote_updates_roadmap(self, tmp_path, monkeypatch):
        """Demoting an epic also updates its tier in ROADMAP.yml."""
        import yaml

        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "my-epic"
        src.mkdir(parents=True)

        spoq_dir = tmp_path / "spoq"
        roadmap = {
            "version": 1, "updated_at": "",
            "epics": [{"slug": "my-epic", "title": "My Epic", "tier": "active", "status": "in_progress"}],
        }
        (spoq_dir / "ROADMAP.yml").write_text(yaml.dump(roadmap, default_flow_style=False, sort_keys=False))

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" not in data
        assert data["roadmap_updated"] is True

        saved = yaml.safe_load((spoq_dir / "ROADMAP.yml").read_text())
        entry = next(e for e in saved["epics"] if e["slug"] == "my-epic")
        assert entry["tier"] == "backlog"

    def test_demote_without_roadmap_succeeds(self, tmp_path, monkeypatch):
        """Demotion works when no ROADMAP.yml exists."""
        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "no-roadmap"
        src.mkdir(parents=True)

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" not in data
        assert data["roadmap_updated"] is False

    def test_demote_slug_not_in_roadmap(self, tmp_path, monkeypatch):
        """Demotion succeeds even if slug is not in ROADMAP.yml."""
        import yaml

        epics_base = tmp_path / "spoq" / "epics"
        src = epics_base / "active" / "unlisted"
        src.mkdir(parents=True)

        spoq_dir = tmp_path / "spoq"
        roadmap = {
            "version": 1, "updated_at": "",
            "epics": [{"slug": "other", "title": "Other", "tier": "active", "status": "pending"}],
        }
        (spoq_dir / "ROADMAP.yml").write_text(yaml.dump(roadmap, default_flow_style=False, sort_keys=False))

        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_path)

        data = json.loads(spoq_demote(str(src)))
        assert "error" not in data
        assert data["roadmap_updated"] is False


# =============================================================================
# spoq_list_epics with ROADMAP fixture
# =============================================================================


class TestListEpicsWithRoadmap:
    """Tests for list_epics using the tmp_spoq_dir fixture."""

    def test_list_from_fixture_structure(self, tmp_spoq_dir, monkeypatch):
        """list_epics discovers all 3 tiers from the fixture."""
        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_spoq_dir.parent)

        data = json.loads(spoq_list_epics())
        assert data["counts"]["total"] == 3
        assert data["backlog"] == ["plan-feature"]
        assert data["active"] == ["build-feature"]
        assert data["complete"] == ["ship-feature"]

    def test_list_filter_active_from_fixture(self, tmp_spoq_dir, monkeypatch):
        """Filtering active tier returns only the active epic."""
        import spoq_server.epic_tools as et
        monkeypatch.setattr(et, "project_root", lambda: tmp_spoq_dir.parent)

        data = json.loads(spoq_list_epics(tier="active"))
        assert data["active"] == ["build-feature"]
        assert data["backlog"] == []
        assert data["complete"] == []
