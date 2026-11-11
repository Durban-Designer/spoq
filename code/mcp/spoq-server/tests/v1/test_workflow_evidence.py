import copy
import json

import pytest

from spoq_server.v1.workflows.leases import PhaseRunner
from spoq_server.v1.workflows.evidence import complete_phase, validate_evidence
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.db import transaction
from workflow_support import evidence_for, outputs_for


def planned(store):
    runner = PhaseRunner(store)
    runner.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    call = runner.next('r', 'orchestrator', key='plan')
    return runner, call


def test_public_completion_rejects_arbitrary_nonempty_evidence_and_keeps_attempt(store):
    runner, call = planned(store)
    with pytest.raises(ValueError):
        complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='bad', evidence={'passed': True}, outputs=outputs_for(call))
    assert runner.get('r')['state']['phases']['plan']['status'] == 'running'


def test_valid_completion_returns_durable_journal_and_retries_without_extra_side_effects(store):
    runner, call = planned(store)
    args = dict(key='done', evidence=evidence_for(call), outputs=outputs_for(call))
    result = complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', **args)
    assert complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', **args) == result
    with transaction(store.path) as db:
        report = json.loads(db.execute('SELECT body FROM journal_entries WHERE id=?', (result['validation_journal_id'],)).fetchone()[0])
        assert report['output_hashes']['project_plan']
        assert db.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0] == 1


@pytest.mark.parametrize('body', [None, [], {'artifact_id': []}, {'content': ''}, {'content': 'wrong scope'}])
def test_passing_output_payload_must_be_reviewable_and_bound_to_real_work(store, body):
    runner, call = planned(store)
    with pytest.raises(ValueError):
        complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='bad',
                       evidence=evidence_for(call), outputs={'project_plan': body})
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_artifacts').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0] == 0


@pytest.mark.parametrize('field', ['run_id', 'scope_id', 'phase_id', 'attempt_id', 'definition_hash', 'specification_hash', 'artifact_hashes'])
def test_identity_or_artifact_revision_change_is_rejected(store, field):
    runner, call = planned(store)
    evidence = evidence_for(call)
    evidence[field] = {'old': 'hash'} if field == 'artifact_hashes' else 'stale'
    with pytest.raises(ValueError, match='revision'):
        complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='bad', evidence=evidence, outputs=outputs_for(call))


def test_gate_computes_metrics_and_a_failed_required_command_cannot_pass(store):
    runner, call = planned(store)
    complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='planned', evidence=evidence_for(call), outputs=outputs_for(call))
    gate = runner.next('r', 'orchestrator', key='gate')
    evidence = evidence_for(gate, stage='plan')
    evidence['observed_checks'] = [{'command': 'pytest actual-required-check', 'exit_code': 1,
                                    'source': 'scripted negative fixture', 'observed': True}]
    result = complete_phase(runner, 'r', gate['attempt_id'], gate['token'], 'orchestrator', key='failed-gate', evidence=evidence)
    assert result['outcome'] == 'fail' and runner.get('r')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        report = json.loads(db.execute('SELECT evidence FROM workflow_attempts WHERE id=?', (gate['attempt_id'],)).fetchone()[0])
        assert report['verdict'] == 'FAIL' and not report['checks_passed']
        assert report['provenance'] == 'caller_supplied_observations_not_reexecuted'


def test_decomposition_refresh_is_explicit_and_retains_input_specification(store):
    runner, call = planned(store)
    store.create('task', 'work', 'Planned work', 'feature')
    fresh = {**call, 'specification_hash': runner.get('r')['current_specification_hash']}
    with pytest.raises(ValueError, match='Specification changed'):
        complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='no-refresh', evidence=evidence_for(fresh), outputs=outputs_for(fresh))
    result = complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='refresh', evidence=evidence_for(fresh), outputs=outputs_for(fresh), refresh_spec=True)
    assert result['outcome'] == 'pass'
    with transaction(store.path) as db:
        report = json.loads(db.execute('SELECT evidence FROM workflow_attempts WHERE id=?', (call['attempt_id'],)).fetchone()[0])
        assert report['input_specification_hash'] == call['specification_hash']
        assert report['specification_hash'] == fresh['specification_hash']


def test_execution_cannot_claim_success_with_pending_scoped_tasks(store):
    runner, call = planned(store)
    store.create('task', 'work', 'Not implemented', 'feature')
    call['specification_hash'] = runner.get('r')['current_specification_hash']
    complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='planned', evidence=evidence_for(call), outputs=outputs_for(call), refresh_spec=True)
    gate = runner.next('r', 'orchestrator', key='gate')
    complete_phase(runner, 'r', gate['attempt_id'], gate['token'], 'orchestrator', key='gate-done', evidence=evidence_for(gate, stage='plan'))
    execute = runner.next('r', 'orchestrator', key='execute')
    assert execute['work']['ready_tasks'] == ['work']
    with pytest.raises(ValueError, match='Complete the scoped Tasks'):
        complete_phase(runner, 'r', execute['attempt_id'], execute['token'], 'orchestrator', key='bad', evidence=evidence_for(execute), outputs=outputs_for(execute))


