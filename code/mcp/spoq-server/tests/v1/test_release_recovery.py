"""Release recovery regressions from independent fault-injection tests."""
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import zipfile

import pytest

from spoq_server.v1.board import Board
from spoq_server.v1.cli import import_snapshot,write_snapshot
from spoq_server.v1.db import transaction
from spoq_server.v1.migration import migrate,database_path
from spoq_server.v1.store import Store


@pytest.fixture
def store(tmp_path):
 s=Store(tmp_path/'store'/'spoq.db')
 s.create('project_plan','p','Plan')
 s.create('feature','f','Feature','p')
 s.create('task','t','Task','f')
 return s


@pytest.fixture
def board(store):
 b=Board(store); b.run('r','f');b.register('r','a','worker');b.register('r','qa','reviewer','codex-cli','uuid')
 return b


def make_legacy(root, *, state='pending',epic_state=None):
 epic=root/'spoq/epics/active/api'; (epic/'tasks').mkdir(parents=True)
 (epic/'EPIC.md').write_text('---\nslug: api\n'+(f'status: {epic_state}\n' if epic_state else '')+'---\n# API\n')
 (epic/'tasks/a.yml').write_text(f'id: work\ntitle: Work\nstatus: {state}\n')
 (root/'journal.md').write_bytes(b'---\nagent: Tester\n---\nA journal with CRLF\r\n')
 return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_expired_claim_visible_to_scheduler(store,board):
 store.claim('t','r','a')
 with transaction(store.path,write=True) as db:db.execute('UPDATE claims SET expires_at=0')
 reopened=Store(store.path)
 assert reopened.dag('f')['ready']==['t']
 assert reopened.claim('t','r','a')['token']


def test_migrated_in_progress_task_is_recoverable(tmp_path):
 make_legacy(tmp_path,state='in_progress');migrate(tmp_path,confirmed=True)
 s=Store(database_path(tmp_path));f=s.list('feature')[0];t=s.list('task')[0]
 b=Board(s);b.run('r',f['id']);b.register('r','a','worker')
 assert t['id'] in s.dag(f['id'])['ready']
 assert s.claim(t['id'],'r','a')['token']


def test_blocked_epic_remains_execution_blocked(tmp_path):
 make_legacy(tmp_path,epic_state='blocked');migrate(tmp_path,confirmed=True)
 s=Store(database_path(tmp_path));f=s.list('feature')[0]
 assert f['status']=='blocked'
 assert s.dag(f['id'])['ready']==[]


def test_crash_on_final_send_has_a_terminal_or_recoverable_state(store,board):
 board.post('r','a',['qa'],'Review',request_key='one')
 for _ in range(8):
  assert board.lease()
  with transaction(store.path,write=True) as db:db.execute('UPDATE deliveries SET lease_until=0,next_attempt=0')
 reopened=Board(Store(store.path));next_lease=reopened.lease()
 with transaction(store.path) as db:row=dict(db.execute('SELECT * FROM deliveries').fetchone())
 assert next_lease is not None or row['state']=='failed'
 assert row['state']!='sending' or next_lease is not None


@pytest.mark.parametrize('selector',['role:reviewer','*'])
def test_exact_post_retry_survives_roster_changes(store,board,selector):
 first=board.post('r','a',[selector],'Review',request_key='one')
 board.register('r','new','reviewer')
 retry=board.post('r','a',[selector],'Review',request_key='one')
 assert retry['duplicate'] and retry['id']==first['id']
 assert board.inbox('r','new')==[]


@pytest.mark.parametrize('mutation',['remote-route','unknown-runtime','completed-claim','completed-parent','invalid-thread'])
def test_malformed_snapshot_rejected_atomically(store,board,tmp_path,mutation):
 board.post('r','a',['qa'],'Review',request_key='one')
 if mutation=='completed-claim':store.claim('t','r','a')
 snap=copy.deepcopy(store.snapshot())
 if mutation=='remote-route':next(a for a in snap['tables']['agents'] if a['id']=='qa').update(runtime='codex-app-server',endpoint='ws://203.0.113.1:1234')
 elif mutation=='unknown-runtime':snap['tables']['agents'][0]['runtime']='unknown'
 elif mutation=='completed-claim':next(n for n in snap['tables']['nodes'] if n['id']=='t')['status']='completed'
 elif mutation=='completed-parent':next(n for n in snap['tables']['nodes'] if n['id']=='p')['status']='completed'
 elif mutation=='invalid-thread':snap['tables']['threads'][0]['state']='unknown'
 target=Store(tmp_path/'restored'/'spoq.db');before=target.snapshot()
 with pytest.raises((ValueError,TypeError)):import_snapshot(target,snap)
 assert target.snapshot()==before


