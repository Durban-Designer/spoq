import json
import os
import subprocess
import sys


def command(*args,input=None):
    env={k:v for k,v in os.environ.items() if k!='SPOQ_STORE'}
    return subprocess.run([sys.executable,'-m','spoq_server',*args],input=input,text=True,capture_output=True,env=env,timeout=30)


def test_cli_default_help_uses_new_hierarchy():
    result=command('--help')
    assert result.returncode==0
    assert 'Project Plans → Features → Tasks' in result.stdout
    assert 'migrate' in result.stdout


def test_cli_first_use_refuses_noninteractive_implicit_conversion(legacy):
    result=command('init','--upgrade','--target',str(legacy),'--agents','codex',input='')
    assert result.returncode==1 and 'confirmation' in result.stderr
    result=command('migrate','--root',str(legacy),'--yes')
    assert result.returncode==0,result.stderr
    result=command('list','--root',str(legacy),'--kind','feature')
    assert len(json.loads(result.stdout))==2


def test_cli_roundtrip_snapshot_and_dag(tmp_path):
    one=tmp_path/'one'
    two=tmp_path/'two'
    for args in [('create','project_plan','p','Plan'),('create','feature','f','Feature','--parent','p'),('create','task','t','Task','--parent','f')]:
        result=command(*args,'--root',str(one))
        assert result.returncode==0,result.stderr
    path=tmp_path/'snapshot.json'
    assert command('export','--root',str(one),'--out',str(path)).returncode==0
    result=command('import',str(path),'--root',str(two))
    assert result.returncode==0,result.stderr
    result=command('dag','f','--root',str(two))
    assert json.loads(result.stdout)['ready']==['t']


def test_cli_can_execute_a_claimed_task_without_mcp(tmp_path):
    def call(*args,success=True):
        result=command(*args,'--root',str(tmp_path))
        if success:
            assert result.returncode==0,result.stderr
            return json.loads(result.stdout)
        assert result.returncode==1
        return result
    call('create','project_plan','p','Plan')
    call('create','feature','f','Feature','--parent','p')
    call('create','task','t','Task','--parent','f')
    node=call('get','t')
    edited=call('edit','t','--data','{"acceptance_criteria":["Tests pass"]}','--revision',str(node['revision']))
    assert edited['data']['acceptance_criteria']==['Tests pass']
    call('edit','t','--data','[]',success=False)
    call('run','run','--scope','f')
    call('agent','run','worker','--role','orchestrator')
    claim=call('claim','t','--run','run','--agent','worker')
    call('renew-claim','t',claim['token'])
    call('update','t','completed','--claim-token','wrong','--evidence','{"tests":"passed"}',success=False)
    node=call('get','t')
    call('update','t','completed','--claim-token',claim['token'],'--revision',str(node['revision']),
         '--evidence','{"unit_tests":"passed","build":"passed"}')
    assert call('get','t')['status']=='completed'
    call('update','f','completed')
    call('update','p','completed')
    call('journal','Verified through the CLI','--node','t')
    assert call('journals','--node','t')[0]['body']=='Verified through the CLI'
    assert any(event['kind']=='claimed' for event in call('history','t'))
    assert call('get','p')['status']=='completed'
