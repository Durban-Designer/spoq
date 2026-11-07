#!/usr/bin/env python3
"""
Build dependency graph from parsed epic and compute execution waves.

Usage:
    python3 parse-epic.py spoq/epics/epic-name | python3 build-dependency-graph.py
    python3 build-dependency-graph.py < parsed-epic.json
    python3 build-dependency-graph.py --critical-path < parsed-epic.json
    python3 build-dependency-graph.py --resume < parsed-epic.json
"""

import sys
import json
from pathlib import Path
from typing import Any

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from epic_utils import compute_waves, group_waves, compute_critical_path


def generate_execution_plan(
    parsed_epic: dict, include_critical_path: bool = False, resume: bool = False
) -> dict[str, Any]:
    """Generate a complete execution plan from parsed epic.

    With resume=True the actionable set also includes 'qa' (worker finished but
    never validated) and 'failed' (halted after max_retries — re-attempted using
    its remaining retry_count budget, then escalated to a human once exhausted).
    This mirrors spoq_generate_execution_plan and workflow-execute's resume set
    so all three executors treat resume identically. 'completed' is never
    actionable.
    """
    tasks = parsed_epic.get("tasks", [])

    if not tasks:
        return {"error": "No tasks found in epic"}

    # Filter to only actionable tasks (pending, rework, in_progress; +qa/failed on resume)
    actionable_statuses = {"pending", "rework", "in_progress"}
    if resume:
        actionable_statuses = actionable_statuses | {"qa", "failed"}
    actionable_tasks = [t for t in tasks if t.get("status", "pending") in actionable_statuses]

    # Compute waves for all tasks
    # compute_waves returns {task_id: wave_num}
    task_to_wave = compute_waves(tasks)
    # group_waves returns {wave_num: [task_ids]}
    wave_groups = group_waves(task_to_wave)

    # Create task lookup
    task_map = {t["id"]: t for t in tasks}

    # Build wave details
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
                "files_to_touch": task.get("files_to_touch", []),
                "retry_count": task.get("retry_count", 0),
                "actionable": task.get("status", "pending") in actionable_statuses
            })

        actionable_count = sum(1 for t in wave_tasks if t["actionable"])

        waves.append({
            "wave": wave_num,
            "total_tasks": len(wave_tasks),
            "actionable_tasks": actionable_count,
            "tasks": wave_tasks
        })

    result = {
        "epic_name": parsed_epic.get("epic_name", "unknown"),
        "total_waves": len(waves),
        "total_tasks": len(tasks),
        "actionable_tasks": len(actionable_tasks),
        "waves": waves
    }

    # Add critical path if requested
    if include_critical_path:
        critical_path, duration = compute_critical_path(tasks, task_to_wave)
        critical_tasks = [
            {
                "id": tid,
                "title": task_map.get(tid, {}).get("title", tid),
                "wave": task_to_wave.get(tid, -1)
            }
            for tid in critical_path
        ]
        result["critical_path"] = {
            "length": len(critical_path),
            "duration_hours": duration,
            "tasks": critical_tasks
        }

    return result


def format_dry_run(plan: dict) -> str:
    """Format execution plan for human-readable dry-run output."""
    lines = []

    epic_name = plan.get("epic_name", "unknown")
    lines.append(f"# Execution Plan: {epic_name}")
    lines.append("")
    lines.append(f"Total Waves: {plan.get('total_waves', 0)}")
    lines.append(f"Total Tasks: {plan.get('total_tasks', 0)}")
    lines.append(f"Actionable Tasks: {plan.get('actionable_tasks', 0)}")
    lines.append("")

    for wave in plan.get("waves", []):
        wave_num = wave.get("wave", 0)
        actionable = wave.get("actionable_tasks", 0)
        total = wave.get("total_tasks", 0)

        lines.append(f"## Wave {wave_num} ({actionable}/{total} actionable)")
        lines.append("")

        for task in wave.get("tasks", []):
            status = task.get("status", "pending")
            marker = "[ ]" if task.get("actionable") else "[x]" if status == "completed" else "[~]"
            deps = task.get("dependencies", [])
            dep_str = f" (deps: {', '.join(deps)})" if deps else ""

            lines.append(f"  {marker} {task.get('id')}: {task.get('title')}{dep_str}")

        lines.append("")

    # Critical path if present
    if "critical_path" in plan:
        cp = plan["critical_path"]
        duration = cp.get("duration_hours", 0)
        lines.append(f"## Critical Path (length: {cp.get('length', 0)}, duration: {duration:.1f}h)")
        lines.append("")
        path_str = " -> ".join(t["id"] for t in cp.get("tasks", []))
        lines.append(f"  {path_str}")
        lines.append("")

    return "\n".join(lines)


def main():
    # Check for flags
    include_critical_path = "--critical-path" in sys.argv
    dry_run_format = "--dry-run" in sys.argv
    resume = "--resume" in sys.argv

    # Read parsed epic from stdin
    try:
        parsed_epic = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Check for errors in input
    if "error" in parsed_epic:
        print(f"Error in parsed epic: {parsed_epic['error']}", file=sys.stderr)
        sys.exit(1)

    if "errors" in parsed_epic:
        for err in parsed_epic["errors"]:
            print(f"Warning: {err}", file=sys.stderr)

    # Generate execution plan
    try:
        plan = generate_execution_plan(
            parsed_epic, include_critical_path=include_critical_path, resume=resume
        )
    except ValueError as e:
        print(f"Error computing execution plan: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    if dry_run_format:
        print(format_dry_run(plan))
    else:
        print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
