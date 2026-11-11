"""Read-only consistent snapshots and bounded, replayable history pages."""
from contextlib import closing
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from spoq_server.v1.board import Board
from spoq_server.v1.db import transaction, now, BASE_SCHEMA
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.artifacts import ArtifactRepository
from spoq_server.v1.workflows.evidence import complete_phase
from spoq_server.v1.workflows.queries import ReadModel
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.types import validate_viewer_snapshot
from workflow_support import evidence_for, outputs_for


def running(store):
    engine = WorkflowEngine(store)
    engine.start('run', 'feature', {'uncertainty': 'low'}, strategy='classic')
    call = engine.next('run', 'orchestrator', key='next')
    return engine, call, ReadModel(store)


def test_snapshot_matches_fixed_contract_and_retains_definition_attempt_work_identities(store):
    engine, call, model = running(store)
    snapshot = validate_viewer_snapshot(model.snapshot('run'))
    assert snapshot['run']['run_id'] == 'run'
    assert snapshot['definition']['content_hash'] == call['definition_hash']
    assert snapshot['attempts'][0]['id'] == call['attempt_id']
    assert snapshot['attempts'][0]['number'] == 1 and snapshot['attempts'][0]['owner'] == 'orchestrator'
    assert snapshot['phases'][0]['id'] != snapshot['attempts'][0]['id']
    assert snapshot['run']['provenance'] == 'strategy'
    assert snapshot['routing']['reasons'] and not snapshot['run']['stale_specification']
    assert snapshot['work']['nodes'][0]['id'] == 'feature'
    assert 'data' not in snapshot['work']['nodes'][0]
    assert 'token' not in json.dumps(snapshot)
    assert not any(key in snapshot for key in ('percent_complete', 'predicted_cost'))


def test_snapshot_state_and_cursor_share_one_read_transaction_during_concurrent_commit(store, monkeypatch):
    engine, call, model = running(store)
    before = model.snapshot('run')['cursor']
    original = model._history_page
    once = [False]
    def interleave(db, *args):
        if not once[0]:
            once[0] = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(store.edit, 'feature', {'acceptance_criteria': ['Committed after snapshot began']}).result()
        return original(db, *args)
    monkeypatch.setattr(model, '_history_page', interleave)
    snapshot = model.snapshot('run')
    assert snapshot['cursor'] == before
    assert not snapshot['run']['stale_specification']
    events = model.events('run', after=before)
    assert events['events'] and events['cursor'] > before
    latest = model.snapshot('run')
    assert latest['run']['stale_specification'] and latest['blockers']
    assert latest['run']['status'] == 'running'  # No invented failure or quality pass.


def test_missing_database_queries_never_initialize_workspace(tmp_path):
    path = tmp_path / 'absent' / '.spoq' / 'spoq.db'
    model = ReadModel(path)
    assert model.runs() == {'runs': [], 'pagination': {'has_more': False, 'cursor': None}, 'cursor': 0}
    with pytest.raises(ValueError, match='does not exist'): model.snapshot('unknown')
    assert not path.parent.exists()


def test_schema1_readonly_legacy_runs_do_not_upgrade_or_invent_phases(tmp_path):
    path = tmp_path / 'old.db'
    db = sqlite3.connect(path);db.executescript(BASE_SCHEMA + ';PRAGMA user_version=1;');db.close()
    store = Store(path);store.create('project_plan','p','Old plan');Board(store).run('old','p')
    before = path.read_bytes()
    model = ReadModel(path)
    assert model.runs()['runs'][0]['status'] == 'legacy_unclassified'
    snapshot = validate_viewer_snapshot(model.snapshot('old'))
    assert snapshot['run']['provenance'] == 'legacy_unclassified'
    assert snapshot['definition'] == {} and snapshot['phases'] == [] and snapshot['attempts'] == []
    assert snapshot['artifacts'] == [] and snapshot['decisions'] == []
    assert snapshot['routing'] == {'strategy':'legacy_unclassified'}
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_runs'").fetchone()


def test_event_scan_advances_over_unrelated_rows_and_global_gaps_are_valid(store):
    engine, call, model = running(store)
    start = model.snapshot('run')['cursor']
    with transaction(store.path, write=True) as db:
        for n in range(6):
            db.execute('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
                       ('plan', 'workflow.fixture', 'other', json.dumps({'run_id': 'unrelated', 'token':'do-not-show'}), now()))
        db.execute('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
                   ('feature', 'workflow.fixture', 'orchestrator', json.dumps({'run_id':'run','phase_id':'plan'}), now()))
    first = model.events('run', after=start, limit=3)
    assert first['events'] == [] and first['cursor'] == start + 3 and first['has_more']
    second = model.events('run', after=first['cursor'], limit=3)
    assert second['events'] == [] and second['cursor'] == start + 6
    third = model.events('run', after=second['cursor'], limit=3)
    assert third['events'][0]['payload']['run_id'] == 'run' and not third['has_more']
    assert not third['reset']
    with transaction(store.path, write=True) as db:
        db.execute('DELETE FROM events WHERE sequence=?', (start + 2,))
    gaps = model.events('run', after=start, limit=3)
    assert not gaps['reset'] and gaps['cursor'] == start + 4


