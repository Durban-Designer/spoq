#!/usr/bin/env python3
"""
Shared utilities for map parsing, validation, and DAG analysis.

Maps coordinate multiple epics through wave-based parallel execution.
This module mirrors epic_utils.py patterns at the epic level, importing
from epic_utils for task-level aggregation when resolving individual epics.

Used by:
- map_tools.py (MCP server tools)
- epic-planning skill (map mode)
"""

import re
from pathlib import Path
from collections import defaultdict
from typing import Any


# =============================================================================
# Path Resolution
# =============================================================================

def resolve_map_file(map_path: Path) -> Path | None:
    """Resolve the map markdown file from either storage format.

    Supports two layouts:
    - Directory format: ``map_path/MAP.md``
    - Single-file format: ``map_path`` itself is a ``.md`` file

    Returns the resolved :class:`Path`, or *None* when no file is found.
    """
    if map_path.is_file() and map_path.suffix.lower() == ".md":
        return map_path
    map_md = map_path / "MAP.md"
    if map_md.exists():
        return map_md
    return None


# =============================================================================
# MAP.md Parsing
# =============================================================================

def parse_map_md(map_path: Path) -> dict[str, Any]:
    """Extract metadata from a map markdown file.

    *map_path* may be a directory containing ``MAP.md`` **or** a standalone
    ``.md`` file.

    Returns dict with: title, vision, epics (list of dicts with slug, status,
    dependencies, summary), dispatch_strategy, success_criteria
    """
    map_md = resolve_map_file(map_path)
    if map_md is None:
        return {"error": f"Map file not found at {map_path} (expected MAP.md inside a directory or a standalone .md file)"}

    content = map_md.read_text(encoding='utf-8')

    # Extract title (first # heading)
    title_match = re.search(r'^#\s+(?:Map:\s*)?(.+)$', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else map_path.name

    # Extract vision section
    vision_match = re.search(
        r'##\s*Vision\s*\n(.*?)(?=\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    vision = vision_match.group(1).strip() if vision_match else ""

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

    # Extract epics from the ## Epics section
    epics = _parse_epic_entries(content)

    return {
        "title": title,
        "vision": vision,
        "epics": epics,
        "dispatch_strategy": dispatch_strategy,
        "success_criteria": success_criteria,
        "raw_length": len(content),
    }


def _parse_epic_entries(content: str) -> list[dict[str, Any]]:
    """
    Parse ### subsections under ## Epics into structured dicts.

    Each subsection follows:
        ### epic-slug
        - **Status:** pending
        - **Dependencies:** none | [slug-a, slug-b]
        - **Summary:** ...
    """
    epics_section = re.search(
        r'##\s*Epics\s*\n(.*?)(?=\n##[^#]|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if not epics_section:
        return []

    section_text = epics_section.group(1)

    # Split by ### headings
    epic_blocks = re.split(r'\n###\s+', section_text)
    epics = []

    for block in epic_blocks:
        block = block.strip()
        if not block:
            continue

        # First line is the slug (strip leading ### from first block)
        lines = block.split('\n', 1)
        slug = lines[0].strip().lstrip('#').strip()
        body = lines[1] if len(lines) > 1 else ""

        # Parse fields
        status_match = re.search(
            r'\*\*Status:\*\*\s*(.+)', body, re.IGNORECASE
        )
        deps_match = re.search(
            r'\*\*Dependencies:\*\*\s*(.+)', body, re.IGNORECASE
        )
        summary_match = re.search(
            r'\*\*Summary:\*\*\s*(.+)', body, re.IGNORECASE
        )

        # Parse dependencies
        deps_raw = deps_match.group(1).strip() if deps_match else "none"
        if deps_raw.lower() == "none":
            dependencies = []
        else:
            # Handle both [a, b] and a, b formats
            deps_raw = deps_raw.strip("[]")
            dependencies = [d.strip() for d in deps_raw.split(",") if d.strip()]

        epics.append({
            "slug": slug,
            "status": status_match.group(1).strip() if status_match else "pending",
            "dependencies": dependencies,
            "summary": summary_match.group(1).strip() if summary_match else "",
        })

    return epics


# =============================================================================
# MAP.md Validation
# =============================================================================

def validate_map_md_structure(map_path: Path) -> list[str]:
    """Validate map markdown file has required sections.

    *map_path* may be a directory containing ``MAP.md`` or a standalone
    ``.md`` file.

    Returns list of error messages (empty if valid).
    """
    errors = []
    map_md = resolve_map_file(map_path)

    if map_md is None:
        return ["Map file not found (expected MAP.md inside a directory or a standalone .md file)"]

    content = map_md.read_text(encoding='utf-8')

    required_sections = [
        ("Vision", r"##\s*Vision"),
        ("Epics", r"##\s*Epics"),
        ("Epic Dependencies", r"##\s*Epic Dependencies"),
        ("Dispatch Strategy", r"##\s*Dispatch Strategy"),
        ("Success Criteria", r"##\s*Success Criteria"),
    ]

    for name, pattern in required_sections:
        if not re.search(pattern, content, re.IGNORECASE):
            errors.append(f"MAP.md missing required section: {name}")

    # Check for at least one epic entry
    epics = _parse_epic_entries(content)
    if len(epics) < 2:
        errors.append(
            f"MAP.md has only {len(epics)} epic(s) (minimum 2 for a map)"
        )

    # Check for success criteria checkboxes
    criteria_match = re.search(
        r"##\s*Success Criteria\s*\n(.*?)(?=\n##|\Z)",
        content, re.DOTALL
    )
    if criteria_match:
        criteria_text = criteria_match.group(1)
        checkbox_count = len(re.findall(r"- \[ \]", criteria_text))
        if checkbox_count < 3:
            errors.append(
                f"Success Criteria has only {checkbox_count} items (recommend 5+)"
            )

    return errors


# =============================================================================
# Dependency Validation
# =============================================================================

def validate_map_dependencies(epics: list[dict]) -> list[str]:
    """
    Validate all dependency references point to existing epic slugs.

    Returns list of errors (empty if valid).
    """
    errors = []
    slugs = {e["slug"] for e in epics}

    for epic in epics:
        slug = epic["slug"]
        for dep in epic.get("dependencies", []):
            if dep not in slugs:
                errors.append(
                    f"Epic '{slug}' references unknown dependency: '{dep}'"
                )

    return errors


def detect_epic_cycles(epics: list[dict]) -> list[str]:
    """
    Detect dependency cycles in the inter-epic DAG using DFS.

    Returns list of cycle descriptions (empty if acyclic).
    """
    errors = []
    epic_map = {e["slug"]: e for e in epics}

    # Build adjacency list (slug -> list of dependency slugs)
    graph = {
        e["slug"]: e.get("dependencies", [])
        for e in epics
    }

    # DFS with three-color marking
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {slug: WHITE for slug in graph}

    def dfs(node: str, path: list[str]) -> bool:
        if color.get(node) == GRAY:
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            errors.append(f"Epic dependency cycle: {' -> '.join(cycle)}")
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

    for slug in graph:
        if color[slug] == WHITE:
            dfs(slug, [])

    return errors


# =============================================================================
# Wave Computation
# =============================================================================

def compute_epic_waves(epics: list[dict]) -> dict[str, int]:
    """
    Compute execution waves for epics using topological sort.

    Wave N = epics whose dependencies all reside in waves 0..N-1.

    Returns dict mapping epic_slug -> wave_number.
    """
    # Build dependency structures
    dependents = defaultdict(set)  # who depends on me
    dep_counts = {}  # remaining unresolved dependency count

    for epic in epics:
        slug = epic["slug"]
        deps = set(epic.get("dependencies", []))
        dep_counts[slug] = len(deps)
        for dep in deps:
            dependents[dep].add(slug)

    # Assign waves via BFS-style topological sort
    waves = {}
    current_wave = 0

    while True:
        ready = [
            slug for slug, count in dep_counts.items()
            if count == 0 and slug not in waves
        ]

        if not ready:
            break

        for slug in ready:
            waves[slug] = current_wave

        for slug in ready:
            for dependent in dependents[slug]:
                if dependent in dep_counts:
                    dep_counts[dependent] -= 1

        current_wave += 1

    # Check for unassigned epics (cycle or missing deps)
    all_slugs = {e["slug"] for e in epics}
    unassigned = all_slugs - set(waves.keys())
    if unassigned:
        raise ValueError(
            f"Could not assign wave to epics (possible cycle): {unassigned}"
        )

    return waves


def group_epic_waves(waves: dict[str, int]) -> dict[int, list[str]]:
    """
    Group epic slugs by wave number.

    Returns dict mapping wave_number -> sorted list of epic slugs.
    """
    groups = defaultdict(list)
    for slug, wave in waves.items():
        groups[wave].append(slug)

    for wave in groups:
        groups[wave].sort()

    return dict(groups)


# =============================================================================
# Critical Path Analysis
# =============================================================================

def compute_epic_critical_path(
    epics: list[dict],
    waves: dict[str, int] | None = None,
) -> tuple[list[str], int]:
    """
    Find the critical path (longest chain by epic count) through the epic DAG.

    Returns (path_as_list_of_slugs, path_length).
    """
    epic_map = {e["slug"]: e for e in epics}

    if waves is None:
        waves = compute_epic_waves(epics)

    wave_groups = group_epic_waves(waves)

    # Dynamic programming: longest path ending at each node
    longest = {}
    path_to = {}

    for wave_num in sorted(wave_groups.keys()):
        for slug in wave_groups[wave_num]:
            epic = epic_map[slug]
            deps = epic.get("dependencies", [])

            if not deps:
                longest[slug] = 1
                path_to[slug] = [slug]
            else:
                max_len = 0
                best_path = []
                for dep in deps:
                    if dep in longest and longest[dep] > max_len:
                        max_len = longest[dep]
                        best_path = path_to[dep]

                longest[slug] = max_len + 1
                path_to[slug] = best_path + [slug]

    if not longest:
        return [], 0

    max_slug = max(longest.keys(), key=lambda s: longest[s])
    return path_to[max_slug], longest[max_slug]


# =============================================================================
# Metrics
# =============================================================================

def compute_map_metrics(
    epics: list[dict],
    waves: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Compute parallelism metrics for a map.

    Returns dict with: total_epics, wave_count, max_parallelism,
    wave0_ratio, critical_path_length.
    """
    if waves is None:
        waves = compute_epic_waves(epics)

    wave_groups = group_epic_waves(waves)
    total = len(waves)
    wave0_count = len(wave_groups.get(0, []))

    _, cp_length = compute_epic_critical_path(epics, waves)

    return {
        "total_epics": total,
        "wave_count": len(wave_groups),
        "max_parallelism": max(
            (len(v) for v in wave_groups.values()), default=0
        ),
        "wave0_count": wave0_count,
        "wave0_ratio": wave0_count / total if total > 0 else 0,
        "critical_path_length": cp_length,
        "waves": wave_groups,
    }


# =============================================================================
# Full Map Parsing
# =============================================================================

def parse_map(map_path: Path, epics_base: Path) -> dict[str, Any]:
    """
    Parse a complete map: reads MAP.md, resolves each epic against disk,
    and aggregates statistics.

    Args:
        map_path: Path to the map directory containing MAP.md
        epics_base: Base directory where epic directories live
                    (e.g., spoq/epics/active/)

    Returns dict with metadata, epics (with resolution status), and stats.
    """
    metadata = parse_map_md(map_path)
    if "error" in metadata:
        return metadata

    epics_data = metadata["epics"]
    resolved_epics = []

    for epic_entry in epics_data:
        slug = epic_entry["slug"]
        epic_dir = epics_base / slug

        entry = {
            "slug": slug,
            "status": epic_entry["status"],
            "dependencies": epic_entry["dependencies"],
            "summary": epic_entry["summary"],
            "resolved": False,
        }

        if epic_dir.exists() and epic_dir.is_dir():
            entry["resolved"] = True
            entry["epic_path"] = str(epic_dir)

            # Import epic_utils for task-level stats
            try:
                import epic_utils
                epic_data = epic_utils.parse_epic(epic_dir)
                if "error" not in epic_data:
                    entry["task_stats"] = epic_data.get("stats", {})
            except ImportError:
                pass  # epic_utils not on path; skip task aggregation

        resolved_epics.append(entry)

    # Compute waves and metrics from MAP.md epic entries
    waves = compute_epic_waves(epics_data)
    metrics = compute_map_metrics(epics_data, waves)
    cp_path, cp_length = compute_epic_critical_path(epics_data, waves)

    resolved_count = sum(1 for e in resolved_epics if e["resolved"])

    return {
        "map_path": str(map_path),
        "map_name": map_path.name,
        "title": metadata["title"],
        "vision": metadata["vision"],
        "epics": resolved_epics,
        "stats": {
            "total_epics": len(resolved_epics),
            "resolved_epics": resolved_count,
            "unresolved_epics": len(resolved_epics) - resolved_count,
            "critical_path": cp_path,
            "critical_path_length": cp_length,
            "wave_count": metrics["wave_count"],
            "max_parallelism": metrics["max_parallelism"],
        },
    }


# =============================================================================
# Map Status Rollup
# =============================================================================

def get_map_status(map_path: Path, epics_base: Path) -> dict[str, Any]:
    """
    Compute per-epic status rollup from task statuses and map completion %.

    For resolved epics, reads task YAML files to determine status.
    For unresolved epics, reports status from MAP.md.

    Returns dict with per-epic status and overall progress.
    """
    metadata = parse_map_md(map_path)
    if "error" in metadata:
        return metadata

    epics_data = metadata["epics"]
    epic_statuses = {}
    total_tasks = 0
    completed_tasks = 0

    for epic_entry in epics_data:
        slug = epic_entry["slug"]
        epic_dir = epics_base / slug

        if epic_dir.exists() and epic_dir.is_dir():
            try:
                import epic_utils
                tasks = epic_utils.load_tasks(epic_dir)
                valid = [t for t in tasks if "error" not in t]
                task_count = len(valid)
                done = sum(
                    1 for t in valid if t.get("status") == "completed"
                )
                in_prog = sum(
                    1 for t in valid if t.get("status") == "in_progress"
                )

                total_tasks += task_count
                completed_tasks += done

                if task_count == 0:
                    epic_status = "empty"
                elif done == task_count:
                    epic_status = "completed"
                elif in_prog > 0 or done > 0:
                    epic_status = "in_progress"
                else:
                    epic_status = "pending"

                epic_statuses[slug] = {
                    "status": epic_status,
                    "resolved": True,
                    "tasks_total": task_count,
                    "tasks_completed": done,
                    "tasks_in_progress": in_prog,
                    "tasks_pending": task_count - done - in_prog,
                    "progress": done / task_count if task_count > 0 else 0,
                }
            except ImportError:
                epic_statuses[slug] = {
                    "status": epic_entry["status"],
                    "resolved": True,
                    "note": "epic_utils not available for task aggregation",
                }
        else:
            epic_statuses[slug] = {
                "status": epic_entry["status"],
                "resolved": False,
            }

    overall_progress = (
        completed_tasks / total_tasks if total_tasks > 0 else 0
    )

    return {
        "map_name": map_path.name,
        "title": metadata["title"],
        "epics": epic_statuses,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "progress": overall_progress,
    }


# =============================================================================
# Map Epic Status Update
# =============================================================================

def update_epic_status_in_map(
    map_path: Path, epic_slug: str, new_status: str,
) -> dict[str, Any]:
    """Rewrite an epic's ``**Status:**`` line inside a map markdown file.

    Locates the ``### {epic_slug}`` section and replaces the first
    ``**Status**`` line it finds within that section.

    *map_path* may be a directory containing ``MAP.md`` or a standalone
    ``.md`` file.
    """
    map_md = resolve_map_file(map_path)
    if map_md is None:
        return {"error": f"Map file not found at {map_path}"}

    lines = map_md.read_text(encoding='utf-8').splitlines(keepends=True)

    in_section = False
    status_idx: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect section boundaries
        if stripped.startswith("### "):
            in_section = stripped[4:].strip() == epic_slug
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            in_section = False

        if in_section and re.match(r"[-\s]*\*\*Status", stripped, re.IGNORECASE):
            status_idx = i
            break

    if status_idx is None:
        return {
            "error": f"Epic '{epic_slug}' or its Status line not found in map",
        }

    old_line = lines[status_idx]

    # Preserve leading whitespace / bullet prefix
    prefix_match = re.match(r"^(\s*-\s*|\s*)", old_line)
    prefix = prefix_match.group(1) if prefix_match else ""

    # Preserve colon style: **Status:** vs **Status**:
    if "**Status:**" in old_line:
        lines[status_idx] = f"{prefix}**Status:** {new_status}\n"
    else:
        lines[status_idx] = f"{prefix}**Status**: {new_status}\n"

    map_md.write_text("".join(lines), encoding='utf-8')

    return {
        "map_file": str(map_md),
        "epic_slug": epic_slug,
        "old_status": old_line.strip(),
        "new_status": new_status,
    }
