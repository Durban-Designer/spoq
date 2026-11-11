"""Atomic workflow state, immutable definitions and durable operation receipts.

Engine callbacks use the same transaction for attempts, artifacts and state. They
must perform database work only: external effects need their own durable receipt
and must be inspected on ambiguous completion, never repeated blindly here.
"""
from __future__ import annotations

import json
import hashlib
from typing import Callable

from ..db import event, now, transaction
from ..store import Store
from .schema import require_workflow_schema
from .types import StrategyDefinition, RunStatus, canonical_json, content_hash, identifier

OPERATIONAL_DATA = frozenset({'retry_count', 'claims', 'execution', 'implementation_readiness'})


def request_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('A stable operation key of 1–200 printable characters is required')
    return value


def _object_json(value, label: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(label + ' must be a JSON object')
    return canonical_json(value)


class WorkflowRepository:
    def __init__(self, store: Store):
        self.store = store
        self.path = store.path
        require_workflow_schema(self.path)

    @staticmethod
    def specification_hash(db, scope_id: str) -> str:
        """Hash semantic work specifications, not leases or lifecycle bookkeeping."""
        Store._get(db, scope_id)
        rows = db.execute('''WITH RECURSIVE scope(id) AS (
            SELECT id FROM nodes WHERE id=? UNION ALL
            SELECT n.id FROM nodes n JOIN scope s ON n.parent_id=s.id)
            SELECT n.id FROM nodes n JOIN scope s ON n.id=s.id ORDER BY n.id''', (scope_id,)).fetchall()
        # A scope can exceed the per-message JSON limit. Hash canonical JSON as
        # a stream, preserving the existing byte representation without making
        # a second full-scope payload or weakening request-size guards.
        digest = hashlib.sha256()
        digest.update(b'[')
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        first = True
        for row in rows:
            node = Store._get(db, row['id'])
            data = {k: v for k, v in node['data'].items() if k not in OPERATIONAL_DATA}
            # The execution skill persists its default before the first attempt.
            # Explicit integer 3 and an omitted Task budget mean the same thing;
            # other values (including bool/float lookalikes) stay semantic.
            if node['kind'] == 'task' and type(data.get('max_retries')) is int and data['max_retries'] == 3:
                data.pop('max_retries')
            spec = {'id': node['id'], 'kind': node['kind'], 'parent_id': node['parent_id'],
                          'title': node['title'],
                          'data': data,
                          'dependencies': [edge[0] for edge in db.execute(
                              'SELECT dependency_id FROM edges WHERE node_id=? ORDER BY dependency_id', (node['id'],))]}
            if not first:
                digest.update(b',')
            first = False
            for chunk in encoder.iterencode(spec):
                digest.update(chunk.encode())
        digest.update(b']')
        return digest.hexdigest()

    @staticmethod
    def _get(db, run_id: str) -> dict:
        row = db.execute('''SELECT w.*,d.definition FROM workflow_runs w
            JOIN workflow_definitions d ON d.hash=w.definition_hash WHERE w.run_id=?''', (run_id,)).fetchone()
        if row is None:
            legacy = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if legacy is not None:
                return {'run_id': run_id, 'scope_id': legacy['scope_id'], 'status': 'legacy_unclassified',
                        'strategy': 'legacy_unclassified', 'definition': None, 'state': {},
                        'created_at': legacy['created_at']}
            raise ValueError('Unknown workflow run: ' + run_id)
        result = dict(row)
        for key in ('routing', 'state', 'definition'):
            result[key] = json.loads(result[key])
        return result

    def get(self, run_id: str) -> dict:
        with transaction(self.path) as db:
            result = self._get(db, run_id)
            if result['status'] != 'legacy_unclassified':
                result['current_specification_hash'] = self.specification_hash(db, result['scope_id'])
            return result

    def list(self, scope_id: str = '', limit: int = 100, after: str = '') -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Workflow list limit must be 1–500')
        with transaction(self.path) as db:
            ids = [row[0] for row in db.execute('''SELECT id FROM runs
                WHERE (?='' OR scope_id=?) AND id>? ORDER BY id LIMIT ?''', (scope_id, scope_id, after, limit))]
            return [self._get(db, key) for key in ids]

    @staticmethod
    def _receipt(db, run_id: str, key: str, fingerprint: str):
        row = db.execute('SELECT fingerprint,result FROM workflow_receipts WHERE run_id=? AND key=?', (run_id, key)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint:
                raise ValueError('Operation key reused with different request content')
            return json.loads(row['result'])
        return None

    @staticmethod
    def _record_receipt(db, run_id: str, key: str, fingerprint: str, result):
        db.execute('INSERT INTO workflow_receipts VALUES(?,?,?,?,?)',
                   (run_id, key, fingerprint, canonical_json(result), now()))

    def start(self, run_id: str, scope_id: str, definition: StrategyDefinition | dict,
              routing: dict, state: dict, key: str, actor: str = 'orchestrator') -> dict:
        identifier(run_id, 'run ID')
        identifier(actor, 'actor')
        request_key(key)
        definition = definition if isinstance(definition, StrategyDefinition) else StrategyDefinition.from_dict(definition)
        definition_json = definition.to_dict()
        route_json, state_json = _object_json(routing, 'Routing'), _object_json(state, 'State')
        digest = definition.content_hash
        fingerprint = content_hash({'operation': 'start', 'run_id': run_id, 'scope_id': scope_id,
                                    'definition_hash': digest, 'routing': routing, 'state': state, 'actor': actor})
        with transaction(self.path, write=True) as db:
            previous = self._receipt(db, run_id, key, fingerprint)
            if previous is not None:
                return previous
            scope = Store._get(db, scope_id)
            if scope['data'].get('migration_errors'):
                raise ValueError('Resolve scope migration errors before starting a workflow')
            run = db.execute('SELECT scope_id FROM runs WHERE id=?', (run_id,)).fetchone()
            if run and run[0] != scope_id:
                raise ValueError('Run already exists with a different scope')
            if db.execute('SELECT 1 FROM workflow_runs WHERE run_id=?', (run_id,)).fetchone():
                raise ValueError('Workflow run already exists; resume it instead')
            timestamp = now()
            db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?)', (run_id, scope_id, timestamp))
            db.execute('INSERT OR IGNORE INTO workflow_definitions VALUES(?,?,?,?,?)',
                       (digest, definition.id, definition.version, canonical_json(definition_json), timestamp))
            # A pinned content hash cannot point at different content, even following an imported snapshot.
            pinned = db.execute('SELECT definition FROM workflow_definitions WHERE hash=?', (digest,)).fetchone()[0]
            if pinned != canonical_json(definition_json):
                raise ValueError('Pinned definition hash collision or corrupt stored definition')
            spec_hash = self.specification_hash(db, scope_id)
            status = 'queued'
            db.execute('INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (run_id, scope_id, digest, route_json, spec_hash, state_json, status, 1, timestamp, timestamp))
            event(db, scope_id, 'workflow.started', actor,
                  {'run_id': run_id, 'definition_hash': digest, 'specification_hash': spec_hash})
            result = self._get(db, run_id)
            self._record_receipt(db, run_id, key, fingerprint, result)
            return result

    def mutate(self, run_id: str, key: str, expected_revision: int, actor: str,
               operation: Callable, *, request: dict) -> dict:
        """Fence a transition and commit its callback writes, event and receipt together.

        The request describes all semantically relevant invocation inputs. Expected
        revision is deliberately excluded from its fingerprint so a network retry
        can retrieve an existing receipt after rereading state.
        """
        request_key(key)
        identifier(actor, 'actor')
        _object_json(request, 'Operation request')
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('A positive expected workflow revision is required')
        fingerprint = content_hash({'actor': actor, 'request': request})
        with transaction(self.path, write=True) as db:
            previous = self._receipt(db, run_id, key, fingerprint)
            if previous is not None:
                return previous
            current = self._get(db, run_id)
            if current['status'] == 'legacy_unclassified':
                raise ValueError('Legacy runs have no strategy state; start a new workflow run')
            if current['revision'] != expected_revision:
                raise ValueError('Workflow revision conflict; reload before retrying')
            change = operation(db, current)
            if not isinstance(change, dict) or not {'state', 'status', 'event_kind'} <= change.keys():
                raise ValueError('Transition must return state, status and event_kind')
            state_json = _object_json(change['state'], 'State')
            if not isinstance(change['status'], str) or change['status'] not in RunStatus:
                raise ValueError('Invalid workflow status')
            identifier(change['event_kind'], 'event kind')
            spec_hash = change.get('specification_hash', current['specification_hash'])
            if spec_hash != current['specification_hash'] and spec_hash != self.specification_hash(db, current['scope_id']):
                raise ValueError('Rebased specification hash must match the current scope')
            revision = current['revision'] + 1
            db.execute('''UPDATE workflow_runs SET state=?,status=?,specification_hash=?,revision=?,updated_at=?
                WHERE run_id=? AND revision=?''', (state_json, change['status'], spec_hash, revision, now(), run_id, expected_revision))
            payload = change.get('payload', {})
            _object_json(payload, 'Event payload')
            event(db, current['scope_id'], 'workflow.' + change['event_kind'], actor,
                  {**payload, 'run_id': run_id, 'revision': revision})
            result = change.get('result', {'run_id': run_id, 'revision': revision, 'status': change['status']})
            if not isinstance(result, dict):
                raise ValueError('Transition result must be a JSON object')
            result = {**result, 'run_id': result.get('run_id', run_id), 'revision': result.get('revision', revision)}
            self._record_receipt(db, run_id, key, fingerprint, result)
            return result
