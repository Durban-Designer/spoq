"""Utility MCP tools for SPOQ."""

import json
from datetime import datetime, timezone
from pathlib import Path

from spoq_server.server import mcp, project_root


@mcp.tool()
def spoq_get_timestamp(format: str = "iso") -> str:
    """Get current UTC timestamp in the requested format.

    Args:
        format: One of "iso" (default), "unix", or "readable".

    Returns the timestamp string directly.
    """
    now = datetime.now(timezone.utc)

    if format == "iso":
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif format == "unix":
        return str(int(now.timestamp()))
    elif format == "readable":
        return now.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        return f"Unknown format '{format}'. Use: iso, unix, readable"


@mcp.tool()
def spoq_generate_skeleton(name: str, task_count: int, path: str = "") -> str:
    """Generate an epic skeleton directory structure with templates.

    Args:
        name: Epic name (will be converted to slug).
        task_count: Number of task files to generate (minimum 3).
        path: Base path for the epic. Defaults to spoq/epics/active/ in project root.

    Returns JSON with paths_created list and epic_path.
    """
    try:
        if task_count < 3:
            return json.dumps({"error": "Minimum 3 tasks required for a valid epic"})

        epic_slug = name.lower().replace(" ", "-").replace("_", "-")

        if path:
            base_path = Path(path)
            if not base_path.is_absolute():
                base_path = project_root() / path
        else:
            base_path = project_root() / "spoq" / "epics" / "active"

        epic_path = base_path / epic_slug
        tasks_path = epic_path / "tasks"

        if epic_path.exists():
            return json.dumps({"error": f"Epic already exists: {epic_path}"})

        tasks_path.mkdir(parents=True, exist_ok=True)
        paths_created = [str(epic_path), str(tasks_path)]

        # Generate EPIC.md
        epic_content = f"""# Epic: {name.title()}

## Overview

[TODO: 2-3 sentences describing what this epic accomplishes and why it matters]

## Architecture

```
[TODO: ASCII diagram showing components and data flow]
```

## Components

### 1. [Component Name]
- Key responsibility
- Files/modules involved

## Success Criteria

- [ ] [Specific, measurable criterion 1]
- [ ] [Specific, measurable criterion 2]
- [ ] [Build verification: test command passes]
- [ ] [Integration verification: service health check]
- [ ] [Documentation updated]

## Task Dependencies

```
[TODO: ASCII DAG showing task relationships]
```

## Dispatch Strategy

**Wave 0 (Parallel):** Foundation tasks
**Wave 1 (Parallel):** Core implementation
**Wave 2 (Sequential):** Integration and testing
"""
        epic_file = epic_path / "EPIC.md"
        epic_file.write_text(epic_content, encoding='utf-8')
        paths_created.append(str(epic_file))

        # Calculate wave distribution: ~30% Wave 0, ~40% Wave 1, ~30% later
        wave0_count = max(1, int(task_count * 0.3))
        wave1_count = max(1, int(task_count * 0.4))
        later_count = task_count - wave0_count - wave1_count

        priorities = ["critical", "high", "medium", "medium", "low"]
        task_num = 1

        # Wave 0 tasks
        wave0_ids = []
        for i in range(wave0_count):
            task_id = f"{task_num:02d}-task-{task_num}"
            wave0_ids.append(task_id)
            priority = priorities[min(i, len(priorities) - 1)]
            content = _task_template(task_id, epic_slug, 0, priority, "[]")
            task_file = tasks_path / f"{task_id}.yml"
            task_file.write_text(content, encoding='utf-8')
            paths_created.append(str(task_file))
            task_num += 1

        # Wave 1 tasks
        wave1_ids = []
        for i in range(wave1_count):
            task_id = f"{task_num:02d}-task-{task_num}"
            wave1_ids.append(task_id)
            dep_idx = i % len(wave0_ids)
            deps = f"[{wave0_ids[dep_idx]}]"
            priority = priorities[min(i + wave0_count, len(priorities) - 1)]
            content = _task_template(task_id, epic_slug, 1, priority, deps)
            task_file = tasks_path / f"{task_id}.yml"
            task_file.write_text(content, encoding='utf-8')
            paths_created.append(str(task_file))
            task_num += 1

        # Later wave tasks
        for i in range(later_count):
            task_id = f"{task_num:02d}-task-{task_num}"
            dep_idx = i % max(1, len(wave1_ids))
            deps = f"[{wave1_ids[dep_idx]}]" if wave1_ids else "[]"
            phase = 2 + (i // max(1, later_count // 2))
            content = _task_template(task_id, epic_slug, phase, "medium", deps)
            task_file = tasks_path / f"{task_id}.yml"
            task_file.write_text(content, encoding='utf-8')
            paths_created.append(str(task_file))
            task_num += 1

        return json.dumps({
            "epic_path": str(epic_path),
            "epic_name": epic_slug,
            "task_count": task_count,
            "paths_created": paths_created,
            "wave_distribution": {
                "wave_0": wave0_count,
                "wave_1": wave1_count,
                "later": later_count,
            },
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def _task_template(task_id: str, epic: str, phase: int, priority: str, deps: str) -> str:
    """Generate a task YAML template."""
    return f"""id: {task_id}
title: "Task: [Description]"
epic: {epic}
status: pending
priority: {priority}
phase: {phase}

dependencies: {deps}

skills_required:
  - "[skill-name]"

files_to_touch:
  - "[path/to/file]"

acceptance_criteria:
  - "[ ] [Criterion with verification command]"

description: |
  ## Objective

  [One sentence: what this task accomplishes]

  ## Steps

  1. [Step one]
  2. [Step two]

  ## Verification

  [How to verify completion]
"""
