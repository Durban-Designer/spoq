"""SPOQ project initialization command.

Bootstraps a project directory with SPOQ structure, templates, and
optional MCP configuration. Replaces the shell-based spoq-init.sh
for users who install SPOQ via pip/PyPI.

Skills are bundled as package data in data/skills/ and copied during
init. To update bundled skills, sync from .claude/skills/ in the
source repository.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from spoq_server.agents import (
    AGENTS,
    AgentSpec,
    install_commands,
    parse_agents,
    roles_section,
    setup_agent_mcp,
)


# =============================================================================
# Package data location — bundled skills shipped with the wheel
# =============================================================================

_PACKAGE_DIR = Path(__file__).resolve().parent
_BUNDLED_SKILLS_DIR = _PACKAGE_DIR / "data" / "skills"

# Core skills always installed
CORE_SKILLS = [
    "epic-planning",
    "epic-validation",
    "task-validation",
    "agent-execution",
    "workflow-execute",
    "team-execution",
    "agent-validation",
    "journal-tracker",
    "skill-maker",
    "lib",
]

# Skills that only make sense for Claude Code and must NOT be ported to other
# agents. workflow-execute compiles an epic into a Claude Code dynamic workflow;
# the runtime is Claude-family-only (a stage cannot route to gpt-5.5 / qwen),
# so porting it to Qwen/Codex would produce a command referencing a runtime
# they do not have. These install for Claude but are skipped for other agents.
CLAUDE_ONLY_SKILLS = {"workflow-execute"}


# =============================================================================
# Templates — CLAUDE.md, journal.md, ROADMAP.yml, epics README
# =============================================================================

# MCP-registration guidance per agent, embedded in the context file.
_MCP_GUIDANCE = {
    "claude": """Configure in `.mcp.json`:

```json
{
  "mcpServers": {
    "spoq": {
      "command": "spoq",
      "args": ["mcp"]
    }
  }
}
```""",
    "qwen": """Configure in `.qwen/settings.json`:

```json
{
  "mcpServers": {
    "spoq": {
      "command": "spoq",
      "args": ["mcp"]
    }
  }
}
```""",
    "codex": """Configure in `.codex/config.toml`:

```toml
[mcp_servers.spoq]
command = "spoq"
args = ["mcp"]
```""",
    "cursor": """Configure in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "spoq": {
      "command": "spoq",
      "args": ["mcp"]
    }
  }
}
```""",
}


def _context_md(spec: AgentSpec) -> str:
    """Render the SPOQ context file (CLAUDE.md / QWEN.md / AGENTS.md).

    The SPOQ guidance is identical across agents; only the commands location
    and MCP-registration snippet differ.
    """
    mcp_guidance = _MCP_GUIDANCE[spec.key]
    roles = roles_section(spec)
    roles_block = f"\n{roles}" if roles else ""
    invoke = "$" if spec.key == "codex" else "/"
    artifact_label = (
        "skills" if spec.key == "codex" else "commands and skill definitions"
    )
    return f"""\
# Project Guidelines

## SPOQ Methodology

This project uses [SPOQ](https://spoqpaper.com) (Specialist Orchestrated Queuing) for multi-agent development with {spec.label}.

### Common Commands

```bash
# Plan an epic
{invoke}epic-planning "Feature description"

# Validate an epic
{invoke}epic-validation @spoq/epics/active/epic-name

# Execute an epic
{invoke}agent-execution @spoq/epics/active/epic-name

# Execute with agent teams (persona-specialized)
{invoke}team-execution @spoq/epics/active/epic-name

# Validate completed work
{invoke}agent-validation