def test_noncommand_observations_are_distinct_and_obvious_self_independence_is_rejected():
    phase = compile_definition(get_strategy()).phases['plan-validation']
    context = dict(run_id='r', attempt_id='a', scope_id='f', definition_hash='d', specification_hash='s', artifact_hashes={})
    envelope = {**context, 'phase_id': phase.id}
    evidence = evidence_for(envelope, stage='plan')
    report = validate_evidence(evidence, phase, **context)
    assert report['verdict'] == 'PASS' and report['reviewer']['review_type'] == 'scripted_adapter'
    evidence['reviewer'] = {'agent': 'worker', 'review_type': 'independent'}
    with pytest.raises(ValueError, match='independent'):
        validate_evidence(evidence, phase, **context, producer_agents={'worker'})


def test_required_formal_proof_cannot_pass_as_an_unverified_specification(store):
    runner = PhaseRunner(store)
    runner.start('r', 'feature', {'formal_proof_required': True, 'capabilities': {'formal_proof': True}})
    discover = runner.next('r', 'orchestrator', key='discover')
    complete_phase(runner, 'r', discover['attempt_id'], discover['token'], 'orchestrator', key='discovered',
                   evidence=evidence_for(discover), outputs=outputs_for(discover))
    formal = runner.next('r', 'orchestrator', key='formal')
    assert formal['phase_id'] == 'formal'
    with pytest.raises(ValueError, match='Required proof'):
        complete_phase(runner, 'r', formal['attempt_id'], formal['token'], 'orchestrator', key='unverified',
                       evidence=evidence_for(formal), outputs={'formal': {'content': {
                           'status': 'unverified', 'specification': 'An invariant', 'reason': 'No proof obtained'}}})


def test_stronger_declared_threshold_is_enforced_by_the_computed_gate():
    source = get_strategy().to_dict()
    source['phases'][1]['config']['minimum_average'] = 99
    phase = compile_definition(source).phases['plan-validation']
    context = dict(run_id='r', attempt_id='a', scope_id='f', definition_hash='d', specification_hash='s', artifact_hashes={})
    report = validate_evidence(evidence_for({**context, 'phase_id': phase.id}, stage='plan'), phase, **context)
    assert report['average'] == 96 and report['verdict'] == 'FAIL'


@pytest.mark.parametrize(('kind', 'stage'), [('skill', 'plan'), ('gate', 'implementation')])
def test_relabeling_a_validation_skill_cannot_bypass_its_gate(store, kind, stage):
    source = get_strategy().to_dict()
    source['phases'][1]['kind'] = kind
    source['phases'][1]['config']['stage'] = stage
    with pytest.raises(ValueError, match='matching gate'):
        PhaseRunner(store).start('r', 'feature', {'uncertainty': 'low'}, strategy='classic', definition=source)
    phase = compile_definition(source).phases['plan-validation']
    with pytest.raises(ValueError, match='matching gate'):
        validate_evidence({}, phase, run_id='r', attempt_id='a', scope_id='f',
                          definition_hash='d', specification_hash='s', artifact_hashes={})


def test_a_gate_cannot_replace_all_required_observations_with_optional_checks():
    phase = compile_definition(get_strategy()).phases['plan-validation']
    context = dict(run_id='r', attempt_id='a', scope_id='f', definition_hash='d', specification_hash='s', artifact_hashes={})
    evidence = evidence_for({**context, 'phase_id': phase.id}, stage='plan')
    evidence['observed_checks'][0].update(required=False, passed=False)
    with pytest.raises(ValueError, match='required observed'):
        validate_evidence(evidence, phase, **context)
    evidence['observed_checks'].append({'check_type': 'tool', 'name': 'Actual DAG check', 'passed': True,
                                       'source': 'scripted fixture', 'observed': True, 'required': True})
    assert validate_evidence(evidence, phase, **context)['verdict'] == 'PASS'


def test_non_gate_cannot_mislabel_its_own_producer_as_independent(store):
    runner, call = planned(store)
    evidence = evidence_for(call)
    evidence['reviewer'] = {'agent': 'orchestrator', 'review_type': 'independent'}
    with pytest.raises(ValueError, match='independent'):
        complete_phase(runner, 'r', call['attempt_id'], call['token'], 'orchestrator', key='bad',
                       evidence=evidence, outputs=outputs_for(call))


@pytest.mark.parametrize('mutation', ['unobserved', 'bool_exit', 'no_acceptance', 'nan', 'bad_scores', 'malformed_check'])
def test_malformed_claims_cannot_be_mistaken_for_checks(mutation):
    phase = compile_definition(get_strategy()).phases['plan-validation']
    context = dict(run_id='r', attempt_id='a', scope_id='f', definition_hash='d', specification_hash='s', artifact_hashes={})
    evidence = evidence_for({**context, 'phase_id': phase.id}, stage='plan')
    if mutation == 'unobserved': evidence['observed_checks'][0]['observed'] = False
    if mutation == 'bool_exit': evidence['observed_checks'] = [{'command': 'x', 'exit_code': True, 'source': 'x', 'observed': True}]
    if mutation == 'no_acceptance': evidence['acceptance_results'] = []
    if mutation == 'nan': evidence['scores'][next(iter(evidence['scores']))] = float('nan')
    if mutation == 'bad_scores': evidence['scores'] = {'one': 100}
    if mutation == 'malformed_check': evidence['observed_checks'] = [[]]
    with pytest.raises(ValueError): validate_evidence(evidence, phase, **context)
