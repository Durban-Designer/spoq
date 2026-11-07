"""Coding-agent registry for ``spoq init``.

SPOQ can scaffold project files for more than one coding agent. Users who
alternate between Claude Code, Qwen Code, Codex, and Cursor want each agent's
native conventions written into the project. Those conventions differ along
three axes:

================ ============= ==================== =========================
Agent            Context file  Commands location    MCP registration
================ ============= ==================== =========================
Claude Code      CLAUDE.md     .claude/skills/      .mcp.json + settings.json
Qwen Code        QWEN.md       .qwen/commands/      .qwen/settings.json
Codex            AGENTS.md     .agents/skills/      .codex/config.toml
Cursor           AGENTS.md     .cursor/commands/    .cursor/mcp.json
================ ============= ==================== =========================

(Codex and Cursor both read the open ``AGENTS.md`` standard, so when both are
selected they share one context file — the first writer creates it, the
second skips.)

This module describes those conventions and renders the per-agent artifacts.
The bundled SPOQ skills (``data/skills/``) are the single source of truth for
command content; for non-Claude agents the ``SKILL.md`` body is translated
into the agent's command format (TOML for Qwen, SKILL.md for Codex, plain
Markdown for Cursor) and the skill's resource directories (``scripts/``,
``assets/``, ``references/``) plus the shared ``lib/`` are copied alongside.
Resource references inside the body — written as ``.claude/skills/<name>/...``
— are rewritten to the agent's commands root so the copied scripts and
templates resolve correctly.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

# Command-file kinds.
SKILL = "skill"  # Skill directory (SKILL.md + resources).
TOML = "toml"  # Qwen Code custom command (one .toml per command).
MD = "md"  # Cursor custom slash command (one plain .md per command).

# Resource subdirectories copied alongside a ported command.
_RESOURCE_SUBDIRS = ("scripts", "assets", "references")

# Shared skill library; copied as a sibling of the commands so scripts can
# resolve it via ``__file__.parent.parent.parent / "lib"``.
_LIB_SKILL = "lib"

# How the SKILL.md bodies reference their own resources in historical variants.
_RESOURCE_PREFIXES = (".claude/skills/", ".Codex/skills/")


@dataclass(frozen=True)
class AgentSpec:
    """Conventions for one coding agent."""

    key: str
    label: str
    context_file: str
    commands_root: str
    command_kind: str


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        key="claude",
        label="Claude Code",
        context_file="CLAUDE.md",
        commands_root=".claude/skills",
        command_kind=SKILL,
    ),
    "qwen": AgentSpec(
        key="qwen",
        label="Qwen Code",
        context_file="QWEN.md",
        commands_root=".qwen/commands",
        command_kind=TOML,
    ),
    "codex": AgentSpec(
        key="codex",
        label="Codex",
        context_file="AGENTS.md",
        commands_root=".agents/skills",
        command_kind=SKILL,
    ),
    "cursor": AgentSpec(
        key="cursor",
        label="Cursor",
        context_file="AGENTS.md",
        commands_root=".cursor/commands",
        command_kind=MD,
    ),
}

DEFAULT_AGENTS = ["claude"]

# MCP server entry shared across agents.
_SPOQ_MCP_ENTRY = {"command": "spoq", "args": ["mcp"]}


# =============================================================================
# Per-agent translation profile — model families and native tooling
# =============================================================================
#
# The bundled skills are written for Claude Code: a three-tier model hierarchy
# (Opus worker / Sonnet reviewer / Haiku investigator) dispatched via the Task
# tool. When porting to another agent we translate those references to the
# agent's own model family and tooling. Model names live here, in one place,
# so they are trivial to bump as the families evolve.
#
# Sources (verified May 2026):
#   Qwen Code  — qwen3-coder-plus / -flash; native SubAgents (fork sub-agents
#                inherit parent context) and Skills with per-skill `model`.
#                https://github.com/QwenLM/qwen-code
#   Codex      — gpt-5.5 (default) / gpt-5.4-mini (subagents); `codex exec`
#                for non-interactive runs; model via --model / config.toml.
#                https://developers.openai.com/codex/models
#   Cursor     — composer-1 (Composer agent model) / cursor-small for
#                lightweight tasks; background agents run in parallel;
#                `cursor-agent` CLI for non-interactive runs.
#                https://cursor.com/docs

# SPOQ execution role -> native model, per agent.
MODEL_ROLES: dict[str, dict[str, str]] = {
    "qwen": {
        "worker": "qwen3-coder-plus",
        "reviewer": "qwen3-coder-plus",
        "investigator": "qwen3-coder-flash",
    },
    "codex": {
        "worker": "gpt-5.5",
        "reviewer": "gpt-5.5",
        "investigator": "gpt-5.4-mini",
    },
    "cursor": {
        "worker": "composer-1",
        "reviewer": "composer-1",
        "investigator": "cursor-small",
    },
}

# Native tooling each agent uses in place of Claude Code's Task-tool swarm.
_TOOLING: dict[str, dict[str, str]] = {
    "qwen": {
        "spawn": "SubAgent",  # singular, replaces "Task tool"
        "spawn_plural": "SubAgents",  # replaces "Agent Teams"
        "exec_note": (
            "Qwen Code SubAgents (fork sub-agents inherit the parent's full "
            "context and run in parallel); read-only tools are auto-batched "
            "by smart tool parallelism."
        ),
    },
    "codex": {
        "spawn": "subagent",  # singular, replaces "Task tool"
        "spawn_plural": "subagents",  # replaces "Agent Teams"
        "exec_note": (
            "Codex subagents (gpt-5.4-mini) for lighter parallel work, or "
            "`codex exec` invocations for non-interactive task runs."
        ),
    },
    "cursor": {
        "spawn": "background agent",  # singular, replaces "Task tool"
        "spawn_plural": "background agents",  # replaces "Agent Teams"
        "exec_note": (
            "Cursor background agents (isolated parallel runs), or "
            "`cursor-agent` CLI invocations for non-interactive task runs."
        ),
    },
}


def _translations(key: str) -> list[tuple[str, str]]:
    """Ordered (regex, replacement) pairs applied to a ported body/description.

    Multi-word phrases come first so the standalone ``Claude`` rule does not
    pre-empt ``Claude Code``. Applied case-insensitively, after the resource
    path rewrite has already removed ``.claude/skills/`` references.
    """
    if key not in MODEL_ROLES:
        return []

    models = MODEL_ROLES[key]
    product = {"qwen": "Qwen Code", "codex": "Codex", "cursor": "Cursor"}[key]
    short = {"qwen": "Qwen", "codex": "Codex", "cursor": "Cursor"}[key]
    vendor = {"qwen": "Qwen", "codex": "OpenAI", "cursor": "Cursor"}[key]
    spawn = _TOOLING[key]["spawn"]
    spawn_plural = _TOOLING[key]["spawn_plural"]

    return [
        (r"\bClaude Code\b", product),
        (r"\bAnthropic\b", vendor),
        (r"\bOpus\b", models["worker"]),
        (r"\bSonnet\b", models["reviewer"]),
        (r"\bHaiku\b", models["investigator"]),
        (r"\bTask tool\b", spawn),
        (r"\bAgent Teams?\b", spawn_plural),
        (r"\bClaude\b", short),
    ]


def translate_body(key: str, text: str) -> str:
    """Rewrite Claude-specific model/tooling references for ``key``'s agent."""
    for pattern, replacement in _translations(key):
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def roles_section(spec: AgentSpec) -> str:
    """Markdown block mapping SPOQ execution roles to the agent's models.

    Embedded in the agent's context file so the role-to-model mapping and
    native orchestration tooling are documented once, globally.
    """
    if spec.key not in MODEL_ROLES:
        return ""

    models = MODEL_ROLES[spec.key]
    tooling = _TOOLING[spec.key]
    return f"""\
### SPOQ Agent Roles ({spec.label})

SPOQ's three execution tiers map to {spec.label} models as follows:

| SPOQ role | Purpose | Model |
|-----------|---------|-------|
| Worker | Task execution | `{models['worker']}` |
| Reviewer | Quality assurance | `{models['reviewer']}` |
| Investigator | Build-failure triage | `{models['investigator']}` |

Parallel execution uses {tooling['exec_note']}
"""