def test_restore_rejects_existing_unlinked_journal(store,tmp_path):
 target=Store(tmp_path/'other'/'spoq.db');target.journal('Existing user work');before=target.snapshot()
 with pytest.raises(ValueError,match='empty'):import_snapshot(target,store.snapshot())
 assert target.snapshot()==before


def test_second_converter_does_not_replace_live_database(tmp_path):
 make_legacy(tmp_path);target=database_path(tmp_path);entered=threading.Event();resume=threading.Event();real_exists=Path.exists;paused=False;errors=[]
 def paused_exists(path):
  nonlocal paused
  answer=real_exists(path)
  if path==target and threading.current_thread().name=='late-migration' and not paused:
   paused=True;assert not answer;entered.set();assert resume.wait(20)
  return answer
 def late():
  try:migrate(tmp_path,confirmed=True)
  except Exception as e:errors.append(e)
 with patch.object(Path,'exists',paused_exists):
  worker=threading.Thread(target=late,name='late-migration');worker.start();assert entered.wait(10)
  migrate(tmp_path,confirmed=True);Store(target).create('project_plan','new-work','New work after upgrade')
  resume.set();worker.join(20);assert not worker.is_alive()
 assert not errors
 assert Store(target).get('new-work')['title']=='New work after upgrade'


