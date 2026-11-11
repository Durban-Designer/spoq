"""Transactional invocation leases; clients execute the returned skill envelopes."""
from __future__ import annotations

import json
import time

from ..db import now, transaction, uid
from ..store import Store
from .artifacts import parse_artifact
from .compiler import compile_definition
from .definitions import get_strategy
from .design import capability_status, SOURCE_CAPABILITIES
from .engine import initial_state, settle, begin, invocation, run_status, input_names, transition
from .repository import WorkflowRepository
from .routing import route
from .types import content_hash, canonical_json


def scope_input_hash(db, scope_id):
    node = Store._get(db, scope_id)
    # Raw user input stays pinned. Assumptions, architecture and decomposed
    # acceptance criteria are planner outputs; the full specification hash still
    # binds them, but adding them must not masquerade as a changed user goal.
    data = node['data']
    goal = data.get('goal') or node['title']
    return content_hash({'goal': goal, 'user_request': data.get('user_request') or goal,
                         'user_inputs': data.get('user_inputs', {}),
                         'user_constraints': data.get('user_constraints', [])})


def synchronize_attempts(db, current, state):
    """Fence attempts invalidated by a revision without deleting their history."""
    for row in db.execute("SELECT id,phase_id FROM workflow_attempts WHERE run_id=? AND status IN ('running','waiting_human')",
                          (current['run_id'],)).fetchall():
        phase = state['phases'][row['phase_id']]
        if phase.get('attempt_id') != row['id'] or phase['status'] not in {'running', 'waiting_human'}:
            db.execute("UPDATE workflow_attempts SET status='blocked',lease_until=0,updated_at=? WHERE id=?", (now(), row['id']))


def current_artifacts(db, current, phase=None):
    names = set(input_names(phase)) if phase is not None else set(current['state']['outputs'])
    result = {}
    for name, ref in current['state']['outputs'].items():
        if name in names:
            row = db.execute('''SELECT id,run_id,attempt_id,scope_id,kind,author,source,sha256,metadata,created_at,
                             length(CAST(content AS BLOB)) AS content_bytes FROM workflow_artifacts WHERE id=? AND run_id=?''',
                             (ref, current['run_id'])).fetchone()
            if row is None:
                raise ValueError('Missing current artifact: ' + name)
            result[name] = parse_artifact(row)
    return result


def fenced_attempt(db, current, attempt_id, token, actor, *, allow_human=False):
    row = db.execute('SELECT * FROM workflow_attempts WHERE id=? AND run_id=?',
                     (attempt_id, current['run_id'])).fetchone()
    if row is None:
        raise ValueError('Unknown attempt')
    row = dict(row)
    phase = current['state']['phases'].get(row['phase_id'], {})
    expected = 'waiting_human' if allow_human else 'running'
    if (phase.get('attempt_id') != attempt_id or phase.get('status') != expected
            or row['status'] != expected or row['token'] != token or row['owner'] != actor
            or row['specification_hash'] != current['specification_hash']
            or (not allow_human and row['lease_until'] <= time.time())):
        raise ValueError('Stale attempt, owner, or lease fence')
    return row


