"""Pure structured-control reducer. It invokes no skills and performs no I/O.

The repository commits the returned state together with attempts and events.
Joins and unselected branches are control transitions, not model invocations.
"""
from __future__ import annotations

from copy import deepcopy

from .compiler import CompiledStrategy, compile_definition
from .types import identifier, PhaseStatus

TERMINAL = frozenset({'passed', 'failed', 'skipped'})


def initial_state(compiled: CompiledStrategy) -> dict:
    return {'phases': {p: {'status': 'queued', 'ready': p == compiled.definition.entry,
                          'attempt_id': None, 'reason': ''} for p in compiled.forward_order},
            'outputs': {}, 'transitions': 0, 'blockers': [], 'epoch': 0}


def _check(compiled, state):
    if (not isinstance(state, dict) or not isinstance(state.get('phases'), dict)
            or set(state['phases']) != set(compiled.phases)):
        raise ValueError('Workflow phase state does not match its pinned definition')
    if type(state.get('transitions')) is not int or not 0 <= state['transitions'] <= compiled.definition.max_transitions:
        raise ValueError('Invalid persisted transition budget')
    if (not isinstance(state.get('outputs'), dict) or not isinstance(state.get('blockers'), list)
            or type(state.get('epoch')) is not int or not 0 <= state['epoch'] <= compiled.definition.max_transitions
            or 'paused' in state and type(state['paused']) is not bool):
        raise ValueError('Invalid persisted workflow state')
    for value in state['phases'].values():
        if (not isinstance(value, dict) or not isinstance(value.get('status'), str)
                or value['status'] not in PhaseStatus or type(value.get('ready')) is not bool
                or value.get('attempt_id') is not None and not isinstance(value['attempt_id'], str)):
            raise ValueError('Invalid persisted phase state')


def run_status(state: dict) -> str:
    if state.get('paused'):
        return 'paused'
    values = [p['status'] for p in state['phases'].values()]
    if state.get('blockers') or 'blocked' in values:
        return 'blocked'
    if 'failed' in values and not any(p['status'] in {'running', 'waiting_human'}
                                      or p['status'] == 'queued' and p.get('ready')
                                      for p in state['phases'].values()):
        return 'failed'
    if all(s in {'passed', 'skipped'} for s in values):
        return 'passed'
    if 'waiting_human' in values:
        return 'waiting_human'
    return 'running' if any(s != 'queued' for s in values) else 'queued'


def _spend(compiled, state):
    if state['transitions'] >= compiled.definition.max_transitions:
        state['blockers'] = ['Transition budget exhausted; history is retained.']
        return False
    state['transitions'] += 1
    return True


def settle(compiled: CompiledStrategy, state: dict, inputs: dict) -> dict:
    """Resolve forward branches/joins to a fixed point with no repeated spending.

    A numerical event gap is unrelated to this control reducer. Only actual
    committed phase outcomes, not notifications, resolve a predecessor.
    """
    _check(compiled, state)
    if not isinstance(inputs, dict):
        raise ValueError('Pinned routing inputs must be an object')
    state = deepcopy(state)
    if state.get('paused') or state['blockers']:
        return state
    for phase_id in compiled.forward_order:
        value = state['phases'][phase_id]
        if value['status'] != 'queued':
            continue
        if phase_id == compiled.definition.entry:
            value['ready'] = True
            continue
        incoming = compiled.forward_incoming[phase_id]
        if any(state['phases'][e.source]['status'] not in TERMINAL for e in incoming):
            value['ready'] = False
            continue
        selected = [e for e in incoming if state['phases'][e.source]['status'] in {'passed', 'failed'}
                    and (e.when is None or e.when.evaluate(inputs))]
        if not selected:
            if not _spend(compiled, state):
                break
            value.update(status='skipped', ready=False, reason='No selected incoming transition')
        elif any(state['phases'][e.source]['status'] == 'failed'
                 and (compiled.phases[phase_id].kind == 'join' or e.on != 'always') for e in selected):
            value.update(status='blocked', ready=False, reason='A selected predecessor failed')
            state['blockers'].append(phase_id + ': a selected predecessor failed')
        elif compiled.phases[phase_id].kind == 'join':
            if not _spend(compiled, state):
                break
            value.update(status='passed', ready=False, reason='All selected predecessors passed')
        else:
            value['ready'] = True
    if state['transitions'] >= compiled.definition.max_transitions and run_status(state) not in {'passed', 'failed'}:
        state['blockers'] = ['Transition budget exhausted; history is retained.']
    return state


