#!/usr/bin/env python3
"""
Generate epic skeleton directory structure.

Usage:
    python3 generate-skeleton.py --name "my-epic" --tasks 10
    python3 generate-skeleton.py --name "my-epic" --tasks 10 --path spoq/epics/active
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime


EPIC_TEMPLATE = '''# Epic: {title}

## Overview

[TODO: 2-3 sentences describing what this epic accomplishes and why it matters]

## Architecture

```
[TODO: ASCII diagram showing components and data flow]

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Component A │────►│ Component B │────►│ Component C │
└─────────────┘     └─────────────┘     └─────────────┘
```

## Components

### 1. [Component Name]
- Key responsibility
- Files/modules involved

### 2. [Component Name]
- Key responsibility
- Files/modules involved

### 3. [Component Name]
- Key responsibility
- Files/modules involved

## Success Criteria

- [ ] [Specific, measurable criterion 1]
- [ ] [Specific, measurable criterion 2]
- [ ] [Service verification: `curl http://localhost:8080/health`]
- [ ] [Test verification: `npm test` passes]
- [ ] [Build verification: `npm run build` succeeds]

## Task Dependencies

```
[TODO: ASCII DAG showing task relationships]

    01 ──────────┐
                 │
    02 ──────────┼──► 04 ──► 06
                 │         ↗
    03 ──────────┴──► 05 ─┘
```

## Dispatch Strategy

**Wave 0 (Parallel):** Tasks 01, 02, 03
- Foundation setup, no dependencies

**Wave 1 (Parallel):** Tasks 04, 05
- Core implementation, require Wave 0

**Wave 2 (Sequential):** Task 06
- Integration and testing, requires Wave 1

**Critical Path:** 01 → 04 → 06 (3 tasks)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [Dependency issue] | Medium | High | [Early validation] |
| [Integration complexity] | Low | Medium | [Incremental testing] |

---
Generated: {timestamp}
'''

TASK_TEMPLATE = '''id: {id}
title: {title}
epic: {epic}
status: pending
priority: {priority}
phase: {phase}

dependencies: {deps}

skills_required:
  - [skill-name]

files_to_touch:
  - [path/to/file]

outputs:
  - [Concrete deliverable]

acceptance_criteria:
  - [ ] [Criterion with verification command]
  - [ ] [Another measurable criterion]

description: |
  ## Objective

  [One sentence: what this task accomplishes]

  ## Prerequisites

  - [Required tool, service, or configuration]

  ## Steps

  1. **[Step description]**
     ```bash
     # command to run
     ```
     Expected output or next action

  2. **[Next step]**
     - Sub-step a
     - Sub-step b

  ## Verification

  ```bash
  # Command to verify completion
  # Expected output
  ```

  ## Error Handling

  If [X] fails:
  ```bash
  # Recovery command
  ```
'''


def generate_skeleton(name: str, task_count: int, base_path: Path):
    """Generate epic directory structure with templates."""
    epic_slug = name.lower().replace(" ", "-").replace("_", "-")
    epic_path = base_path / epic_slug
    tasks_path = epic_path / "tasks"

    # Check if already exists
    if epic_path.exists():
        print(f"Error: Epic already exists: {epic_path}", file=sys.stderr)
        sys.exit(1)

    # Create directories
    tasks_path.mkdir(parents=True, exist_ok=True)

    # Generate EPIC.md
    epic_content = EPIC_TEMPLATE.format(
        title=name.title(),
        task_count=task_count,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    epic_file = epic_path / "EPIC.md"
    epic_file.write_text(epic_content, encoding='utf-8')
    print(f"Created: {epic_file}")

    # Calculate wave distribution
    # Aim for ~30% in Wave 0, ~40% in Wave 1, ~30% in later waves
    wave0_count = max(1, int(task_count * 0.3))
    wave1_count = max(1, int(task_count * 0.4))
    later_count = task_count - wave0_count - wave1_count

    # Generate task files
    task_num = 1
    priorities = ["critical", "high", "medium", "medium", "low"]

    # Wave 0 tasks (no dependencies)
    for i in range(wave0_count):
        task_id = f"{task_num:02d}-task-{task_num}"
        priority = priorities[min(i, len(priorities) - 1)]
        task_content = TASK_TEMPLATE.format(
            id=task_id,
            title=f"Task {task_num}: [Description]",
            epic=epic_slug,
            phase=0,
            priority=priority,
            deps="[]"
        )
        task_file = tasks_path / f"{task_id}.yml"
        task_file.write_text(task_content, encoding='utf-8')
        print(f"Created: {task_file}")
        task_num += 1

    # Wave 1 tasks (depend on Wave 0)
    wave0_deps = [f"{i:02d}-task-{i}" for i in range(1, wave0_count + 1)]
    for i in range(wave1_count):
        task_id = f"{task_num:02d}-task-{task_num}"
        priority = priorities[min(i + wave0_count, len(priorities) - 1)]
        # Each Wave 1 task depends on a Wave 0 task
        dep_idx = i % wave0_count
        deps = f"[{wave0_deps[dep_idx]}]"
        task_content = TASK_TEMPLATE.format(
            id=task_id,
            title=f"Task {task_num}: [Description]",
            epic=epic_slug,
            phase=1,
            priority=priority,
            deps=deps
        )
        task_file = tasks_path / f"{task_id}.yml"
        task_file.write_text(task_content, encoding='utf-8')
        print(f"Created: {task_file}")
        task_num += 1

    # Later wave tasks (depend on Wave 1)
    wave1_start = wave0_count + 1
    wave1_deps = [f"{i:02d}-task-{i}" for i in range(wave1_start, wave1_start + wave1_count)]
    for i in range(later_count):
        task_id = f"{task_num:02d}-task-{task_num}"
        priority = "medium"
        # Each later task depends on a Wave 1 task
        dep_idx = i % max(1, len(wave1_deps))
        deps = f"[{wave1_deps[dep_idx]}]" if wave1_deps else "[]"
        phase = 2 + (i // max(1, later_count // 2))  # Spread across waves 2+
        task_content = TASK_TEMPLATE.format(
            id=task_id,
            title=f"Task {task_num}: [Description]",
            epic=epic_slug,
            phase=phase,
            priority=priority,
            deps=deps
        )
        task_file = tasks_path / f"{task_id}.yml"
        task_file.write_text(task_content, encoding='utf-8')
        print(f"Created: {task_file}")
        task_num += 1

    # Summary
    print("")
    print("=" * 50)
    print(f"Epic skeleton created: {epic_path}")
    print("=" * 50)
    print("")
    print("Next steps:")
    print(f"  1. Edit {epic_file} with your architecture and criteria")
    print(f"  2. Rename and customize task files in {tasks_path}")
    print(f"  3. Update dependencies to match your actual DAG")
    print(f"  4. Validate: python3 .claude/skills/epic-planning/scripts/validate-epic.py {epic_path}")
    print(f"  5. Analyze: python3 .claude/skills/epic-planning/scripts/analyze-dag.py {epic_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate epic skeleton directory structure"
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="Epic name (will be converted to slug)"
    )
    parser.add_argument(
        "--tasks", "-t",
        type=int,
        default=8,
        help="Number of task files to generate (default: 8)"
    )
    parser.add_argument(
        "--path", "-p",
        type=Path,
        default=Path("spoq/epics/active"),
        help="Base path for epics (default: spoq/epics/active)"
    )

    args = parser.parse_args()

    if args.tasks < 3:
        print("Error: Minimum 3 tasks required", file=sys.stderr)
        sys.exit(1)

    if args.tasks > 30:
        print("Warning: Large epics (>30 tasks) should be split into sub-epics",
              file=sys.stderr)

    generate_skeleton(args.name, args.tasks, args.path)


if __name__ == "__main__":
    main()
