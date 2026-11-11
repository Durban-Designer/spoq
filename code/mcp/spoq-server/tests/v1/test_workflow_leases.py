import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from spoq_server.v1.board import Board
from spoq_server.v1.db import transaction
from spoq_server.v1.workflows.artifacts import ArtifactRepository
from spoq_server.v1.workflows.leases import PhaseRunner, fenced_attempt


def runner(store, inputs=None, strategy='classic'):
    r = PhaseRunner(store)
    r.start('r', 'feature', inputs or {'uncertainty': 'low'}, strategy=strategy)
    Board(store).register('r', 'other', 'worker')
    return r


def test_next_retries_original_receipt_and_conflicts_on_changed_request(store):
    r = runner(store)
    first = r.next('r', 'orchestrator', key='next')
    assert first['phase_id'] == 'plan' and first['skill'] == 'spoq-plan'
    assert r.next('r', 'orchestrator', key='next') == first
    with pytest.raises(ValueError, match='different request'):
        r.next('r', 'orchestrator', key='next', ttl=200)
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 1


def test_concurrent_orchestrators_only_one_owns_phase(store):
    r = runner(store)
    revision = r.get('r')['revision']
    def claim(actor):
        try:
            return r.next('r', actor, key='next-' + actor, expected_revision=revision)
        except ValueError as exc:
            assert 'revision conflict' in str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ['orchestrator', 'other']))
    assert sum(bool(result and result.get('attempt_id')) for result in results) == 1
    active = next(result for result in results if result)
    blocked = r.next('r', 'other' if active['token'] and active == results[0] else 'orchestrator', key='another')
    assert 'attempt_id' not in blocked


def test_lease_recovery_keeps_attempt_and_artifacts_but_fences_previous_owner(store, monkeypatch):
    import spoq_server.v1.workflows.leases as module
    clock = [100.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    r = runner(store)
    first = r.next('r', 'orchestrator', key='claim', ttl=1)
    with transaction(store.path, write=True) as db:
        ArtifactRepository.add(db, 'r', first['attempt_id'], 'project_plan', 'ambiguous output', 'orchestrator')
    clock[0] = 102
    assert 'attempt_id' not in r.next('r', 'other', key='inspect-without-recovery')
    recovered = r.next('r', 'other', key='recover', recover=True)
    assert recovered['attempt_id'] == first['attempt_id']
    assert recovered['token'] != first['token'] and recovered['needs_inspection']
    assert len(recovered['prior_artifacts']) == 1
    with transaction(store.path) as db:
        with pytest.raises(ValueError, match='Stale'):
            fenced_attempt(db, r.repository._get(db, 'r'), first['attempt_id'], first['token'], 'orchestrator')
    assert r.renew('r', recovered['attempt_id'], recovered['token'], 'other', key='renew')['lease_until'] > 102


@pytest.mark.parametrize('ttl', [0, 3601, True, [], '300'])
def test_invalid_ttl_does_not_start_an_attempt(store, ttl):
    r = runner(store)
    with pytest.raises(ValueError, match='TTL'):
        r.next('r', 'orchestrator', key='bad', ttl=ttl)
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 0


def test_unregistered_participant_cannot_claim(store):
    r = runner(store)
    with pytest.raises(ValueError, match='Register'):
        r.next('r', 'unknown', key='bad')


def test_changed_spec_requires_deliberate_refresh(store):
    r = runner(store)
    node = store.get('feature')
    store.edit('feature', {'acceptance_criteria': ['Changed']}, expected_revision=node['revision'])
    with pytest.raises(ValueError, match='Specification changed'):
        r.next('r', 'orchestrator', key='bad')


def test_start_retry_does_not_override_existing_native_delivery_registration(store):
    r = runner(store)
    Board(store).register('r', 'orchestrator', 'worker', 'manual')
    r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    with transaction(store.path) as db:
        assert db.execute("SELECT role FROM agents WHERE run_id='r' AND id='orchestrator'").fetchone()[0] == 'worker'


def test_atomic_commit_receipt_cannot_duplicate_artifact_or_transition(store):
    r = runner(store)
    first = r.next('r', 'orchestrator', key='claim')
    def publish(db, current, attempt):
        artifact = ArtifactRepository.add(db, 'r', attempt['id'], 'project_plan', 'plan', 'orchestrator')
        return {'outcome': 'pass', 'outputs': {'project_plan': artifact['id']}, 'evidence': {'adapter': 'internal transaction test'}}
    result = r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='complete',
                       request={'content': 'plan'}, publish=publish)
    assert r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='complete',
                     request={'content': 'plan'}, publish=publish) == result
    with pytest.raises(ValueError, match='different request'):
        r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='complete',
                  request={'content': 'changed'}, publish=publish)
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_artifacts').fetchone()[0] == 1
        assert r.repository._get(db, 'r')['state']['transitions'] == 1
    assert r.next('r', 'orchestrator', key='gate')['phase_id'] == 'plan-validation'


def test_failed_atomic_publication_does_not_leave_artifacts_or_receipts(store):
    r = runner(store)
    first = r.next('r', 'orchestrator', key='claim')
    def fail(db, current, attempt):
        ArtifactRepository.add(db, 'r', attempt['id'], 'project_plan', 'plan', 'orchestrator')
        raise ValueError('publication failed')
    with pytest.raises(ValueError, match='publication failed'):
        r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='complete', request={}, publish=fail)
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_artifacts').fetchone()[0] == 0
        assert r.repository._get(db, 'r')['state']['transitions'] == 0


