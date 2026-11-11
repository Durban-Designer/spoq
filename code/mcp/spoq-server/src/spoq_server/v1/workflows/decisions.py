"""Revision-bound human responses with explicit local-client provenance.

The caller attests that a user performed this action. This does not authenticate
an operating-system human. Board traffic, peer messages and notifications never
supply the attestation automatically.
"""
from __future__ import annotations

from ..db import now, transaction, uid
from .artifacts import text
from .repository import WorkflowRepository
from .types import identifier


class DecisionRepository:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository
        self.path = repository.path

    @staticmethod
    def add(db, run_id: str, attempt_id: str, artifact_id: str, artifact_hash: str,
            decision: str, author: str, reason: str = '', *, source: str,
            user_confirmed: bool = False, decision_id: str | None = None) -> dict:
        if source != 'user' or user_confirmed is not True:
            raise ValueError('Human responses require an explicit user-originated action attestation')
        if not isinstance(decision, str) or decision not in {'approve', 'reject'}:
            raise ValueError('Human decision must be approve or reject')
        text(author, 'Decision author')
        if not isinstance(reason, str) or len(reason) > 100_000:
            raise ValueError('Decision reason must be bounded text')
        run = WorkflowRepository._get(db, run_id)
        attempt = db.execute('SELECT * FROM workflow_attempts WHERE id=? AND run_id=?', (attempt_id, run_id)).fetchone()
        if run['status'] == 'legacy_unclassified' or attempt is None:
            raise ValueError('Decision attempt must belong to this workflow run')
        phase = next((p for p in run['definition']['phases'] if p['id'] == attempt['phase_id']), None)
        active = run['state'].get('phases', {}).get(attempt['phase_id'], {})
        if (phase is None or phase['kind'] != 'human' or attempt['status'] != 'waiting_human'
                or active.get('attempt_id') != attempt_id or active.get('status') != 'waiting_human'):
            raise ValueError('A human response requires the active waiting_human attempt')
        artifact = db.execute('SELECT * FROM workflow_artifacts WHERE id=? AND run_id=?', (artifact_id, run_id)).fetchone()
        if artifact is None or artifact_hash != artifact['sha256']:
            raise ValueError('Decision artifact revision does not match')
        outputs = run['state'].get('outputs', {})
        if artifact_id not in [outputs.get(name) for name in phase['inputs']]:
            raise ValueError('Decision artifact is no longer a current required review input')
        expected_kind = phase.get('config', {}).get('artifact_kind')
        if expected_kind and artifact['kind'] != expected_kind:
            raise ValueError('Decision artifact kind does not match the review contract')
        actual_spec = WorkflowRepository.specification_hash(db, run['scope_id'])
        if run['specification_hash'] != actual_spec or attempt['specification_hash'] != actual_spec:
            raise ValueError('Specification changed; refresh the review before responding')
        decision_id = decision_id or uid()
        identifier(decision_id, 'decision ID')
        db.execute('INSERT INTO workflow_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (decision_id, run_id, attempt_id, artifact_id, artifact_hash, actual_spec,
                    run['definition_hash'], source, author, decision, reason, now()))
        return dict(db.execute('SELECT * FROM workflow_decisions WHERE id=?', (decision_id,)).fetchone())

    def get(self, decision_id: str, *, run_id: str | None = None) -> dict:
        with transaction(self.path) as db:
            row = db.execute('SELECT * FROM workflow_decisions WHERE id=?', (decision_id,)).fetchone()
            if row is None or run_id is not None and row['run_id'] != run_id:
                raise ValueError('Unknown decision in this workflow run')
            return dict(row)

    def is_current(self, decision_id: str) -> bool:
        with transaction(self.path) as db:
            row = db.execute('SELECT * FROM workflow_decisions WHERE id=?', (decision_id,)).fetchone()
            if row is None:
                return False
            run = WorkflowRepository._get(db, row['run_id'])
            attempt = db.execute('SELECT * FROM workflow_attempts WHERE id=? AND run_id=?',
                                 (row['attempt_id'], row['run_id'])).fetchone()
            artifact = db.execute('SELECT * FROM workflow_artifacts WHERE id=? AND run_id=?',
                                  (row['artifact_id'], row['run_id'])).fetchone()
            if attempt is None or artifact is None:
                return False
            phase = next((p for p in run['definition']['phases'] if p['id'] == attempt['phase_id']), None)
            active = run['state'].get('phases', {}).get(attempt['phase_id'], {})
            return (phase is not None and phase['kind'] == 'human'
                    and active.get('attempt_id') == row['attempt_id']
                    and active.get('status') in {'waiting_human', 'passed'}
                    and attempt['status'] in {'waiting_human', 'passed'}
                    and artifact['sha256'] == row['artifact_hash']
                    and row['artifact_id'] in [run['state'].get('outputs', {}).get(name) for name in phase['inputs']]
                    and (not phase.get('config', {}).get('artifact_kind')
                         or artifact['kind'] == phase['config']['artifact_kind'])
                    and row['specification_hash'] == self.repository.specification_hash(db, run['scope_id'])
                    and row['definition_hash'] == run['definition_hash'])

    def list(self, run_id: str, *, limit: int = 100, after: str = '') -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Decision list limit must be 1–500')
        with transaction(self.path) as db:
            WorkflowRepository._get(db, run_id)
            return [dict(r) for r in db.execute('SELECT * FROM workflow_decisions WHERE run_id=? AND id>? ORDER BY id LIMIT ?',
                                               (run_id, after, limit))]
