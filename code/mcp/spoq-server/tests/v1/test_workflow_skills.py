from pathlib import Path
import re
import tomllib

import pytest
import yaml

from spoq_server.agents import AGENTS
from spoq_server.v1.cli import GUIDANCE,init
from spoq_server.v1.migration import database_path
from spoq_server.v1.store import Store


def installed_path(root,spec,name):
    if spec.command_kind=='toml': return root/spec.commands_root/(name+'.toml')
    if spec.command_kind=='md': return root/spec.commands_root/(name+'.md')
    return root/spec.commands_root/name/'SKILL.md'


@pytest.mark.parametrize('agent',['claude','codex','qwen','cursor'])
def test_fresh_install_exposes_composable_workflows_in_native_format(tmp_path,agent):
    spec=AGENTS[agent]
    init(tmp_path,agents=agent)
    names=('spoq','spoq-plan','spoq-plan-validation','spoq-execution','spoq-validation')
    for name in names:
        path=installed_path(tmp_path,spec,name)
        assert path.is_file()
        if spec.command_kind=='toml':
            command=tomllib.loads(path.read_text())
            assert command['prompt'] and command['description']
        elif spec.command_kind=='skill':
            metadata=yaml.safe_load(path.read_text().split('---',2)[1])
            assert metadata['name']==name
            ui=yaml.safe_load((path.parent/'agents/openai.yaml').read_text())
            assert ui['interface']['display_name']=='/'+name
            assert '$'+name in ui['interface']['default_prompt']
        # Every stage handoff and shared helper resolves in each native format.
        body=tomllib.loads(path.read_text())['prompt'] if spec.command_kind=='toml' else path.read_text()
        resources=re.findall(r'`((?:\.\./)?spoq[a-z-]*/(?:SKILL\.md|(?:scripts|references)/[a-z_./-]+))',body)
        references=re.findall(r'`(spoq[a-z-]*\.(?:md|toml))`',body)
        assert resources or references
        for reference in resources+references:
            assert (path.parent/reference).is_file(),(agent,name,reference)
    assert not installed_path(tmp_path,spec,'epic-planning').exists()
    workflow=installed_path(tmp_path,spec,'spoq')
    if spec.command_kind=='toml': reference='spoq-plan.toml'
    elif spec.command_kind=='md': reference='spoq-plan.md'
    else: reference='../spoq-plan/SKILL.md'
    assert reference in workflow.read_text()
    assert (workflow.parent/reference).is_file()


@pytest.mark.parametrize('agent',['claude','codex','qwen','cursor'])
def test_upgrade_archives_retired_stages_and_preserves_custom_resources(tmp_path,agent):
    spec=AGENTS[agent]
    init(tmp_path,agents=agent)
    retired=('epic-planning','feature-planning','project-planning','epic-validation',
             'agent-execution','agent-validation','feature-execution')
    for name in retired:
        path=installed_path(tmp_path,spec,name)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('Custom legacy workflow '+name)
        if spec.command_kind=='skill': (path.parent/'custom.txt').write_text('Preserve me')
    # Existing users need no extra flag merely to retire old planning entry points.
    init(tmp_path,agents=agent)
    for name in retired:
        assert not installed_path(tmp_path,spec,name).exists()
        backup=tmp_path/'.spoq/legacy-skills'/agent
        if spec.command_kind=='skill':
            assert (installed_path(tmp_path,spec,name).parent/'custom.txt').read_text()=='Preserve me'
            assert (backup/name/'custom.txt').read_text()=='Preserve me'
            assert (backup/name/'SKILL.md').read_text()=='Custom legacy workflow '+name
        else:
            suffix='.toml' if spec.command_kind=='toml' else '.md'
            assert (backup/(name+suffix)).read_text()=='Custom legacy workflow '+name
    init(tmp_path,agents=agent,upgrade=True)
    assert installed_path(tmp_path,spec,'spoq').exists()


def test_managed_guidance_refresh_keeps_user_rules_and_existing_database(tmp_path):
    init(tmp_path,agents='codex')
    store=Store(database_path(tmp_path))
    store.create('project_plan','existing','Existing work')
    old='<!-- SPOQ 1.0 -->\nUse the retired workflow.\n<!-- /SPOQ 1.0 -->'
    context=tmp_path/'AGENTS.md'
    before='User rule before.\n'+old+'\nUser rule after.\n'
    context.write_text(before)
    init(tmp_path,agents='codex',upgrade=True)
    updated=context.read_text()
    assert updated=='User rule before.\n'+GUIDANCE.strip()+'\nUser rule after.\n'
    assert (tmp_path/'.spoq/legacy-guidance/AGENTS.md').read_text()==before
    assert store.get('existing')['title']=='Existing work'
    init(tmp_path,agents='codex',upgrade=True)
    assert context.read_text()==updated
    assert len(list((tmp_path/'.spoq/legacy-guidance').iterdir()))==1


def test_reinstall_keeps_custom_agent_files_and_invocation_policy(tmp_path):
    init(tmp_path,agents='codex')
    metadata=tmp_path/'.agents/skills/spoq/agents'
    custom=metadata/'custom-reviewer.md'
    custom.write_text('User-owned reviewer instructions')
    settings=metadata/'openai.yaml'
    value=yaml.safe_load(settings.read_text())
    value['policy']={'allow_implicit_invocation':False}
    value['interface']['display_name']='My custom name'
    settings.write_text(yaml.safe_dump(value))
    original=settings.read_text()
    init(tmp_path,agents='codex')
    assert custom.read_text()=='User-owned reviewer instructions'
    after=yaml.safe_load(settings.read_text())
    assert after['policy']['allow_implicit_invocation'] is False
    assert after['interface']['display_name']=='/spoq'
    backup=tmp_path/'.spoq/legacy-skill-metadata/codex/spoq/agents/openai.yaml'
    assert backup.read_text()==original
    init(tmp_path,agents='codex')
    assert len(list(backup.parent.iterdir()))==1


def test_resource_only_retired_workflow_directory_remains_callable(tmp_path):
    init(tmp_path,agents='codex')
    helper=tmp_path/'.agents/skills/epic-planning/scripts/helper.py'
    helper.parent.mkdir(parents=True,exist_ok=True)
    helper.write_text('print("legacy helper")\n')
    init(tmp_path,agents='codex')
    init(tmp_path,agents='codex',upgrade=True)
    assert helper.read_text()=='print("legacy helper")\n'
    assert not (tmp_path/'.spoq/legacy-skills/codex/epic-planning').exists()


def test_installer_cannot_override_existing_invocation_policy(tmp_path):
    from spoq_server.agents import install_commands
    bundle=tmp_path/'bundle/spoq'
    (bundle/'agents').mkdir(parents=True)
    (bundle/'SKILL.md').write_text('---\nname: spoq\ndescription: Test workflow\n---\nWorkflow body\n')
    metadata={'interface':{'display_name':'/spoq'},'policy':{'allow_implicit_invocation':True}}
    (bundle/'agents/openai.yaml').write_text(yaml.safe_dump(metadata))
    target=tmp_path/'project'
    install_commands(AGENTS['codex'],bundle.parent,['spoq'],target)
    path=target/'.agents/skills/spoq/agents/openai.yaml'
    metadata['policy']['allow_implicit_invocation']=False
    path.write_text(yaml.safe_dump(metadata))
    install_commands(AGENTS['codex'],bundle.parent,['spoq'],target)
    assert yaml.safe_load(path.read_text())['policy']['allow_implicit_invocation'] is False
