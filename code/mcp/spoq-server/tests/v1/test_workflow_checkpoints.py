"""Actual PIQARD user checkpoints, including revision and restart boundaries."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from spoq_server.v1.db import transaction
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.checkpoints import respond, propose_route
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.evidence import complete_phase
from spoq_server.v1.workflows.leases import PhaseRunner
from spoq_server.v1.workflows.repository import WorkflowRepository
from spoq_server.v1.workflows.decisions import DecisionRepository
from workflow_support import evidence_for, outputs_for


def narrative(revision='one'):
    return {'scope': 'Implement the agreed feature, revision ' + revision,
            'decisions': ['Use the local store'], 'assumptions': ['Offline user review'],
            'risks': ['Stale approval'], 'acceptance_criteria': ['Tests and current revision pass']}


def waiting(store, *, definition=None):
    runner = PhaseRunner(store)
    runner.start('r', 'feature', {'uncertainty': 'high'}, strategy='piqard', definition=definition)
    discover = runner.next('r', 'orchestrator', key='discover')
    assert discover['phase_id'] == 'discover'
    complete_phase(runner, 'r', discover['attempt_id'], discover['token'], 'orchestrator', key='discover-done',
                   evidence=evidence_for(discover), outputs={'discovery': {'content': 'Record the user constraints and decisions.'}})
    drafted = runner.next('r', 'orchestrator', key='narrative')
    assert drafted['phase_id'] == 'narrative'
    complete_phase(runner, 'r', drafted['attempt_id'], drafted['token'], 'orchestrator', key='narrative-done',
                   evidence=evidence_for(drafted), outputs={'narrative_plan': {'content': narrative()}})
    review = runner.next('r', 'orchestrator', key='review')
    assert review['phase_id'] == 'review' and review['status'] == 'waiting_human'
    return runner, review


def reply(runner, review, decision='approve', *, key='response', reason='', **kwargs):
    row = review['inputs']['narrative_plan']
    return respond(runner, 'r', review['attempt_id'], row['id'], row['sha256'], decision,
                   'User Name', key=key, source='user', user_confirmed=True, reason=reason, **kwargs)


def test_approval_is_bound_to_revision_and_unlocks_decomposition_with_persisted_journal(store):
    runner, review = waiting(store)
    before = runner.get('r')
    assert not before['state']['phases']['plan']['ready']
    result = reply(runner, review)
    assert result['outcome'] == 'pass' and runner.get('r')['state']['phases']['plan']['ready']
    planned = runner.next('r', 'orchestrator', key='plan')
    assert planned['skill'] == 'spoq-plan'
    with transaction(store.path) as db:
        decision = dict(db.execute('SELECT * FROM workflow_decisions').fetchone())
        report = json.loads(db.execute('SELECT body FROM journal_entries WHERE id=?', (result['validation_journal_id'],)).fetchone()[0])
        assert decision['author'] == 'User Name' and decision['source'] == 'user'
        assert decision['artifact_hash'] == review['inputs']['narrative_plan']['sha256']
        assert report['reviewer']['review_type'] == 'human' and report['verdict'] == 'APPROVED'
        assert report['stage'] == 'human_checkpoint' and 'scores' not in report and 'average' not in report
        assert report['artifact_hashes'] == review['artifact_hashes']
        assert report['definition_hash'] == review['definition_hash']
        assert report['output_hashes']['decision']
        assert report['provenance'] == 'user_action_attested_by_local_client_not_os_authenticated'
    assert DecisionRepository(runner.repository).is_current(result['decision_id'])


def test_rejection_revises_narrative_and_rejects_stale_approval(store):
    runner, first = waiting(store)
    rejected = reply(runner, first, 'reject', reason='Clarify the rollback risk.')
    assert rejected['outcome'] == 'fail'
    state = runner.get('r')['state']
    assert state['phases']['narrative']['ready'] and not state['phases']['plan']['ready']
    assert 'narrative_plan' not in state['outputs'] and 'decision' not in state['outputs']
    assert state['epoch'] == 1
    drafted = runner.next('r', 'orchestrator', key='narrative-v2')
    assert drafted['attempt_id'] != first['attempt_id']
    complete_phase(runner, 'r', drafted['attempt_id'], drafted['token'], 'orchestrator', key='narrative-v2-done',
                   evidence=evidence_for(drafted), outputs={'narrative_plan': {'content': narrative('two')}})
    second = runner.next('r', 'orchestrator', key='review-v2')
    assert second['attempt_id'] != first['attempt_id']
    with pytest.raises(ValueError):
        reply(runner, first, key='stale-approve')
    original = first['inputs']['narrative_plan']
    with pytest.raises(ValueError, match='exact primary artifact'):
        respond(runner, 'r', second['attempt_id'], original['id'], original['sha256'], 'approve', 'User Name',
                key='wrong-revision', source='user', user_confirmed=True)
    assert reply(runner, second, key='approve-v2')['outcome'] == 'pass'
    with transaction(store.path) as db:
        decisions = list(db.execute('SELECT * FROM workflow_decisions ORDER BY rowid'))
        assert [row['decision'] for row in decisions] == ['reject', 'approve']
        assert decisions[0]['artifact_hash'] != decisions[1]['artifact_hash']
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='narrative'").fetchone()[0] == 2
        assert db.execute('SELECT status FROM workflow_attempts WHERE id=?', (first['attempt_id'],)).fetchone()[0] == 'failed'
        report = json.loads(db.execute('SELECT body FROM journal_entries WHERE id=?', (rejected['validation_journal_id'],)).fetchone()[0])
        assert report['findings'] == 'Clarify the rollback risk.'


def test_waiting_days_and_duplicate_polls_do_not_spend_attempts_or_transitions(store, monkeypatch):
    import spoq_server.v1.workflows.leases as leases
    clock = [100.0]
    monkeypatch.setattr(leases.time, 'time', lambda: clock[0])
    runner, review = waiting(store)
    before = runner.get('r')['state']['transitions']
    clock[0] += 7 * 86400
    for n in range(5):
        polled = runner.next('r', 'orchestrator', key='human-poll-' + str(n))
        assert polled['attempt_id'] == review['attempt_id'] and polled['token'] is None
    assert runner.get('r')['state']['transitions'] == before
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='review'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='execute'").fetchone()[0] == 0
    assert reply(runner, review)['outcome'] == 'pass'


def test_duplicate_response_returns_original_receipt_and_changed_payload_rejected(store):
    runner, review = waiting(store)
    one = reply(runner, review)
    after = runner.get('r')
    assert reply(runner, review, expected_revision=1) == one
    assert runner.get('r')['revision'] == after['revision']
    assert runner.get('r')['state']['transitions'] == after['state']['transitions']
    with pytest.raises(ValueError, match='different request'):
        reply(runner, review, 'reject', reason='Changed request')
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM workflow_artifacts WHERE kind='decision'").fetchone()[0] == 1


@pytest.mark.parametrize('source,confirmed', [('agent', True), ('peer', True), ('notification', True), ('user', False), ('user', 1), ([], True)])
def test_only_attested_user_action_can_advance_human_checkpoint(store, source, confirmed):
    runner, review = waiting(store)
    artifact = review['inputs']['narrative_plan']
    with pytest.raises(ValueError, match='user-originated'):
        respond(runner, 'r', review['attempt_id'], artifact['id'], artifact['sha256'], 'approve', 'Human',
                key='bad-origin', source=source, user_confirmed=confirmed)
    assert not runner.get('r')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 0


@pytest.mark.parametrize('decision', [[], {}, None, False, 'maybe'])
def test_malformed_decision_has_deliberate_error(store, decision):
    runner, review = waiting(store)
    with pytest.raises(ValueError, match='approve or reject'):
        reply(runner, review, decision)


def test_changed_scope_or_artifact_hash_refuses_response_without_partial_records(store):
    runner, review = waiting(store)
    artifact = review['inputs']['narrative_plan']
    with pytest.raises(ValueError, match='revision does not match'):
        respond(runner, 'r', review['attempt_id'], artifact['id'], 'f' * 64, 'approve', 'User',
                key='wrong-hash', source='user', user_confirmed=True)
    store.edit('feature', {'acceptance_criteria': ['Changed after presentation']})
    with pytest.raises(ValueError, match='Specification changed'):
        reply(runner, review)
    with transaction(store.path) as db:
        assert not db.execute('SELECT 1 FROM workflow_decisions').fetchone()
        assert not db.execute("SELECT 1 FROM workflow_artifacts WHERE kind='decision'").fetchone()


def test_wrong_current_discovery_artifact_cannot_substitute_for_narrative(store):
    runner, review = waiting(store)
    artifact = runner.get('r')['state']['outputs']['discovery']
    with transaction(store.path) as db:
        wrong = dict(db.execute('SELECT * FROM workflow_artifacts WHERE id=?', (artifact,)).fetchone())
    with pytest.raises(ValueError, match='exact primary artifact'):
        respond(runner, 'r', review['attempt_id'], wrong['id'], wrong['sha256'], 'approve', 'User',
                key='wrong-artifact', source='user', user_confirmed=True)


def test_human_attempt_budget_exhaustion_blocks_without_granting_another_review(store):
    definition = get_strategy('piqard').to_dict()
    next(p for p in definition['phases'] if p['id'] == 'review')['max_attempts'] = 1
    runner, review = waiting(store, definition=definition)
    reply(runner, review, 'reject', reason='Need a revision.')
    draft = runner.next('r', 'orchestrator', key='draft2')
    complete_phase(runner, 'r', draft['attempt_id'], draft['token'], 'orchestrator', key='draft2-done',
                   evidence=evidence_for(draft), outputs={'narrative_plan': {'content': narrative('two')}})
    blocked = runner.next('r', 'orchestrator', key='review2')
    assert blocked['status'] == 'blocked' and 'budget exhausted' in blocked['blockers'][0]
    assert not runner.get('r')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='review'").fetchone()[0] == 1
        assert db.execute('SELECT reason FROM workflow_decisions').fetchone()[0] == 'Need a revision.'


def test_transition_budget_exhaustion_retains_rejection_and_blocks_dependents(store):
    definition = get_strategy('piqard').to_dict()
    definition['max_transitions'] = 8
    runner, review = waiting(store, definition=definition)
    response = reply(runner, review, 'reject', reason='Revise within a new authorized budget.')
    assert response['status'] == 'blocked'
    assert runner.next('r', 'orchestrator', key='exhausted')['status'] == 'blocked'
    assert runner.get('r')['state']['transitions'] == 8
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='narrative'").fetchone()[0] == 1


def test_paused_run_records_user_response_without_dispatching_next_phase(store):
    runner, review = waiting(store)
    current = runner.get('r')
    def pause(db, run):
        run['state']['paused'] = True
        return {'state': run['state'], 'status': 'paused', 'event_kind': 'test_paused'}
    runner.repository.mutate('r', 'pause', current['revision'], 'orchestrator', pause, request={'paused': True})
    assert reply(runner, review)['status'] == 'paused'
    assert runner.next('r', 'orchestrator', key='while-paused')['status'] == 'paused'
    assert not runner.get('r')['state']['phases']['plan']['ready']
    assert DecisionRepository(runner.repository).list('r')[0]['decision'] == 'approve'


def test_atomic_response_failure_leaves_no_decision_artifact_journal_or_transition(store, monkeypatch):
    import spoq_server.v1.workflows.checkpoints as module
    runner, review = waiting(store)
    before = runner.get('r')
    with transaction(store.path) as db:
        journal_count = db.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0]
    def fail(*args, **kwargs):
        raise ValueError('injected publication failure')
    monkeypatch.setattr(module, 'index_document', fail)
    with pytest.raises(ValueError, match='injected'):
        reply(runner, review)
    assert runner.get('r') == before
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM workflow_artifacts WHERE kind='decision'").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0] == journal_count


def test_concurrent_user_responses_only_one_revision_wins(store):
    runner, review = waiting(store)
    revision = runner.get('r')['revision']
    def act(n):
        try:
            return reply(runner, review, key='concurrent-' + str(n), expected_revision=revision)
        except ValueError as exc:
            assert 'revision conflict' in str(exc)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(act, [1, 2]))
    assert sum(result is not None for result in results) == 1
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 1


def test_successor_proposal_preserves_history_and_never_reuses_approvals_automatically(store):
    runner, review = waiting(store)
    reply(runner, review)
    original = copy.deepcopy(runner.get('r'))
    proposal = propose_route(runner, 'r', {'impact': 'critical'}, key='successor-proposal', actor='orchestrator',
                             reason='New high impact assumptions require reviewed successor planning.')
    assert proposal['requires_explicit_adoption']
    assert proposal['predecessor_run_id'] == 'r' and proposal['reusable_artifacts']
    assert all(row['output'] not in {'decision', 'plan_gate'} for row in proposal['reusable_artifacts'])
    assert runner.get('r')['routing'] == original['routing']
    assert runner.get('r')['state']['outputs'] == original['state']['outputs']
    assert propose_route(runner, 'r', {'impact': 'critical'}, key='successor-proposal', actor='orchestrator',
                         reason='New high impact assumptions require reviewed successor planning.') == proposal
    # Explicit adoption starts a separate run; content references are candidates,
    # not grants of approval or inherited passing gates.
    successor = runner.start('successor', 'feature', proposal['proposed_route']['inputs'],
                             strategy=proposal['proposed_route']['strategy'], key='adopt-successor')
    assert successor['state']['outputs'] == {}
    assert all(value['status'] == 'queued' for value in successor['state']['phases'].values())
    assert DecisionRepository(runner.repository).list('successor') == []
    assert DecisionRepository(runner.repository).list('r')


def test_successor_proposal_rejects_mid_worker_execution_and_unregistered_author(store):
    runner = PhaseRunner(store)
    runner.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    runner.next('r', 'orchestrator', key='working')
    with pytest.raises(ValueError, match='safe phase boundary'):
        propose_route(runner, 'r', {'uncertainty': 'high'}, key='mid-work', actor='orchestrator', reason='Escalate')
    with pytest.raises(ValueError, match='Register'):
        propose_route(runner, 'r', {'uncertainty': 'high'}, key='unknown', actor='unknown', reason='Escalate')


def test_no_remaining_transition_captures_user_action_but_cannot_grant_success(store):
    definition = get_strategy('piqard').to_dict()
    definition['max_transitions'] = 8
    definition['phases'].append({'id': 'side', 'kind': 'skill', 'skill': 'spoq-discover',
                                 'inputs': ['narrative_plan'], 'outputs': ['side_note'], 'max_attempts': 1})
    definition['edges'].append({'source': 'narrative', 'target': 'side'})
    runner, review = waiting(store, definition=definition)
    side = runner.next('r', 'orchestrator', key='side', phase_id='side')
    complete_phase(runner, 'r', side['attempt_id'], side['token'], 'orchestrator', key='side-done',
                   evidence=evidence_for(side), outputs={'side_note': {'content': 'Independent committed result'}})
    assert runner.get('r')['state']['transitions'] == 8
    result = reply(runner, review)
    assert result['outcome'] == 'blocked' and result['status'] == 'blocked'
    assert 'decision' not in runner.get('r')['state']['outputs']
    assert not runner.get('r')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 1
        assert db.execute('SELECT status FROM workflow_attempts WHERE id=?', (review['attempt_id'],)).fetchone()[0] == 'blocked'
        report = json.loads(db.execute('SELECT body FROM journal_entries WHERE id=?', (result['validation_journal_id'],)).fetchone()[0])
        assert report['decision'] == 'approve' and report['verdict'] == 'BLOCKED'


def test_nonhuman_attempt_cannot_be_completed_through_user_checkpoint_api(store):
    runner, review = waiting(store)
    artifact = review['inputs']['narrative_plan']
    with pytest.raises(ValueError, match='not a human checkpoint'):
        respond(runner, 'r', artifact['attempt_id'], artifact['id'], artifact['sha256'], 'approve', 'User',
                key='wrong-attempt-kind', source='user', user_confirmed=True)


def test_rejection_without_feedback_records_absence_instead_of_invented_changes(store):
    runner, review = waiting(store)
    result = reply(runner, review, 'reject')
    with transaction(store.path) as db:
        row = db.execute('SELECT reason FROM workflow_decisions').fetchone()
        report = json.loads(db.execute('SELECT body FROM journal_entries WHERE id=?', (result['validation_journal_id'],)).fetchone()[0])
        assert row['reason'] == ''
        assert report['findings'] == 'User requested revision without additional notes.'
