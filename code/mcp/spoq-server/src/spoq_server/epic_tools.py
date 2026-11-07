"""Epic management MCP tools for SPOQ.

Persistence (epic/task reads, tier-transition directory moves) is delegated to
:class:`spoq_server.stores.fs.FsStore`; ROADMAP and MAP.md updates still flow
through ``roadmap_utils`` / ``map_utils`` (those backends are extracted in a
later task of this epic). This module holds no direct ``yaml``/``Path``/``glob``/
``shutil`` calls.
"""

import json
from datetime import datetime, timezone

from spoq_server.server import mcp, project_root
from spoq_server import epic_utils
from spoq_server import roadmap_utils


def _store():
    """Return the single shared store instance selected at server init.

    Resolved at call time (not import time) so tests that reload the server
    under a patched ``SPOQ_STORE`` observe the active backend. The instance is
    injected by the server — this module never constructs its own store.

    The module-local :func:`project_root` reference is handed to ``get_store``
    as the fs-mode root resolver, so a test that monkeypatches
    ``epic_tools.project_root`` to a tmpdir gets a store anchored there.
    """
    from spoq_server.server import get_store

    return get_store(project_root)


@mcp.tool()
def spoq_parse_epic(epic_path: str) -> str:
    """Parse an epic directory and return its metadata, tasks, and stats as JSON.

    Args:
        epic_path: Path to epic directory (absolute or relative to project root).
                   Example: "spoq/epics/active/spoq-mcp-server"
    """
    try:
        store = _store()
        result = store.load_epic(epic_path)
        # Remove _source_file from tasks for cleaner output
        for task in result.get("tasks", []):
            task.pop("_source_file", None)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_validate_epic(
    epic_path: str, strict: bool = False, require_frontmatter: bool = False
) -> str:
    """Validate an epic's structure, dependencies, and phases.

    Args:
        epic_path: Path to epic directory.
        strict: If true, warnings become errors.
        require_frontmatter: If true, a missing EPIC.md frontmatter fence is a
            hard error instead of a warning. (Present-but-invalid frontmatter is
            always an error regardless of this flag.)

    Returns JSON with errors[], warnings[], and summary.
    """
    try:
        eu = epic_utils
        store = _store()
        resolved = store._resolve(epic_path)

        if not resolved.exists():
            return json.dumps({"error": f"Epic directory not found: {resolved}"})

        errors = []
        warnings = []

        # Validate EPIC.md leading frontmatter against the closed schema.
        fm_errors, fm_warnings = eu.validate_epic_frontmatter(
            resolved, require_present=require_frontmatter or strict
        )
        errors.extend(fm_errors)
        warnings.extend(fm_warnings)

        # Validate EPIC.md structure
        md_errors = eu.validate_epic_md_structure(resolved)
        # Treat "recommend" messages as warnings unless strict
        for err in md_errors:
            if "recommend" in err.lower() and not strict:
                warnings.append(err)
            else:
                errors.append(err)

        # Load and validate tasks
        tasks = store.load_tasks(epic_path)
        valid_tasks = [t for t in tasks if "error" not in t]
        error_tasks = [t for t in tasks if "error" in t]

        for t in error_tasks:
            errors.append(t["error"])

        for task in valid_tasks:
            source = store._resolve(task.get("_source_file", "unknown"))
            task_errors = eu.validate_task_yaml_structure(task, source)
            errors.extend(task_errors)

        # Validate dependencies
        errors.extend(eu.validate_dependencies(valid_tasks))

        # Detect cycles
        cycle_errors = eu.detect_cycles(valid_tasks)
        errors.extend(cycle_errors)

        # Validate phases
        phase_errors = eu.validate_phases(valid_tasks)
        if strict:
            errors.extend(phase_errors)
        else:
            warnings.extend(phase_errors)

        summary = {
            "valid": len(errors) == 0,
            "total_tasks": len(tasks),
            "valid_tasks": len(valid_tasks),
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

        return json.dumps({"errors": errors, "warnings": warnings, "summary": summary})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_compute_waves(epic_path: str, critical_path: bool = False) -> str:
    """Compute execution waves from task dependency graph.

    Args:
        epic_path: Path to epic directory.
        critical_path: Include critical path analysis in output.

    Returns JSON with waves[], each containing task details.
    """
    try:
        eu = epic_utils
        store = _store()
        result = store.load_epic(epic_path)

        if "error" in result:
            return json.dumps(result)

        tasks = result["tasks"]
        if not tasks:
            return json.dumps({"error": "No tasks found in epic"})

        waves_map = eu.compute_waves(tasks)
        wave_groups = eu.group_waves(waves_map)
        task_map = {t["id"]: t for t in tasks}

        waves = []
        for wave_num in sorted(wave_groups.keys()):
            task_ids = wave_groups[wave_num]
            wave_tasks = []
            for tid in sorted(task_ids):
                task = task_map.get(tid, {})
                wave_tasks.append({
                    "id": tid,
                    "title": task.get("title", tid),
                    "status": task.get("status", "pending"),
                    "priority": task.get("priority", "medium"),
                    "dependencies": task.get("dependencies", []),
                })
            waves.append({
                "wave": wave_num,
                "task_count": len(wave_tasks),
                "tasks": wave_tasks,
            })

        output = {
            "epic_name": result.get("epic_name", "unknown"),
            "total_waves": len(waves),
            "total_tasks": len(tasks),
            "waves": waves,
        }

        if critical_path:
            cp_tasks, _ = eu.compute_critical_path(tasks, waves_map)
            output["critical_path"] = {
                "tasks": cp_tasks,
                "length": len(cp_tasks),
            }

        return json.dumps(output, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_get_wave_tasks(epic_path: str, wave: int) -> str:
    """Get tasks for a specific wave number.

    Args:
        epic_path: Path to epic directory.
        wave: Wave number (0-indexed).

    Returns JSON with the wave's tasks only.
    """
    try:
        eu = epic_utils
        store = _store()
        result = store.load_epic(epic_path)

        if "error" in result:
            return json.dumps(result)

        tasks = result["tasks"]
        waves_map = eu.compute_waves(tasks)
        wave_groups = eu.group_waves(waves_map)

        if wave not in wave_groups:
            available = sorted(wave_groups.keys())
            return json.dumps({
                "error": f"Wave {wave} not found. Available waves: {available}"
            })

        task_map = {t["id"]: t for t in tasks}
        wave_tasks = []
        for tid in sorted(wave_groups[wave]):
            task = task_map.get(tid, {})
            wave_tasks.append({
                "id": tid,
                "title": task.get("title", tid),
                "status": task.get("status", "pending"),
                "dependencies": task.get("dependencies", []),
                "files_to_touch": task.get("files_to_touch", []),
                "skills_required": task.get("skills_required", []),
            })

        return json.dumps({
            "wave": wave,
            "task_count": len(wave_tasks),
            "tasks": wave_tasks,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_generate_execution_plan(
    epic_path: str, include_critical_path: bool = True, resume: bool = False
) -> str:
    """Generate a full execution plan with actionable task filtering.

    Computes waves from the dependency graph and marks each task actionable or
    not. By default actionable = {pending, in_progress, rework} (completed, qa,
    and failed are skipped). With resume=True, also re-actions work a prior run
    left mid-flight: 'qa' (worker finished but never validated) and 'failed'
    (halted after max_retries). A re-actioned 'failed' task continues toward the
    same 3-attempt budget via its persisted retry_count — once retry_count hits
    max_retries it is escalated to a human (HALT) rather than retried forever.
    'completed' is never actionable so finished work is always skipped.

    This matches /workflow-execute's RESUME_ACTIONABLE_STATUSES so all three
    executors (agent-, team-, workflow-execute) treat resume identically.

    Used by both /agent-execution and /team-execution as the primary planning step.

    Args:
        epic_path: Path to epic directory.
        include_critical_path: Include critical path analysis (default True).
        resume: Treat qa/failed carryover as actionable for a --resume run.

    Returns JSON with waves[], actionable counts, and per-task actionable flags
    (each task also carries retry_count for the 3-attempt escalation budget).
    """
    try:
        eu = epic_utils
        store = _store()
        result = store.load_epic(epic_path)

        if "error" in result:
            return json.dumps(result)

        tasks = result["tasks"]
        if not tasks:
            return json.dumps({"error": "No tasks found in epic"})

        actionable_statuses = {"pending", "rework", "in_progress"}
        if resume:
            actionable_statuses = actionable_statuses | {"qa", "failed"}

        waves_map = eu.compute_waves(tasks)
        wave_groups = eu.group_waves(waves_map)
        task_map = {t["id"]: t for t in tasks}

        waves = []
        total_actionable = 0
        for wave_num in sorted(wave_groups.keys()):
            task_ids = wave_groups[wave_num]
            wave_tasks = []
            wave_actionable = 0
            for tid in sorted(task_ids):
                task = task_map.get(tid, {})
                is_actionable = task.get("status", "pending") in actionable_statuses
                if is_actionable:
                    wave_actionable += 1
                wave_tasks.append({
                    "id": tid,
                    "title": task.get("title", tid),
                    "status": task.get("status", "pending"),
                    "priority": task.get("priority", "medium"),
                    "dependencies": task.get("dependencies", []),
                    "files_to_touch": task.get("files_to_touch", []),
                    "skills_required": task.get("skills_required", []),
                    "retry_count": task.get("retry_count", 0),
                    "actionable": is_actionable,
                })
            total_actionable += wave_actionable
            waves.append({
                "wave": wave_num,
                "total_tasks": len(wave_tasks),
                "actionable_tasks": wave_actionable,
                "tasks": wave_tasks,
            })

        output = {
            "epic_name": result.get("epic_name", "unknown"),
            "total_waves": len(waves),
            "total_tasks": len(tasks),
            "actionable_tasks": total_actionable,
            "waves": waves,
        }

        if include_critical_path:
            cp_tasks, _ = eu.compute_critical_path(tasks, waves_map)
            output["critical_path"] = {
                "tasks": [
                    {
                        "id": tid,
                        "title": task_map.get(tid, {}).get("title", tid),
                        "wave": waves_map.get(tid, -1),
                    }
                    for tid in cp_tasks
                ],
                "length": len(cp_tasks),
            }

        return json.dumps(output, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_analyze_dag(epic_path: str) -> str:
    """Analyze the dependency DAG for critical path and parallelism metrics.

    Args:
        epic_path: Path to epic directory.

    Returns JSON with critical_path and parallelism analysis.
    """
    try:
        eu = epic_utils
        store = _store()
        resolved = store._resolve(epic_path)

        tasks = store.load_tasks(epic_path)
        valid_tasks = [t for t in tasks if "error" not in t]

        if not valid_tasks:
            return json.dumps({"error": "No valid tasks found"})

        waves = eu.compute_waves(valid_tasks)
        cp_tasks, cp_length = eu.compute_critical_path(valid_tasks, waves)
        parallelism = eu.compute_parallelism_metrics(valid_tasks, waves)

        task_map = {t["id"]: t for t in valid_tasks}

        return json.dumps({
            "epic_name": resolved.name,
            "total_tasks": len(valid_tasks),
            "critical_path": {
                "tasks": cp_tasks,
                "length": cp_length,
                "task_details": [
                    {
                        "id": tid,
                        "title": task_map.get(tid, {}).get("title", tid),
                        "wave": waves.get(tid, -1),
                    }
                    for tid in cp_tasks
                ],
            },
            "parallelism": {
                "wave_count": parallelism["phase_count"],
                "max_parallelism": parallelism["max_parallelism"],
                "wave0_tasks": parallelism["phase1_tasks"],
                "wave0_ratio": parallelism["phase1_ratio"],
                "waves": {str(k): v for k, v in parallelism["phases"].items()},
            },
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_complete_epic(
    epic_path: str,
    map_path: str = "",
    map_status: str = "",
    force: bool = False,
) -> str:
    """Archive a completed epic by moving it from active/ to complete/.

    Verifies every task has status "completed" (unless force=True), then
    moves the epic directory into the sibling ``complete/`` directory.
    When *map_path* is provided, the epic's **Status:** line in the map
    file is updated as well.

    Args:
        epic_path: Path to epic directory (e.g. "spoq/epics/active/my-epic").
        map_path: Optional path to map directory or .md file whose epic
                  status should be updated.
        map_status: Status text written to the map. Defaults to
                    "Complete ({done}/{total} tasks, {date})".
        force: Move the epic even if not all tasks are completed.

    Returns JSON with the new path, task summary, and optional map update.
    """
    try:
        store = _store()
        resolved = store._resolve(epic_path)

        if not resolved.exists():
            return json.dumps({"error": f"Epic directory not found: {resolved}"})
        if not resolved.is_dir():
            return json.dumps({"error": f"Not a directory: {resolved}"})

        # --- verify completion ------------------------------------------------
        tasks = store.load_tasks(epic_path)
        valid = [t for t in tasks if "error" not in t]
        total = len(valid)
        done = sum(1 for t in valid if t.get("status") == "completed")

        if not force and done != total:
            incomplete = [
                {"id": t["id"], "status": t.get("status", "pending")}
                for t in valid
                if t.get("status") != "completed"
            ]
            return json.dumps({
                "error": f"{total - done} of {total} tasks are not completed. "
                         "Set force=True to move anyway.",
                "incomplete_tasks": incomplete,
            })

        # --- move active/ -> complete/ via the store -------------------------
        slug = resolved.name
        try:
            move = store.complete_epic(epic_path)
        except FileExistsError as exc:
            return json.dumps({"error": str(exc)})
        destination = move["new_path"]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # --- optional map update ----------------------------------------------
        map_result = None
        if map_path:
            from spoq_server import map_utils

            resolved_map = store._resolve(map_path)
            status_text = map_status or f"Complete ({done}/{total} tasks, {today})"
            map_result = map_utils.update_epic_status_in_map(
                resolved_map, slug, status_text,
            )

        # --- ROADMAP.yml update -----------------------------------------------
        roadmap_updated = False
        try:
            spoq_dir = str(project_root() / "spoq")
            data = roadmap_utils.load_roadmap(spoq_dir)
            entry = roadmap_utils.find_entry(data, slug)
            if entry is not None:
                roadmap_utils.update_entry_tier(data, slug, "complete")
                roadmap_utils.save_roadmap(spoq_dir, data)
                roadmap_updated = True
        except Exception:
            roadmap_updated = False

        return json.dumps({
            "epic_slug": slug,
            "old_path": move["old_path"],
            "new_path": destination,
            "tasks_completed": done,
            "tasks_total": total,
            "date": today,
            "map_update": map_result,
            "roadmap_updated": roadmap_updated,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# Lifecycle tools: list, promote, demote
# =============================================================================

TIER_ORDER = ["backlog", "active", "complete"]


@mcp.tool()
def spoq_list_epics(tier: str = "", include_stats: bool = False) -> str:
    """List epics across backlog, active, and complete tiers.

    Scans spoq/epics/{backlog,active,complete} directories and returns
    slugs grouped by tier with optional task-level statistics.

    Args:
        tier: Filter to a single tier ("backlog", "active", or "complete").
              Empty string returns all tiers.
        include_stats: When True, load task YAMLs to compute progress
                       (tasks_total, tasks_completed, progress).

    Returns JSON with {backlog: [], active: [], complete: [], counts: {}}.
    """
    try:
        store = _store()
        tiers_to_scan = [tier] if tier else TIER_ORDER

        result: dict = {t: [] for t in TIER_ORDER}

        for t in tiers_to_scan:
            if t not in TIER_ORDER:
                return json.dumps({"error": f"Invalid tier '{t}'. Must be one of {TIER_ORDER}"})
            for slug in store.list_epics(t):
                if include_stats:
                    epic_rel = f"spoq/epics/{t}/{slug}"
                    tasks_total, tasks_completed = store.task_stats(epic_rel)
                    progress = tasks_completed / tasks_total if tasks_total > 0 else 0.0
                    result[t].append({
                        "slug": slug,
                        "tasks_total": tasks_total,
                        "tasks_completed": tasks_completed,
                        "progress": round(progress, 2),
                    })
                else:
                    result[t].append(slug)

        counts = {t: len(result[t]) for t in TIER_ORDER}
        counts["total"] = sum(counts[t] for t in TIER_ORDER)
        result["counts"] = counts

        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_promote(path: str, resource_type: str = "epic") -> str:
    """Promote an epic or map to the next lifecycle tier.

    Moves a resource directory from its current tier to the next one
    in the chain: backlog -> active -> complete.

    Args:
        path: Path to the epic or map directory (absolute or relative).
        resource_type: Either "epic", "map", or "feature". "feature" is an
                       alias of "map" (a feature IS a map on disk) and is
                       normalized to "map" here before the store is called.

    Returns JSON with {old_path, new_path, old_tier, new_tier, slug, roadmap_updated}.
    """
    try:
        if resource_type == "feature":
            resource_type = "map"
        store = _store()
        try:
            move = store.promote(path, resource_type=resource_type)
        except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
            return json.dumps({"error": str(exc)})

        slug = move["slug"]
        current_tier = move["old_tier"]
        next_tier = move["new_tier"]

        warnings = []
        if resource_type == "epic" and current_tier == "active" and next_tier == "complete":
            warnings.append(
                "Consider using spoq_complete_epic instead for active->complete "
                "promotion, as it validates task completion status."
            )

        # Attempt roadmap update (non-fatal)
        roadmap_updated = False
        try:
            spoq_dir = str(project_root() / "spoq")
            data = roadmap_utils.load_roadmap(spoq_dir)
            if roadmap_utils.update_entry_tier(data, slug, next_tier):
                roadmap_utils.save_roadmap(spoq_dir, data)
                roadmap_updated = True
        except Exception:
            pass

        result = {
            "old_path": move["old_path"],
            "new_path": move["new_path"],
            "old_tier": current_tier,
            "new_tier": next_tier,
            "slug": slug,
            "roadmap_updated": roadmap_updated,
        }
        if warnings:
            result["warnings"] = warnings

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_demote(path: str, resource_type: str = "epic") -> str:
    """Demote an epic or map to the previous lifecycle tier.

    Moves a resource directory from its current tier to the previous one
    in the chain: complete -> active -> backlog.

    Args:
        path: Path to the epic or map directory (absolute or relative).
        resource_type: Either "epic", "map", or "feature". "feature" is an
                       alias of "map" (a feature IS a map on disk) and is
                       normalized to "map" here before the store is called.

    Returns JSON with {old_path, new_path, old_tier, new_tier, slug, roadmap_updated}.
    """
    try:
        if resource_type == "feature":
            resource_type = "map"
        store = _store()
        try:
            move = store.demote(path, resource_type=resource_type)
        except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
            return json.dumps({"error": str(exc)})

        slug = move["slug"]
        current_tier = move["old_tier"]
        prev_tier = move["new_tier"]

        # Attempt roadmap update (non-fatal)
        roadmap_updated = False
        try:
            spoq_dir = str(project_root() / "spoq")
            data = roadmap_utils.load_roadmap(spoq_dir)
            if roadmap_utils.update_entry_tier(data, slug, prev_tier):
                roadmap_utils.save_roadmap(spoq_dir, data)
                roadmap_updated = True
        except Exception:
            pass

        return json.dumps({
            "old_path": move["old_path"],
            "new_path": move["new_path"],
            "old_tier": current_tier,
            "new_tier": prev_tier,
            "slug": slug,
            "roadmap_updated": roadmap_updated,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