def parse_agents(value: str | list[str] | None) -> list[str]:
    """Normalize a ``--agents`` value into an ordered, de-duplicated key list.

    Accepts a comma-separated string (``"claude,qwen"``), a list of keys, or
    ``None`` (defaults to Claude only, preserving legacy behavior). Raises
    ``ValueError`` on unknown agent keys.
    """
    if not value:
        return list(DEFAULT_AGENTS)

    if isinstance(value, str):
        keys = [v.strip().lower() for v in value.split(",") if v.strip()]
    else:
        keys = [str(v).strip().lower() for v in value if str(v).strip()]

    unknown = [k for k in keys if k not in AGENTS]
    if unknown:
        valid = ", ".join(AGENTS)
        raise ValueError(
            f"Unknown agent(s): {', '.join(unknown)}. Choose from: {valid}"
        )

    ordered: list[str] = []
    for k in keys:
        if k not in ordered:
            ordered.append(k)
    return ordered or list(DEFAULT_AGENTS)


# =============================================================================
# Command porting — translate bundled skills into per-agent command files
# =============================================================================

def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into its YAML frontmatter dict and Markdown body."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].lstrip("\n")
    return {}, text


def _render_toml_command(description: str, body: str) -> str:
    """Render a Qwen Code ``.toml`` custom command.

    Uses a TOML literal (single-quote) multiline string for the prompt so the
    Markdown body — which contains double quotes and backslashes — needs no
    escaping. SKILL.md bodies are verified not to contain ``'''``.
    """
    return (
        f"description = {json.dumps(description)}\n"
        f"prompt = '''\n{body.rstrip()}\n'''\n"
    )