def test_migration_lock_released_after_sigkill(tmp_path):
 make_legacy(tmp_path);marker=tmp_path/'paused';child=tmp_path/'crash_child.py'
 child.write_text('from pathlib import Path\nimport sys,time\nimport spoq_server.v1.migration as m\ndef pause(path):\n Path(sys.argv[2]).touch()\n while True:time.sleep(1)\nm.Store=pause\nm.migrate(Path(sys.argv[1]),confirmed=True)\n')
 process=subprocess.Popen([sys.executable,str(child),str(tmp_path),str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:
  deadline=time.monotonic()+10
  while not marker.exists() and time.monotonic()<deadline and process.poll() is None:time.sleep(.01)
  assert marker.exists()
  process.kill();process.wait(5)
  assert migrate(tmp_path,confirmed=True)['converted']
 finally:
  if process.poll() is None:process.kill();process.wait(5)


def test_migration_provenance_roundtrip_is_byte_exact(tmp_path):
 root=tmp_path/'legacy';root.mkdir();original=make_legacy(root);report=migrate(root,confirmed=True)
 with zipfile.ZipFile(report['backup']) as archive:
  assert {n:archive.read(n) for n in archive.namelist()}==original
 source=Store(database_path(root));snap=source.snapshot();destination=tmp_path/'snapshot.json';write_snapshot(source,destination)
 target=Store(tmp_path/'target'/'spoq.db');import_snapshot(target,json.loads(destination.read_text()))
 assert target.snapshot()==snap
 with transaction(target.path) as db:
  restored={r['path']:r['content'] for r in db.execute('SELECT * FROM legacy_sources')}
 assert restored==original
 assert all((root/path).read_bytes()==data for path,data in original.items())


def test_cross_run_reply_and_ack_stay_isolated(store,board):
 message=board.post('r','a',['qa'],'Review',request_key='one');board.run('other');board.register('other','a','worker');board.register('other','qa','reviewer')
 assert board.inbox('other','qa')==[]
 with pytest.raises(ValueError):board.acknowledge('other','qa',message['id'])
 with pytest.raises(ValueError):board.post('other','a',['qa'],'Wrong run',reply_to=message['id'],request_key='two')


def test_expired_worker_cannot_finish_or_renew(store,board):
 old=store.claim('t','r','a')
 with transaction(store.path,write=True) as db:db.execute('UPDATE claims SET expires_at=0')
 current=store.claim('t','r','qa')
 with pytest.raises(ValueError):store.renew_claim('t',old['token'])
 with pytest.raises(ValueError):store.update('t','completed',claim_token=old['token'],evidence={'tests':True})
 store.update('t','completed',claim_token=current['token'],evidence={'tests':True})


def test_post_fanout_is_atomic(store,board):
 with pytest.raises(ValueError):board.post('r','a',['qa','unknown'],'Review',request_key='one')
 assert board.inbox('r','qa')==[]
 assert store.snapshot()['tables']['messages']==[]


def test_concurrent_claim_has_one_live_owner(store,board):
 def claim(agent):
  try:return store.claim('t','r',agent)
  except ValueError:return None
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(claim,['a','qa']*4))
 assert sum(c is not None for c in claims)==1


@pytest.mark.parametrize('table,field,value',[
 ('claims','expires_at','never'),('claims','expires_at',True),
 ('deliveries','next_attempt','never'),('deliveries','lease_until','never'),
 ('deliveries','attempts',1.5),('nodes','revision',0),('nodes','revision',True),
])
def test_snapshot_rejects_poisoned_numeric_fields(store,board,tmp_path,table,field,value):
 store.claim('t','r','a');board.post('r','a',['qa'],'Review',request_key='one')
 snapshot=store.snapshot();snapshot['tables'][table][0][field]=value
 target=Store(tmp_path/'restored'/'spoq.db');before=target.snapshot()
 with pytest.raises(ValueError):import_snapshot(target,snapshot)
 assert target.snapshot()==before


def test_export_race_does_not_clobber_a_new_destination(store,tmp_path,monkeypatch):
 destination=tmp_path/'export.json';original=store.snapshot
 def snapshot():
  destination.write_text('Concurrent user content')
  return original()
 monkeypatch.setattr(store,'snapshot',snapshot)
 with pytest.raises(ValueError,match='exists'):write_snapshot(store,destination)
 assert destination.read_text()=='Concurrent user content'


@pytest.mark.parametrize('operation',['create','update','edit','claim'])
def test_mid_mutation_event_failure_rolls_back_every_table(store,board,operation):
 before=store.snapshot()
 with patch('spoq_server.v1.store.event',side_effect=RuntimeError('injected audit failure')):
  with pytest.raises(RuntimeError,match='injected'):
   if operation=='create':store.create('task','other','Other','f')
   elif operation=='update':store.update('t','qa')
   elif operation=='edit':store.edit('t',{'new':'mutation'})
   else:store.claim('t','r','a')
 assert store.snapshot()==before


def test_post_index_failure_rolls_back_thread_message_and_deliveries(store,board):
 before=store.snapshot()
 with patch('spoq_server.v1.board.index_document',side_effect=RuntimeError('injected index failure')):
  with pytest.raises(RuntimeError,match='injected'):
   board.post('r','a',['qa'],'Review',request_key='one')
 assert store.snapshot()==before


def test_reopened_transitive_dependency_blocks_downstream(store,board):
 store.create('task','b','B','f');store.create('task','c','C','f');store.depend('b','t');store.depend('c','b')
 store.update('t','completed',evidence={'tests':True});store.update('b','completed',evidence={'tests':True})
 try:store.update('t','rework')
 except ValueError:
  assert store.get('t')['status']=='completed'
 else:assert 'c' not in store.dag('f')['ready']


@pytest.mark.parametrize('shape',['null-envelope','null-tables','empty-journal','bad-journal-json'])
def test_snapshot_invalid_shapes_are_clean_errors(store,tmp_path,shape):
 store.journal('A real journal');snapshot=store.snapshot()
 if shape=='null-envelope':snapshot=None
 elif shape=='null-tables':snapshot['tables']=None
 elif shape=='empty-journal':snapshot['tables']['journal_entries'][0]['body']=''
 else:snapshot['tables']['journal_entries'][0]['metadata']='not JSON'
 target=Store(tmp_path/'target'/'spoq.db');before=target.snapshot()
 with pytest.raises(ValueError):import_snapshot(target,snapshot)
 assert target.snapshot()==before


def test_feature_reopen_transitively_gates_tasks_and_own_snapshot(store,tmp_path):
 store.create('feature','b','B','p');store.create('feature','c','C','p');store.depend('b','f');store.depend('c','b');store.create('task','b/t','B task','b');store.create('task','c/t','C task','c')
 store.update('t','completed',evidence={'tests':True});store.update('f','completed');store.update('b/t','completed',evidence={'tests':True});store.update('b','completed');store.update('f','rework')
 assert 'c' not in store.dag('p')['ready']
 assert store.dag('c')['ready']==[]
 target=Store(tmp_path/'target'/'spoq.db');import_snapshot(target,store.snapshot())
 assert target.dag('c')['ready']==[]