def test_reset_signals_ahead_and_retention_loss_and_duplicate_reads_are_idempotent(store):
    engine, call, model = running(store)
    cursor = model.snapshot('run')['cursor']
    one = model.events('run', after=0)
    assert model.events('run', after=0) == one
    assert model.events('run', after=cursor + 1)['reset']
    with transaction(store.path, write=True) as db: db.execute('DELETE FROM events WHERE sequence<?', (cursor,))
    assert model.events('run', after=0)['reset']
    assert not model.events('run', after=cursor-1)['reset']


def test_work_events_include_scoped_node_changes_without_leaking_claim_tokens(store):
    engine, call, model = running(store)
    cursor = model.snapshot('run')['cursor']
    store.create('task','t','Task','feature')
    claim = store.claim('t','run','orchestrator')
    result = model.events('run', after=cursor)
    assert any(event['kind'] == 'claimed' for event in result['events'])
    assert claim['token'] not in json.dumps(result)
    assert 'token' not in json.dumps(model.attempt('run',call['attempt_id']))


def test_artifact_and_attempt_details_are_scoped_and_list_projections_are_bounded(store):
    engine, call, model = running(store)
    metadata = {'padding':'x'*900000,'formal_status':'unverified'}
    with transaction(store.path, write=True) as db:
        artifact = ArtifactRepository.add(db,'run',call['attempt_id'],'project_plan','<script>never execute this</script>',
                                          'orchestrator',metadata=metadata)
    huge = evidence_for(call);huge['padding']='y'*700000;huge['average']={'junk':'z'*100000}
    complete_phase(engine,'run',call['attempt_id'],call['token'],'orchestrator',key='complete',
                   evidence=huge,outputs=outputs_for(call))
    snapshot = model.snapshot('run')
    assert len(json.dumps(snapshot)) < 60000
    preview = next(item for item in snapshot['artifacts'] if item['id']==artifact['id'])
    assert preview['metadata_truncated'] and preview['metadata']['formal_status']=='unverified'
    assert 'content' not in preview
    assert snapshot['attempts'][0]['evidence']['average'] is None
    detail = model.artifact('run', artifact['id'])
    assert detail['content'].startswith('<script>') and detail['render_as']=='text'  # Caller escapes text; never HTML execution.
    assert detail['metadata'] == metadata
    assert model.attempt('run',call['attempt_id'])['evidence']['padding']=='y'*700000
    engine.start('other','feature',{'uncertainty':'low'},strategy='classic')
    with pytest.raises(ValueError,match='Unknown'): model.artifact('other',artifact['id'])
    with pytest.raises(ValueError,match='Unknown'): model.attempt('other',call['attempt_id'])


def test_large_history_is_paginated_chronologically_and_responses_stay_bounded(store):
    engine = WorkflowEngine(store)
    definition = get_strategy('piqard').to_dict()
    for phase in definition['phases']: phase['max_attempts']=100
    engine.start('run','feature',{'uncertainty':'high'},strategy='piqard',definition=definition)
    phases = [p['id'] for p in definition['phases'] if p['kind'] != 'join']
    with transaction(store.path,write=True) as db:
        spec = engine.repository._get(db,'run')['specification_hash']
        for n in range(1000):
            phase = phases[n % len(phases)];number=n//len(phases)+1
            db.execute('INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('attempt-'+str(n),'run',phase,number,'failed','worker','never-return-token',0,spec,
                        json.dumps({'verdict':'FAIL','reviewer':{'agent':'fixture','review_type':'scripted_adapter'},'padding':'x'*2000}),now(),now()))
            if n<300:
                ArtifactRepository.add(db,'run','attempt-'+str(n),'fixture','text','worker',metadata={'padding':'x'*8000})
        db.executemany('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
                       [('feature','workflow.fixture','worker',json.dumps({'run_id':'run','reason':'x'*1000}),now()) for _ in range(10000)])
    model=ReadModel(store)
    snapshot=model.snapshot('run',limit=100)
    assert len(snapshot['attempts'])==100 and snapshot['has_more_attempts']
    assert snapshot['attempts'][0]['id']=='attempt-900' and snapshot['attempts'][-1]['id']=='attempt-999'
    assert len(json.dumps(snapshot))<1000000
    all_ids={row['id'] for row in snapshot['attempts']};before=snapshot['attempt_cursor']
    while before is not None:
        page=model.history('run',before=before,limit=137)
        ids={row['id'] for row in page['items']}
        assert not (ids & all_ids)
        assert [row['cursor'] for row in page['items']]==sorted(row['cursor'] for row in page['items'])
        all_ids|=ids;before=page['pagination']['cursor']
    assert len(all_ids)==1000
    events=model.events('run',after=0,limit=100)
    assert len(events['events'])<=100 and len(json.dumps(events))<150000 and events['has_more']
    artifact_page=model.history('run',resource='artifacts',limit=100)
    assert len(artifact_page['items'])==100 and artifact_page['pagination']['has_more']