def _render_md_command(description: str, body: str) -> str:
    """Render a Cursor ``.md`` custom slash command.

    Cursor commands are plain Markdown — the file name becomes the command
    name and the file content becomes the prompt. The description leads the
    file as a blockquote so the command's purpose survives the port.
    """
    return f"> {description}\n\n{body.rstrip()}\n"


def _render_skill(name: str, description: str, body: str) -> str:
    """Render a Codex-compatible ``SKILL.md`` file."""
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        sort_keys=False,
        allow_unicode=False,
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"


def _rewrite_ported_text(spec: AgentSpec, text: str) -> str:
    """Rewrite resource text for a ported non-Claude agent."""
    resource_prefix = spec.commands_root.rstrip("/") + "/"
    for prefix in _RESOURCE_PREFIXES:
        text = text.replace(prefix, resource_prefix)
    return translate_body(spec.key, text)


def _copy_tree(
    src: Path,
    dst: Path,
    rewrite: Callable[[str], str] | None = None,
) -> None:
    """Replace ``dst`` with a copy of ``src``, skipping bytecode."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    if rewrite is None:
        return

    for path in dst.rglob("*"):
        if not path.is_file():
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = rewrite(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")


def _merge_skill_metadata(src: Path, dst: Path, backup_root: Path) -> None:
    """Refresh managed UI files without deleting custom agents or invocation policy."""
    from uuid import uuid4
    for source in src.rglob('*'):
        if not source.is_file():
            continue
        relative=source.relative_to(src)
        target=dst/relative
        content=source.read_bytes()
        if target.is_file():
            original=target.read_bytes()
            if content==original:
                continue
            if source.name=='openai.yaml':
                try:
                    before=yaml.safe_load(original) or {}
                    managed=yaml.safe_load(content) or {}
                except yaml.YAMLError as exc:
                    raise ValueError(f'Invalid skill UI metadata: {target}') from exc
                if not isinstance(before,dict) or not isinstance(managed,dict):
                    raise ValueError(f'Skill UI metadata must be a mapping: {target}')
                merged={**before,**managed}
                if 'policy' in before:
                    merged['policy']=before['policy']
                if 'interface' in managed:
                    if not isinstance(before.get('interface') or {},dict) or not isinstance(managed['interface'],dict):
                        raise ValueError(f'Skill UI interface must be a mapping: {target}')
                    merged['interface']={**(before.get('interface') or {}),**managed['interface']}
                if merged==before:
                    continue
                content=yaml.safe_dump(merged,sort_keys=False).encode()
            backup=backup_root/relative
            backup.parent.mkdir(parents=True,exist_ok=True)
            if backup.exists():
                backup=backup.with_name(backup.name+'-'+str(uuid4()))
            shutil.copy2(target,backup)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content)


def install_commands(
    spec: AgentSpec,
    bundled_skills_dir: Path,
    skill_names: list[str],
    target: Path,
) -> int:
    """Install SPOQ commands for a non-Claude agent.

    Translates each skill's ``SKILL.md`` body into the agent's command format,
    copies the skill's resource directories plus the shared ``lib/``, and
    rewrites resource references to the agent's commands root.

    Returns the number of commands written (the shared library does not count).
    """
    root = target / spec.commands_root
    root.mkdir(parents=True, exist_ok=True)
    resource_prefix = spec.commands_root.rstrip("/") + "/"
    installed = 0

    for name in skill_names:
        src = bundled_skills_dir / name
        if not src.is_dir():
            continue

        # The shared library is a resource, not a command.
        if name == _LIB_SKILL:
            _copy_tree(
                src,
                root / _LIB_SKILL,
                rewrite=lambda text, s=spec: _rewrite_ported_text(s, text),
            )
            continue

        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            continue

        meta, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
        for prefix in _RESOURCE_PREFIXES:
            body = body.replace(prefix, resource_prefix)
        body = translate_body(spec.key, body)
        if spec.command_kind in {TOML,MD}:
            suffix='.toml' if spec.command_kind==TOML else '.md'
            body=re.sub(r'\.\./([a-z0-9-]+)/SKILL\.md',lambda match:match[1]+suffix,body)
            body=re.sub(r'\.\./([a-z0-9-]+)/(scripts|references|assets)/',r'\1/\2/',body)
        description = translate_body(
            spec.key, str(meta.get("description", "")).strip()
        )
        command_name = str(meta.get("name") or name).strip()

        # Copy resource directories so the rewritten references resolve.
        for sub in _RESOURCE_SUBDIRS:
            sub_src = src / sub
            if sub_src.is_dir():
                _copy_tree(
                    sub_src,
                    root / name / sub,
                    rewrite=lambda text, s=spec: _rewrite_ported_text(s, text),
                )

        if spec.command_kind == TOML:
            (root / f"{name}.toml").write_text(
                _render_toml_command(description, body), encoding="utf-8"
            )
        elif spec.command_kind == MD:
            (root / f"{name}.md").write_text(
                _render_md_command(description, body), encoding="utf-8"
            )
        else:  # SKILL
            skill_dir = root / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _render_skill(command_name, description, body), encoding="utf-8"
            )
            if (src / 'agents').is_dir():
                _merge_skill_metadata(src/'agents',skill_dir/'agents',
                                     target/'.spoq/legacy-skill-metadata'/spec.key/name/'agents')
        installed += 1

    return installed


# =============================================================================
# MCP registration — per-agent config files
# =============================================================================

def setup_agent_mcp(spec: AgentSpec, target: Path) -> str:
    """Register the SPOQ MCP server in a non-Claude agent's config.

    Returns a human-readable status line. (Claude's MCP wiring lives in
    ``init_cmd`` so its long-standing behavior and tests stay untouched.)
    """
    if spec.key == "qwen":
        return _mcp_qwen(target)
    if spec.key == "codex":
        return _mcp_codex(target)
    if spec.key == "cursor":
        return _mcp_cursor(target)
    raise ValueError(f"setup_agent_mcp does not handle agent: {spec.key}")


def _mcp_qwen(target: Path) -> str:
    """Merge the SPOQ entry into ``.qwen/settings.json`` (``mcpServers``)."""
    settings = target / ".qwen" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    servers = data.setdefault("mcpServers", {})
    if "spoq" in servers:
        return "  .qwen/settings.json already has spoq entry (skipped)"

    servers["spoq"] = dict(_SPOQ_MCP_ENTRY)
    settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "  Registered SPOQ MCP server in .qwen/settings.json"


def _mcp_cursor(target: Path) -> str:
    """Merge the SPOQ entry into ``.cursor/mcp.json`` (``mcpServers``)."""
    config = target / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    servers = data.setdefault("mcpServers", {})
    if "spoq" in servers:
        return "  .cursor/mcp.json already has spoq entry (skipped)"

    servers["spoq"] = dict(_SPOQ_MCP_ENTRY)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "  Registered SPOQ MCP server in .cursor/mcp.json"


def _mcp_codex(target: Path) -> str:
    """Append an ``[mcp_servers.spoq]`` table to ``.codex/config.toml``."""
    config = target / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)

    existing = config.read_text(encoding="utf-8") if config.exists() else ""
    if "[mcp_servers.spoq]" in existing:
        return "  .codex/config.toml already has spoq entry (skipped)"

    block = '[mcp_servers.spoq]\ncommand = "spoq"\nargs = ["mcp"]\n'
    if existing and not existing.endswith("\n"):
        existing += "\n"
    separator = "\n" if existing else ""
    config.write_text(existing + separator + block, encoding="utf-8")

    verb = "Added spoq entry to existing" if existing else "Created"
    return f"  {verb} .codex/config.toml"
