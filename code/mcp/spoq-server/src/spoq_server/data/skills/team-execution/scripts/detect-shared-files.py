#!/usr/bin/env python3
"""
Detect shared file conflicts within a wave of tasks.

Reads a JSON wave task list from stdin and identifies files touched by
multiple tasks. Outputs a conflict report for the orchestrator.

Usage:
    python3 detect-shared-files.py < wave_tasks.json
    python3 detect-shared-files.py --verbose < wave_tasks.json

Input format (JSON array of tasks or object with "tasks" key):
    [{"id": "01-foo", "files_to_touch": ["src/Header.tsx", "src/api.ts"]}, ...]

Output format:
    {
      "conflicts": [{"file": "src/Header.tsx", "tasks": ["01-foo", "03-bar"], "resolution": "orchestrator_merge"}],
      "safe_tasks": ["02-baz"],
      "conflicting_tasks": ["01-foo", "03-bar"]
    }
"""

import sys
import json
from collections import defaultdict


def detect_conflicts(tasks: list[dict]) -> dict:
    """
    Detect files touched by multiple tasks in a wave.

    Returns conflict report with:
    - conflicts: list of {file, tasks, resolution}
    - safe_tasks: task IDs with no shared files
    - conflicting_tasks: task IDs that share files with others
    """
    # Build file -> tasks mapping
    file_tasks: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        task_id = task.get("id", "unknown")
        # Handle field name variance
        files = task.get("files_to_touch", []) or task.get("deliverables", []) or []
        for f in files:
            file_tasks[f].append(task_id)

    # Identify conflicts (files touched by 2+ tasks)
    conflicts = []
    conflicting_task_ids = set()

    for filepath, task_ids in sorted(file_tasks.items()):
        if len(task_ids) > 1:
            conflicts.append({
                "file": filepath,
                "tasks": sorted(task_ids),
                "resolution": "orchestrator_merge",
            })
            conflicting_task_ids.update(task_ids)

    # Identify safe tasks (no shared files)
    all_task_ids = {t.get("id", "unknown") for t in tasks}
    safe_tasks = sorted(all_task_ids - conflicting_task_ids)

    return {
        "conflicts": conflicts,
        "safe_tasks": safe_tasks,
        "conflicting_tasks": sorted(conflicting_task_ids),
    }


def main():
    verbose = "--verbose" in sys.argv

    # Read input from stdin
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Accept either task list or object with "tasks" key
    if isinstance(data, list):
        tasks = data
    elif isinstance(data, dict) and "tasks" in data:
        tasks = data["tasks"]
    else:
        print("Error: Expected JSON array of tasks or object with 'tasks' key", file=sys.stderr)
        sys.exit(1)

    report = detect_conflicts(tasks)

    if verbose and report["conflicts"]:
        print(f"Found {len(report['conflicts'])} shared file conflict(s):", file=sys.stderr)
        for c in report["conflicts"]:
            print(f"  {c['file']} -> {', '.join(c['tasks'])}", file=sys.stderr)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