# Plan a multi-epic program
{invoke}epic-planning --map "Program name"
```

### Validation Thresholds

- **Planning**: 95 avg / 90 min
- **Code**: 95 avg / 80 min

### Repository Structure

- `{spec.commands_root}/` - SPOQ {artifact_label}
- `code/` - Application source code
- `documents/` - Documentation
- `spoq/epics/` - Epic and task definitions
- `spoq/maps/` - Multi-epic program maps
- `infrastructure/` - Docker and Terraform configs
- `tests/` - Integration and end-to-end tests
- `journal.md` - Development journal
- `TODO.yml` - Time-boxed task tracker

### MCP Server

The SPOQ MCP server provides tools for epic, map, and task management.
{mcp_guidance}
{roles_block}
### Workflow

1. **Plan** — `{invoke}epic-planning` decomposes goals into atomic tasks
2. **Validate** — `{invoke}epic-validation` scores against 10 quality metrics
3. **Execute** — `{invoke}agent-execution` dispatches parallel agent swarms
4. **Verify** — `{invoke}agent-validation` scores delivered code

### Git Operations

- NEVER create commits automatically - user handles git
- Update journal.md when completing significant work
"""

JOURNAL_MD_TEMPLATE = """\
# Development Journal

This journal tracks all AI agent work sessions with timestamps, confidence scores, and detailed summaries.

## Journal Format

Each entry includes:
- **Agent**: Name of AI assistant
- **Timestamps**: Start/end times (UTC)
- **Confidence**: 0.0-1.0 quality score
- **Session Type**: Category of work (development, refactor, bugfix, planning, etc.)
- **Files Modified**: List of changed files

---

"""

def _roadmap_yml_content() -> str:
    """Generate a fresh ROADMAP.yml with the current UTC timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""\
version: 1
updated_at: "{ts}"
epics: []
"""


ROADMAP_YML_TEMPLATE = _roadmap_yml_content

TODO_YML_TEMPLATE = """\
version: "1"
updated: "<timestamp>"

sections: []

standalone: []

maps: []
"""

EPICS_README_TEMPLATE = """\
# Epic Definitions

This directory contains SPOQ epic definitions.

## Structure

Each epic is a directory containing:
```
epic-name/
├── EPIC.md         # Epic overview, architecture, waves
└── tasks/          # Task YAML files
    ├── 01-task.yml
    ├── 02-task.yml
    └── ...
```

## Creating an Epic

```bash
/epic-planning "Your feature description"
```

## Running an Epic

```bash
# Validate first
/epic-validation @spoq/epics/active/your-epic

