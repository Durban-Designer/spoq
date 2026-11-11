"""Receipts, fencing and pinned state persist across real repository reopen."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from spoq_server.v1.board import Board
from spoq_server.v1.db import transaction, now
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.repository import WorkflowRepository
from spoq_server.v1.workflows.types import content_hash


def definition():
    return {'schema_version': 1, 'id': 'test', 'version': '1.0.0', 'title': 'Test',
            'entry': 'plan', 'max_transitions': 6, 'edges': [],
            'phases': [{'id': 'plan', 'kind': 'skill', 'skill': 'spoq-plan', 'inputs': [], 'outputs': ['plan'], 'max_attempts': 3}]}


def state():
    return {'phases': {'plan': {'status': 'queued', 'ready': True, 'attempt_id': None}},
            'outputs': {}, 'transitions': 0, 'blockers': [], 'epoch': 0}


def started(store):
    repo = WorkflowRepository(store)
    row = repo.start('workflow-run', 'feature', definition(), {'inputs': {'goal': 'Build'}}, state(), 'start')
    return repo, row


def transition(db, current):
    value = current['state']
    value['transitions'] += 1
    return {'state': value, 'status': 'running', 'event_kind': 'test', 'payload': {'counter': value['transitions']},
            'result': {'counter': value['transitions']}}


def test_definition_and_route_are_immutable_and_survive_reopen(store):
    source, route = definition(), {'inputs': {'goal': 'Build'}}
    repo = WorkflowRepository(store)
    row = repo.start('workflow-run', 'feature', source, route, state(), 'start')
    source['title'] = 'Changed installed definition'
    route['inputs']['goal'] = 'Changed mutable request'
    row['definition']['title'] = 'Changed client copy'
    reopened = WorkflowRepository(Store(store.path)).get('workflow-run')
    assert reopened['definition']['title'] == 'Test'
    assert reopened['routing']['inputs']['goal'] == 'Build'
    assert reopened['definition_hash'] != 'changed'
    assert reopened['current_specification_hash'] == reopened['specification_hash']


def test_specification_digest_retains_exact_preexisting_canonical_hash(store):
    store.create('task', 'work', 'Unicode café', 'feature', {'nested': {'β': [True, None, 1.5]}, 'retry_count': 2})
    from spoq_server.v1.workflows.repository import OPERATIONAL_DATA
    with transaction(store.path) as db:
        specs = []
        for node_id in ['feature', 'work']:
            node = store._get(db, node_id)
            specs.append({'id': node['id'], 'kind': node['kind'], 'parent_id': node['parent_id'],
                          'title': node['title'], 'data': {k: v for k, v in node['data'].items() if k not in OPERATIONAL_DATA},
                          'dependencies': []})
        assert WorkflowRepository.specification_hash(db, 'feature') == content_hash(specs)


def test_large_realistic_specification_can_start_without_relaxing_message_limits(store):
    for i in range(120):
        store.create('task', f'task-{i:03}', 'Work item', 'feature',
                     {'description': 'Reviewable source context. ' * 500, 'acceptance_criteria': ['Observed result']})
    repo = WorkflowRepository(store)
    result = repo.start('large', 'feature', definition(), {'inputs': {'goal': 'Large plan'}}, state(), 'start')
    assert len(result['specification_hash']) == 64
    assert result['specification_hash'] == repo.get('large')['current_specification_hash']
    with pytest.raises(ValueError, match='finite JSON'):
        content_hash({'oversized_message': 'x' * (1024 * 1024 + 1)})


def test_start_idempotency_and_scope_identity(store):
    repo, row = started(store)
    assert repo.start('workflow-run', 'feature', definition(), {'inputs': {'goal': 'Build'}}, state(), 'start') == row
    changed = definition(); changed['title'] = 'Changed'
    with pytest.raises(ValueError, match='different request'):
        repo.start('workflow-run', 'feature', changed, {'inputs': {'goal': 'Build'}}, state(), 'start')
    with pytest.raises(ValueError, match='already exists'):
        repo.start('workflow-run', 'feature', definition(), {}, state(), 'other-start')
    Board(store).run('legacy', 'plan')
    with pytest.raises(ValueError, match='different scope'):
        repo.start('legacy', 'feature', definition(), {}, state(), 'start')


def test_mutation_receipt_returns_original_result_and_preserves_event_order(store):
    repo, row = started(store)
    result = repo.mutate('workflow-run', 'complete', row['revision'], 'worker', transition, request={'phase': 'plan'})
    assert result == {'counter': 1, 'run_id': 'workflow-run', 'revision': 2}
    assert repo.mutate('workflow-run', 'complete', 999, 'worker', transition, request={'phase': 'plan'}) == result
    with pytest.raises(ValueError, match='different request'):
        repo.mutate('workflow-run', 'complete', 2, 'worker', transition, request={'phase': 'other'})
    with pytest.raises(ValueError, match='revision conflict'):
        repo.mutate('workflow-run', 'next', 1, 'worker', transition, request={'phase': 'plan'})
    events = [r for r in store.history('feature') if r['kind'].startswith('workflow.')]
    assert [r['kind'] for r in events] == ['workflow.started', 'workflow.test']
    assert json.loads(events[-1]['payload'])['revision'] == 2
    assert WorkflowRepository(Store(store.path)).get('workflow-run')['state']['transitions'] == 1


def insert_attempt(db, current, key='attempt-1', number=1):
    db.execute('INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               (key, current['run_id'], 'plan', number, 'running', 'worker', 'fence', 9999999999,
                current['specification_hash'], '{}', now(), now()))


def test_callback_writes_and_failed_transition_roll_back_together(store):
    repo, row = started(store)
    def invalid(db, current):
        insert_attempt(db, current)
        return {'state': current['state'], 'status': 'invented', 'event_kind': 'invalid'}
    with pytest.raises(ValueError, match='status'):
        repo.mutate('workflow-run', 'bad', 1, 'worker', invalid, request={})
    with transaction(store.path) as db:
        assert not db.execute('SELECT 1 FROM workflow_attempts').fetchone()
        assert not db.execute("SELECT 1 FROM workflow_receipts WHERE key='bad'").fetchone()
    assert repo.get('workflow-run')['revision'] == 1


def test_concurrent_attempt_claim_has_one_winner_and_unique_active_phase(store):
    repo, row = started(store)
    def attempt(n):
        def callback(db, current):
            insert_attempt(db, current, 'attempt-' + str(n))
            return transition(db, current)
        try:
            return repo.mutate('workflow-run', 'claim-' + str(n), 1, 'worker', callback, request={'n': n})
        except ValueError as exc:
            assert 'revision conflict' in str(exc)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sum(r is not None for r in results) == 1
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 1
    def duplicate(db, current):
        insert_attempt(db, current, 'attempt-duplicate', 2)
        return transition(db, current)
    with pytest.raises(sqlite3.IntegrityError):
        repo.mutate('workflow-run', 'duplicate', 2, 'worker', duplicate, request={})
    assert repo.get('workflow-run')['revision'] == 2


def test_legacy_runs_are_explicitly_unclassified(store):
    Board(store).run('legacy', 'feature')
    repo = WorkflowRepository(store)
    row = repo.get('legacy')
    assert row['strategy'] == 'legacy_unclassified' and row['state'] == {} and row['definition'] is None
    assert repo.list()[0]['run_id'] == 'legacy'
    with pytest.raises(ValueError, match='Legacy runs'):
        repo.mutate('legacy', 'key', 1, 'worker', transition, request={})


def test_scope_specification_ignores_bookkeeping_but_not_acceptance_or_dependencies(store):
    store.create('task', 'a', 'A', 'feature', {'acceptance_criteria': ['Tests'], 'retry_count': 0})
    store.create('task', 'b', 'B', 'feature')
    repo, row = started(store)
    original = row['specification_hash']
    store.update('a', 'in_progress')
    store.edit('a', {'retry_count': 1, 'execution': {'worker': 'backend'}})
    assert repo.get('workflow-run')['current_specification_hash'] == original
    store.edit('a', {'acceptance_criteria': ['Different tests']})
    changed = repo.get('workflow-run')['current_specification_hash']
    assert changed != original
    store.depend('b', 'a')
    assert repo.get('workflow-run')['current_specification_hash'] != changed
    assert repo.get('workflow-run')['specification_hash'] == original


def test_explicit_specification_rebase_must_match_actual_scope(store):
    repo, row = started(store)
    store.edit('feature', {'acceptance_criteria': ['New']})
    actual = repo.get('workflow-run')['current_specification_hash']
    def callback(db, current):
        return {**transition(db, current), 'specification_hash': actual}
    repo.mutate('workflow-run', 'rebase', 1, 'worker', callback, request={'specification_hash': actual})
    assert repo.get('workflow-run')['specification_hash'] == actual
    def forged(db, current):
        return {**transition(db, current), 'specification_hash': 'f' * 64}
    with pytest.raises(ValueError, match='match the current scope'):
        repo.mutate('workflow-run', 'forged', 2, 'worker', forged, request={})


@pytest.mark.parametrize('key', ['', ' ', 'line\nbreak', 'a' * 201])
def test_operation_key_is_explicit_and_bounded(store, key):
    repo = WorkflowRepository(store)
    with pytest.raises(ValueError, match='operation key'):
        repo.start('workflow-run', 'feature', definition(), {}, state(), key)


@pytest.mark.parametrize('limit', [0, 501, True])
def test_list_is_bounded(store, limit):
    with pytest.raises(ValueError, match='limit'):
        WorkflowRepository(store).list(limit=limit)


def test_persisting_default_task_budget_is_semantically_equivalent_to_omission(store):
    store.create('task', 'work', 'Work', 'feature', {'acceptance_criteria': ['Checks pass']})
    repo, original = started(store)
    store.edit('work', {'max_retries': 3, 'retry_count': 1})
    assert repo.get('workflow-run')['current_specification_hash'] == original['specification_hash']
    store.edit('work', {'max_retries': 4})
    assert repo.get('workflow-run')['current_specification_hash'] != original['specification_hash']
    store.edit('work', {'max_retries': 3})
    assert repo.get('workflow-run')['current_specification_hash'] == original['specification_hash']


@pytest.mark.parametrize('budget', [4, 0, -1, True, False, 3.0, '3', None, [], {}])
def test_nondefault_or_differently_typed_task_budget_remains_semantic(store, budget):
    store.create('task', 'work', 'Work', 'feature')
    repo, original = started(store)
    store.edit('work', {'max_retries': budget})
    assert repo.get('workflow-run')['current_specification_hash'] != original['specification_hash']


def test_default_equivalence_does_not_hide_feature_domain_metadata(store):
    repo, original = started(store)
    store.edit('feature', {'max_retries': 3})
    assert repo.get('workflow-run')['current_specification_hash'] != original['specification_hash']


def _execution_ready_with_omitted_task_budget(store):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for, outputs_for
    store.create('task', 'work', 'Implement planned work', 'feature',
                 {'acceptance_criteria': ['Actual implementation checks pass']})
    engine = WorkflowEngine(store)
    engine.start('execution-run', 'feature', {'uncertainty': 'low'}, strategy='classic')
    plan = engine.next('execution-run', 'orchestrator', key='plan')
    engine.complete('execution-run', plan['attempt_id'], plan['token'], 'orchestrator', key='planned',
                    evidence=evidence_for(plan), outputs=outputs_for(plan))
    gate = engine.next('execution-run', 'orchestrator', key='planning-gate')
    engine.complete('execution-run', gate['attempt_id'], gate['token'], 'orchestrator', key='planning-gate-done',
                    evidence=evidence_for(gate, stage='plan'))
    invocation = engine.next('execution-run', 'orchestrator', key='execute')
    assert invocation['work']['ready_tasks'] == ['work']
    claim = store.claim('work', 'execution-run', 'orchestrator')
    return engine, invocation, claim


def test_execution_default_persistence_finishes_original_phase_without_spec_refresh(store):
    """Regression for the real native-client first-use flow, not a hash-only test."""
    from workflow_support import evidence_for, outputs_for
    engine, invocation, claim = _execution_ready_with_omitted_task_budget(store)
    task = store.get('work')
    store.edit('work', {'max_retries': 3, 'retry_count': 1}, expected_revision=task['revision'])
    store.update('work', 'completed', claim_token=claim['token'],
                 evidence={'source': 'scripted adapter regression', 'checks_passed': True})
    assert engine.inspect('execution-run')['current_specification_hash'] == invocation['specification_hash']
    result = engine.complete('execution-run', invocation['attempt_id'], invocation['token'], 'orchestrator',
                             key='implemented', evidence=evidence_for(invocation), outputs=outputs_for(invocation))
    assert result['outcome'] == 'pass'
    final = engine.next('execution-run', 'orchestrator', key='implementation-gate')
    assert final['phase_id'] == 'implementation-validation'
    assert engine.complete('execution-run', final['attempt_id'], final['token'], 'orchestrator',
                           key='implementation-gate-done', evidence=evidence_for(final, stage='implementation'))['status'] == 'passed'
    current = engine.inspect('execution-run')
    assert current['state']['epoch'] == 0
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 4
        assert db.execute('SELECT MAX(number) FROM workflow_attempts').fetchone()[0] == 1


def test_nondefault_task_budget_change_still_prevents_unchanged_execution_evidence(store):
    from workflow_support import evidence_for, outputs_for
    engine, invocation, claim = _execution_ready_with_omitted_task_budget(store)
    store.edit('work', {'max_retries': 4, 'retry_count': 1})
    store.update('work', 'completed', claim_token=claim['token'], evidence={'source': 'scripted regression'})
    assert engine.inspect('execution-run')['current_specification_hash'] != invocation['specification_hash']
    with pytest.raises(ValueError, match='Specification changed'):
        engine.complete('execution-run', invocation['attempt_id'], invocation['token'], 'orchestrator',
                        key='must-not-accept', evidence=evidence_for(invocation), outputs=outputs_for(invocation))
