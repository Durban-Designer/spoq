"""Durable user checkpoints and recorded proposals for successor strategies.

The local client explicitly attests to a user action. Waiting, notifications and
peer messages never supply consent. A human response is not a model quality gate
and cannot expand repository publication or implementation authorization.
"""
from __future__ import annotations

import re

from ..db import now, uid, index_document
from .artifacts import ArtifactRepository, text
from .compiler import compile_definition
from .decisions import DecisionRepository
from .engine import transition, run_status
from .leases import current_artifacts, synchronize_attempts
from .routing import propose_escalation
from .types import canonical_json, identifier, content_hash


def _review_artifact(phase, artifacts: dict, artifact_id: str):
    """Select one primary reviewed input, never an arbitrary earlier output."""
    kind = phase.config.get('artifact_kind')
    if kind is not None and (not isinstance(kind, str) or not kind):
        raise ValueError('Human checkpoint artifact_kind must be nonempty text')
    required = {name: row for name, row in artifacts.items() if name in phase.inputs}
    candidates = [row for row in required.values() if kind is None or row['kind'] == kind]
    if len(candidates) != 1 or candidates[0]['id'] != artifact_id:
        raise ValueError('Response must identify the exact primary artifact declared by this human checkpoint')
    return candidates[0]


def respond(runner, run_id: str, attempt_id: str, artifact_id: str, artifact_hash: str,
            decision: str, author: str, *, key: str, source: str, user_confirmed: bool,
            expected_revision: int | None = None, reason: str = '') -> dict:
    """Apply a revision-bound user response atomically, without a worker TTL.

    The stable event actor is ``user``; the attested human's display name is kept
    in the immutable decision and journal. Returning an old receipt never creates
    another decision, spends another attempt or approves a later revision.
    """
    if source != 'user' or user_confirmed is not True:
        raise ValueError('Human checkpoints require an explicit user-originated action attestation')
    for value, label in ((run_id, 'run ID'), (attempt_id, 'attempt ID'), (artifact_id, 'artifact ID')):
        identifier(value, label)
    if not isinstance(artifact_hash, str) or not re.fullmatch('[a-f0-9]{64}', artifact_hash):
        raise ValueError('Reviewed artifact hash must be a SHA-256 digest')
    if not isinstance(decision, str) or decision not in {'approve', 'reject'}:
        raise ValueError('Human decision must be approve or reject')
    text(author, 'Human author')
    if not isinstance(reason, str) or len(reason) > 100_000:
        raise ValueError('Human findings must be bounded text')
    current = runner.get(run_id)

    def operation(db, current):
        runner._context(db, current)
        compiled = compile_definition(current['definition'])
        attempt = db.execute('SELECT * FROM workflow_attempts WHERE id=? AND run_id=?', (attempt_id, run_id)).fetchone()
        if attempt is None or attempt['phase_id'] not in compiled.phases:
            raise ValueError('Unknown human checkpoint attempt')
        phase = compiled.phases[attempt['phase_id']]
        if phase.kind != 'human':
            raise ValueError('This attempt is not a human checkpoint')
        artifacts = current_artifacts(db, current, phase)
        reviewed = _review_artifact(phase, artifacts, artifact_id)
        if reviewed['sha256'] != artifact_hash:
            raise ValueError('Reviewed artifact revision does not match')
        # The repository verifies the current waiting attempt, spec/hash and user
        # attestation. A response may arrive days after the dispatch lease elapsed.
        record = DecisionRepository.add(db, run_id, attempt_id, artifact_id, artifact_hash,
                                        decision, author, reason, source=source, user_confirmed=user_confirmed)
        outputs, hashes = {}, {}
        for name in phase.outputs:
            artifact = ArtifactRepository.add(db, run_id, attempt_id, name,
                canonical_json(record), author, source='user',
                metadata={'decision_id': record['id'], 'reviewed_artifact_id': artifact_id,
                          'reviewed_artifact_hash': artifact_hash})
            outputs[name], hashes[name] = artifact['id'], artifact['sha256']
        outcome = 'pass' if decision == 'approve' else 'fail'
        state = transition(compiled, current['state'], phase.id, attempt_id, outcome,
                           current['routing']['inputs'], outputs)
        blocked = state['phases'][phase.id]['status'] == 'blocked'
        attempt_status = 'blocked' if blocked else ('passed' if decision == 'approve' else 'failed')
        findings = reason.strip() or ('User requested revision without additional notes.' if decision == 'reject' else '')
        journal_id = uid()
        report = {'stage': 'human_checkpoint', 'run_id': run_id, 'scope_id': current['scope_id'],
                  'phase_id': phase.id, 'attempt_id': attempt_id, 'definition_hash': current['definition_hash'],
                  'specification_hash': current['specification_hash'], 'artifact_id': artifact_id,
                  'artifact_hash': artifact_hash, 'artifact_hashes': {name: row['sha256'] for name, row in artifacts.items()},
                  'decision_id': record['id'], 'decision': decision, 'author': author, 'source': source,
                  'user_confirmed': True, 'findings': findings, 'output_hashes': hashes,
                  'verdict': 'BLOCKED' if blocked else ('APPROVED' if decision == 'approve' else 'REJECTED'),
                  'reviewer': {'agent': author, 'review_type': 'human', 'identity_verification': 'caller_attested'},
                  'provenance': 'user_action_attested_by_local_client_not_os_authenticated',
                  'validation_journal_id': journal_id,
                  'authorization': 'Only this reviewed revision; no additional Git, publication or deployment permission.'}
        body = canonical_json(report)
        db.execute('INSERT INTO journal_entries VALUES(?,?,?,?,?,?)',
                   (journal_id, current['scope_id'], author, body,
                    canonical_json({'stage': 'human_checkpoint', 'run_id': run_id, 'attempt_id': attempt_id}), now()))
        index_document(db, journal_id, 'journal', phase.id + ': ' + report['verdict'], body)
        db.execute('''UPDATE workflow_attempts SET status=?,evidence=?,lease_until=0,updated_at=? WHERE id=?''',
                   (attempt_status, body, now(), attempt_id))
        synchronize_attempts(db, current, state)
        return {'state': state, 'status': run_status(state), 'event_kind': 'human_responded',
                'payload': {'phase_id': phase.id, 'attempt_id': attempt_id, 'decision_id': record['id'],
                            'decision': decision, 'artifact_id': artifact_id, 'artifact_hash': artifact_hash},
                'result': {'status': run_status(state), 'attempt_id': attempt_id, 'decision_id': record['id'],
                           'decision': decision, 'outcome': 'blocked' if blocked else outcome,
                           'outputs': outputs, 'blockers': state['blockers'], 'validation_journal_id': journal_id}}

    return runner.repository.mutate(run_id, key, runner._revision(current, expected_revision), 'user', operation,
        request={'operation': 'respond', 'attempt_id': attempt_id, 'artifact_id': artifact_id,
                 'artifact_hash': artifact_hash, 'decision': decision, 'author': author,
                 'source': source, 'user_confirmed': user_confirmed, 'reason': reason})


