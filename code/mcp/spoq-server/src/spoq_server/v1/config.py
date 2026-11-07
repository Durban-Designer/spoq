"""Refresh project-local MCP launchers without losing client configuration."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path

import tomlkit


def _mapping(value, label):
    if not isinstance(value, MutableMapping):
        raise ValueError(f'{label} must be an object/table; original configuration was not changed')
    return value


def _entry(servers, root):
    _mapping(servers, 'MCP servers')
    if 'spoq' not in servers:
        servers['spoq'] = {}
    entry = _mapping(servers['spoq'], 'SPOQ MCP registration')
    env = _mapping(entry.get('env', {}), 'SPOQ environment')
    # Replace only the SPOQ launch route; retain unrelated per-server preferences.
    for key in ('url', 'headers', 'transport', 'http_headers', 'bearer_token_env_var'):
        entry.pop(key, None)
    entry['command'] = 'spoq'
    entry['args'] = ['mcp', '--root', str(root)]
    entry['env'] = {**env, 'SPOQ_STORE': 'sqlite'}
    if 'type' in entry:
        entry['type'] = 'stdio'


CONFIG_PATHS = {'claude': '.mcp.json', 'qwen': '.qwen/settings.json',
                'cursor': '.cursor/mcp.json', 'codex': '.codex/config.toml'}


def detect_agents(root):
    from spoq_server.agents import AGENTS
    names = {'spoq', 'spoq-plan', 'epic-planning', 'agent-execution'}
    found = []
    for key, spec in AGENTS.items():
        folder = root / spec.commands_root
        alternatives = [folder]
        if key == 'codex': alternatives.append(root / '.codex/prompts')
        if key == 'claude': alternatives.append(root / '.claude/commands')
        if any((base/name/'SKILL.md').is_file() or (base/(name+suffix)).is_file()
               for base in alternatives for name in names for suffix in ('.md','.toml')):
            found.append(key)
            continue
        path = root / CONFIG_PATHS[key]
        if path.is_file():
            try:
                value = tomlkit.parse(path.read_text()) if key=='codex' else json.loads(path.read_text())
                if 'spoq' in value.get('mcp_servers' if key=='codex' else 'mcpServers', {}):
                    found.append(key)
            except (ValueError, AttributeError, TypeError, tomlkit.exceptions.ParseError) as exc:
                raise ValueError(f'Invalid client configuration {path}; original was not changed') from exc
    return found or ['claude']


def plan_configuration(root: Path, agents: list[str], *, existing_only=False) -> dict[Path, str]:
    """Validate all selected configurations before any initialization writes."""
    planned = {}
    for agent in agents:
        path = root / CONFIG_PATHS[agent]
        if existing_only and not path.is_file():
            continue
        original = path.read_text() if path.exists() else ''
        try:
            if agent == 'codex':
                value = tomlkit.parse(original)
                if 'mcp_servers' in value:
                    _mapping(value['mcp_servers'], 'MCP servers')
                if existing_only and 'spoq' not in value.get('mcp_servers', {}):
                    continue
                if 'mcp_servers' not in value:
                    value['mcp_servers'] = tomlkit.table()
                _entry(value['mcp_servers'], root)
                rendered = tomlkit.dumps(value)
            else:
                value = json.loads(original) if path.exists() else {}
                _mapping(value, str(path))
                if 'mcpServers' in value:
                    _mapping(value['mcpServers'], 'MCP servers')
                if existing_only and 'spoq' not in value.get('mcpServers', {}):
                    continue
                if 'mcpServers' not in value:
                    value['mcpServers'] = {}
                _entry(value['mcpServers'], root)
                rendered = json.dumps(value, indent=2, allow_nan=False) + '\n'
        except (ValueError, tomlkit.exceptions.ParseError) as exc:
            raise ValueError(f'Invalid MCP configuration {path}: {exc}') from exc
        planned[path] = rendered
    return planned


def write_configuration(root: Path, planned: dict[Path, str]) -> list[dict]:
    """Back up changed registrations and publish each file atomically."""
    from .db import uid
    changes = []
    for path, rendered in planned.items():
        original = path.read_bytes() if path.exists() else None
        if original == rendered.encode():
            continue
        change = {'path': str(path.relative_to(root))}
        if original is not None:
            backup = root / '.spoq/legacy-mcp' / path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                backup = backup.with_name(backup.name + '-' + uid())
            backup.write_bytes(original)
            backup.chmod(0o600)
            change['backup'] = str(backup.relative_to(root))
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
        try:
            with os.fdopen(descriptor, 'w') as output:
                output.write(rendered)
                output.flush()
                os.fsync(output.fileno())
            if path.exists():
                os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        changes.append(change)
    return changes
