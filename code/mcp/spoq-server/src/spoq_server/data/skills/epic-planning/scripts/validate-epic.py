#!/usr/bin/env python3
"""
Validate an epic's structure, task files, and dependency graph.

Usage:
    python3 validate-epic.py spoq/epics/epic-name
    python3 validate-epic.py spoq/epics/epic-name --strict
"""

import sys
from pathlib import Path

# Add lib directory to path for imports
lib_path = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from epic_utils import (
    parse_epic,
    validate_epic_md_structure,
    validate_task_yaml_structure,
    validate_dependencies,
    detect_cycles,
    validate_phases,
    load_tasks,
    parse_task_yaml,
    compute_waves,
    group_waves
)


def validate_epic(epic_path: Path, strict: bool = False) -> tuple[list[str], list[str]]:
    """
    Validate an epic comprehensively.

    Returns (errors, warnings) tuple.
    """
    errors = []
    warnings = []

    # Validate EPIC.md structure
    epic_md_errors = validate_epic_md_structure(epic_path)
    errors.extend(epic_md_errors)

    # Load and validate task files
    tasks_dir = epic_path / "tasks"
    if tasks_dir.exists():
        task_files = sorted(tasks_dir.glob("*.yml"))
    else:
        task_files = sorted(epic_path.glob("*.yml"))

    if not task_files:
        errors.append("No task YAML files found")
        return errors, warnings

    tasks = []
    for tf in task_files:
        task = parse_task_yaml(tf)
        if "error" in task:
            errors.append(task["error"])
        else:
            tasks.append(task)
            # Additional structure validation
            struct_errors = validate_task_yaml_structure(task, tf)
            if strict:
                errors.extend(struct_errors)
            else:
                warnings.extend(struct_errors)

    if not tasks:
        errors.append("No valid tasks found")
        return errors, warnings

    # Validate dependencies
    dep_errors = validate_dependencies(tasks)
    errors.extend(dep_errors)

    # Detect cycles
    cycle_errors = detect_cycles(tasks)
    errors.extend(cycle_errors)

    # Validate phase consistency
    phase_errors = validate_phases(tasks)
    if strict:
        errors.extend(phase_errors)
    else:
        warnings.extend(phase_errors)

    # Check Wave 0 ratio
    try:
        waves = compute_waves(tasks)
        wave_groups = group_waves(waves)
        wave0_count = len(wave_groups.get(0, []))
        total_tasks = len(tasks)
        wave0_ratio = wave0_count / total_tasks if total_tasks > 0 else 0

        if wave0_ratio < 0.15:
            warnings.append(
                f"Wave 0 has only {wave0_count}/{total_tasks} tasks "
                f"({wave0_ratio*100:.0f}%) - consider reducing dependency depth"
            )
    except ValueError as e:
        errors.append(f"Wave computation failed: {e}")

    return errors, warnings


def format_report(epic_path: Path, errors: list[str], warnings: list[str]) -> str:
    """Format validation results as human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"EPIC VALIDATION: {epic_path.name}")
    lines.append("=" * 60)
    lines.append("")

    if errors:
        lines.append("ERRORS (must fix):")
        lines.append("-" * 40)
        for err in errors:
            lines.append(f"  [X] {err}")
        lines.append("")

    if warnings:
        lines.append("WARNINGS (should fix):")
        lines.append("-" * 40)
        for warn in warnings:
            lines.append(f"  [!] {warn}")
        lines.append("")

    if not errors and not warnings:
        lines.append("VALIDATION PASSED")
        lines.append("")

        # Show summary
        result = parse_epic(epic_path, validate=False)
        stats = result.get("stats", {})
        lines.append(f"  Tasks: {stats.get('valid_tasks', 0)}")
        lines.append(f"  Phases: {stats.get('phases', [])}")
        lines.append(f"  Status: {stats.get('pending', 0)} pending, "
                     f"{stats.get('completed', 0)} completed")
    elif errors:
        lines.append("VALIDATION FAILED")
    else:
        lines.append("VALIDATION PASSED WITH WARNINGS")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: validate-epic.py <epic-path> [--strict]", file=sys.stderr)
        sys.exit(1)

    epic_path = Path(sys.argv[1])
    strict = "--strict" in sys.argv

    if not epic_path.exists():
        print(f"Error: Epic path not found: {epic_path}", file=sys.stderr)
        sys.exit(1)

    errors, warnings = validate_epic(epic_path, strict=strict)
    report = format_report(epic_path, errors, warnings)
    print(report)

    # Exit with error code if there were errors
    if errors:
        sys.exit(1)
    elif warnings and strict:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
