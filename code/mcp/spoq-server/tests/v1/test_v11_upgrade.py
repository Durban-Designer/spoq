"""Cross-version upgrade contracts; optional SPOQ_V1_PYTHON uses the real 1.0 client.

Without that variable the same checks use a schema-1 fixture, so contributor CI
has no network dependency on a historical installation. Release verification runs
these four cases again against an isolated installed published1.0 environment.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tomllib
from contextlib import closing

import pytest
import tomlkit

from spoq_server.v1.db import BASE_SCHEMA
from spoq_server.v1.store import Store
from spoq_server.v1.board import Board
from spoq_server.v1.migration import database_path
from spoq_server.v1.cli import import_snapshot
from spoq_server.v1.config import CONFIG_PATHS

ROOT = Path(__file__).resolve().parents[5]
ENV = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'SPOQ_STORE', 'SPOQ_PROJECT_ROOT'}}


def command(root, *args, success=True):
    result = subprocess.run([sys.executable, '-m', 'spoq_server', *args, '--root', str(root)],
                            cwd=root, env={**ENV, 'SPOQ_STORE': 'sqlite'}, input='',
                            text=True, capture_output=True, timeout=45)
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def manifest(root):
    # SQLite read-only WAL connections can create empty WAL/SHM bookkeeping.
    # Main database bytes and all logical rows are checked separately below.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()
            and p.relative_to(root).as_posix() not in {'.spoq/spoq.db-wal', '.spoq/spoq.db-shm'}}


def assert_preserved(before, after):
    assert before['format'] == after['format']
    for name, rows in before['tables'].items():
        if name == 'meta':
            assert all(row in after['tables'][name] for row in rows)
            assert {row['key'] for row in after['tables'][name]} - {row['key'] for row in rows} <= {'schema-2-upgrade'}
        else:
            assert after['tables'][name] == rows, name


def seed_schema1(root, agent):
    old_python = os.environ.get('SPOQ_V1_PYTHON')
    if old_python:
        code = '''from pathlib import Path
import sys,spoq_server
from spoq_server.v1.cli import init
assert spoq_server.__version__ == '1.0.0', spoq_server.__version__
init(Path(sys.argv[1]),agents=sys.argv[2],with_mcp=True)
'''
        subprocess.run([old_python, '-c', code, str(root), agent], cwd=root,
                       env=ENV, check=True, text=True, capture_output=True, timeout=60)
    else:
        path = database_path(root);path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db:
            db.executescript(BASE_SCHEMA + ';PRAGMA user_version=1;')
    # These legacy APIs are unchanged, and run in the old interpreter when supplied.
    code = '''from pathlib import Path
import sys,json
from spoq_server.v1.store import Store
from spoq_server.v1.board import Board
from spoq_server.v1.migration import database_path
s=Store(database_path(Path(sys.argv[1])))
s.create('project_plan','legacy-plan','Preserved Project Plan',data={'goal':'User goal','custom':{'keep':True}})
s.create('feature','legacy-feature','Preserved Feature','legacy-plan')
s.create('task','legacy-task','Claimed Task','legacy-feature',data={'retry_count':1,'max_retries':4})
b=Board(s);b.run('old-run','legacy-feature');b.register('old-run','author','orchestrator');b.register('old-run','worker','worker')
b.post('old-run','author',['worker'],'Preserved board message',request_key='old-message')
s.claim('legacy-task','old-run','worker',ttl=3600)
s.journal('Preserved journal body',agent='Historical worker',node_id='legacy-task')
print(json.dumps(s.snapshot()))'''
    result = subprocess.run([old_python or sys.executable, '-c', code, str(root)],
                            cwd=root, env=ENV, check=True, text=True, capture_output=True, timeout=45)
    with closing(sqlite3.connect(database_path(root))) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    context = root / {'claude':'CLAUDE.md', 'qwen':'QWEN.md', 'codex':'AGENTS.md', 'cursor':'AGENTS.md'}[agent]
    context.write_text(context.read_text() + '\nUSER_POLICY_SENTINEL\n' if context.exists() else 'USER_POLICY_SENTINEL\n')
    directory = root / {'claude':'.claude/skills', 'codex':'.agents/skills', 'qwen':'.qwen/commands', 'cursor':'.cursor/commands'}[agent]
    directory.mkdir(parents=True, exist_ok=True)
    if agent in {'claude', 'codex'}:
        entry = directory/'spoq/SKILL.md';entry.parent.mkdir(exist_ok=True)
        entry.write_text('---\nname: spoq\ndescription: Old managed entry\nallowed-tools: [Read]\n---\nUSER_OLD_ENTRY_SENTINEL\n')
    else:
        entry = directory/('spoq.toml' if agent == 'qwen' else 'spoq.md')
        entry.write_text('description = "Old managed entry"\nprompt = "USER_OLD_ENTRY_SENTINEL"\n' if agent == 'qwen' else 'USER_OLD_ENTRY_SENTINEL\n')
    sibling = directory/('user-custom.toml' if agent == 'qwen' else 'user-custom.md')
    sibling.write_text('USER_CUSTOM_COMMAND_SENTINEL')
    config = root / CONFIG_PATHS[agent];config.parent.mkdir(parents=True, exist_ok=True)
    key = 'mcp_servers' if agent == 'codex' else 'mcpServers'
    data = (tomlkit.parse(config.read_text()) if agent == 'codex' else json.loads(config.read_text())) if config.exists() else {}
    servers = data.setdefault(key, {})
    servers['user_fixture'] = {'command':'user-custom-command', 'args':['USER_SERVER_SENTINEL']}
    spoq = servers.setdefault('spoq', {'command':'spoq', 'args':['mcp', '--root', str(root)]})
    spoq['custom_policy'] = 'USER_POLICY_KEEP'
    spoq.setdefault('env', {})['USER_ENV_SENTINEL'] = 'retain'
    config.write_text(tomlkit.dumps(data) if agent == 'codex' else json.dumps(data))
    return json.loads(result.stdout), context, sibling


@pytest.mark.parametrize('agent', ['claude', 'codex', 'qwen', 'cursor'])
def test_v1_database_board_claims_and_journal_upgrade_requires_consent_and_is_idempotent(tmp_path, agent):
    before, context, sibling = seed_schema1(tmp_path, agent)
    original = manifest(tmp_path)
    preview = command(tmp_path, 'workflow', 'upgrade', '--dry-run')
    assert json.loads(preview.stdout)['confirmation_required']
    assert manifest(tmp_path) == original
    assert Store(database_path(tmp_path)).snapshot() == before
    refused = command(tmp_path, 'init', '--upgrade', '--agents', agent, success=False)
    assert refused.returncode != 0 and 'confirmation' in refused.stderr
    assert manifest(tmp_path) == original
    assert Store(database_path(tmp_path)).snapshot() == before
    upgraded = command(tmp_path, 'init', '--upgrade', '--agents', agent, '--yes')
    result = json.loads(upgraded.stdout.splitlines()[-1])
    assert result['schema_upgrade']['upgraded']
    backup = Path(result['schema_upgrade']['backup']);assert backup.is_file()
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    store = Store(database_path(tmp_path))
    assert_preserved(before, store.snapshot())
    assert Board(store).inbox('old-run', 'worker')[0]['body'] == 'Preserved board message'
    assert store.get('legacy-task')['data'] == {'retry_count':1, 'max_retries':4}
    assert 'USER_POLICY_SENTINEL' in context.read_text()
    assert sibling.read_text() == 'USER_CUSTOM_COMMAND_SENTINEL'
    config = tmp_path / CONFIG_PATHS[agent]
    data = tomllib.loads(config.read_text()) if agent == 'codex' else json.loads(config.read_text())
    servers = data['mcp_servers' if agent == 'codex' else 'mcpServers']
    assert servers['user_fixture'] == {'command':'user-custom-command','args':['USER_SERVER_SENTINEL']}
    assert servers['spoq']['custom_policy'] == 'USER_POLICY_KEEP'
    assert servers['spoq']['env']['USER_ENV_SENTINEL'] == 'retain'
    assert servers['spoq']['env']['SPOQ_STORE'] == 'sqlite'
    archives = tmp_path/'.spoq/legacy-managed-skills'
    assert any('USER_OLD_ENTRY_SENTINEL' in p.read_text() for p in archives.rglob('*') if p.is_file())
    stable = manifest(tmp_path)
    command(tmp_path, 'init', '--upgrade', '--agents', agent, '--yes')
    assert manifest(tmp_path) == stable
    assert_preserved(before, store.snapshot())
    target = tmp_path/'imported';target.mkdir()
    assert import_snapshot(Store(database_path(target)), before)['imported']
    assert Store(database_path(target)).get('legacy-plan')['data']['custom'] == {'keep':True}
    assert Board(Store(database_path(target))).inbox('old-run','worker')[0]['body'] == 'Preserved board message'
    # Legacy runs are explicitly unclassified, never fabricated strategy progress.
    shown = json.loads(command(tmp_path, 'workflow', 'show', 'old-run').stdout)
    assert shown['run']['provenance'] == 'legacy_unclassified' and shown['attempts'] == []
    with closing(sqlite3.connect(database_path(tmp_path))) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def release_module():
    path = ROOT/'tests/e2e/spoq_release.py'
    if not path.is_file():pytest.skip('Contributor release harness is outside the package')
    spec = importlib.util.spec_from_file_location('release_harness', path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_release_harness_removes_checkout_and_backend_leaks_but_retains_other_environment():
    module = release_module()
    assert module.isolated_environment({'PYTHONPATH':'source','SPOQ_STORE':'fs','SPOQ_PROJECT_ROOT':'wrong',
                                        'VIRTUAL_ENV':'wrong','PATH':'allowed','HOME':'retained'}) == {'PATH':'allowed','HOME':'retained'}


def test_lowest_direct_uses_installed_artifact_metadata_including_selected_extras():
    module = release_module()
    observed = []
    def run(argv, label):
        observed.append((argv, label))
        result = subprocess.run(argv, capture_output=True, text=True, check=True)
        return result.stdout
    requirements = module.minimum_requirements(sys.executable, run, 'codex')
    from importlib.metadata import requires
    from packaging.requirements import Requirement
    actual = next(Requirement(value) for value in requirements if Requirement(value).name == 'mcp')
    declared = next(Requirement(value) for value in requires('spoq') if Requirement(value).name == 'mcp')
    assert actual.specifier == declared.specifier
    assert any(value.startswith('pydantic') and '2.11' in value for value in requirements)
    assert any(value.startswith('websockets') for value in requirements)
    assert not any(value.startswith('fastembed') for value in requirements)
    assert observed[0][1] == 'minimum-requirements' and observed[0][0][-1] == 'codex'
