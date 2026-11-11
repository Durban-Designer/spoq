"""Installed client resources, truthful payloads and first-use upgrade boundaries.

Workflow fixtures are scripted skill adapters, not live model evaluations.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest
import yaml

from spoq_server.agents import AGENTS, install_commands
from spoq_server.v1.cli import init, dispatch
from spoq_server.v1.db import transaction
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.mcp import READ_ONLY_TOOLS, MUTATING_TOOLS
from spoq_server.v1.workflows.recovery import WorkflowEngine
from workflow_support import evidence_for, outputs_for

BUNDLE = Path(__file__).parents[2] / 'src/spoq_server/data/v1_skills'
STAGES = ('spoq', 'spoq-plan', 'spoq-plan-validation', 'spoq-execution',
          'spoq-validation', 'spoq-discover', 'spoq-design')


def entry(root, spec, name):
    return root / spec.commands_root / (name + ('.toml' if spec.command_kind == 'toml' else '.md')) if spec.command_kind in {'toml', 'md'} else root / spec.commands_root / name / 'SKILL.md'


def body(path, spec):
    return tomllib.loads(path.read_text())['prompt'] if spec.command_kind == 'toml' else path.read_text()


def load_helper(path):
    spec = importlib.util.spec_from_file_location('installed_workflow_payload', path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('agent', list(AGENTS))
def test_all_installed_native_formats_resolve_workflow_resources_and_execute_payload_helper(tmp_path, agent):
    spec = AGENTS[agent]
    init(tmp_path, agents=agent)
    for name in STAGES:
        path = entry(tmp_path, spec, name)
        text = body(path, spec)
        assert text
        if spec.command_kind == 'skill':
            frontmatter = yaml.safe_load(text.split('---', 2)[1])
            assert frontmatter['name'] == name
            ui = yaml.safe_load((path.parent / 'agents/openai.yaml').read_text())
            assert '$' + name in ui['interface']['default_prompt']
        # Follow real adjacent-stage and reference links, not just wording.
        import re
        links = re.findall(r'`((?:\.\./)?spoq[a-z-]*(?:/(?:SKILL\.md|references/[a-z.-]+\.md)|\.(?:toml|md)))`', text)
        assert links, (agent, name)
        for link in links:
            assert (path.parent / link).is_file(), (agent, name, link)
    resources = tmp_path / spec.commands_root / 'spoq'
    reference = (resources / 'references/workflows.md').read_text()
    assert str(spec.commands_root) + '/spoq/scripts/workflow_payload.py' in reference
    tools = set(READ_ONLY_TOOLS) | set(MUTATING_TOOLS)
    assert {name for name in re.findall(r'\bspoq_[a-z_]+\b', reference) if 'workflow' in name} <= tools
    helper = resources / 'scripts/workflow_payload.py'
    reviewed = tmp_path / 'module.py';reviewed.write_text('answer = 42\n')
    envelope = tmp_path / 'envelope.json';envelope.write_text(json.dumps({'scope_id': 'feature', 'specification_hash': 'a' * 64, 'expected_outputs': ['implementation']}))
    output = tmp_path / 'output.json'
    command = [sys.executable, str(helper), 'work-output', str(envelope), '--root', str(tmp_path), '--files', 'module.py', '--journals', 'validation-1', '--output', str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text())['implementation']['content']
    assert manifest['reviewed_files'] == {'module.py': hashlib.sha256(reviewed.read_bytes()).hexdigest()}
    assert manifest['validation_journal_ids'] == ['validation-1']
    compare = [sys.executable, str(helper), 'check-files', str(output), '--root', str(tmp_path)]
    assert subprocess.run(compare, capture_output=True).returncode == 0
    reviewed.write_text('answer = 43\n')
    stale = subprocess.run(compare, capture_output=True, text=True)
    assert stale.returncode == 1 and json.loads(stale.stdout)['changed_or_missing'] == ['module.py']


@pytest.mark.parametrize('agent', list(AGENTS))
def test_upgrade_archives_distinct_managed_versions_and_preserves_custom_siblings(tmp_path, agent):
    spec = AGENTS[agent]
    init(tmp_path, agents=agent)
    path = entry(tmp_path, spec, 'spoq')
    customized = path.read_bytes() + b'\nUser customization retained in archive.\n'
    path.write_bytes(customized)
    scripts = tmp_path / spec.commands_root / 'spoq/scripts'
    custom = scripts / 'user-helper.py';custom.write_text('print("owned by user")\n')
    managed = scripts / 'workflow_payload.py';old = managed.read_bytes() + b'\n# Custom helper modification\n';managed.write_bytes(old)
    init(tmp_path, agents=agent, upgrade=True)
    backups = tmp_path / '.spoq/legacy-managed-skills' / agent
    expected = backups / ('spoq/SKILL.md' if spec.command_kind == 'skill' else path.name)
    assert expected.read_bytes() == customized
    assert (backups / 'spoq/scripts/workflow_payload.py').read_bytes() == old
    assert custom.read_text() == 'print("owned by user")\n'
    first = sorted(p.relative_to(backups) for p in backups.rglob('*') if p.is_file())
    init(tmp_path, agents=agent, upgrade=True)
    assert sorted(p.relative_to(backups) for p in backups.rglob('*') if p.is_file()) == first
    # Restoring an already archived custom version must not duplicate its backup.
    managed.write_bytes(old);init(tmp_path, agents=agent)
    assert sorted(p.relative_to(backups) for p in backups.rglob('*') if p.is_file()) == first


@pytest.mark.parametrize('agent', list(AGENTS))
def test_installer_rejects_escaped_skill_parent_before_any_managed_write(tmp_path, agent):
    target = tmp_path / 'project';outside = tmp_path / 'outside';outside.mkdir();target.mkdir()
    spec = AGENTS[agent];commands = target / spec.commands_root;commands.mkdir(parents=True)
    sentinel = outside / 'SKILL.md';sentinel.write_text('User content outside selected project\n')
    (commands / 'spoq').symlink_to(outside, target_is_directory=True)
    other = entry(target, spec, 'spoq-plan');other.parent.mkdir(parents=True, exist_ok=True);other.write_text('Existing managed content\n')
    before = {str(p): p.read_bytes() for p in outside.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='escapes the target workspace'):
        install_commands(spec, BUNDLE, ['spoq-plan', 'spoq'], target)
    assert other.read_text() == 'Existing managed content\n'
    assert {str(p): p.read_bytes() for p in outside.rglob('*') if p.is_file()} == before
    assert not (target / '.spoq').exists()


@pytest.mark.parametrize('agent', list(AGENTS))
def test_installer_rejects_escaped_backup_parent_before_refreshing_native_files(tmp_path, agent):
    target = tmp_path / 'project';outside = tmp_path / 'outside';target.mkdir();outside.mkdir()
    spec = AGENTS[agent]
    path = entry(target, spec, 'spoq');path.parent.mkdir(parents=True);path.write_text('Old customized managed bytes\n')
    archives = target / '.spoq/legacy-managed-skills';archives.mkdir(parents=True)
    (archives / agent).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='escapes the target workspace'):
        install_commands(spec, BUNDLE, ['spoq'], target)
    assert path.read_text() == 'Old customized managed bytes\n' and not list(outside.iterdir())


def test_installer_allows_an_explicitly_selected_resolved_target_root(tmp_path):
    physical = tmp_path / 'physical';physical.mkdir()
    selected = tmp_path / 'selected';selected.symlink_to(physical, target_is_directory=True)
    assert install_commands(AGENTS['codex'], BUNDLE, ['spoq'], selected) == 1
    assert (physical / '.agents/skills/spoq/SKILL.md').is_file()


def test_metadata_preserves_optional_frontmatter_policy_and_unrelated_tool_dependencies(tmp_path):
    bundle = tmp_path / 'bundle/spoq'
    (bundle / 'agents').mkdir(parents=True)
    frontmatter = {'name': 'spoq', 'description': 'Test skill', 'license': 'MIT',
                   'metadata': {'category': 'user-workflows'}, 'allowed-tools': 'Read'}
    (bundle / 'SKILL.md').write_text('---\n' + yaml.safe_dump(frontmatter) + '---\nBody\n')
    managed = {'interface': {'display_name': '/spoq'}, 'policy': {'allow_implicit_invocation': True},
               'dependencies': {'tools': [{'type': 'mcp', 'value': 'spoq', 'description': 'Current workflow tools'}]}}
    (bundle / 'agents/openai.yaml').write_text(yaml.safe_dump(managed))
    install_commands(AGENTS['codex'], bundle.parent, ['spoq'], tmp_path / 'target')
    target = tmp_path / 'target/.agents/skills/spoq'
    customized_frontmatter = {**frontmatter, 'allowed-tools': 'Read Glob',
                              'metadata': {**frontmatter['metadata'], 'user_tag': 'keep'}}
    (target / 'SKILL.md').write_text('---\n' + yaml.safe_dump(customized_frontmatter) + '---\nCustom body\n')
    current = {**managed, 'policy': {'allow_implicit_invocation': False},
               'dependencies': {'custom': True, 'tools': [{'type': 'mcp', 'value': 'spoq', 'custom': 'keep'}, {'type': 'mcp', 'value': 'other'}]},
               'interface': {'display_name': 'Custom', 'custom_ui_field': 'keep'}}
    (target / 'agents/openai.yaml').write_text(yaml.safe_dump(current))
    install_commands(AGENTS['codex'], bundle.parent, ['spoq'], tmp_path / 'target')
    result = yaml.safe_load((target / 'agents/openai.yaml').read_text())
    assert result['policy']['allow_implicit_invocation'] is False
    assert result['dependencies']['custom'] is True
    assert result['dependencies']['tools'][0]['custom'] == 'keep'
    assert result['dependencies']['tools'][1]['value'] == 'other'
    assert result['interface']['custom_ui_field'] == 'keep'
    merged = yaml.safe_load((target / 'SKILL.md').read_text().split('---', 2)[1])
    assert merged['metadata'] == {'category': 'user-workflows', 'user_tag': 'keep'}
    assert merged['license'] == 'MIT'
    assert merged['allowed-tools'] == 'Read Glob'


def old_store(path):
    frozen = Path(__file__).parents[1] / 'fixtures/v1_0_db.py'
    spec = importlib.util.spec_from_file_location('genuine_v1_db', frozen)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.initialize(path)
    store = Store(path);store.create('project_plan', 'existing', 'Existing plan')
    return store


def test_old_schema_noninteractive_init_requires_confirmation_before_database_or_native_writes(tmp_path, monkeypatch, capsys):
    path = tmp_path / '.spoq/spoq.db';path.parent.mkdir()
    store = old_store(path)
    context = tmp_path / 'AGENTS.md';context.write_text('User guidance unchanged\n')
    config = tmp_path / '.codex/config.toml';config.parent.mkdir();config.write_text('[mcp_servers.other]\ncommand = "keep"\n')
    before = store.snapshot();database_bytes = path.read_bytes();config_bytes = config.read_bytes()
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    with pytest.raises(ValueError, match='confirmation'):
        init(tmp_path, upgrade=True, agents='codex', with_mcp=True)
    assert json.loads(capsys.readouterr().out)['schema_upgrade']['from_version'] == 1
    assert path.read_bytes() == database_bytes and store.snapshot() == before
    assert context.read_text() == 'User guidance unchanged\n' and config.read_bytes() == config_bytes
    assert not (tmp_path / '.agents').exists() and not (tmp_path / '.spoq/backups').exists()


def test_authorized_old_schema_upgrade_has_consistent_backup_and_keeps_existing_context_and_config(tmp_path):
    path = tmp_path / '.spoq/spoq.db';path.parent.mkdir()
    store = old_store(path);store.journal('Existing work retained', node_id='existing')
    context = tmp_path / 'AGENTS.md';context.write_text('User rule.\n<!-- SPOQ 1.0 -->\nOld managed text.\n<!-- /SPOQ 1.0 -->\n')
    config = tmp_path / '.codex/config.toml';config.parent.mkdir();config.write_text('[mcp_servers.other]\ncommand = "keep"\n')
    before = store.snapshot()
    result = init(tmp_path, upgrade=True, yes=True, agents='codex', with_mcp=True)
    assert result['schema_upgrade']['upgraded'] and Path(result['schema_upgrade']['backup']).is_file()
    assert 'User rule.' in context.read_text() and context.read_text().count('<!-- SPOQ 1.0 -->') == 1
    assert tomllib.loads(config.read_text())['mcp_servers']['other']['command'] == 'keep'
    assert store.get('existing')['title'] == 'Existing plan'
    assert any(j['body'] == 'Existing work retained' for j in store.journals('existing'))
    from spoq_server.v1.workflows.schema import restore_backup
    restored = tmp_path / 'restored.db';restore_backup(Path(result['schema_upgrade']['backup']), restored, confirmed=True)
    assert Store(restored).snapshot() == before
    second = init(tmp_path, upgrade=True, yes=True, agents='codex', with_mcp=True)
    assert 'schema_upgrade' not in second


def test_legacy_conversion_produces_current_schema_with_one_conversion_preview(legacy, capsys):
    result = init(legacy, upgrade=True, yes=True, agents='codex')
    assert result['converted']
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 1 and 'mapping' in rows[0] and 'schema_upgrade' not in rows[0]
    from spoq_server.v1.workflows.schema import schema_status
    assert schema_status(Path(result['database']))['from_version'] == 2


def test_help_uses_actual_package_version(monkeypatch, capsys):
    import spoq_server
    monkeypatch.setattr(spoq_server, '__version__', '9.8.7')
    dispatch(['--help'])
    assert capsys.readouterr().out.startswith('SPOQ 9.8.7')


def test_payload_helper_does_not_invent_success_or_escape_workspace(tmp_path):
    helper = load_helper(BUNDLE / 'spoq/scripts/workflow_payload.py')
    envelope = {'run_id': 'r', 'scope_id': 'f', 'phase_id': 'execute', 'attempt_id': 'a',
                'definition_hash': 'd', 'specification_hash': 's', 'current_specification_hash': 'new',
                'artifact_hashes': {}, 'expected_outputs': ['implementation']}
    with pytest.raises(ValueError, match='Missing actual observation'):
        helper.build_evidence(envelope, {'passed': True})
    actual = {'reviewer': {'agent': 'reviewer', 'review_type': 'self_review'}, 'checks_passed': False,
              'observed_checks': [{'command': 'actual failing command', 'exit_code': 1, 'source': 'test fixture', 'observed': True}],
              'acceptance_results': [{'criterion': 'Requirement', 'passed': False}]}
    evidence = helper.build_evidence(envelope, actual, True)
    assert evidence['checks_passed'] is False and evidence['specification_hash'] == 'new' and 'scores' not in evidence
    outside = tmp_path.parent / (tmp_path.name + '-outside.py');outside.write_text('private = True\n')
    try:
        with pytest.raises(ValueError, match='inside'):
            helper.work_output(envelope, tmp_path, [str(outside)], [])
    finally:
        outside.unlink()


@pytest.mark.parametrize('content', ['{"checks_passed": false, "checks_passed": true}',
                                    '{"score": NaN}', '{"score": Infinity}',
                                    '{"content": "' + 'x' * (1024 * 1024) + '"}'])
def test_payload_helper_rejects_ambiguous_nonfinite_or_oversized_observations(tmp_path, content):
    helper = load_helper(BUNDLE / 'spoq/scripts/workflow_payload.py')
    source = tmp_path / 'observations.json';source.write_text(content)
    with pytest.raises(ValueError):
        helper.load(source)


@pytest.mark.parametrize('agent', list(AGENTS))
def test_installed_piqard_planning_only_adapter_pauses_before_implementation(tmp_path, agent):
    spec = AGENTS[agent];init(tmp_path, agents=agent)
    store = Store(tmp_path / '.spoq/spoq.db');store.create('project_plan', 'plan', 'Goal');store.create('feature', 'feature', 'Feature', 'plan')
    engine = WorkflowEngine(store);engine.start('r', 'feature', {'uncertainty': 'high'}, strategy='piqard')
    discover = engine.next('r', 'orchestrator', key='discover')
    assert entry(tmp_path, spec, discover['skill']).is_file()
    engine.complete('r', discover['attempt_id'], discover['token'], 'orchestrator', key='discover-done', evidence=evidence_for(discover), outputs=outputs_for(discover))
    design = engine.next('r', 'orchestrator', key='design')
    assert entry(tmp_path, spec, design['skill']).is_file()
    narrative = {name: 'Reviewable ' + name for name in ['scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria']}
    engine.complete('r', design['attempt_id'], design['token'], 'orchestrator', key='design-done', evidence=evidence_for(design), outputs={'narrative_plan': {'content': narrative}})
    human = engine.next('r', 'orchestrator', key='human')
    assert human['status'] == 'waiting_human' and not store.list('task')
    assert not engine.get('r')['state']['phases']['plan']['ready']
    artifact = human['inputs']['narrative_plan']
    # This is an explicitly scripted user-action fixture, never inferred consent.
    engine.respond('r', human['attempt_id'], artifact['id'], artifact['sha256'], 'approve', 'Fixture user', key='approve', source='user', user_confirmed=True)
    planner = engine.next('r', 'orchestrator', key='plan')
    assert entry(tmp_path, spec, planner['skill']).is_file()
    store.create('task', 'task', 'Planned work', 'feature')
    planner['specification_hash'] = engine.get('r')['current_specification_hash']
    engine.complete('r', planner['attempt_id'], planner['token'], 'orchestrator', key='plan-done', evidence=evidence_for(planner), outputs=outputs_for(planner), refresh_spec=True)
    gate = engine.next('r', 'orchestrator', key='gate')
    assert entry(tmp_path, spec, gate['skill']).is_file()
    engine.complete('r', gate['attempt_id'], gate['token'], 'orchestrator', key='gate-done', evidence=evidence_for(gate, stage='plan'))
    assert engine.pause('r', key='planning-only-finish')['status'] == 'paused'
    assert engine.next('r', 'orchestrator', key='cannot-implement')['status'] == 'paused'
    assert store.get('task')['status'] == 'pending'
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='execute'").fetchone()[0] == 0


def test_new_goal_planner_can_save_root_planning_metadata_and_decomposition(tmp_path):
    store = Store(tmp_path / 'spoq.db');store.create('project_plan', 'goal', 'Build service', data={'goal': 'Build service'})
    engine = WorkflowEngine(store);engine.start('r', 'goal', {'uncertainty': 'low'}, strategy='classic')
    call = engine.next('r', 'orchestrator', key='plan')
    store.edit('goal', {'assumptions': ['Local SQLite'], 'acceptance_criteria': ['Tests and runtime pass'], 'architecture': {'components': ['service']}})
    store.create('feature', 'goal/service', 'Service', 'goal');store.create('task', 'goal/service/code', 'Implement service', 'goal/service')
    call['specification_hash'] = engine.get('r')['current_specification_hash']
    result = engine.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='planned', evidence=evidence_for(call), outputs=outputs_for(call), refresh_spec=True)
    assert result['outcome'] == 'pass'