def propose_route(runner, run_id: str, new_inputs: dict, *, key: str, actor: str,
                  reason: str, preference: str | None = None, expected_revision: int | None = None) -> dict:
    """Record an explicit successor proposal; never modify a pinned route in place."""
    if not isinstance(new_inputs, dict):
        raise ValueError('Successor routing inputs must be a JSON object')
    current = runner.get(run_id)
    def operation(db, current):
        if not db.execute('SELECT 1 FROM agents WHERE run_id=? AND id=?', (run_id, actor)).fetchone():
            raise ValueError('Register this participant before proposing a successor strategy')
        boundary = not any(p['status'] == 'running' for p in current['state']['phases'].values())
        merged_inputs = {**current['routing']['inputs'], **new_inputs}
        proposal = propose_escalation(current['routing'], merged_inputs, at_phase_boundary=boundary,
                                      reason=reason, preference=preference)
        compiled = compile_definition(current['definition'])
        current_outputs = current_artifacts(db, current)
        reusable = []
        for name, artifact in current_outputs.items():
            owner = next(p for p in compiled.phases.values() if name in p.outputs)
            if owner.kind not in {'gate', 'human'} and current['state']['phases'][owner.id]['status'] == 'passed':
                reusable.append({'output': name, 'artifact_id': artifact['id'], 'sha256': artifact['sha256'],
                                 'source_run_id': run_id, 'source_attempt_id': artifact['attempt_id']})
        proposal = {**proposal, 'proposal_id': uid(), 'source_run_id': run_id, 'predecessor_run_id': run_id,
                    'source_definition_hash': current['definition_hash'],
                    'source_specification_hash': current['specification_hash'],
                    'current_specification_hash': runner.repository.specification_hash(db, current['scope_id']),
                    'reusable_artifacts': reusable,
                    'reuse_policy': 'Re-register content with source provenance and revalidate in a successor; never copy approval or gate outcomes.'}
        journal_id = uid()
        body = canonical_json(proposal)
        db.execute('INSERT INTO journal_entries VALUES(?,?,?,?,?,?)',
                   (journal_id, current['scope_id'], actor, body,
                    canonical_json({'stage': 'strategy_successor_proposal', 'run_id': run_id}), now()))
        index_document(db, journal_id, 'journal', 'Strategy successor proposal', body)
        state = {**current['state'], 'successor_proposal_id': proposal['proposal_id']}
        return {'state': state, 'status': current['status'], 'event_kind': 'successor_proposed',
                'payload': {'proposal_id': proposal['proposal_id'], 'proposed_route_hash': content_hash(proposal['proposed_route'])},
                'result': {**proposal, 'journal_id': journal_id}}
    return runner.repository.mutate(run_id, key, runner._revision(current, expected_revision), actor, operation,
        request={'operation': 'propose_route', 'inputs': new_inputs, 'reason': reason, 'preference': preference})
