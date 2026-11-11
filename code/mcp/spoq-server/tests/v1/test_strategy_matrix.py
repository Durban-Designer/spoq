"""Cross-strategy invariants; all simulated reviews are explicitly test adapters."""
from copy import deepcopy
from itertools import permutations, product
import json
from pathlib import Path

import pytest

from spoq_server.v1.db import transaction
from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.engine import begin, initial_state, run_status, settle, transition
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.routing import route
from workflow_support import evidence_for, outputs_for

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/spoq-1.1-routing-cases.json'
CASES = json.loads(FIXTURE.read_text())
ADDONS = tuple(CASES['addons'])


def test_repository_review_fixture_matches_the_self_contained_sdist_cases():
    parents = Path(__file__).resolve().parents
    review = parents[5] / 'tests/fixtures/spoq-1.1/routing-cases.json' if len(parents) > 5 else None
    if review is not None and review.is_file():
        assert review.read_bytes() == FIXTURE.read_bytes(), 'Regenerate the review snapshot with the packaged cases'
    assert CASES['expected_generated_cases'] == 5120


@pytest.mark.parametrize('case', CASES['cases'], ids=lambda row: row['name'])
def test_observed_signal_contract_cases(case):
    result = route(case['inputs'], case.get('preference'))
    assert (result['strategy'], result['profile']) == (case['strategy'], case['profile']), case
    assert result['reasons'] and result['input_evidence'] == case['inputs'].get('evidence', [])


def test_every_declared_signal_addon_combination_preserves_gates_inputs_and_determinism():
    axes = CASES['generated_axes']
    expected_hashes = {(name, profile): get_strategy(name, profile).content_hash
                       for name, profile in [('classic', 'compact'), ('classic', 'standard'), ('piqard', 'standard')]}
    count = 0
    for signals in product(*(axes[name] for name in axes)):
        for choices in product((False, True), repeat=4):
            inputs = {**dict(zip(axes, signals)), 'addons': dict(zip(ADDONS, choices))}
            original = deepcopy(inputs)
            result = route(inputs)
            diagnostic = json.dumps(inputs, sort_keys=True)
            assert result['definition_hash'] == expected_hashes[result['strategy'], result['profile']], diagnostic
            assert result['mandatory_gates'] == {
                'plan': {'average': 95, 'floor': 90},
                'implementation': {'average': 95, 'floor': 80}, 'required_checks': True}, diagnostic
            assert result['inputs']['addons'] == original['addons'] and inputs == original, diagnostic
            if any(choices):
                assert result['strategy'] == 'piqard', diagnostic
            assert route(inputs) == result, diagnostic
            count += 1
    assert count == CASES['expected_generated_cases']


def finish(compiled, state, phase, inputs, outcome='pass'):
    attempt = f'fixture-{phase}-{state["transitions"]}'
    running = begin(compiled, state, phase, attempt)
    before = deepcopy(running)
    result = transition(compiled, running, phase, attempt, outcome, inputs,
                        {name: 'artifact-' + name for name in compiled.phases[phase].outputs}
                        if outcome == 'pass' else {})
    assert running == before, 'The reducer must not mutate caller snapshots'
    assert settle(compiled, result, inputs) == result, 'Replaying settlement must not spend transitions'
    return result


@pytest.mark.parametrize('choices', list(product((False, True), repeat=4)))
def test_all_branch_selections_and_completion_orders_join_without_phantom_outputs(choices):
    compiled = compile_definition(get_strategy('piqard'))
    inputs = {'addons': dict(zip(ADDONS, choices))}
    selected = [name for name, chosen in zip(ADDONS, choices) if chosen]
    for order in permutations(selected):
        state = finish(compiled, initial_state(compiled), 'discover', inputs)
        for name in set(ADDONS) - set(selected):
            assert state['phases'][name]['status'] == 'skipped'
            assert name not in state['outputs']
        for index, name in enumerate(order):
            assert not state['phases']['narrative']['ready']
            state = finish(compiled, state, name, inputs)
            assert state['phases']['narrative']['ready'] is (index == len(order) - 1)
        assert state['phases']['design-join']['status'] == 'passed'
        for name in ('narrative', 'review', 'plan', 'plan-validation', 'execute', 'implementation-validation'):
            assert state['phases'][name]['ready'], (choices, order, name)
            state = finish(compiled, state, name, inputs)
        assert run_status(state) == 'passed'
        assert state['epoch'] == 0
        assert state['transitions'] == len(compiled.phases)


@pytest.mark.parametrize('failed', ADDONS)
def test_a_failed_selected_branch_cannot_be_reclassified_as_an_unselected_input(failed):
    c = compile_definition(get_strategy('piqard'))
    inputs = {'addons': dict.fromkeys(ADDONS, True)}
    state = finish(c, initial_state(c), 'discover', inputs)
    for name in ADDONS:
        state = finish(c, state, name, inputs, outcome='fail' if name == failed else 'pass')
    assert run_status(state) == 'blocked'
    assert state['phases']['design-join']['status'] == 'blocked'
    assert not state['phases']['narrative']['ready']
    assert failed not in state['outputs']


