"""Client-driven workflow facade, interruption inspection and explicit resumption."""
from __future__ import annotations

import time
from copy import deepcopy

from ..db import transaction
from .checkpoints import respond, propose_route
from .compiler import compile_definition
from .engine import initial_state, settle, run_status
from .evidence import complete_phase
from .leases import PhaseRunner, scope_input_hash, synchronize_attempts
from .types import content_hash


class WorkflowEngine(PhaseRunner):
    """Persist next actions; a coding client performs their actual software work."""

    def complete(self, *args, **kwargs):
        return complete_phase(self, *args, **kwargs)

    def respond(self, *args, **kwargs):
        return respond(self, *args, **kwargs)

    def propose_route(self, *args, **kwargs):
        return propose_route(self, *args, **kwargs)

    def inspect(self, run_id):
        with transaction(self.path) as db:
            current = self.repository._get(db, run_id)
            if current['status'] == 'legacy_unclassified':
                return {**current, 'client_mode': 'legacy_unclassified', 'next_action': 'Start a strategy run; no past phases are inferred.'}
            current['current_specification_hash'] = self.repository.specification_hash(db, current['scope_id'])
            active = [dict(row) for row in db.execute('''SELECT id,phase_id,status,owner,lease_until
                FROM workflow_attempts WHERE run_id=? AND status IN ('running','waiting_human') ORDER BY rowid LIMIT 256''', (run_id,))]
        for row in active:
            row['recoverable'] = row['status'] == 'running' and row['lease_until'] <= time.time()
        return {**current, 'active_attempts': active, 'client_mode': 'client_driven',
                'engine_launches_models': False,
                'next_action': ('A user must respond to the exact reviewed revision.' if current['status'] == 'waiting_human'
                                else 'Use a connected coding client to inspect and execute returned skill envelopes; registration alone does not establish model availability.')}

    def pause(self, run_id, actor='orchestrator', *, key, expected_revision=None, reason=''):
        if not isinstance(reason, str) or len(reason) > 100_000:
            raise ValueError('Pause reason must be bounded text')
        current = self.get(run_id)
        def operation(db, current):
            self._participant(db, run_id, actor)
            state = deepcopy(current['state'])
            if current['status'] != 'passed':
                state.update(paused=True, pause_reason=reason)
            return {'state': state, 'status': run_status(state), 'event_kind': 'paused',
                    'payload': {'reason': reason}, 'result': {'status': run_status(state)}}
        return self.repository.mutate(run_id, key, self._revision(current, expected_revision), actor, operation,
                                      request={'operation': 'pause', 'reason': reason})

    @staticmethod
    def _participant(db, run_id, actor):
        if not db.execute('SELECT 1 FROM agents WHERE run_id=? AND id=?', (run_id, actor)).fetchone():
            raise ValueError('Register this participant before changing workflow control')

    def resume(self, run_id, actor='orchestrator', *, key, expected_revision=None,
               refresh_spec=False, retry_phase=None):
        if type(refresh_spec) is not bool or retry_phase is not None and not isinstance(retry_phase, str):
            raise ValueError('Refresh must be boolean and retry phase must be text')
        current = self.get(run_id)
        def operation(db, current):
            self._participant(db, run_id, actor)
            compiled = compile_definition(current['definition'])
            state = deepcopy(current['state'])
            actual = self.repository.specification_hash(db, current['scope_id'])
            changed = actual != current['specification_hash']
            node = self.store._get(db, current['scope_id'])
            if (changed and refresh_spec and state.get('node_goal_hash')
                    != content_hash(node['data'].get('goal') or node['title'])):
                raise ValueError('Goal changed: pause this run and start an explicit successor with fresh routing; the original routing inputs stay pinned')
            root_unchanged = state.get('scope_input_hash') == scope_input_hash(db, current['scope_id'])
            if changed and refresh_spec and not root_unchanged:
                raise ValueError('User inputs changed: pause this run and start an explicit successor with fresh routing')
            active_planner = any(p.skill == 'spoq-plan' and state['phases'][p.id]['status'] == 'running'
                                 for p in compiled.phases.values())
            target = retry_phase
            if target is None and not active_planner:
                target = next((p for p in compiled.forward_order if state['phases'][p]['status'] == 'failed'), None)
            if target is not None:
                if target not in compiled.phases or compiled.phases[target].kind == 'join' or state['phases'][target]['status'] not in {'failed', 'blocked'}:
                    raise ValueError('Retry must identify a failed/blocked executable phase; inspect interrupted attempts instead')
            expected_planning_change = root_unchanged and (active_planner or target is not None and compiled.phases[target].skill == 'spoq-plan')
            if changed and not refresh_spec and not expected_planning_change:
                raise ValueError('Specification changed; explicitly resume with --refresh-spec to invalidate old results')
            reset_all = changed and refresh_spec
            resets = reset_all or target is not None
            new_spec = current['specification_hash']
            invalidated = []
            if resets:
                counts = {r[0]: r[1] for r in db.execute('''SELECT phase_id,MAX(number) FROM workflow_attempts
                    WHERE run_id=? GROUP BY phase_id''', (run_id,))}
                entry = compiled.definition.entry if reset_all else target
                if (state['transitions'] >= compiled.definition.max_transitions
                        or counts.get(entry, 0) >= compiled.phases[entry].max_attempts):
                    state.update(paused=False, blockers=['Attempt or transition budget exhausted; explicit user authorization is required to increase it.'])
                    return {'state': state, 'status': 'blocked', 'event_kind': 'resume_blocked',
                            'result': {'status': 'blocked', 'blockers': state['blockers']}}
                affected = set(compiled.phases) if reset_all else {target, *compiled.descendants(target)}
                invalidated = [r[0] for r in db.execute("SELECT id,phase_id FROM workflow_attempts WHERE run_id=? AND status IN ('running','waiting_human')", (run_id,))
                               if r[1] in affected]
                for p in affected:
                    state['phases'][p] = {'status': 'queued', 'ready': False, 'attempt_id': None,
                                          'reason': 'Invalidated by explicit specification refresh' if reset_all else 'Explicit bounded retry'}
                    for output in compiled.phases[p].outputs:
                        state['outputs'].pop(output, None)
                state['blockers'] = [p + ': ' + value.get('reason', 'Blocked')
                                     for p, value in state['phases'].items() if value['status'] == 'blocked']
                state['transitions'] += 1
                state['epoch'] += 1
                if changed:
                    new_spec = actual
                state['scope_input_hash'] = scope_input_hash(db, current['scope_id'])
            state['paused'] = False
            state.pop('pause_reason', None)
            state = settle(compiled, state, current['routing']['inputs'])
            synchronize_attempts(db, current, state)
            return {'state': state, 'status': run_status(state), 'specification_hash': new_spec,
                    'event_kind': 'resumed',
                    'payload': {'refresh_spec': reset_all, 'retry_phase': target,
                                'old_specification_hash': current['specification_hash'], 'specification_hash': new_spec,
                                'invalidated_attempts': invalidated},
                    'result': {'status': run_status(state), 'specification_hash': new_spec,
                               'requires_specification_refresh': changed and new_spec != actual,
                               'inspection_required': invalidated, 'blockers': state['blockers']}}
        return self.repository.mutate(run_id, key, self._revision(current, expected_revision), actor, operation,
            request={'operation': 'resume', 'refresh_spec': refresh_spec, 'retry_phase': retry_phase})

    def recover(self, run_id, actor='orchestrator', *, key, **kwargs):
        return self.next(run_id, actor, key=key, recover=True, **kwargs)
