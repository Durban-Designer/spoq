#!/usr/bin/env python3
"""
Shared utilities for epic parsing, validation, and DAG analysis.

Used by:
- agent-execution skill (parse-epic.py, build-dependency-graph.py)
- epic-planning skill (validate-epic.py, analyze-dag.py)
"""

import re
import sys
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import Any


def _ensure_yaml():
    """
    Ensure PyYAML is importable, bootstrapping a local venv if necessary.

    On PEP 668 systems (externally-managed Python), pip install is blocked.
    This creates a lightweight venv at .claude/skills/lib/.venv and installs
    pyyaml there as a one-time setup step.
    """
    try:
        import yaml
        return yaml
    except ImportError:
        pass

    venv_dir = Path(__file__).parent / ".venv"

    # Create venv if it doesn't exist
    if not (venv_dir / "bin").exists() and not (venv_dir / "Scripts").exists():
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(venv_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Locate pip inside the venv
    pip_path = venv_dir / "bin" / "pip"
    if not pip_path.exists():
        pip_path = venv_dir / "Scripts" / "pip.exe"  # Windows

    # Install pyyaml
    subprocess.check_call(
        [str(pip_path), "install", "pyyaml", "-q"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Add the venv's site-packages to sys.path
    import glob as _glob
    patterns = [
        str(venv_dir / "lib" / "python*" / "site-packages"),  # Linux/macOS
        str(venv_dir / "Lib" / "site-packages"),               # Windows
    ]
    for pattern in patterns:
        matches = _glob.glob(pattern)
        if matches:
            sys.path.insert(0, matches[0])
            break

    import yaml
    return yaml


yaml = _ensure_yaml()


# =============================================================================
# EPIC.md Parsing
# =============================================================================

def parse_epic_md(epic_path: Path) -> dict[str, Any]:
    """
    Extract metadata from EPIC.md file.

    Returns dict with: title, overview, architecture, dispatch_strategy, raw_length
    """
    epic_md = epic_path / "EPIC.md"
    if not epic_md.exists():
        return {"error": f"EPIC.md not found in {epic_path}"}

    content = epic_md.read_text(encoding='utf-8')

    # Extract title (first # heading)
    title_match = re.search(r'^#\s+(?:Epic:\s*)?(.+)$', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else epic_path.name

    # Extract overview section
    overview_match = re.search(
        r'##\s*(?:Overview|Vision)\s*\n(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    overview = overview_match.group(1).strip() if overview_match else ""

    # Extract architecture section
    arch_match = re.search(
        r'##\s*Architecture\s*\n(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    architecture = arch_match.group(1).strip() if arch_match else ""

    # Extract dispatch strategy
    dispatch_match = re.search(
        r'##\s*Dispatch Strategy\s*\n(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    dispatch_strategy = dispatch_match.group(1).strip() if dispatch_match else ""

    # Extract success criteria
    criteria_match = re.search(
        r'##\s*Success Criteria\s*\n(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    success_criteria = criteria_match.group(1).strip() if criteria_match else ""

    return {
        "title": title,
        "overview": overview,
        "architecture": architecture,
        "dispatch_strategy": dispatch_strategy,
        "success_criteria": success_criteria,
        "raw_length": len(content)
    }


def validate_epic_md_structure(epic_path: Path) -> list[str]:
    """
    Validate EPIC.md has required sections.

    Returns list of error messages (empty if valid).
    """
    errors = []
    epic_md = epic_path / "EPIC.md"

    if not epic_md.exists():
        return ["EPIC.md not found"]

    content = epic_md.read_text(encoding='utf-8')

    required_sections = [
        ("Overview", r"##\s*(?:Overview|Vision)"),
        ("Architecture", r"##\s*Architecture"),
        ("Success Criteria", r"##\s*Success Criteria"),
        ("Task Dependencies", r"##\s*Task Dependencies"),
        ("Dispatch Strategy", r"##\s*Dispatch Strategy"),
    ]

    for name, pattern in required_sections:
        if not re.search(pattern, content, re.IGNORECASE):
            errors.append(f"EPIC.md missing required section: {name}")

    # Check for success criteria checkboxes
    criteria_match = re.search(
        r"##\s*Success Criteria\s*\n(.*?)(?=\n##|\Z)",
        content, re.DOTALL
    )
    if criteria_match:
        criteria_text = criteria_match.group(1)
        checkbox_count = len(re.findall(r"- \[ \]", criteria_text))
        if checkbox_count < 5:
            errors.append(f"Success Criteria has only {checkbox_count} items (recommend 10+)")

    return errors


# =============================================================================
# Task YAML Parsing
# =============================================================================

def parse_task_yaml(task_file: Path) -> dict[str, Any]:
    """
    Parse a single task YAML file.

    Returns task dict with normalized fields, or dict with 'error' key on failure.
    """
    try:
        content = task_file.read_text(encoding='utf-8')
        task = yaml.safe_load(content)

        if not isinstance(task, dict):
            return {"error": f"Invalid YAML structure in {task_file.name}"}

        # Ensure required fields exist
        required_fields = ["id", "title", "description"]
        missing = [f for f in required_fields if f not in task]
        if missing:
            return {"error": f"Missing required fields in {task_file.name}: {missing}"}

        # Normalize optional fields
        task.setdefault("status", "pending")
        task.setdefault("priority", "medium")
        task.setdefault("phase", 1)
        task.setdefault("dependencies", [])
        task.setdefault("files_to_touch", [])
        task.setdefault("acceptance_criteria", [])
        task.setdefault("outputs", [])
        task.setdefault("skills_required", [])

        # Add source file reference
        task["_source_file"] = str(task_file)

        return task

    except yaml.YAMLError as e:
        return {"error": f"YAML parse error in {task_file.name}: {e}"}
    except Exception as e:
        return {"error": f"Error reading {task_file.name}: {e}"}


def validate_task_yaml_structure(task: dict, task_file: Path) -> list[str]:
    """
    Validate task YAML has proper structure.

    Returns list of errors (empty if valid).
    """
    errors = []

    if "error" in task:
        return [task["error"]]

    # ID should match filename pattern
    if "id" in task:
        expected_prefix = task_file.stem.split("-")[0]
        actual_prefix = task["id"].split("-")[0]
        if expected_prefix != actual_prefix:
            errors.append(f"{task_file.name}: ID '{task['id']}' prefix doesn't match filename")

    # Description should have key sections
    if "description" in task:
        desc = task["description"]
        for section in ["Objective", "Steps", "Verification"]:
            if f"## {section}" not in desc:
                errors.append(f"{task_file.name}: Description missing '## {section}' section")

    return errors


# =============================================================================
# Dependency Validation
# =============================================================================

def validate_dependencies(tasks: list[dict]) -> list[str]:
    """
    Validate all dependencies reference existing task IDs.

    Returns list of errors (empty if valid).
    """
    errors = []
    task_ids = {t["id"] for t in tasks if "id" in t and "error" not in t}

    for task in tasks:
        if "error" in task:
            continue
        task_id = task.get("id", "unknown")
        for dep in task.get("dependencies", []):
            if dep not in task_ids:
                errors.append(f"Task '{task_id}' references unknown dependency: '{dep}'")

    return errors


def detect_cycles(tasks: list[dict]) -> list[str]:
    """
    Detect dependency cycles using DFS.

    Returns list of cycle descriptions (empty if no cycles).
    """
    errors = []
    task_map = {t["id"]: t for t in tasks if "id" in t and "error" not in t}

    # Build adjacency list
    graph = {tid: task.get("dependencies", []) for tid, task in task_map.items()}

    # DFS cycle detection with coloring
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in graph}

    def dfs(node: str, path: list[str]) -> bool:
        if color.get(node) == GRAY:
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            errors.append(f"Dependency cycle: {' -> '.join(cycle)}")
            return True
        if color.get(node) == BLACK:
            return False

        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor in graph and dfs(neighbor, path):
                return True

        path.pop()
        color[node] = BLACK
        return False

    for task_id in graph:
        if color[task_id] == WHITE:
            dfs(task_id, [])

    return errors


def validate_phases(tasks: list[dict]) -> list[str]:
    """
    Validate phase assignments are consistent with dependencies.

    A task in phase N should only depend on tasks in phases < N.
    """
    errors = []
    task_map = {t["id"]: t for t in tasks if "id" in t and "error" not in t}

    for task in tasks:
        if "error" in task:
            continue
        task_id = task.get("id")
        task_phase = task.get("phase", 1)

        for dep in task.get("dependencies", []):
            if dep in task_map:
                dep_phase = task_map[dep].get("phase", 1)
                if dep_phase >= task_phase:
                    errors.append(
                        f"Task '{task_id}' (phase {task_phase}) depends on "
                        f"'{dep}' (phase {dep_phase}) - dependency should be earlier phase"
                    )

    return errors


# =============================================================================
# Wave Computation
# =============================================================================

def compute_waves(tasks: list[dict]) -> dict[str, int]:
    """
    Compute execution waves using topological sort.

    Wave N = tasks whose all dependencies are in waves 0..N-1

    Returns dict mapping task_id -> wave_number
    """
    task_map = {t["id"]: t for t in tasks if "id" in t and "error" not in t}

    # Build dependency maps
    dependents = defaultdict(set)  # who depends on me
    dependencies = {}  # who do I depend on

    for task in tasks:
        if "error" in task:
            continue
        tid = task["id"]
        deps = set(task.get("dependencies", []))
        dependencies[tid] = deps
        for dep in deps:
            dependents[dep].add(tid)

    # Track remaining unresolved dependencies
    remaining = {tid: len(deps) for tid, deps in dependencies.items()}

    # Assign waves
    waves = {}
    current_wave = 0

    while True:
        # Find tasks ready for this wave
        ready = [tid for tid, count in remaining.items()
                 if count == 0 and tid not in waves]

        if not ready:
            break

        # Assign wave
        for tid in ready:
            waves[tid] = current_wave

        # Reduce dependency counts
        for tid in ready:
            for dependent in dependents[tid]:
                if dependent in remaining:
                    remaining[dependent] -= 1

        current_wave += 1

    # Check for unassigned tasks (indicates cycles or missing deps)
    unassigned = set(task_map.keys()) - set(waves.keys())
    if unassigned:
        raise ValueError(f"Could not assign wave to tasks (possible cycle): {unassigned}")

    return waves


def group_waves(waves: dict[str, int]) -> dict[int, list[str]]:
    """
    Group task IDs by wave number.

    Returns dict mapping wave_number -> sorted list of task_ids
    """
    wave_groups = defaultdict(list)
    for tid, wave in waves.items():
        wave_groups[wave].append(tid)

    # Sort tasks within each wave
    for wave in wave_groups:
        wave_groups[wave].sort()

    return dict(wave_groups)


# =============================================================================
# Critical Path Analysis
# =============================================================================

def compute_critical_path(tasks: list[dict], waves: dict[str, int] = None) -> tuple[list[str], int]:
    """
    Find critical path (longest dependency chain by task count) through the graph.

    Returns (path_as_list_of_task_ids, path_length)
    """
    task_map = {t["id"]: t for t in tasks if "id" in t and "error" not in t}

    if waves is None:
        waves = compute_waves(tasks)

    wave_groups = group_waves(waves)

    # Compute longest path using dynamic programming
    longest_path = {}
    path_to = {}

    # Process waves in order
    for wave in sorted(wave_groups.keys()):
        for tid in wave_groups[wave]:
            task = task_map[tid]
            deps = task.get("dependencies", [])

            if not deps:
                longest_path[tid] = 1
                path_to[tid] = [tid]
            else:
                # Find dependency with longest path
                max_len = 0
                best_path = []
                for dep in deps:
                    if dep in longest_path and longest_path[dep] > max_len:
                        max_len = longest_path[dep]
                        best_path = path_to[dep]

                longest_path[tid] = max_len + 1
                path_to[tid] = best_path + [tid]

    if not longest_path:
        return [], 0

    # Find task with longest path
    max_task = max(longest_path.keys(), key=lambda t: longest_path[t])
    return path_to[max_task], longest_path[max_task]


# =============================================================================
# Parallelism Metrics
# =============================================================================

def compute_parallelism_metrics(tasks: list[dict], waves: dict[str, int] = None) -> dict[str, Any]:
    """
    Compute parallelism metrics for an epic.

    Returns dict with:
    - total_tasks: int
    - phase_count: int
    - phase1_tasks: int
    - phase1_ratio: float (0-1)
    - max_parallelism: int
    - phases: dict[int, list[str]]
    """
    if waves is None:
        waves = compute_waves(tasks)

    wave_groups = group_waves(waves)
    total_tasks = len(waves)
    phase1_count = len(wave_groups.get(0, []))

    return {
        "total_tasks": total_tasks,
        "phases": wave_groups,
        "phase_count": len(wave_groups),
        "phase1_tasks": phase1_count,
        "phase1_ratio": phase1_count / total_tasks if total_tasks > 0 else 0,
        "max_parallelism": max(len(v) for v in wave_groups.values()) if wave_groups else 0,
    }


# =============================================================================
# Epic Loading
# =============================================================================

def load_tasks(epic_path: Path) -> list[dict]:
    """
    Load all task files from epic directory.

    Supports both nested (tasks/) and flat structures.
    """
    tasks = []
    tasks_dir = epic_path / "tasks"

    if tasks_dir.exists():
        task_files = sorted(tasks_dir.glob("*.yml"))
    else:
        task_files = sorted(epic_path.glob("*.yml"))

    for tf in task_files:
        task = parse_task_yaml(tf)
        tasks.append(task)

    return tasks


def parse_epic(epic_path: Path, validate: bool = True) -> dict[str, Any]:
    """
    Parse an entire epic directory.

    Returns dict with:
    - epic_path: str
    - epic_name: str
    - metadata: dict (from EPIC.md)
    - tasks: list[dict]
    - stats: dict
    - errors: list[str] (if any)
    """
    if not epic_path.exists():
        return {"error": f"Epic directory not found: {epic_path}"}

    if not epic_path.is_dir():
        return {"error": f"Not a directory: {epic_path}"}

    # Parse EPIC.md
    epic_metadata = parse_epic_md(epic_path)

    # Load tasks
    tasks = load_tasks(epic_path)

    # Separate valid tasks from errors
    valid_tasks = [t for t in tasks if "error" not in t]
    task_errors = [t["error"] for t in tasks if "error" in t]

    # Validation
    validation_errors = []
    if validate:
        validation_errors.extend(validate_dependencies(valid_tasks))
        validation_errors.extend(detect_cycles(valid_tasks))

    # Compute stats
    stats = {
        "total_tasks": len(tasks),
        "valid_tasks": len(valid_tasks),
        "pending": sum(1 for t in valid_tasks if t.get("status") == "pending"),
        "in_progress": sum(1 for t in valid_tasks if t.get("status") == "in_progress"),
        "completed": sum(1 for t in valid_tasks if t.get("status") == "completed"),
        "failed": sum(1 for t in valid_tasks if t.get("status") == "failed"),
        "phases": sorted(set(t.get("phase", 1) for t in valid_tasks))
    }

    result = {
        "epic_path": str(epic_path),
        "epic_name": epic_path.name,
        "metadata": epic_metadata,
        "tasks": valid_tasks,
        "stats": stats
    }

    # Add errors if any
    all_errors = task_errors + validation_errors
    if all_errors:
        result["errors"] = all_errors

    return result
