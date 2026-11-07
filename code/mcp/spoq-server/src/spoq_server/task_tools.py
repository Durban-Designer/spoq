"""Task management MCP tools for SPOQ.

Persistence is delegated to :class:`spoq_server.stores.fs.FsStore`; this module
holds tool orchestration only — no direct ``yaml``/``Path``/``glob``/``shutil``
calls remain.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from spoq_server.server import mcp


def _store():
    """Return the single shared store instance selected at server init.

    Resolved at call time (not import time) so tests that reload the server
    under a patched ``SPOQ_STORE`` observe the active backend. The instance is
    injected by the server — this module never constructs its own store.
    """
    from spoq_server.server import get_store

    return get_store()


VALID_STATUSES = {"pending", "in_progress", "qa", "rework", "completed", "failed"}


def _find_task_file(epic_path: Path, task_id: str):
    """Find task YAML file by task_id prefix match.

    Thin compatibility shim retained for any in-process caller; the prefix-match
    logic now lives in :meth:`FsStore.find_task`.
    """
    return _store().find_task(epic_path, task_id)


@mcp.tool()
def spoq_get_task(epic_path: str, task_id: str) -> str:
    """Get full details for a single task by ID.

    Args:
        epic_path: Path to epic directory.
        task_id: Task identifier (e.g., "01-setup").

    Returns JSON with the task's full YAML data.
    """
    try:
        store = _store()
        resolved = store._resolve(epic_path)

        if not resolved.exists():
            return json.dumps({"error": f"Epic directory not found: {resolved}"})

        task = store.get_task(epic_path, task_id)
        if task is None:
            return json.dumps({"error": f"Task '{task_id}' not found in epic at {resolved}"})

        task.pop("_source_file", None)
        return json.dumps(task, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_update_task_status(epic_path: str, task_id: str, status: str, notes: str = "") -> str:
    """Update a task's status in-place in its YAML file.

    Args:
        epic_path: Path to epic directory.
        task_id: Task identifier.
        status: New status. Must be one of: pending, in_progress, qa, rework, completed, failed.
        notes: Optional progress notes to append.

    Returns JSON confirmation with updated fields.
    """
    try:
        if status not in VALID_STATUSES:
            return json.dumps({
                "error": f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            })

        store = _store()
        resolved = store._resolve(epic_path)
        if not resolved.exists():
            return json.dumps({"error": f"Epic directory not found: {resolved}"})

        current = store.read_task_raw(epic_path, task_id)
        if current is None:
            return json.dumps({"error": f"Task '{task_id}' not found in epic at {resolved}"})

        old_status = current.get("status", "unknown")

        last_update = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = {"status": status, "last_update": last_update}

        if notes:
            existing_notes = current.get("progress_notes", "")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            new_note = f"[{timestamp}] {notes}"
            if existing_notes:
                fields["progress_notes"] = f"{existing_notes}\n{new_note}"
            else:
                fields["progress_notes"] = new_note

        store.update_task(epic_path, task_id, fields)

        result = {
            "task_id": task_id,
            "old_status": old_status,
            "new_status": status,
            "last_update": last_update,
            "notes_added": bool(notes),
        }

        # Signal when the entire epic is now complete
        if status == "completed":
            all_tasks = store.load_tasks(epic_path)
            valid = [t for t in all_tasks if "error" not in t]
            total = len(valid)
            done = sum(1 for t in valid if t.get("status") == "completed")
            result["epic_tasks_completed"] = done
            result["epic_tasks_total"] = total
            if done == total:
                result["epic_complete"] = True

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_list_task_statuses(epic_path: str) -> str:
    """List all task statuses in an epic as a compact map.

    Args:
        epic_path: Path to epic directory.

    Returns JSON with {task_id: status} mapping and status counts.
    """
    try:
        store = _store()
        resolved = store._resolve(epic_path)

        if not resolved.exists():
            return json.dumps({"error": f"Epic directory not found: {resolved}"})

        tasks = store.load_tasks(epic_path)

        statuses = {}
        counts = {}
        for task in tasks:
            if "error" in task:
                continue
            tid = task.get("id", "unknown")
            status = task.get("status", "pending")
            statuses[tid] = status
            counts[status] = counts.get(status, 0) + 1

        return json.dumps({
            "tasks": statuses,
            "counts": counts,
            "total": len(statuses),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
