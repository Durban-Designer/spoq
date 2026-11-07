"""Unit tests for task management MCP tools."""

import json
import pytest


class TestGetTask:
    def test_happy_path(self, fixture_epic_path):
        from spoq_server.task_tools import spoq_get_task
        result = json.loads(spoq_get_task(str(fixture_epic_path), "01-setup"))
        assert "error" not in result
        assert result["id"] == "01-setup"
        assert result["title"] == "Project Setup and Config Parser"
        assert result["status"] == "pending"

    def test_missing_task(self, fixture_epic_path):
        from spoq_server.task_tools import spoq_get_task
        result = json.loads(spoq_get_task(str(fixture_epic_path), "99-nonexistent"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_invalid_epic_path(self):
        from spoq_server.task_tools import spoq_get_task
        result = json.loads(spoq_get_task("/nonexistent/path", "01-setup"))
        assert "error" in result


class TestUpdateTaskStatus:
    def test_update_status(self, tmp_epic_copy):
        from spoq_server.task_tools import spoq_update_task_status
        result = json.loads(spoq_update_task_status(str(tmp_epic_copy), "01-setup", "in_progress"))
        assert "error" not in result
        assert result["old_status"] == "pending"
        assert result["new_status"] == "in_progress"
        assert "last_update" in result

    def test_update_with_notes(self, tmp_epic_copy):
        from spoq_server.task_tools import spoq_update_task_status
        result = json.loads(spoq_update_task_status(
            str(tmp_epic_copy), "01-setup", "in_progress", "Started working on config parser"
        ))
        assert result["notes_added"] is True

    def test_invalid_status(self, tmp_epic_copy):
        from spoq_server.task_tools import spoq_update_task_status
        result = json.loads(spoq_update_task_status(str(tmp_epic_copy), "01-setup", "invalid_status"))
        assert "error" in result
        assert "Invalid status" in result["error"]

    def test_file_actually_changes(self, tmp_epic_copy):
        """Verify the YAML file on disk is actually modified."""
        from spoq_server.task_tools import spoq_update_task_status
        import yaml

        task_file = tmp_epic_copy / "tasks" / "01-setup.yml"
        before = yaml.safe_load(task_file.read_text())
        assert before["status"] == "pending"

        spoq_update_task_status(str(tmp_epic_copy), "01-setup", "completed")

        after = yaml.safe_load(task_file.read_text())
        assert after["status"] == "completed"
        assert "last_update" in after

    def test_missing_task(self, tmp_epic_copy):
        from spoq_server.task_tools import spoq_update_task_status
        result = json.loads(spoq_update_task_status(str(tmp_epic_copy), "99-missing", "completed"))
        assert "error" in result


class TestListTaskStatuses:
    def test_lists_all_tasks(self, fixture_epic_path):
        from spoq_server.task_tools import spoq_list_task_statuses
        result = json.loads(spoq_list_task_statuses(str(fixture_epic_path)))
        assert "error" not in result
        assert result["total"] == 4
        assert "01-setup" in result["tasks"]
        assert "04-tests" in result["tasks"]

    def test_status_counts(self, fixture_epic_path):
        from spoq_server.task_tools import spoq_list_task_statuses
        result = json.loads(spoq_list_task_statuses(str(fixture_epic_path)))
        assert result["counts"]["pending"] == 4

    def test_reflects_updates(self, tmp_epic_copy):
        from spoq_server.task_tools import spoq_update_task_status, spoq_list_task_statuses
        spoq_update_task_status(str(tmp_epic_copy), "01-setup", "completed")
        result = json.loads(spoq_list_task_statuses(str(tmp_epic_copy)))
        assert result["tasks"]["01-setup"] == "completed"
        assert result["counts"].get("completed") == 1
        assert result["counts"].get("pending") == 3

    def test_invalid_epic_path(self):
        from spoq_server.task_tools import spoq_list_task_statuses
        result = json.loads(spoq_list_task_statuses("/nonexistent/path"))
        assert "error" in result


class TestEpicCompletionSignal:
    """spoq_update_task_status signals when all tasks reach 'completed'."""

    def test_signals_epic_complete(self, tmp_epic_copy):
        """Completing the last task returns epic_complete=True."""
        from spoq_server.task_tools import spoq_update_task_status

        # Complete all four tasks
        for task_id in ["01-setup", "02-core", "03-api", "04-tests"]:
            result = json.loads(spoq_update_task_status(
                str(tmp_epic_copy), task_id, "completed",
            ))
            assert "error" not in result

        # The final update should signal full completion
        assert result["epic_complete"] is True
        assert result["epic_tasks_completed"] == 4
        assert result["epic_tasks_total"] == 4

    def test_no_signal_when_incomplete(self, tmp_epic_copy):
        """Completing one task does not signal epic completion."""
        from spoq_server.task_tools import spoq_update_task_status

        result = json.loads(spoq_update_task_status(
            str(tmp_epic_copy), "01-setup", "completed",
        ))
        assert "error" not in result
        assert result.get("epic_complete") is not True
        assert result["epic_tasks_completed"] == 1
        assert result["epic_tasks_total"] == 4

    def test_no_signal_for_non_completed_status(self, tmp_epic_copy):
        """Non-completed status transitions don't include epic counts."""
        from spoq_server.task_tools import spoq_update_task_status

        result = json.loads(spoq_update_task_status(
            str(tmp_epic_copy), "01-setup", "in_progress",
        ))
        assert "error" not in result
        assert "epic_complete" not in result
        assert "epic_tasks_completed" not in result
