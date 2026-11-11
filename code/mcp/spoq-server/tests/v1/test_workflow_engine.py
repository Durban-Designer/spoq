import copy

import pytest

from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.engine import initial_state, settle, begin, transition, run_status, invocation


def finish(compiled, state, phase, inputs=None, outcome='pass'):
    state = begin(compiled, state, phase, 'attempt-' + phase)
    return transition(compiled, state, phase, 'attempt-' + phase, outcome, inputs or {},
                      {o: 'artifact-' + o for o in compiled.phases[phase].outputs} if outcome == 'pass' else {})


def test_classic_sequences_gates_and_requires_all_outputs():
    c = compile_definition(get_strategy())
    state = initial_state(c)
    for phase in c.forward_order:
        assert state['phases'][phase]['ready']
        state = finish(c, state, phase)
    assert run_status(state) == 'passed'
    assert state['transitions'] == 4
    assert settle(c, state, {}) == state


@pytest.mark.parametrize('addons', [{}, {'erd': True}, {'diagram': True, 'algorithm': True, 'formal': True}])
def test_selected_parallel_branches_join_only_after_selected_work(addons):
    c = compile_definition(get_strategy('piqard'))
    inputs = {'addons': addons}
    state = finish(c, initial_state(c), 'discover', inputs)
    selected = [p for p in ('diagram', 'erd', 'algorithm', 'formal') if addons.get(p)]
    for p in ('diagram', 'erd', 'algorithm', 'formal'):
        assert state['phases'][p]['status'] == ('queued' if p in selected else 'skipped')
    if selected:
        assert not state['phases']['narrative']['ready']
        for i, p in enumerate(selected):
            state = finish(c, state, p, inputs)
            assert state['phases']['narrative']['ready'] is (i == len(selected) - 1)
    else:
        assert state['phases']['narrative']['ready']
    assert state['phases']['design-join']['status'] == 'passed'
    assert settle(c, state, inputs) == state


def test_human_rejection_invalidates_descendants_but_keeps_upstream_outputs():
    c = compile_definition(get_strategy('piqard'))
    inputs = {'addons': {}}
    state = finish(c, initial_state(c), 'discover', inputs)
    state = finish(c, state, 'narrative', inputs)
    state = begin(c, state, 'review', 'review-first')
    assert run_status(state) == 'waiting_human'
    state = transition(c, state, 'review', 'review-first', 'fail', inputs)
    assert state['epoch'] == 1 and state['phases']['narrative']['ready']
    assert 'narrative_plan' not in state['outputs'] and 'discovery' in state['outputs']
    assert not state['phases']['plan']['ready']


def test_stale_unknown_and_incomplete_results_do_not_advance():
    c = compile_definition(get_strategy())
    original = initial_state(c)
    state = begin(c, original, 'plan', 'first')
    for phase, attempt in [('unknown', 'first'), ('plan', 'other')]:
        with pytest.raises(ValueError):
            transition(c, state, phase, attempt, 'pass', {}, {'project_plan': 'x'})
    with pytest.raises(ValueError, match='every declared'):
        transition(c, state, 'plan', 'first', 'pass', {})
    assert original == initial_state(c)
    assert state['phases']['plan']['status'] == 'running'


def test_pause_and_transition_exhaustion_do_not_grant_pass():
    source = get_strategy().to_dict()
    source['max_transitions'] = 1
    c = compile_definition(source)
    state = finish(c, initial_state(c), 'plan')
    assert run_status(state) == 'blocked'
    with pytest.raises(ValueError):
        begin(c, state, 'plan-validation', 'two')
    paused = initial_state(c)
    paused['paused'] = True
    assert run_status(paused) == 'paused'
    with pytest.raises(ValueError):
        begin(c, paused, 'plan', 'one')


