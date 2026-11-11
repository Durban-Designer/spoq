import json

import pytest

from spoq_server.v1.db import transaction
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.leases import fenced_attempt
from spoq_server.v1.workflows.artifacts import ArtifactRepository
from spoq_server.v1.store import Store
from workflow_support import evidence_for, outputs_for


def started(store, definition=None):
    r = WorkflowEngine(store)
    r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic', definition=definition)
    return r


def test_pause_allows_inflight_evidence_but_stops_new_dispatch_until_resumed(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    assert r.pause('r', key='pause')['status'] == 'paused'
    result = r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='done', evidence=evidence_for(call), outputs=outputs_for(call))
    assert result['status'] == 'paused'
    assert r.next('r', 'orchestrator', key='stopped')['status'] == 'paused'
    assert r.resume('r', key='resume')['status'] == 'running'
    assert r.next('r', 'orchestrator', key='gate')['phase_id'] == 'plan-validation'


def test_changed_criteria_requires_explicit_refresh_preserves_history_and_fences_active_attempt(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='planned', evidence=evidence_for(call), outputs=outputs_for(call))
    call = r.next('r', 'orchestrator', key='gate')
    store.edit('feature', {'acceptance_criteria': ['Changed observable criterion']})
    with pytest.raises(ValueError, match='explicitly resume'):
        r.resume('r', key='implicit')
    result = r.resume('r', key='explicit', refresh_spec=True)
    assert result['inspection_required'] == [call['attempt_id']]
    with transaction(store.path) as db:
        with pytest.raises(ValueError, match='Stale'):
            fenced_attempt(db, r.repository._get(db, 'r'), call['attempt_id'], call['token'], 'orchestrator')
        assert db.execute('SELECT status FROM workflow_attempts WHERE id=?', (call['attempt_id'],)).fetchone()[0] == 'blocked'
    after = r.next('r', 'orchestrator', key='replanned')
    assert after['attempt_id'] != call['attempt_id']
    assert after['specification_hash'] != call['specification_hash']


def test_changed_goal_uses_successor_so_no_invocation_can_receive_a_stale_pinned_goal(store):
    r = started(store)
    old = r.next('r', 'orchestrator', key='plan')
    store.edit('feature', {'goal': 'Changed requested outcome'})
    with pytest.raises(ValueError, match='Goal changed'):
        r.resume('r', key='cannot-rewrite-route', refresh_spec=True)
    r.pause('r', key='pause-old')
    successor = r.start('successor', 'feature', {'uncertainty': 'low'}, strategy='classic')
    assert successor['routing']['inputs']['goal'] == 'Changed requested outcome'
    assert r.get('r')['routing']['inputs']['goal'] == old['inputs']['goal']
    assert r.next('successor', 'orchestrator', key='fresh')['inputs']['goal'] == 'Changed requested outcome'
    assert r.get('successor')['state']['outputs'] == {}


def test_minimal_new_plan_can_record_derived_root_metadata_and_decomposition(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    store.edit('feature', {'assumptions': ['Local execution'], 'architecture': {'design': 'Small modules'},
                           'acceptance_criteria': ['An observed passing check']})
    store.create('task', 'work', 'Implement the planned work', 'feature')
    current_hash = r.get('r')['current_specification_hash']
    assert current_hash != call['specification_hash']
    call['specification_hash'] = current_hash
    result = r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='planned',
                         evidence=evidence_for(call), outputs=outputs_for(call), refresh_spec=True)
    assert result['outcome'] == 'pass'
    assert r.next('r', 'orchestrator', key='gate')['phase_id'] == 'plan-validation'


@pytest.mark.parametrize('key,value', [('user_inputs', {'constraint': 'New input'}),
                                      ('user_constraints', ['New user constraint']),
                                      ('user_request', 'A different raw request')])
def test_changed_raw_user_input_cannot_be_reclassified_as_derived_planning_output(store,key,value):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    store.edit('feature', {key: value})
    fresh = {**call, 'specification_hash': r.get('r')['current_specification_hash']}
    with pytest.raises(ValueError, match='Specification changed'):
        r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='bad',
                   evidence=evidence_for(fresh), outputs=outputs_for(fresh), refresh_spec=True)
    with pytest.raises(ValueError, match='User inputs changed'):
        r.resume('r', key='cannot-change-route', refresh_spec=True)


@pytest.mark.parametrize('field', ['inputs', 'outputs'])
def test_control_only_joins_cannot_implicitly_validate_or_produce_artifacts(store, field):
    source = get_strategy('piqard').to_dict()
    join = next(p for p in source['phases'] if p['id'] == 'design-join')
    join[field] = ['discovery'] if field == 'inputs' else ['joined']
    with pytest.raises(ValueError, match='control-only'):
        WorkflowEngine(store).start('r', 'feature', {}, definition=source)


