import json
import os
import subprocess
import sys

import pytest

from spoq_server.v1.cli import init
from spoq_server.v1.db import transaction
from spoq_server.v1.migration import database_path
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.cli import json_argument
from workflow_support import evidence_for, outputs_for


def call(root,*args,ok=True):
    env={**os.environ,'SPOQ_STORE':'sqlite'}
    p=subprocess.run([sys.executable,'-m','spoq_server','workflow',*args,'--root',str(root)],capture_output=True,text=True,env=env,timeout=30)
    if ok:
        assert p.returncode==0,p.stderr
        return json.loads(p.stdout)
    assert p.returncode!=0
    assert 'Traceback' not in p.stderr
    return p


def workspace(root):
    init(root,agents='codex')
    s=Store(database_path(root));s.create('project_plan','p','Plan');s.create('feature','f','Feature','p')
    return s


@pytest.mark.parametrize('flag', ['--root', '--target'])
def test_actual_init_workspace_alias_is_explicit_and_preserves_target_compatibility(tmp_path, flag):
    selected = tmp_path / 'chosen workspace'
    unrelated = tmp_path / 'launch directory'
    unrelated.mkdir()
    result = subprocess.run(
        [sys.executable, '-m', 'spoq_server', 'init', flag, str(selected),
         '--agents', 'codex', '--with-mcp'],
        cwd=unrelated, capture_output=True, text=True,
        env={**os.environ, 'SPOQ_STORE': 'sqlite'}, timeout=30)
    assert result.returncode == 0, result.stderr
    initialized = json.loads(result.stdout)
    assert initialized['database'] == str(selected / '.spoq/spoq.db')
    assert (selected / '.agents/skills/spoq/SKILL.md').is_file()
    assert (selected / '.codex/config.toml').is_file()
    assert Store(database_path(selected)).list() == []
    assert not list(unrelated.iterdir()), 'Initialization must not write into launch CWD'


def test_readonly_routing_inventory_and_missing_runs_never_create_store(tmp_path):
    assert call(tmp_path,'route','--inputs','{"uncertainty":"high"}')['strategy']=='piqard'
    assert {s['id'] for s in call(tmp_path,'list','--strategies')}=={'classic','piqard'}
    assert call(tmp_path,'list')['runs']==[]
    call(tmp_path,'inspect','unknown',ok=False)
    assert not (tmp_path/'.spoq').exists()


def test_actual_cli_start_next_file_completion_snapshot_history_pause_resume(tmp_path):
    workspace(tmp_path)
    root_arg=['--root',str(tmp_path)]
    assert call(tmp_path,*root_arg,'route','--inputs','{"uncertainty":"low"}')['strategy']=='classic'
    call(tmp_path,'start','r','--scope','f','--inputs','{"uncertainty":"low"}','--key','start')
    envelope=call(tmp_path,'next','r','--key','plan')
    assert call(tmp_path,'renew','r',envelope['attempt_id'],'--token',envelope['token'],'--key','renew','--ttl','1200')['lease_until']>envelope['lease_until']
    evidence=tmp_path/'evidence.json';evidence.write_text(json.dumps(evidence_for(envelope)))
    outputs=tmp_path/'outputs.json';outputs.write_text(json.dumps(outputs_for(envelope)))
    arguments=['complete','r',envelope['attempt_id'],'--token',envelope['token'],'--key','done','--evidence','@'+str(evidence),'--outputs','@'+str(outputs)]
    result=call(tmp_path,*arguments)
    assert call(tmp_path,*arguments)==result
    assert call(tmp_path,'show','r')['phases'][0]['status']=='passed'
    assert len(call(tmp_path,'history','r')['items'])==1
    artifact_id=result['outputs']['project_plan']
    assert call(tmp_path,'artifact','r',artifact_id)['render_as']=='text'
    assert call(tmp_path,'attempt','r',envelope['attempt_id'])['evidence']['verdict']=='PASS'
    assert call(tmp_path,'node','r','f')['title']=='Feature'
    assert call(tmp_path,'pause','r','--key','pause')['status']=='paused'
    assert call(tmp_path,'resume','r','--key','resume')['status']=='running'
    assert call(tmp_path,'events','r')['events']


def test_root_before_subcommand_pins_mutations_without_a_duplicate_trailing_flag(tmp_path):
    workspace(tmp_path)
    p=subprocess.run([sys.executable,'-m','spoq_server','workflow','--root',str(tmp_path),
                      'start','r','--scope','f','--strategy','classic','--key','start'],
                      capture_output=True,text=True,env={**os.environ,'SPOQ_STORE':'sqlite'},timeout=30)
    assert p.returncode==0,p.stderr
    assert json.loads(p.stdout)['scope_id']=='f'
    assert len(call(tmp_path,'list')['runs'])==1