def test_dense_work_pages_bound_both_nodes_and_edges_without_losing_graph(store):
    engine,call,model=running(store)
    for n in range(30): store.create('task','task-'+str(n).zfill(2),'T'*9000,'feature',{'acceptance_criteria':['A']})
    with transaction(store.path,write=True) as db:
        for n in range(30):
            for dep in range(n):
                db.execute('INSERT INTO edges VALUES(?,?,?)',('feature','task-'+str(n).zfill(2),'task-'+str(dep).zfill(2)))
    page=model.work('run',limit=7);nodes={};edges=set()
    while True:
        assert len(page['nodes'])<=7 and len(page['edges'])<=7
        for node in page['nodes']:
            assert len(node['title'])<=500 and 'data' not in node
            assert node['id'] not in nodes;nodes[node['id']]=node
        for edge in page['edges']:
            key=(edge['node_id'],edge['dependency_id']);assert key not in edges;edges.add(key)
        if not page['pagination']['has_more']:break
        page=model.work('run',after=page['pagination']['cursor'],limit=7)
    assert len(nodes)==31 and len(edges)==435
    assert model.node('run','task-00')['data']['acceptance_criteria']==['A']
    with pytest.raises(ValueError,match='Unknown'):model.node('run','plan')


def test_runs_and_participants_pages_are_complete_and_delivery_routes_hidden(store):
    engine,call,model=running(store)
    for n in range(5):
        engine.start('run-'+str(n),'feature',{'uncertainty':'low'},strategy='classic')
        Board(store).register('run','agent-'+str(n),'worker')
    first=model.runs(limit=2)
    assert len(first['runs'])==2 and first['pagination']['has_more']
    second=model.runs(limit=10,after=first['pagination']['cursor'])
    assert len(second['runs'])==4
    p=model.history('run',resource='participants',limit=2)
    assert p['pagination']['has_more'] and all('endpoint' not in item and 'target' not in item for item in p['items'])


@pytest.mark.parametrize('limit',[0,501,True,[],None,'100'])
def test_all_paged_queries_reject_unbounded_or_malformed_limits(store,limit):
    engine,call,model=running(store)
    for operation in [lambda:model.runs(limit=limit),lambda:model.snapshot('run',limit=limit),
                      lambda:model.events('run',limit=limit),lambda:model.history('run',limit=limit),lambda:model.work('run',limit=limit)]:
        with pytest.raises(ValueError):operation()


@pytest.mark.parametrize('value',[-1,True,[],{},'1',2**63])
def test_event_and_history_cursor_types_are_explicit(store,value):
    engine,call,model=running(store)
    with pytest.raises(ValueError):model.events('run',after=value)
    with pytest.raises(ValueError):model.history('run',before=value)


def test_unknown_resources_runs_and_bad_work_cursor_have_clear_errors(store):
    engine,call,model=running(store)
    for resource in ['unknown',[],{}]:
        with pytest.raises(ValueError):model.history('run',resource=resource)
    with pytest.raises(ValueError):model.work('run',after='spoq-work-1:bad-base64')
    with pytest.raises(ValueError):model.snapshot('unknown')
    with pytest.raises(ValueError):model.events('unknown')


def test_legacy_malformed_event_metadata_is_explicit_and_does_not_break_replay(store):
    engine,call,model=running(store)
    cursor=model.snapshot('run')['cursor']
    with transaction(store.path,write=True) as db:
        db.execute('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
                   ('feature','legacy_imported_event','old','not-json',now()))
    result=model.events('run',after=cursor)
    assert result['events'][0]['payload']=={} and result['events'][0]['payload_invalid']
    assert not result['reset']


def test_waiting_human_decision_metadata_and_truncated_findings_link_to_full_attempt(store):
    from test_workflow_checkpoints import waiting,reply
    engine,review=waiting(store)
    response=reply(engine,review,'reject',reason='Feedback '*1000)
    model=ReadModel(store)
    snapshot=model.snapshot('r')
    decision=snapshot['decisions'][0]
    assert decision['decision']=='reject' and decision['reason_truncated'] and len(decision['reason'])==1000
    assert model.attempt('r',review['attempt_id'])['evidence']['findings']=='Feedback '*999+'Feedback'
    assert decision['details_url'].endswith('/attempts/'+review['attempt_id'])