def test_pause_resume_interrupted_planning_outputs_does_not_spend_another_attempt(store, monkeypatch):
    import spoq_server.v1.workflows.leases as leases
    now = [100.0]
    monkeypatch.setattr(leases.time, 'time', lambda: now[0])
    source = get_strategy().to_dict(); source['phases'][0]['max_attempts'] = 1
    r = started(store, source)
    call = r.next('r', 'orchestrator', key='plan', ttl=1)
    store.create('task', 'generated', 'Expected planned task', 'feature')
    r.pause('r', key='pause')
    now[0] = 102
    assert r.resume('r', key='resume')['requires_specification_refresh']
    recovered = r.recover('r', key='recover')
    assert recovered['attempt_id'] == call['attempt_id'] and recovered['needs_inspection']
    recovered['specification_hash'] = recovered['current_specification_hash']
    assert r.complete('r', recovered['attempt_id'], recovered['token'], 'orchestrator', key='done',
                      evidence=evidence_for(recovered), outputs=outputs_for(recovered), refresh_spec=True)['outcome'] == 'pass'


def test_bounded_retry_after_failure_keeps_old_attempt_and_never_resets_counters(store):
    source = get_strategy().to_dict(); source['phases'][0]['max_attempts'] = 1
    r = started(store, source)
    call = r.next('r', 'orchestrator', key='plan')
    assert r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='fail', evidence=evidence_for(call, passed=False))['outcome'] == 'fail'
    result = r.resume('r', key='retry')
    assert result['status'] == 'blocked'
    assert 'exhausted' in result['blockers'][0]
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 1


def test_available_retry_reopens_only_failed_phase_and_preserves_evidence(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    r.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='fail', evidence=evidence_for(call, passed=False))
    assert r.resume('r', key='retry')['status'] == 'queued'
    second = r.next('r', 'orchestrator', key='again')
    assert second['attempt_id'] != call['attempt_id']
    with transaction(store.path) as db:
        assert db.execute('SELECT MAX(number) FROM workflow_attempts').fetchone()[0] == 2
        assert json.loads(db.execute('SELECT evidence FROM workflow_attempts WHERE id=?', (call['attempt_id'],)).fetchone()[0])['verdict'] == 'FAIL'


def test_inspection_never_launches_a_model_and_is_read_only(store):
    r = started(store)
    before = r.get('r')['revision']
    inspected = r.inspect('r')
    assert inspected['engine_launches_models'] is False
    assert inspected['client_mode'] == 'client_driven'
    assert r.get('r')['revision'] == before


def test_reopen_after_publication_inspects_same_unexpired_attempt_and_reuses_immutable_artifact(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    artifact = ArtifactRepository(r.repository).register('r', call['attempt_id'], 'project_plan',
        json.dumps(outputs_for(call)['project_plan']['content']), 'orchestrator', key='publish',
        expected_revision=r.get('r')['revision'])
    reopened = WorkflowEngine(Store(store.path))
    recovered = reopened.recover('r', key='inspect')
    assert recovered['attempt_id'] == call['attempt_id'] and recovered['needs_inspection']
    assert recovered['prior_artifacts'][0]['id'] == artifact['id']
    result = reopened.complete('r', recovered['attempt_id'], recovered['token'], 'orchestrator', key='done',
                               evidence=evidence_for(recovered), outputs={'project_plan': artifact['id']})
    assert result['outcome'] == 'pass'
    again = WorkflowEngine(Store(store.path)).recover('r', key='next-after-restart')
    assert again['phase_id'] == 'plan-validation'
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_artifacts').fetchone()[0] == 1
        assert db.execute("SELECT MAX(number) FROM workflow_attempts WHERE phase_id='plan'").fetchone()[0] == 1


def test_completed_receipt_and_journal_survive_reopen_without_duplicate_work(store):
    r = started(store)
    call = r.next('r', 'orchestrator', key='plan')
    kwargs = dict(key='done', evidence=evidence_for(call), outputs=outputs_for(call))
    result = r.complete('r', call['attempt_id'], call['token'], 'orchestrator', **kwargs)
    reopened = WorkflowEngine(Store(store.path))
    assert reopened.complete('r', call['attempt_id'], call['token'], 'orchestrator', **kwargs) == result
    assert result['validation_journal_id'] in [j['id'] for j in store.journals('feature')]


@pytest.mark.parametrize('kwargs', [{'refresh_spec': 'yes'}, {'retry_phase': []}, {'retry_phase': 'unknown'}])
def test_invalid_recovery_requests_do_not_mutate_state(store, kwargs):
    r = started(store)
    before = r.get('r')['revision']
    with pytest.raises(ValueError): r.resume('r', key='bad', **kwargs)
    assert r.get('r')['revision'] == before
