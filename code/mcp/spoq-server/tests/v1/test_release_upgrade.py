"""Native client upgrades, source entry point, and preserved legacy layouts."""
import json
import os
from pathlib import Path
import subprocess
import tomllib

import pytest

from spoq_server.v1.cli import init
from spoq_server.v1.config import CONFIG_PATHS
from spoq_server.v1.migration import migrate, database_path, status
from spoq_server.v1.store import Store


@pytest.mark.parametrize('agent', ['claude','codex','qwen','cursor'])
def test_upgrade_refreshes_existing_launchers_without_requesting_new_mcp(tmp_path,agent):
    path=tmp_path/CONFIG_PATHS[agent]
    path.parent.mkdir(parents=True,exist_ok=True)
    entry={'command':'uv','args':['run','python','-m','spoq_server.server'],
           'env':{'SPOQ_STORE':'fs','KEEP':'value'},'custom':'retain'}
    if agent=='codex':
        original='# User model preference\nmodel = "custom"\n[mcp_servers.other]\ncommand = "other"\n[mcp_servers.spoq]\ncommand = "python"\nargs = ["-m", "spoq_server.server"]\ncustom = "retain"\n[mcp_servers.spoq.env]\nSPOQ_STORE = "fs"\nKEEP = "value"\n'
        load=tomllib.loads
        key='mcp_servers'
    else:
        original=json.dumps({'custom':'top-level','mcpServers':{'other':{'command':'other'},'spoq':entry}})
        load=json.loads
        key='mcpServers'
    path.write_text(original)
    result=init(tmp_path,upgrade=True,agents=agent)
    data=load(path.read_text());new=data[key]['spoq']
    assert new['command']=='spoq' and new['args']==['mcp','--root',str(tmp_path)]
    assert new['env']=={'SPOQ_STORE':'sqlite','KEEP':'value'}
    assert new['custom']=='retain' and data[key]['other']=={'command':'other'}
    backup=tmp_path/result['mcp_changes'][0]['backup']
    assert backup.read_text()==original
    before=path.read_bytes()
    assert init(tmp_path,upgrade=True,agents=agent)['mcp_changes']==[]
    assert path.read_bytes()==before
    if agent=='codex': assert '# User model preference' in path.read_text()


@pytest.mark.parametrize('agent', ['claude','codex','qwen','cursor'])
def test_upgrade_without_agent_option_detects_existing_client(tmp_path,agent):
    init(tmp_path,agents=agent,with_mcp=True)
    init(tmp_path,upgrade=True)
    # Detection never creates a different agent's context just due to default Claude.
    if agent!='claude': assert not (tmp_path/'CLAUDE.md').exists()
    if agent=='claude': assert not (tmp_path/'AGENTS.md').exists()


@pytest.mark.parametrize('content',['{','[]','{"mcpServers": []}','{"mcpServers": {"spoq": {"env": []}}}'])
def test_invalid_configuration_fails_before_conversion_or_scaffolding(tmp_path,content):
    path=tmp_path/'.mcp.json';path.write_text(content)
    (tmp_path/'journal.md').write_text('Legacy journal remains untouched')
    with pytest.raises(ValueError,match='configuration'):
        init(tmp_path,with_mcp=True,yes=True)
    assert path.read_text()==content
    assert not database_path(tmp_path).exists()
    assert not (tmp_path/'CLAUDE.md').exists()


def test_unknown_agent_fails_before_creating_database(tmp_path):
    with pytest.raises(ValueError): init(tmp_path,agents='invalid')
    assert not database_path(tmp_path).exists()


@pytest.mark.parametrize('folder,agent',[('.codex/prompts','codex'),('.claude/commands','claude')])
def test_old_command_aliases_are_backed_up_and_retired(tmp_path,folder,agent):
    source=tmp_path/folder/'agent-execution.md'
    source.parent.mkdir(parents=True)
    source.write_text('User-customized old execution command')
    sibling=source.with_name('custom.md');sibling.write_text('Other command')
    init(tmp_path,upgrade=True)
    assert not source.exists() and sibling.read_text()=='Other command'
    assert (tmp_path/'.spoq/legacy-skills'/agent/'commands/agent-execution.md').read_text()=='User-customized old execution command'


@pytest.mark.parametrize('base',['automation/tasks','factory/epics/active','spoq/epics/active'])
def test_historical_epic_layouts_convert_with_source_bytes_unchanged(tmp_path,base):
    epic=tmp_path/base/'sample';(epic/'tasks').mkdir(parents=True)
    source=epic/'EPIC.md';source.write_text('---\nslug: sample\n---\n# Sample\n')
    task=epic/'tasks/one.yml';task.write_text('id: one\ntitle: One\n')
    before={source:source.read_bytes(),task:task.read_bytes()}
    assert status(tmp_path)['migration_required']
    assert migrate(tmp_path,confirmed=True)['counts']['epics']==1
    assert len(Store(database_path(tmp_path)).list('task'))==1
    assert all(path.read_bytes()==content for path,content in before.items())


def test_source_bootstrap_defaults_to_sqlite(tmp_path):
    root=Path(__file__).parents[5]
    script=root/'scripts/spoq-init.sh'
    if not script.is_file(): pytest.skip('Source checkout bootstrap is outside installed package')
    env={key:value for key,value in os.environ.items() if key not in {'SPOQ_STORE','SPOQ_PROJECT_ROOT'}}
    result=subprocess.run(['bash',str(script),'--target',str(tmp_path),'--agents','claude','--with-mcp'],env=env,text=True,capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert database_path(tmp_path).is_file()
    assert (tmp_path/'.claude/skills/spoq/SKILL.md').is_file()
    assert not (tmp_path/'.claude/skills/epic-planning/SKILL.md').is_file()


def test_blocked_legacy_map_keeps_project_plan_gate(tmp_path):
    epic=tmp_path/'spoq/epics/active/api';(epic/'tasks').mkdir(parents=True)
    (epic/'EPIC.md').write_text('---\nslug: api\n---\n# API\n')
    (epic/'tasks/one.yml').write_text('id: one\ntitle: One\n')
    maps=tmp_path/'spoq/maps/active';maps.mkdir(parents=True)
    (maps/'program.md').write_text('---\nstatus: blocked\nepics: [api]\n---\n# Program\n')
    migrate(tmp_path,confirmed=True)
    store=Store(database_path(tmp_path))
    feature=store.list('feature')[0]
    assert store.get(feature['parent_id'])['status']=='blocked'
    assert store.dag(feature['id'])['ready']==[]


def test_inconsistent_completed_legacy_task_blocks_affected_scope(tmp_path):
    epic=tmp_path/'spoq/epics/active/api';(epic/'tasks').mkdir(parents=True)
    (epic/'EPIC.md').write_text('# API\n')
    (epic/'tasks/a.yml').write_text('id: a\ntitle: A\n')
    (epic/'tasks/b.yml').write_text('id: b\ntitle: B\nstatus: completed\ndependencies: [a]\n')
    (epic/'tasks/c.yml').write_text('id: c\ntitle: C\ndependencies: [b]\n')
    result=migrate(tmp_path,confirmed=True)
    store=Store(database_path(tmp_path));feature=store.list('feature')[0]
    assert result['warnings'] and feature['status']=='blocked'
    assert store.dag(feature['id'])['ready']==[]