def test_human_response_and_successor_proposal_use_real_cli_protocol(tmp_path):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    store=workspace(tmp_path)
    call(tmp_path,'start','r','--scope','f','--key','start','--strategy','piqard')
    engine=WorkflowEngine(store)
    discover=engine.next('r','orchestrator',key='discover')
    engine.complete('r',discover['attempt_id'],discover['token'],'orchestrator',key='discovered',
                    evidence=evidence_for(discover),outputs=outputs_for(discover))
    draft=engine.next('r','orchestrator',key='draft')
    narrative={k:['Recorded '+k] for k in ['scope','decisions','assumptions','risks','acceptance_criteria']}
    engine.complete('r',draft['attempt_id'],draft['token'],'orchestrator',key='drafted',
                    evidence=evidence_for(draft),outputs={'narrative_plan':{'content':narrative}})
    review=call(tmp_path,'next','r','--key','review')
    assert review['status']=='waiting_human'
    proposal=call(tmp_path,'propose','r','--key','proposal','--inputs','{"uncertainty":"low"}',
                  '--reason','Scripted fixture resolved requirements')
    assert proposal['requires_explicit_adoption']
    artifact=review['inputs']['narrative_plan']
    args=['respond','r',review['attempt_id'],'--key','response','--artifact',artifact['id'],'--hash',artifact['sha256'],
          '--decision','approve','--author','Simulated User','--source','user']
    call(tmp_path,*args,ok=False)
    response=call(tmp_path,*args,'--user-confirmed')
    assert response['outcome']=='pass'
    assert call(tmp_path,*args,'--user-confirmed')==response
    assert call(tmp_path,'next','r','--key','decompose')['phase_id']=='plan'


@pytest.mark.parametrize('payload',['[]','NaN','{"uncertainty":"low","uncertainty":"high"}'])
def test_invalid_json_or_shape_has_stable_nonzero_exit(tmp_path,payload):
    call(tmp_path,'route','--inputs',payload,ok=False)
    assert not (tmp_path/'.spoq').exists()


def test_invalid_revision_and_arbitrary_evidence_cannot_mutate_work(tmp_path):
    workspace(tmp_path)
    call(tmp_path,'start','r','--scope','f','--key','start','--strategy','classic')
    call(tmp_path,'next','r','--key','stale','--revision','999',ok=False)
    next=call(tmp_path,'next','r','--key','plan')
    call(tmp_path,'complete','r',next['attempt_id'],'--token',next['token'],'--key','bad','--evidence','{"ok":true}',ok=False)
    assert call(tmp_path,'inspect','r')['state']['phases']['plan']['status']=='running'


def test_old_schema_readonly_queries_do_not_upgrade_and_explicit_upgrade_preserves_data(tmp_path):
    s=workspace(tmp_path)
    with transaction(s.path,write=True) as db:
        for table in ['workflow_receipts','workflow_decisions','workflow_artifacts','workflow_attempts','workflow_runs','workflow_definitions']:
            db.execute('DROP TABLE '+table)
        db.execute('PRAGMA user_version=1')
    import sqlite3
    db=sqlite3.connect(s.path,isolation_level=None)
    try: assert db.execute('PRAGMA journal_mode=DELETE').fetchone()[0]=='delete'
    finally: db.close()
    assert call(tmp_path,'list')['runs']==[]
    call(tmp_path,'inspect','unknown',ok=False)
    db=sqlite3.connect(s.path,isolation_level=None)
    try: assert db.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
    finally: db.close()
    preview=call(tmp_path,'upgrade','--dry-run')
    assert preview['upgrade_required'] and not preview['upgraded']
    call(tmp_path,'start','r','--scope','f','--key','blocked',ok=False)
    with transaction(s.path) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==1
    db=sqlite3.connect(s.path,isolation_level=None)
    try: assert db.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
    finally: db.close()
    result=call(tmp_path,'upgrade','--yes')
    assert result['upgraded'] and result['backup']
    assert call(tmp_path,'start','r','--scope','f','--key','start')['scope_id']=='f'


def test_json_file_limit_is_checked_before_parsing(tmp_path):
    file=tmp_path/'large.json';file.write_bytes(b' '* (1024*1024+1))
    import argparse
    with pytest.raises(argparse.ArgumentTypeError,match='one MiB'):
        json_argument('@'+str(file))