def test_always_transition_can_run_cleanup_but_never_erase_failed_work():
    source = get_strategy().to_dict()
    source['phases'] = [source['phases'][0], {**source['phases'][0], 'id': 'cleanup',
                                            'inputs': [], 'outputs': ['receipt']}]
    source['edges'] = [{'source': 'plan', 'target': 'cleanup', 'on': 'always'}]
    c = compile_definition(source)
    state = finish(c, initial_state(c), 'plan', outcome='fail')
    assert state['phases']['cleanup']['ready']
    assert run_status(state) == 'running'
    state = finish(c, state, 'cleanup')
    assert run_status(state) == 'failed'


def test_always_join_cannot_treat_failed_selected_input_as_a_pass():
    source = get_strategy().to_dict()
    source['phases'] = [source['phases'][0], {'id': 'join', 'kind': 'join', 'skill': None,
                                           'inputs': [], 'outputs': [], 'config': {'join': 'selected'}}]
    source['edges'] = [{'source': 'plan', 'target': 'join', 'on': 'always'}]
    c = compile_definition(source)
    state = finish(c, initial_state(c), 'plan', outcome='fail')
    assert run_status(state) == 'blocked'
    assert state['phases']['join']['status'] == 'blocked'


def test_failed_selected_design_cannot_disappear_from_join_requirements():
    c = compile_definition(get_strategy('piqard'))
    inputs = {'addons': {'erd': True}}
    state = finish(c, initial_state(c), 'discover', inputs)
    state = finish(c, state, 'erd', inputs, outcome='fail')
    assert state['phases']['design-join']['status'] == 'blocked'
    assert not state['phases']['narrative']['ready']
    assert run_status(state) == 'blocked'


def test_failing_gate_resets_work_and_gate_outputs_without_resetting_global_budget():
    c = compile_definition(get_strategy())
    state = finish(c, initial_state(c), 'plan')
    state = finish(c, state, 'plan-validation', outcome='fail')
    assert state['phases']['plan']['ready'] and state['outputs'] == {}
    assert state['transitions'] == 2 and state['epoch'] == 1


def test_invocation_carries_pinned_context_and_only_actual_input_artifact_hashes():
    definition = get_strategy()
    current = {'run_id': 'r', 'scope_id': 'p', 'definition': definition.to_dict(),
               'definition_hash': definition.content_hash, 'specification_hash': 'a' * 64,
               'routing': {'inputs': {'goal': 'Build'}}, 'revision': 2}
    envelope = invocation(current, 'plan-validation', {'id': 'a', 'status': 'running'},
                          {'project_plan': {'id': 'p', 'sha256': 'b' * 64},
                           'implementation': {'id': 'i', 'sha256': 'c' * 64}})
    assert envelope['skill'] == 'spoq-plan-validation'
    assert envelope['artifact_hashes'] == {'project_plan': 'b' * 64}
    assert envelope['expected_outputs'] == ['plan_gate']
    with pytest.raises(ValueError, match='Missing required'):
        invocation(current, 'execute', {'id': 'a', 'status': 'running'}, {})


@pytest.mark.parametrize('optional', [None, 1, True, 'discovery', {'input': 'discovery'}, [[]], [{}], [None]])
def test_optional_input_config_cannot_crash_or_silently_turn_into_characters(optional):
    from spoq_server.v1.workflows.engine import input_names
    source = get_strategy('piqard').to_dict()
    narrative = next(p for p in source['phases'] if p['id'] == 'narrative')
    narrative['config']['optional_inputs'] = optional
    c = compile_definition(source)
    with pytest.raises(ValueError, match='input'):
        input_names(c.phases['narrative'])


@pytest.mark.parametrize(('field', 'value'), [('phases', [[]]), ('outputs', None), ('blockers', 1),
                                           ('epoch', True), ('paused', 'yes'), ('transitions', True)])
def test_corrupt_runtime_state_has_an_explicit_validation_error(field, value):
    c = compile_definition(get_strategy())
    state = initial_state(c)
    state[field] = value
    with pytest.raises(ValueError):
        settle(c, state, {})
