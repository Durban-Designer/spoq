import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from spoq_server.v1.db import transaction
from spoq_server.v1.graph import waves
from spoq_server.v1.store import Store


def test_feature_and_project_plan_use_same_dag(store):
    store.create('task','a','A','feature')
    store.create('task','b','B','feature')
    store.depend('b','a')
    assert store.dag('feature')['waves']==[['a'],['b']]
    assert store.dag('feature')['ready']==['a']
    store.create('feature','next','Next','plan')
    store.depend('next','feature')
    assert store.dag('plan')['waves']==[['feature'],['next']]
    assert store.dag('next')['ready']==[]


def test_cycle_rejected_without_partial_edge_or_event(store):
    for key in ('a','b'): store.create('task',key,key,'feature')
    store.depend('b','a')
    before=store.history('a')
    with pytest.raises(ValueError,match='cycle'): store.depend('a','b')
    assert store.dag('feature')['dependencies']['a']==[]
    assert store.history('a')==before


def test_unknown_and_cross_scope_dependencies_rejected(store):
    store.create('feature','other','Other','plan')
    store.create('task','a','A','feature')
    store.create('task','b','B','other')
    with pytest.raises(ValueError): store.depend('a','b')
    with pytest.raises(ValueError): store.depend('a','missing')
    with pytest.raises(ValueError): store.create('task','c','C','plan')
    with pytest.raises(ValueError): waves({'a':['missing']})


def test_revision_and_validation_evidence(store):
    store.create('task','a','A','feature')
    with pytest.raises(ValueError,match='evidence'): store.update('a','completed')
    store.update('a','in_progress',expected_revision=1)
    with pytest.raises(ValueError,match='Revision'): store.update('a','qa',expected_revision=1)
    store.update('a','completed',expected_revision=2,evidence={'unit_tests':'passed','build':'passed'})
    assert json.loads(store.history('a')[-1]['payload'])['evidence']['build']=='passed'
    store.update('feature','completed')
    store.update('plan','completed')


def test_dependencies_cannot_be_bypassed_by_completion(store):
    for key in ('a','b'): store.create('task',key,key,'feature')
    store.depend('b','a')
    with pytest.raises(ValueError,match='Dependencies'): store.update('b','completed',evidence={'tests':True})
    with pytest.raises(ValueError,match='children'): store.update('feature','completed')


def test_plan_dependency_blocks_tasks_in_later_feature(store):
    store.create('feature','later','Later','plan')
    store.create('task','b','B','later')
    store.depend('later','feature')
    assert store.dag('later')['ready']==[]
    with pytest.raises(ValueError): store.update('b','in_progress')
    with pytest.raises(ValueError,match='ancestor'): store.update('b','completed',evidence={'tests':'passed'})


def test_concurrent_claim_has_one_owner(store,board):
    store.create('task','a','A','feature')
    def attempt(agent):
        try: return store.claim('a','run',agent)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,['backend','frontend']))
    assert sum(r is not None for r in results)==1


def test_expired_claim_fences_old_worker(store,board):
    store.create('task','a','A','feature')
    old=store.claim('a','run','backend')
    with transaction(store.path,write=True) as db: db.execute('UPDATE claims SET expires_at=0')
    new=store.claim('a','run','frontend')
    with pytest.raises(ValueError,match='claim token'): store.update('a','completed',evidence={'tests':True},claim_token=old['token'])
    store.renew_claim('a',new['token'])
    store.update('a','completed',evidence={'tests':True},claim_token=new['token'])


def test_journal_and_state_survive_reopen(store):
    entry=store.journal('## Decision\nUse SQLite.',node_id='feature',metadata={'confidence':0.9})
    reopened=Store(store.path)
    assert reopened.journals('feature')[0]['id']==entry['id']
    assert reopened.get('feature')['title']=='Feature'


def test_released_claim_still_rejects_old_token(store,board):
    store.create('task','a','A','feature')
    claim=store.claim('a','run','backend')
    store.update('a','qa',claim_token=claim['token'])
    with pytest.raises(ValueError,match='Stale claim'): store.update('a','completed',evidence={'tests':True},claim_token=claim['token'])


def test_completed_ancestors_must_be_reopened_explicitly(store):
    store.create('task','a','A','feature')
    store.update('a','completed',evidence={'tests':True})
    store.update('feature','completed')
    with pytest.raises(ValueError,match='Reopen'): store.update('a','rework')
    with pytest.raises(ValueError,match='Reopen'): store.create('task','b','B','feature')
    store.update('feature','rework')
    store.update('a','rework')
    assert store.dag('feature')['ready']==['a']


def test_incorrect_dependencies_can_be_removed_with_history(store):
    for key in ('a','b'): store.create('task',key,key,'feature')
    store.depend('b','a')
    assert store.remove_dependency('b','a')['removed']
    assert store.dag('feature')['waves']==[['a','b']]
    assert store.history('b')[-1]['kind']=='dependency_removed'
    assert not store.remove_dependency('b','a')['removed']
