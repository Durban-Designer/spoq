#!/usr/bin/env python3
"""
Analyze dependency DAG for critical path and parallelism metrics.

Usage:
    python3 analyze-dag.py spoq/epics/epic-name
"""

import sys
from pathlib import Path

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from epic_utils import (
    load_tasks,
    compute_waves,
    group_waves,
    compute_critical_path,
    compute_parallelism_metrics,
)


def analyze_epic(epic_path: Path) -> dict:
    """
    Perform comprehensive DAG analysis on an epic.

    Returns dict with critical path and parallelism metrics.
    """
    tasks = load_tasks(epic_path)
    valid_tasks = [t for t in tasks if "error" not in t]

    if not valid_tasks:
        return {"error": "No valid tasks found"}

    # Compute waves
    try:
        waves = compute_waves(valid_tasks)
        wave_groups = group_waves(waves)
    except ValueError as e:
        return {"error": f"Wave computation failed: {e}"}

    # Compute critical path
    critical_path, critical_length = compute_critical_path(valid_tasks, waves)

    # Compute parallelism metrics
    parallelism = compute_parallelism_metrics(valid_tasks, waves)

    # Build task map for titles
    task_map = {t["id"]: t for t in valid_tasks}

    return {
        "epic_name": epic_path.name,
        "total_tasks": len(valid_tasks),
        "critical_path": {
            "tasks": critical_path,
            "length": critical_length,
            "task_details": [
                {
                    "id": tid,
                    "title": task_map.get(tid, {}).get("title", tid),
                    "wave": waves.get(tid, -1),
                }
                for tid in critical_path
            ]
        },
        "parallelism": {
            "wave_count": parallelism["phase_count"],
            "wave0_tasks": parallelism["phase1_tasks"],
            "wave0_ratio": parallelism["phase1_ratio"],
            "max_parallelism": parallelism["max_parallelism"],
            "waves": {
                wave: tasks
                for wave, tasks in sorted(parallelism["phases"].items())
            }
        }
    }


def format_report(analysis: dict) -> str:
    """Format analysis results as human-readable report."""
    lines = []

    if "error" in analysis:
        return f"Error: {analysis['error']}"

    lines.append("=" * 60)
    lines.append(f"EPIC DAG ANALYSIS: {analysis['epic_name']}")
    lines.append("=" * 60)
    lines.append("")

    # Critical Path
    cp = analysis["critical_path"]
    lines.append("CRITICAL PATH")
    lines.append("-" * 40)
    path_str = " -> ".join(cp["tasks"])
    lines.append(f"  Path: {path_str}")
    lines.append(f"  Length: {cp['length']} tasks")
    lines.append("")
    lines.append("  Task breakdown:")
    for task in cp["task_details"]:
        lines.append(f"    {task['id']}: {task['title']} (wave {task['wave']})")
    lines.append("")

    # Parallelism
    par = analysis["parallelism"]
    lines.append("PARALLELISM METRICS")
    lines.append("-" * 40)
    lines.append(f"  Total tasks: {analysis['total_tasks']}")
    lines.append(f"  Wave count: {par['wave_count']}")
    lines.append(f"  Wave 0 tasks: {par['wave0_tasks']} ({par['wave0_ratio']*100:.0f}%)")
    lines.append(f"  Max parallelism: {par['max_parallelism']} agents")
    lines.append("")
    lines.append("  Wave breakdown:")
    for wave, tasks in par["waves"].items():
        lines.append(f"    Wave {wave}: {', '.join(tasks)}")
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append("-" * 40)
    if par["wave0_ratio"] >= 0.25:
        lines.append("  [OK] Good parallelism (Wave 0 >= 25%)")
    else:
        lines.append("  [!!] Low parallelism (Wave 0 < 25%) - consider restructuring")

    if len(cp["tasks"]) <= analysis["total_tasks"] * 0.4:
        lines.append("  [OK] Critical path is reasonable (<40% of tasks)")
    else:
        lines.append("  [!!] Long critical path (>40% of tasks) - limits speedup")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze-dag.py <epic-path>", file=sys.stderr)
        sys.exit(1)

    epic_path = Path(sys.argv[1])

    if not epic_path.exists():
        print(f"Error: Epic path not found: {epic_path}", file=sys.stderr)
        sys.exit(1)

    analysis = analyze_epic(epic_path)
    report = format_report(analysis)
    print(report)

    if "error" in analysis:
        sys.exit(1)


if __name__ == "__main__":
    main()