def test_live_claim_remains_required_even_if_caller_has_a_different_valid_agent_id(store):
    r = runner(store)
    first = r.next('r', 'orchestrator', key='claim')
    with pytest.raises(ValueError, match='Stale'):
        r._commit('r', first['attempt_id'], first['token'], 'other', key='bad', request={},
                  publish=lambda *args: pytest.fail('A stale publisher must not execute'))


def test_legacy_run_is_diagnosable_but_cannot_infer_a_strategy(store):
    r = runner(store)
    Board(store).run('old', 'feature')
    assert r.get('old')['status'] == 'legacy_unclassified'
    with pytest.raises(ValueError, match='Legacy runs'):
        r.next('old', 'orchestrator', key='bad')


def test_interrupted_last_planner_attempt_can_inspect_generated_tasks_before_refresh(store, monkeypatch):
    import spoq_server.v1.workflows.leases as module
    from spoq_server.v1.workflows.definitions import get_strategy
    clock = [100.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    source = get_strategy().to_dict()
    source['phases'][0]['max_attempts'] = 1
    r = PhaseRunner(store)
    r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic', definition=source)
    first = r.next('r', 'orchestrator', key='claim', ttl=1)
    store.create('task', 'generated', 'Expected planning output', 'feature')
    clock[0] = 102
    recovered = r.next('r', 'orchestrator', key='recover', recover=True)
    assert recovered['attempt_id'] == first['attempt_id']
    assert recovered['needs_inspection'] and recovered['requires_specification_refresh']
    assert recovered['current_specification_hash'] != recovered['specification_hash']
    with transaction(store.path) as db:
        assert db.execute('SELECT number FROM workflow_attempts').fetchone()[0] == 1
    # Root-goal edits cannot use the expected decomposition exception.
    store.edit('feature', {'goal': 'Different requested outcome'})
    with pytest.raises(ValueError, match='Specification changed'):
        r.next('r', 'orchestrator', key='wrong-root', recover=True)


def test_start_receipt_recovers_crash_between_run_commit_and_participant_registration(store, monkeypatch):
    import spoq_server.v1.workflows.leases as module
    from contextlib import contextmanager
    original = module.transaction
    crash = [True]
    @contextmanager
    def interrupted(path, *, write=False):
        if write and crash[0]:
            crash[0] = False
            raise OSError('simulated crash after run commit')
        with original(path, write=write) as db:
            yield db
    monkeypatch.setattr(module, 'transaction', interrupted)
    r = PhaseRunner(store)
    with pytest.raises(OSError, match='simulated crash'):
        r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    assert r.get('r')['revision'] == 1
    r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    assert r.next('r', 'orchestrator', key='claim')['phase_id'] == 'plan'


def test_rework_fences_other_parallel_attempts_in_the_invalidated_subgraph(store):
    from spoq_server.v1.workflows.definitions import get_strategy
    source = get_strategy('piqard').to_dict()
    source['edges'].append({'source': 'erd', 'target': 'discover', 'on': 'fail'})
    r = PhaseRunner(store)
    r.start('r', 'feature', {'addons': {'erd': True, 'diagram': True}}, definition=source)
    first = r.next('r', 'orchestrator', key='discover')
    def publish(db, current, attempt):
        artifact = ArtifactRepository.add(db, 'r', attempt['id'], 'discovery', 'discovery', 'orchestrator')
        return {'outcome': 'pass', 'outputs': {'discovery': artifact['id']}, 'evidence': {'adapter': 'internal test'}}
    r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='discover-done', request={}, publish=publish)
    diagram = r.next('r', 'orchestrator', key='diagram', phase_id='diagram')
    erd = r.next('r', 'orchestrator', key='erd', phase_id='erd')
    r._commit('r', erd['attempt_id'], erd['token'], 'orchestrator', key='fail', request={},
              publish=lambda *args: {'outcome': 'fail', 'outputs': {}, 'evidence': {'findings': ['Revise discovery']}})
    with transaction(store.path) as db:
        assert db.execute('SELECT status FROM workflow_attempts WHERE id=?', (diagram['attempt_id'],)).fetchone()[0] == 'blocked'
        with pytest.raises(ValueError, match='Stale'):
            fenced_attempt(db, r.repository._get(db, 'r'), diagram['attempt_id'], diagram['token'], 'orchestrator')
    assert r.next('r', 'orchestrator', key='revision')['phase_id'] == 'discover'


def test_exhausted_phase_budget_persists_and_duplicate_notifications_spend_nothing(store):
    from spoq_server.v1.workflows.definitions import get_strategy
    source = get_strategy().to_dict()
    source['phases'][0]['max_attempts'] = 1
    source['edges'].append({'source': 'plan', 'target': 'plan', 'on': 'fail'})
    r = PhaseRunner(store)
    r.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic', definition=source)
    first = r.next('r', 'orchestrator', key='claim')
    r._commit('r', first['attempt_id'], first['token'], 'orchestrator', key='fail', request={},
              publish=lambda *args: {'outcome': 'fail', 'outputs': {}, 'evidence': {'findings': ['Failed work']}})
    blocked = r.next('r', 'orchestrator', key='again')
    assert blocked['status'] == 'blocked'
    assert r.next('r', 'orchestrator', key='again') == blocked
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 1