# Then execute
/agent-execution @spoq/epics/active/your-epic
```

## Examples

See `example-config-validator/` for a complete working example.
"""


# =============================================================================
# 5-Category Directory Structure
# =============================================================================

# Directories created for every init (fresh or upgrade). Agent-specific
# command directories (.claude/skills, .qwen/commands, .agents/skills) are
# created by each agent's installer, not here.
DIRECTORIES = [
    "code",
    "documents",
    "infrastructure/docker",
    "infrastructure/terraform",
    "spoq/epics/active",
    "spoq/epics/backlog",
    "spoq/epics/complete",
    "spoq/maps/active",
    "spoq/maps/backlog",
    "spoq/maps/complete",
    "tests",
]


# =============================================================================
# Public API
# =============================================================================

def run_init(
    target: str = ".",
    full: bool = False,
    with_mcp: bool = False,
    upgrade: bool = False,
    agents: str | list[str] | None = None,
) -> None:
    """Bootstrap or upgrade SPOQ in the target directory.

    ``agents`` selects which coding agents to scaffold for (any of
    ``claude``, ``qwen``, ``codex``, ``cursor``); defaults to Claude only.
    """
    specs = [AGENTS[key] for key in parse_agents(agents)]
    target_path = Path(target).resolve()

    if not target_path.exists():
        target_path.mkdir(parents=True)
        print(f"Created directory: {target_path}")

    if upgrade:
        _upgrade(target_path, specs)
    else:
        _fresh_init(target_path, specs, full=full)

    if with_mcp:
        for spec in specs:
            if spec.key == "claude":
                _setup_mcp(target_path)
            else:
                print(setup_agent_mcp(spec, target_path))

    # Configure Claude Code permissions for MCP tools when Claude is targeted.
    if any(spec.key == "claude" for spec in specs):
        _setup_claude_settings(target_path)

    labels = ", ".join(spec.label for spec in specs)
    invoke = "$" if specs[0].key == "codex" else "/"
    print(f"\nSPOQ initialized in: {target_path}")
    print(f"Coding agents: {labels}")
    print("\nNext steps:")
    print(f"  1. Open the project in {specs[0].label}")
    print(f"  2. Run {invoke}epic-planning to plan your first epic")
    print(f"  3. Run {invoke}epic-validation to verify quality")
    print(f"  4. Run {invoke}agent-execution to dispatch agent swarms")


# =============================================================================
# Fresh init
# =============================================================================

def _fresh_init(target: Path, specs: list[AgentSpec], full: bool = False) -> None:
    """Create fresh SPOQ project structure."""
    # Directory structure (5-category model)
    for d in DIRECTORIES:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Per-agent context files (CLAUDE.md / QWEN.md / AGENTS.md)
    for spec in specs:
        _write_context_file(target, spec)

    # journal.md
    journal = target / "journal.md"
    if not journal.exists():
        journal.write_text(encoding="utf-8", data=JOURNAL_MD_TEMPLATE)
        print("  Created journal.md")

    # ROADMAP.yml
    roadmap = target / "spoq" / "ROADMAP.yml"
    if not roadmap.exists():
        roadmap.write_text(encoding="utf-8", data=ROADMAP_YML_TEMPLATE())
        print("  Created spoq/ROADMAP.yml")

    # TODO.yml
    todo_yml = target / "TODO.yml"
    if not todo_yml.exists():
        todo_yml.write_text(encoding="utf-8", data=TODO_YML_TEMPLATE)
        print("  Created TODO.yml")

    # spoq/epics/README.md
    epics_readme = target / "spoq" / "epics" / "README.md"
    if not epics_readme.exists():
        epics_readme.write_text(encoding="utf-8", data=EPICS_README_TEMPLATE)
        print("  Created spoq/epics/README.md")

    # SPOQ commands for each selected agent
    for spec in specs:
        _install_agent_commands(target, spec)

    # Example epic (if --full)
    if full:
        _create_example_epic(target)

    print(f"  Created {len(DIRECTORIES)} directories")


# =============================================================================
# Per-agent context files and command installation
# =============================================================================

def _write_context_file(target: Path, spec: AgentSpec) -> None:
    """Write an agent's context file, skipping if it already exists."""
    context = target / spec.context_file
    if context.exists():
        print(f"  {spec.context_file} already exists (skipped)")
        return
    context.write_text(encoding="utf-8", data=_context_md(spec))
    print(f"  Created {spec.context_file}")


def _install_agent_commands(target: Path, spec: AgentSpec) -> None:
    """Install SPOQ commands or skills for one agent in its native format."""
    if spec.key == "claude":
        _install_skills(target)
        return

    if not _BUNDLED_SKILLS_DIR.is_dir():
        print(f"  WARNING: Bundled skills not found, cannot port commands for {spec.label}")
        return

    # Claude-only skills (e.g. workflow-execute) are not ported to other agents.
    portable_skills = [s for s in CORE_SKILLS if s not in CLAUDE_ONLY_SKILLS]
    count = install_commands(spec, _BUNDLED_SKILLS_DIR, portable_skills, target)
    if count:
        noun = "skills" if spec.key == "codex" else "commands"
        print(f"  Installed {count} {spec.label} {noun} in {spec.commands_root}/")


# =============================================================================
# Skills installation — copies bundled package data
# =============================================================================

def _install_skills(target: Path) -> None:
    """Copy full skill definitions from bundled package data."""
    skills_dir = target / ".claude" / "skills"
    copied = 0
    skipped = 0

    if not _BUNDLED_SKILLS_DIR.is_dir():
        print("  WARNING: Bundled skills not found, creating stubs instead")
        _create_skill_stubs_fallback(target)
        return

    for skill_name in CORE_SKILLS:
        src = _BUNDLED_SKILLS_DIR / skill_name
        dst = skills_dir / skill_name

        if not src.is_dir():
            continue

        if dst.exists():
            # Check if existing skill is a stub (< 50 lines in SKILL.md)
            skill_md = dst / "SKILL.md"
            if skill_md.exists():
                line_count = len(skill_md.read_text(encoding="utf-8").splitlines())
                if line_count >= 50:
                    skipped += 1
                    continue
            # Overwrite stubs with full skills
            shutil.rmtree(dst)

        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        copied += 1

    if copied:
        print(f"  Installed {copied} skills (full definitions)")
    if skipped:
        print(f"  Skipped {skipped} skills (already present)")


def _create_skill_stubs_fallback(target: Path) -> None:
    """Fallback: create minimal skill stubs when package data is missing.

    This path should only be reached in development or broken installs.
    """
    _STUB_DESCRIPTIONS = {
        "epic-planning": "Decompose high-level goals into structured epics with atomic tasks, dependency DAGs, and wave-based phases. Use when planning new features, migrations, or complex initiatives in spoq/epics/.",
        "epic-validation": "Validate EPIC.md files and task sets with 10 planning-focused metrics (0-100). Use after epic planning and before agent-execution. Pass threshold 95+.",
        "agent-execution": "Orchestrate parallel sub-agent swarms on automation epics. Use when running /agent-execution @spoq/epics/epic-name to execute multi-task epics with Opus workers and Sonnet QA.",
        "workflow-execute": "Run a SPOQ epic as a Claude Code dynamic workflow with deterministic compiled dispatch. Use when running /workflow-execute @spoq/epics/active/epic-name. Claude Code only; degrades to /agent-execution when workflows are unavailable.",
        "agent-validation": "Validate sub-agent work against task definitions with 10-metric scoring (0-100). Use after Opus completes work and code compiles. Invokes Sonnet sub-agent for review. Pass threshold 95+.",
        "team-execution": "Orchestrate wave-based agent teams with persona-specialized workers. Use when running /team-execution @spoq/epics/epic-name to execute multi-task epics with Agent Teams, inter-agent messaging, and context-preserving rework.",
        "task-validation": "Validate task YAML definitions before execution with 10 planning-focused metrics (0-100). Use after task creation and before agent-execution. Pass threshold 95+.",
        "journal-tracker": "Track AI agent work sessions in journal.md with timestamps, confidence scores, and detailed summaries. Supports auto-archiving, database parsing, and XAI/meta-orchestration integration.",
        "skill-maker": "Create new Claude Code skills following Anthropic best practices. Use when you need to create a new skill for a specific domain or workflow that doesn't exist yet.",
    }

    skills_dir = target / ".claude" / "skills"
    created = 0

    for skill_name, description in _STUB_DESCRIPTIONS.items():
        skill_dir = skills_dir / skill_name
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists():
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)
        title = skill_name.replace("-", " ").title()
        content = f"---\nname: {skill_name}\ndescription: {description}\n---\n\n# {title}\n\nThis is a stub. Install the full SPOQ package for complete skill definitions.\n"
        skill_file.write_text(encoding="utf-8", data=content)
        created += 1

    if created:
        print(f"  Created {created} skill stubs (install spoq package for full skills)")


# =============================================================================
# Example epic
# =============================================================================

def _create_example_epic(target: Path) -> None:
    """Create the example config-validator epic."""
    epic_dir = target / "spoq" / "epics" / "active" / "example-config-validator"
    if epic_dir.exists():
        print("  Example epic already exists (skipped)")
        return

    tasks_dir = epic_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # EPIC.md
    (epic_dir / "EPIC.md").write_text(encoding="utf-8", data="""\
# Epic: Example Config Validator

## Overview

A minimal example epic demonstrating SPOQ structure. Build a configuration
validator with a parser, API, and test suite across 3 execution waves.

## Architecture

```
Parser -> API -> Tests
```

## Success Criteria

- [ ] Parser handles YAML input
- [ ] API returns structured JSON
- [ ] Tests cover the full pipeline
- [ ] Dependency graph is acyclic

## Task Dependencies

```
Wave 0: 01-parser, 02-models (parallel)
Wave 1: 03-api (depends on 01, 02)
Wave 2: 04-tests (depends on 03)
```

## Dispatch Strategy

**Wave 0:** Tasks 01, 02 (parallel foundation)
**Wave 1:** Task 03 (API, depends on Wave 0)
**Wave 2:** Task 04 (tests, depends on Wave 1)
""")

    # Task YAMLs
    tasks = [
        ("01-parser.yml", "01-parser", "Config Parser", 0, "critical", "[]"),
        ("02-models.yml", "02-models", "Data Models", 0, "high", "[]"),
        ("03-api.yml", "03-api", "REST API", 1, "high", "[01-parser, 02-models]"),
        ("04-tests.yml", "04-tests", "Integration Tests", 2, "medium", "[03-api]"),
    ]

    for filename, tid, title, phase, priority, deps in tasks:
        (tasks_dir / filename).write_text(encoding="utf-8", data=f"""\
id: {tid}
title: {title}
epic: example-config-validator
status: pending
priority: {priority}
phase: {phase}

dependencies: {deps}

skills_required:
  - python

files_to_touch:
  - src/{tid.split('-')[1]}.py

acceptance_criteria:
  - "[ ] Implementation complete"
  - "[ ] Tests pass"

description: |
  ## Objective
  Implement the {title.lower()} component.

  ## Steps
  1. Create the module
  2. Add core logic
  3. Write tests

  ## Verification
  Run pytest to verify.
""")

    print("  Created example epic: example-config-validator (4 tasks)")


# =============================================================================
# Upgrade
# =============================================================================

def _upgrade(target: Path, specs: list[AgentSpec]) -> None:
    """Upgrade an existing SPOQ installation."""
    upgraded = []

    # Ensure full directory structure (5-category model)
    for d in DIRECTORIES:
        path = target / d
        if not path.exists():
            path.mkdir(parents=True)
            upgraded.append(f"Created {d}/")

    # Ensure each selected agent has its context file
    for spec in specs:
        context = target / spec.context_file
        if not context.exists():
            context.write_text(encoding="utf-8", data=_context_md(spec))
            upgraded.append(f"Created {spec.context_file}")

    # Migrate legacy structures
    legacy_automation = target / "automation" / "tasks"
    if legacy_automation.exists():
        dest = target / "spoq" / "epics" / "active"
        for item in legacy_automation.iterdir():
            if item.is_dir():
                target_dest = dest / item.name
                if not target_dest.exists():
                    shutil.move(str(item), str(target_dest))
                    upgraded.append(f"Migrated automation/tasks/{item.name} -> spoq/epics/active/")
        print("  Migrated legacy automation/tasks/ structure")

    legacy_factory = target / "factory" / "epics"
    if legacy_factory.exists():
        dest = target / "spoq" / "epics"
        for item in legacy_factory.iterdir():
            if item.is_dir():
                target_dest = dest / "active" / item.name
                if not target_dest.exists():
                    shutil.move(str(item), str(target_dest))
                    upgraded.append(f"Migrated factory/epics/{item.name} -> spoq/epics/active/")
        print("  Migrated legacy factory/ structure")

    # Install/refresh SPOQ commands for each selected agent
    for spec in specs:
        _install_agent_commands(target, spec)

    # Ensure ROADMAP.yml (auto-migrate from ROADMAP.md if needed)
    roadmap_yml = target / "spoq" / "ROADMAP.yml"
    roadmap_md = target / "spoq" / "ROADMAP.md"
    if not roadmap_yml.exists():
        roadmap_yml.write_text(encoding="utf-8", data=ROADMAP_YML_TEMPLATE())
        upgraded.append("Created spoq/ROADMAP.yml")
        if roadmap_md.exists():
            print("  NOTICE: spoq/ROADMAP.md detected — created spoq/ROADMAP.yml as the new machine-readable roadmap.")
            print("          Review and remove spoq/ROADMAP.md once migration is confirmed.")

    # Ensure TODO.yml
    todo_yml = target / "TODO.yml"
    if not todo_yml.exists():
        todo_yml.write_text(encoding="utf-8", data=TODO_YML_TEMPLATE)
        upgraded.append("Created TODO.yml")

    # Ensure epics README
    epics_readme = target / "spoq" / "epics" / "README.md"
    if not epics_readme.exists():
        epics_readme.write_text(encoding="utf-8", data=EPICS_README_TEMPLATE)
        upgraded.append("Created spoq/epics/README.md")

    if upgraded:
        print(f"  Upgraded {len(upgraded)} items")
    else:
        print("  Already up to date")


# =============================================================================
# MCP configuration
# =============================================================================

def _setup_mcp(target: Path) -> None:
    """Configure .mcp.json for the SPOQ MCP server."""
    mcp_file = target / ".mcp.json"

    mcp_config = {
        "mcpServers": {
            "spoq": {
                "command": "spoq",
                "args": ["mcp"],
            }
        }
    }

    if mcp_file.exists():
        existing = json.loads(mcp_file.read_text(encoding="utf-8"))
        servers = existing.get("mcpServers", {})
        if "spoq" not in servers:
            servers["spoq"] = mcp_config["mcpServers"]["spoq"]
            existing["mcpServers"] = servers
            mcp_file.write_text(encoding="utf-8", data=json.dumps(existing, indent=2) + "\n")
            print("  Added spoq entry to existing .mcp.json")
        else:
            print("  .mcp.json already has spoq entry (skipped)")
    else:
        mcp_file.write_text(encoding="utf-8", data=json.dumps(mcp_config, indent=2) + "\n")
        print("  Created .mcp.json")


def _setup_claude_settings(target: Path) -> None:
    """Configure .claude/settings.json with permissions to allow all SPOQ MCP tools.

    Ensures users are never prompted for permission when SPOQ tools are invoked.
    Merges into existing settings without overwriting other configuration.
    """
    settings_dir = target / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"

    spoq_permission = "mcp__spoq__*"

    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

        permissions = existing.setdefault("permissions", {})
        allow_list = permissions.setdefault("allow", [])

        if spoq_permission not in allow_list:
            allow_list.append(spoq_permission)
            settings_file.write_text(
                encoding="utf-8",
                data=json.dumps(existing, indent=2) + "\n",
            )
            print("  Added SPOQ MCP permissions to .claude/settings.json")
        else:
            print("  .claude/settings.json already allows SPOQ tools (skipped)")
    else:
        settings = {
            "permissions": {
                "allow": [spoq_permission]
            }
        }
        settings_file.write_text(
            encoding="utf-8",
            data=json.dumps(settings, indent=2) + "\n",
        )
        print("  Created .claude/settings.json with SPOQ MCP permissions")