def complete(engine, invocation, key, *, stage=None, passed=True, outputs=None):
    return engine.complete('matrix', invocation['attempt_id'], invocation['token'], 'orchestrator', key=key,
                           evidence=evidence_for(invocation, stage=stage, passed=passed), outputs=outputs)


def test_three_failed_required_planning_checks_exhaust_attempts_and_never_grant_success(store):
    engine = WorkflowEngine(store)
    engine.start('matrix', 'feature', {'uncertainty': 'low'}, strategy='classic')
    ids = []
    for number in range(3):
        plan = engine.next('matrix', 'orchestrator', key=f'plan-{number}')
        ids.append(plan['attempt_id'])
        complete(engine, plan, f'planned-{number}', outputs=outputs_for(plan))
        gate = engine.next('matrix', 'orchestrator', key=f'gate-{number}')
        assert complete(engine, gate, f'failed-{number}', stage='plan', passed=False)['outcome'] == 'fail'
    exhausted = engine.next('matrix', 'orchestrator', key='cannot-get-a-fourth-attempt')
    assert exhausted['status'] == 'blocked' and len(set(ids)) == 3
    for number in range(5):
        assert engine.next('matrix', 'orchestrator', key=f'replay-block-{number}')['status'] == 'blocked'
    with transaction(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM workflow_attempts').fetchone()[0] == 6
        assert db.execute('SELECT MAX(number) FROM workflow_attempts').fetchone()[0] == 3


def test_missing_selected_outputs_and_stale_gate_inputs_are_atomic_failures(store):
    engine = WorkflowEngine(store)
    engine.start('matrix', 'feature', {'uncertainty': 'low'}, strategy='classic')
    plan = engine.next('matrix', 'orchestrator', key='plan')
    revision = engine.get('matrix')['revision']
    with pytest.raises(ValueError, match='declared outputs'):
        complete(engine, plan, 'missing-outputs', outputs={})
    assert engine.get('matrix')['revision'] == revision
    complete(engine, plan, 'planned', outputs=outputs_for(plan))
    gate = engine.next('matrix', 'orchestrator', key='gate')
    store.edit('feature', {'acceptance_criteria': ['Changed actual work criterion']})
    revision = engine.get('matrix')['revision']
    with pytest.raises(ValueError, match='Specification changed'):
        complete(engine, gate, 'stale-pass', stage='plan')
    assert engine.get('matrix')['revision'] == revision
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_artifacts WHERE kind='plan_gate'").fetchone()[0] == 0


def narrative():
    return {section: 'Scripted fixture ' + section for section in
            ('scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria')}


def waiting(engine):
    discover = engine.next('matrix', 'orchestrator', key='discover')
    complete(engine, discover, 'discovered', outputs=outputs_for(discover))
    draft = engine.next('matrix', 'orchestrator', key='draft')
    complete(engine, draft, 'drafted', outputs={'narrative_plan': {'content': narrative()}})
    return engine.next('matrix', 'orchestrator', key='human')


def test_waiting_and_peer_attestations_never_consume_human_budget_or_authorize_decomposition(store):
    engine = WorkflowEngine(store)
    engine.start('matrix', 'feature', {'uncertainty': 'high'}, strategy='piqard')
    review = waiting(engine)
    baseline = engine.get('matrix')['state']['transitions']
    for number in range(12):
        assert engine.next('matrix', 'orchestrator', key=f'waiting-{number}')['attempt_id'] == review['attempt_id']
    artifact = review['inputs']['narrative_plan']
    revision = engine.get('matrix')['revision']
    for source, confirmed in [('peer', True), ('user', False)]:
        with pytest.raises(ValueError):
            engine.respond('matrix', review['attempt_id'], artifact['id'], artifact['sha256'], 'approve',
                           'Simulated peer', key=f'no-approval-{source}', source=source, user_confirmed=confirmed)
    assert engine.get('matrix')['revision'] == revision
    assert engine.get('matrix')['state']['transitions'] == baseline
    assert not engine.get('matrix')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='review'").fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM workflow_decisions').fetchone()[0] == 0


def test_unavailable_required_formal_proof_blocks_before_a_proof_attempt_is_created(store):
    engine = WorkflowEngine(store)
    engine.start('matrix', 'feature', {'uncertainty': 'low', 'formal_proof_required': True,
                                     'capabilities': {}}, strategy='piqard')
    discover = engine.next('matrix', 'orchestrator', key='discover')
    complete(engine, discover, 'discovered', outputs=outputs_for(discover))
    assert engine.next('matrix', 'orchestrator', key='proof')['status'] == 'blocked'
    assert 'Required capability unavailable' in engine.get('matrix')['state']['blockers'][0]
    assert not engine.get('matrix')['state']['phases']['plan']['ready']
    with transaction(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM workflow_attempts WHERE phase_id='formal'").fetchone()[0] == 0