class PhaseRunner:
    def __init__(self, store: Store):
        self.store = store
        self.repository = WorkflowRepository(store)
        self.path = store.path

    def start(self, run_id, scope_id, inputs=None, *, strategy=None, key='start', actor='orchestrator', definition=None):
        if inputs is not None and not isinstance(inputs, dict):
            raise ValueError('Routing inputs must be an object')
        inputs = dict(inputs or {})
        scope = self.store.get(scope_id)
        inputs.setdefault('goal', scope['data'].get('goal') or scope['title'])
        routing = route(inputs, strategy)
        compiled = compile_definition(get_strategy(routing['strategy'], routing['profile']) if definition is None else definition)
        from .evidence import validate_phase_contract
        for phase in compiled.phases.values():
            validate_phase_contract(phase)
            input_names(phase)  # Envelope config is validated before publishing a run.
            for field in ('capability', 'capability_required_input'):
                if field in phase.config and not isinstance(phase.config[field], str):
                    raise ValueError('Phase ' + field + ' must be text')
            if 'capability_required_input' in phase.config and not phase.config.get('capability'):
                raise ValueError('A capability requirement must name its capability')
            if 'provider' in phase.config and (not isinstance(phase.config['provider'], str)
                                             or phase.config['provider'] not in SOURCE_CAPABILITIES):
                raise ValueError('Design provider must be one of the bundled source providers')
            if phase.kind == 'design' and 'provider' not in phase.config and not set(phase.outputs) <= SOURCE_CAPABILITIES:
                raise ValueError('A design phase must name its bundled source provider')
        if definition is not None:
            routing = {**routing, 'strategy': compiled.definition.id,
                       'definition_hash': compiled.definition.content_hash}
        state = initial_state(compiled)
        state['node_goal_hash'] = content_hash(scope['data'].get('goal') or scope['title'])
        state['input_contract_version'] = 'spoq-user-inputs-1'
        with transaction(self.path) as db:
            state['scope_input_hash'] = scope_input_hash(db, scope_id)
        result = self.repository.start(run_id, scope_id, compiled.definition, routing, state, key, actor)
        with transaction(self.path, write=True) as db:
            db.execute('''INSERT OR IGNORE INTO agents(run_id,id,role,runtime,target,heartbeat)
                VALUES(?,?,'orchestrator','manual','',?)''', (run_id, actor, now()))
        return result

    def get(self, run_id):
        return self.repository.get(run_id)

    @staticmethod
    def _revision(current, expected_revision):
        if current['status'] == 'legacy_unclassified':
            raise ValueError('Legacy runs have no strategy; start a new workflow run')
        return current['revision'] if expected_revision is None else expected_revision

    @staticmethod
    def _context(db, current):
        actual = WorkflowRepository.specification_hash(db, current['scope_id'])
        if actual != current['specification_hash']:
            raise ValueError('Specification changed; explicitly resume with refreshed specification before advancing')
        return actual

    def next(self, run_id, actor, *, key, expected_revision=None, phase_id=None, ttl=300, recover=False):
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise ValueError('Phase lease TTL must be 1–3600 seconds')
        if phase_id is not None and not isinstance(phase_id, str):
            raise ValueError('Phase ID must be text')
        if type(recover) is not bool:
            raise ValueError('Recovery must be an explicit boolean')
        current = self.get(run_id)
        revision = self._revision(current, expected_revision)
        def operation(db, current):
            actual_spec = self.repository.specification_hash(db, current['scope_id'])
            stale_planning = actual_spec != current['specification_hash']
            eligible = []
            if stale_planning:
                eligible = [p['id'] for p in current['definition']['phases'] if p['skill'] == 'spoq-plan'
                            and current['state']['phases'][p['id']]['status'] == 'running']
                if (recover is not True or not eligible
                        or current['state'].get('scope_input_hash') != scope_input_hash(db, current['scope_id'])):
                    raise ValueError('Specification changed; explicitly resume with refreshed specification before advancing')
            if not db.execute('SELECT 1 FROM agents WHERE run_id=? AND id=?', (run_id, actor)).fetchone():
                raise ValueError('Register this participant before claiming a phase')
            compiled = compile_definition(current['definition'])
            state = settle(compiled, current['state'], current['routing']['inputs'])
            if current['status'] == 'paused' or state.get('paused'):
                return {'state': state, 'status': 'paused', 'event_kind': 'checkpoint', 'result': {'status': 'paused'}}
            status = run_status(state)
            if status in {'passed', 'failed', 'blocked'}:
                return {'state': state, 'status': status, 'event_kind': 'checkpoint',
                        'result': {'status': status, 'blockers': state['blockers']}}
            candidates = [p for p in compiled.forward_order if state['phases'][p]['status'] in {'running', 'waiting_human'}
                          or state['phases'][p].get('ready')]
            if stale_planning:
                candidates = [p for p in candidates if p in eligible]
            if phase_id is not None:
                if phase_id not in compiled.phases:
                    raise ValueError('Unknown requested phase')
                candidates = [phase_id] if phase_id in candidates else []
            for p in candidates:
                phase = compiled.phases[p]
                value = state['phases'][p]
                attempt = db.execute('SELECT * FROM workflow_attempts WHERE id=?', (value.get('attempt_id'),)).fetchone()
                inspected = stale_planning or recover and attempt is not None
                if attempt is not None:
                    attempt = dict(attempt)
                    if attempt['status'] != value['status']:
                        raise ValueError('Persisted phase and attempt statuses disagree')
                    if phase.kind != 'human' and attempt['lease_until'] <= time.time():
                        if not recover:
                            continue
                        attempt.update(owner=actor, token=uid(), lease_until=time.time() + ttl)
                        db.execute('UPDATE workflow_attempts SET owner=?,token=?,lease_until=?,updated_at=? WHERE id=?',
                                   (actor, attempt['token'], attempt['lease_until'], now(), attempt['id']))
                        inspected = True
                    elif phase.kind != 'human' and attempt['owner'] != actor:
                        continue
                else:
                    if not value.get('ready'):
                        continue
                    required_proof = (phase.config.get('capability_required_input')
                                      and current['routing']['inputs'].get(phase.config['capability_required_input']))
                    if required_proof:
                        capability = capability_status(phase.config['capability'],
                            current['routing']['inputs'].get('capabilities', {}), required=True)
                        if capability['status'] == 'blocked':
                            state['blockers'] = [p + ': ' + capability['reason']]
                            state['phases'][p].update(status='blocked', ready=False, reason=capability['reason'])
                            break
                    count = db.execute('SELECT COALESCE(MAX(number),0) FROM workflow_attempts WHERE run_id=? AND phase_id=?',
                                       (run_id, p)).fetchone()[0]
                    if count >= phase.max_attempts or state['transitions'] >= compiled.definition.max_transitions:
                        state['blockers'] = [p + ': attempt or transition budget exhausted; explicit user authorization is needed to increase it.']
                        state['phases'][p].update(status='blocked', ready=False, reason=state['blockers'][0])
                        break
                    artifacts = current_artifacts(db, {**current, 'state': state}, phase)
                    # Validate required inputs before creating any invocation or consuming an attempt.
                    dummy = {'id': 'pending', 'status': 'running'}
                    invocation(current, p, dummy, artifacts)
                    attempt = {'id': uid(), 'run_id': run_id, 'phase_id': p, 'number': count + 1,
                               'status': 'waiting_human' if phase.kind == 'human' else 'running',
                               'owner': actor, 'token': uid(), 'lease_until': time.time() + ttl,
                               'specification_hash': current['specification_hash'], 'evidence': '{}',
                               'created_at': now(), 'updated_at': now()}
                    db.execute('INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', tuple(attempt.values()))
                    state = begin(compiled, state, p, attempt['id'])
                contextual = {**current, 'state': state}
                envelope = invocation(contextual, p, attempt, current_artifacts(db, contextual, phase))
                envelope['token'] = None if phase.kind == 'human' else attempt['token']
                envelope['lease_until'] = None if phase.kind == 'human' else attempt['lease_until']
                envelope['needs_inspection'] = inspected
                envelope['current_specification_hash'] = actual_spec
                envelope['requires_specification_refresh'] = stale_planning
                envelope['prior_artifacts'] = [dict(r) for r in db.execute(
                    'SELECT id,kind,sha256,source FROM workflow_artifacts WHERE attempt_id=? ORDER BY rowid LIMIT 100', (attempt['id'],))]
                envelope['work'] = self.work(db, current['scope_id']) if phase.skill == 'spoq-execution' else None
                # The mutation itself increments revision; expose that committed revision.
                envelope['revision'] = current['revision'] + 1
                return {'state': state, 'status': run_status(state), 'event_kind': 'invoked',
                        'payload': {'phase_id': p, 'attempt_id': attempt['id'], 'recovered': inspected,
                                    'specification_hash': current['specification_hash']}, 'result': envelope}
            return {'state': state, 'status': run_status(state), 'event_kind': 'checkpoint',
                    'result': {'status': run_status(state), 'blockers': state['blockers'],
                               'needed_participant': 'Wait for active workers or explicitly recover an expired lease.'}}
        return self.repository.mutate(run_id, key, revision, actor, operation,
            request={'operation': 'next', 'phase_id': phase_id, 'ttl': ttl, 'recover': recover})

    @staticmethod
    def work(db, scope_id):
        rows = db.execute('''WITH RECURSIVE scope(id) AS (SELECT id FROM nodes WHERE id=? UNION ALL
            SELECT n.id FROM nodes n JOIN scope s ON n.parent_id=s.id)
            SELECT n.id,n.kind,n.status FROM nodes n JOIN scope s ON n.id=s.id
            WHERE n.kind='task' AND n.status<>'completed' ORDER BY n.id LIMIT 501''', (scope_id,)).fetchall()
        tasks = [dict(r) for r in rows[:500]]
        counts = db.execute('''WITH RECURSIVE scope(id) AS (SELECT id FROM nodes WHERE id=? UNION ALL
            SELECT n.id FROM nodes n JOIN scope s ON n.parent_id=s.id)
            SELECT COUNT(*), COALESCE(SUM(n.status<>'completed'),0) FROM nodes n JOIN scope s ON n.id=s.id
            WHERE n.kind='task' ''', (scope_id,)).fetchone()
        return {'scope_id': scope_id, 'ready_tasks': [r['id'] for r in tasks if Store._ready(db, r['id'])],
                'remaining_tasks': [r['id'] for r in tasks if r['status'] != 'completed'],
                'total_tasks': counts[0], 'remaining_count': counts[1],
                'has_more': len(rows) > 500, 'after': tasks[-1]['id'] if len(rows) > 500 else None,
                'claim_policy': 'Use SPOQ Task claims and durable retry counters before work; phase lease does not replace them.'}

    def renew(self, run_id, attempt_id, token, actor, *, key, expected_revision=None, ttl=300):
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise ValueError('Phase lease TTL must be 1–3600 seconds')
        current = self.get(run_id)
        def operation(db, current):
            attempt = fenced_attempt(db, current, attempt_id, token, actor)
            expires = time.time() + ttl
            db.execute('UPDATE workflow_attempts SET lease_until=?,updated_at=? WHERE id=?', (expires, now(), attempt_id))
            return {'state': current['state'], 'status': current['status'], 'event_kind': 'lease_renewed',
                    'payload': {'attempt_id': attempt_id}, 'result': {'attempt_id': attempt_id, 'lease_until': expires}}
        return self.repository.mutate(run_id, key, self._revision(current, expected_revision), actor, operation,
            request={'operation': 'renew', 'attempt_id': attempt_id, 'token': token, 'ttl': ttl})

    def _commit(self, run_id, attempt_id, token, actor, *, key, request, publish,
                expected_revision=None, refresh_spec=False):
        """Internal transaction hook; public completion must supply evidence validation.

        publish runs inside the transaction and returns validated output references,
        outcome and evidence. No external side effect belongs in this callback.
        """
        current = self.get(run_id)
        def operation(db, current):
            attempt = fenced_attempt(db, current, attempt_id, token, actor)
            compiled = compile_definition(current['definition'])
            phase = compiled.phases[attempt['phase_id']]
            if phase.kind == 'human':
                raise ValueError('Human checkpoints require an explicit user response')
            old_spec = current['specification_hash']
            actual_spec = self.repository.specification_hash(db, current['scope_id'])
            if actual_spec != old_spec:
                if (refresh_spec is not True or phase.skill != 'spoq-plan'
                        or current['state'].get('scope_input_hash') != scope_input_hash(db, current['scope_id'])):
                    raise ValueError('Specification changed; review changed inputs before completing')
                current = {**current, 'specification_hash': actual_spec}
            result = publish(db, current, attempt)
            outcome, outputs, evidence = result['outcome'], result['outputs'], result['evidence']
            if outcome == 'pass':
                if phase.skill == 'spoq-execution':
                    work = self.work(db, current['scope_id'])
                    if work['remaining_count'] or not work['total_tasks']:
                        raise ValueError('Complete the scoped Tasks with claims and validation before completing execution')
                for name, ref in outputs.items():
                    artifact = db.execute('SELECT run_id,attempt_id,kind FROM workflow_artifacts WHERE id=?', (ref,)).fetchone()
                    if artifact is None or artifact['run_id'] != run_id or artifact['attempt_id'] != attempt_id or artifact['kind'] != name:
                        raise ValueError('Output artifact does not belong to this attempt and output kind')
            state = transition(compiled, current['state'], phase.id, attempt_id, outcome,
                               current['routing']['inputs'], outputs)
            attempt_status = 'blocked' if state['phases'][phase.id]['status'] == 'blocked' else ('passed' if outcome == 'pass' else 'failed')
            evidence = {**evidence, 'input_specification_hash': old_spec, 'specification_hash': actual_spec}
            db.execute('''UPDATE workflow_attempts SET status=?,evidence=?,specification_hash=?,lease_until=0,updated_at=? WHERE id=?''',
                       (attempt_status, canonical_json(evidence), actual_spec, now(), attempt_id))
            synchronize_attempts(db, current, state)
            return {'state': state, 'status': run_status(state), 'event_kind': 'completed',
                    'specification_hash': actual_spec,
                    'payload': {'phase_id': phase.id, 'attempt_id': attempt_id, 'outcome': outcome,
                                'specification_hash': actual_spec, 'input_specification_hash': old_spec},
                    'result': {'status': run_status(state), 'attempt_id': attempt_id, 'outcome': outcome,
                               'outputs': outputs, 'blockers': state['blockers'],
                               'validation_journal_id': evidence.get('validation_journal_id')}}
        return self.repository.mutate(run_id, key, self._revision(current, expected_revision), actor, operation,
            request={**request, 'operation': 'complete', 'attempt_id': attempt_id, 'token': token, 'refresh_spec': refresh_spec})