def begin(compiled: CompiledStrategy, state: dict, phase_id: str, attempt_id: str) -> dict:
    _check(compiled, state)
    identifier(phase_id, 'phase ID')
    identifier(attempt_id, 'attempt ID')
    if phase_id not in compiled.phases:
        raise ValueError('Unknown phase')
    value = state['phases'][phase_id]
    if state.get('paused') or state['blockers'] or not value.get('ready') or value['status'] != 'queued':
        raise ValueError('Phase is not ready')
    if compiled.phases[phase_id].kind == 'join':
        raise ValueError('Joins are resolved by the control reducer')
    result = deepcopy(state)
    result['phases'][phase_id].update(
        status='waiting_human' if compiled.phases[phase_id].kind == 'human' else 'running',
        attempt_id=attempt_id, ready=False, reason='')
    return result


def transition(compiled: CompiledStrategy, state: dict, phase_id: str, attempt_id: str,
               outcome: str, inputs: dict, outputs: dict | None = None) -> dict:
    """Apply a fenced result after the caller validates its lease and evidence."""
    _check(compiled, state)
    identifier(phase_id, 'phase ID')
    identifier(attempt_id, 'attempt ID')
    if phase_id not in compiled.phases or not isinstance(outcome, str) or outcome not in {'pass', 'fail'}:
        raise ValueError('Unknown phase or outcome')
    if outputs is not None and not isinstance(outputs, dict):
        raise ValueError('Phase outputs must be an object')
    phase_state = state['phases'][phase_id]
    if phase_state['status'] not in {'running', 'waiting_human'} or phase_state['attempt_id'] != attempt_id:
        raise ValueError('Unknown or stale phase result')
    result = deepcopy(state)
    if not _spend(compiled, result):
        result['phases'][phase_id].update(status='blocked', ready=False, reason='Transition budget exhausted')
        return result
    result['phases'][phase_id].update(status='passed' if outcome == 'pass' else 'failed', ready=False)
    if outcome == 'pass':
        if set(outputs or {}) != set(compiled.phases[phase_id].outputs):
            raise ValueError('A selected phase requires every declared output')
        result['outputs'].update(outputs or {})
    else:
        loops = [e for e in compiled.loop_edges if e.source == phase_id
                 and (e.when is None or e.when.evaluate(inputs))]
        if len(loops) > 1:
            result['blockers'] = ['Multiple revision targets selected; choose an unambiguous definition.']
        elif loops:
            affected = {loops[0].target, *compiled.descendants(loops[0].target)}
            for p in affected:
                # Attempt rows are immutable history; only the current projection resets.
                result['phases'][p] = {'status': 'queued', 'ready': False, 'attempt_id': None,
                                       'reason': 'Invalidated by revision of ' + loops[0].target}
                for name in compiled.phases[p].outputs:
                    result['outputs'].pop(name, None)
            result['epoch'] += 1
    return settle(compiled, result, inputs)


def input_names(phase) -> tuple[str, ...]:
    optional = phase.config.get('optional_inputs', ())
    if not isinstance(optional, (tuple, list)):
        raise ValueError('Optional phase inputs must be an array of identifiers')
    for name in optional:
        identifier(name, 'optional input')
    return tuple(dict.fromkeys((*phase.inputs, *optional)))


def invocation(current: dict, phase_id: str, attempt: dict, artifacts: dict) -> dict:
    """Build a client envelope without implying the engine executed its skill."""
    compiled = compile_definition(current['definition'])
    phase = compiled.phases[phase_id]
    inputs = {name: artifacts[name] for name in input_names(phase) if name in artifacts}
    external = current['routing'].get('inputs', {})
    for name in phase.inputs:
        if name in {'goal', 'context', 'routing', 'scope'}:
            inputs[name] = {'scope': current['scope_id'], 'routing': current['routing']}.get(name, external.get(name))
        elif name not in inputs:
            raise ValueError('Missing required phase input: ' + name)
    return {'run_id': current['run_id'], 'scope_id': current['scope_id'],
            'phase_id': phase_id, 'attempt_id': attempt['id'], 'kind': phase.kind,
            'skill': phase.skill, 'definition_hash': current['definition_hash'],
            'specification_hash': current['specification_hash'], 'inputs': inputs,
            'expected_outputs': list(phase.outputs), 'config': phase.to_dict()['config'],
            'artifact_hashes': {name: value['sha256'] for name, value in artifacts.items()
                                if name in input_names(phase)},
            'status': attempt['status'], 'revision': current['revision']}
