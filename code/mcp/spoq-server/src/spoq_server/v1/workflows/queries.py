"""Bounded read-only projections shared by CLI, MCP and the local viewer.

Every response uses one committed SQLite read transaction. Event cursors are
GLOBAL identities: scanning an unrelated event advances a cursor, and numeric
gaps never by themselves indicate lost data. No query initializes or upgrades a
store, publishes artifacts, launches a model, or exposes invocation lease tokens.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from ..store import Store
from .repository import WorkflowRepository
from .schema import VERSION
from .types import canonical_json

MAX_TEXT_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 4096
WORK_CURSOR = 'spoq-work-1:'
SCOPE_SQL = '''WITH RECURSIVE scope(id) AS (SELECT id FROM nodes WHERE id=? UNION ALL
 SELECT n.id FROM nodes n JOIN scope s ON n.parent_id=s.id)'''


def _limit(value, maximum=500):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'Query limit must be an integer from 1 to {maximum}')
    return value


def _sequence(value, label='Cursor', *, nullable=False):
    if nullable and value is None:
        return value
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError(label + ' must be a nonnegative SQLite integer')
    return value


def _text(value, label='Cursor'):
    if not isinstance(value, str) or len(value) > 16384:
        raise ValueError(label + ' must be bounded text')
    return value


def _detail(run_id, resource, identity):
    return '/api/runs/' + quote(run_id, safe='') + '/' + resource + '/' + quote(identity, safe='')


META_SQL = '''CASE WHEN length(CAST(metadata AS BLOB))<=4096 THEN metadata ELSE
 json_object('formal_status',substr(CAST(json_extract(metadata,'$.formal_status') AS TEXT),1,128),
             'decision_id',substr(CAST(json_extract(metadata,'$.decision_id') AS TEXT),1,128),
             'reviewed_artifact_id',substr(CAST(json_extract(metadata,'$.reviewed_artifact_id') AS TEXT),1,128),
             'reviewed_artifact_hash',substr(CAST(json_extract(metadata,'$.reviewed_artifact_hash') AS TEXT),1,64),
             'confluence',json_object('url',substr(CAST(json_extract(metadata,'$.confluence.url') AS TEXT),1,1000),
                 'version',substr(CAST(json_extract(metadata,'$.confluence.version') AS TEXT),1,128))) END AS metadata'''
ARTIFACT_SQL = '''rowid AS _cursor,id,run_id,attempt_id,scope_id,kind,author,source,sha256,created_at,
 length(CAST(content AS BLOB)) AS content_bytes,
 (length(CAST(metadata AS BLOB))>4096) AS metadata_truncated,''' + META_SQL
ATTEMPT_SQL = '''rowid AS _cursor,id,run_id,phase_id,number,status,owner,lease_until,
 specification_hash,created_at,updated_at,
 substr(CAST(json_extract(evidence,'$.verdict') AS TEXT),1,64) AS verdict,
 CASE WHEN json_type(evidence,'$.checks_passed') IN ('true','false') THEN json_extract(evidence,'$.checks_passed') END AS checks_passed,
 CASE WHEN json_type(evidence,'$.average') IN ('integer','real') THEN json_extract(evidence,'$.average') END AS average,
 CASE WHEN json_type(evidence,'$.minimum') IN ('integer','real') THEN json_extract(evidence,'$.minimum') END AS minimum,
 substr(CAST(json_extract(evidence,'$.reviewer.agent') AS TEXT),1,200) AS reviewer_agent,
 substr(CAST(json_extract(evidence,'$.reviewer.review_type') AS TEXT),1,64) AS review_type,
 substr(CAST(json_extract(evidence,'$.provenance') AS TEXT),1,256) AS provenance,
 substr(CAST(json_extract(evidence,'$.validation_journal_id') AS TEXT),1,128) AS validation_journal_id,
 json_array_length(evidence,'$.observed_checks') AS check_count,
 length(CAST(evidence AS BLOB)) AS evidence_bytes'''
DECISION_SQL = '''rowid AS _cursor,id,run_id,attempt_id,artifact_id,artifact_hash,specification_hash,
 definition_hash,source,author,decision,substr(reason,1,1000) AS reason,
 (length(reason)>1000) AS reason_truncated,created_at'''


class ReadModel:
    def __init__(self, store: Store | Path):
        self.path = Path(store.path if isinstance(store, Store) else store).expanduser().resolve()

    @contextmanager
    def _read(self, *, allow_missing=False):
        if not self.path.is_file():
            if allow_missing:
                yield None
                return
            raise ValueError('SPOQ database does not exist; no read query initializes it')
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > VERSION:
                raise ValueError('Database is newer than this SPOQ installation; upgrade SPOQ')
            if version not in {1, VERSION}:
                raise ValueError('Database does not contain a supported SPOQ schema')
            yield db
        finally:
            db.rollback()
            db.close()

    @staticmethod
    def _workflow_tables(db):
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_runs'").fetchone())

    @staticmethod
    def _bounds(db):
        row = db.execute('SELECT COALESCE(MIN(sequence),0),COALESCE(MAX(sequence),0) FROM events').fetchone()
        return row[0], row[1]

    def _run(self, db, run_id):
        _text(run_id, 'Run ID')
        if self._workflow_tables(db):
            return WorkflowRepository._get(db, run_id)
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown workflow run: ' + run_id)
        return {'run_id': run_id, 'scope_id': row['scope_id'], 'status': 'legacy_unclassified',
                'strategy': 'legacy_unclassified', 'definition': None, 'state': {}, 'created_at': row['created_at']}

    def runs(self, scope_id='', limit=100, after=''):
        _limit(limit);_text(scope_id, 'Scope ID');_text(after)
        with self._read(allow_missing=True) as db:
            if db is None:
                return {'runs': [], 'pagination': {'has_more': False, 'cursor': None}, 'cursor': 0}
            columns = 'r.id AS run_id,r.scope_id,r.created_at'
            joins = ''
            if self._workflow_tables(db):
                columns += ",w.status,w.revision,w.definition_hash,w.updated_at,substr(CAST(json_extract(w.routing,'$.strategy') AS TEXT),1,128) AS strategy"
                joins = ' LEFT JOIN workflow_runs w ON w.run_id=r.id'
            rows = db.execute(f'''SELECT {columns} FROM runs r {joins}
                WHERE (?='' OR r.scope_id=?) AND r.id>? ORDER BY r.id LIMIT ?''',
                (scope_id, scope_id, after, limit + 1)).fetchall()
            more = len(rows) > limit
            items = []
            for raw in rows[:limit]:
                row = dict(raw)
                row['provenance'] = 'strategy' if row.get('status') else 'legacy_unclassified'
                row['status'] = row.get('status') or 'legacy_unclassified'
                items.append(row)
            return {'runs': items, 'pagination': {'has_more': more, 'cursor': items[-1]['run_id'] if more else None},
                    'cursor': self._bounds(db)[1]}

    def inspect(self, run_id):
        """Read lifecycle diagnostics, including schema-1 runs, without Store init."""
        with self._read() as db:
            current = self._run(db, run_id)
            if current['status'] == 'legacy_unclassified':
                return {**current, 'client_mode': 'legacy_unclassified',
                        'next_action': 'Start a strategy run; no past phases are inferred.'}
            current['current_specification_hash'] = WorkflowRepository.specification_hash(db, current['scope_id'])
            active = [dict(row) for row in db.execute('''SELECT id,phase_id,status,owner,lease_until
                FROM workflow_attempts WHERE run_id=? AND status IN ('running','waiting_human') ORDER BY rowid LIMIT 256''', (run_id,))]
            for row in active:
                row['recoverable'] = row['status'] == 'running' and row['lease_until'] <= time.time()
            return {**current, 'active_attempts': active, 'client_mode': 'client_driven',
                    'engine_launches_models': False,
                    'next_action': ('A user must respond to the exact reviewed revision.' if current['status'] == 'waiting_human'
                                    else 'Use a connected coding client to inspect and execute returned skill envelopes; registration alone does not establish model availability.')}

    @staticmethod
    def _history_page(db, run_id, resource, limit, before):
        if resource == 'participants':
            columns, table, order = 'rowid AS _cursor,id,role,runtime,heartbeat', 'agents', 'rowid'
        elif resource == 'attempts': columns, table, order = ATTEMPT_SQL, 'workflow_attempts', 'rowid'
        elif resource == 'artifacts': columns, table, order = ARTIFACT_SQL, 'workflow_artifacts', 'rowid'
        elif resource == 'decisions': columns, table, order = DECISION_SQL, 'workflow_decisions', 'rowid'
        else: raise ValueError('History resource must be attempts, artifacts, decisions or participants')
        rows = db.execute(f'SELECT {columns} FROM {table} WHERE run_id=? AND (? IS NULL OR {order}<?) ORDER BY {order} DESC LIMIT ?',
                          (run_id, before, before, limit + 1)).fetchall()
        more = len(rows) > limit
        selected = list(reversed(rows[:limit]))
        items = []
        for raw in selected:
            item = dict(raw)
            item['cursor'] = item.pop('_cursor')
            if resource == 'artifacts':
                item['metadata'] = json.loads(item['metadata'])
                item['metadata_truncated'] = bool(item['metadata_truncated'])
                item['details_url'] = _detail(run_id, 'artifacts', item['id'])
            elif resource == 'attempts':
                item['evidence'] = {key: item.pop(key) for key in ('verdict', 'checks_passed', 'average', 'minimum',
                    'reviewer_agent', 'review_type', 'provenance', 'validation_journal_id', 'check_count')}
                item['evidence']['reviewer'] = {'agent': item['evidence'].pop('reviewer_agent'),
                                               'review_type': item['evidence']['review_type']}
                value = item['evidence']['checks_passed']
                item['evidence']['checks_passed'] = bool(value) if type(value) is int and value in (0, 1) else None
                item['details_url'] = _detail(run_id, 'attempts', item['id'])
            elif resource == 'decisions':
                item['reason_truncated'] = bool(item['reason_truncated'])
                item['details_url'] = _detail(run_id, 'attempts', item['attempt_id'])
            items.append(item)
        return {'resource': resource, 'items': items,
                'pagination': {'has_more': more, 'cursor': selected[0]['_cursor'] if more else None}}

    def history(self, run_id, resource='attempts', before=None, limit=100):
        if not isinstance(resource, str): raise ValueError('History resource must be text')
        _limit(limit);_sequence(before, nullable=True)
        with self._read() as db:
            run = self._run(db, run_id)
            if run['status'] == 'legacy_unclassified' and resource != 'participants':
                if resource not in {'attempts', 'artifacts', 'decisions'}:
                    raise ValueError('Unknown history resource')
                return {'resource': resource, 'items': [], 'pagination': {'has_more': False, 'cursor': None}}
            return self._history_page(db, run_id, resource, limit, before)

    @staticmethod
    def _work_cursor(after):
        _text(after)
        value = {'n': '', 'e': ['', ''], 'nd': False, 'ed': False}
        if not after.startswith(WORK_CURSOR):
            value['n'] = after;value['e'][0] = after
            return value
        try:
            raw = base64.urlsafe_b64decode(after[len(WORK_CURSOR):].encode())
            result = json.loads(raw)
            if (not isinstance(result, dict) or set(result) != set(value) or not isinstance(result['n'], str)
                    or not isinstance(result['e'], list) or len(result['e']) != 2
                    or any(not isinstance(item, str) for item in result['e'])
                    or type(result['nd']) is not bool or type(result['ed']) is not bool):
                raise ValueError('shape')
            return result
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError('Invalid work-page cursor') from exc

    @classmethod
    def _work(cls, db, scope_id, after='', limit=500):
        state = cls._work_cursor(after)
        if scope_id is None:
            return {'scope_id': None, 'nodes': [], 'edges': [], 'pagination': {'has_more': False, 'cursor': None}}
        nodes, edges = [], []
        if not state['nd']:
            rows = db.execute(SCOPE_SQL + ''' SELECT n.id,n.kind,n.parent_id,n.status,substr(n.title,1,500) AS title,
                length(n.title)>500 AS title_truncated FROM nodes n JOIN scope s ON s.id=n.id
                WHERE n.id>? ORDER BY n.id LIMIT ?''', (scope_id, state['n'], limit + 1)).fetchall()
            nodes = [dict(row) for row in rows[:limit]]
            state['nd'] = len(rows) <= limit
            if nodes: state['n'] = nodes[-1]['id']
        if not state['ed']:
            rows = db.execute(SCOPE_SQL + ''' SELECT e.scope_id,e.node_id,e.dependency_id FROM edges e JOIN scope s ON s.id=e.scope_id
                WHERE e.node_id>? OR (e.node_id=? AND e.dependency_id>?)
                ORDER BY e.node_id,e.dependency_id LIMIT ?''',
                (scope_id, state['e'][0], state['e'][0], state['e'][1], limit + 1)).fetchall()
            edges = [dict(row) for row in rows[:limit]]
            state['ed'] = len(rows) <= limit
            if edges: state['e'] = [edges[-1]['node_id'], edges[-1]['dependency_id']]
        more = not state['nd'] or not state['ed']
        cursor = WORK_CURSOR + base64.urlsafe_b64encode(canonical_json(state).encode()).decode() if more else None
        for node in nodes: node['title_truncated'] = bool(node['title_truncated'])
        return {'scope_id': scope_id, 'nodes': nodes, 'edges': edges, 'pagination': {'has_more': more, 'cursor': cursor}}

    def work(self, run_id, after='', limit=500):
        _limit(limit)
        with self._read() as db:
            run = self._run(db, run_id)
            return self._work(db, run['scope_id'], after, limit)

    def snapshot(self, run_id, limit=100, before=None):
        _limit(limit);_sequence(before, nullable=True)
        with self._read() as db:
            current = self._run(db, run_id)
            legacy = current['status'] == 'legacy_unclassified'
            pages = {resource: self._history_page(db, run_id, resource, limit, before if resource == 'attempts' else None)
                     for resource in ('attempts', 'artifacts', 'decisions')} if not legacy else {
                resource: {'items': [], 'pagination': {'has_more': False, 'cursor': None}}
                for resource in ('attempts', 'artifacts', 'decisions')}
            participants = self._history_page(db, run_id, 'participants', limit, None)
            stale = False
            actual = None
            if not legacy:
                actual = WorkflowRepository.specification_hash(db, current['scope_id'])
                stale = actual != current['specification_hash']
            state = current['state']
            blockers = list(state.get('blockers', []))
            if stale: blockers.append('Saved specification changed; previous phase results require explicit invalidation/review before progression.')
            if not legacy:
                for phase_id, phase in state['phases'].items():
                    if phase['status'] == 'waiting_human': blockers.append('Awaiting a user response for phase ' + phase_id + ' at its exact reviewed artifact revision.')
            run = {key: current.get(key) for key in ('run_id', 'scope_id', 'status', 'revision', 'created_at', 'updated_at',
                                                   'definition_hash', 'specification_hash')}
            run.update(provenance='legacy_unclassified' if legacy else 'strategy',
                       current_specification_hash=actual, stale_specification=stale,
                       transitions=state.get('transitions'), epoch=state.get('epoch'),
                       pagination={resource: pages[resource]['pagination'] for resource in ('artifacts', 'decisions')})
            run['pagination']['participants'] = participants['pagination']
            definition = {} if legacy else {**current['definition'], 'content_hash': current['definition_hash']}
            phases = []
            if not legacy:
                for phase in current['definition']['phases']:
                    value = state['phases'][phase['id']]
                    visible = {key: value.get(key) for key in ('status','ready','attempt_id','last_outcome')}
                    visible.update(id=phase['id'],reason=str(value.get('reason',''))[:1000])
                    if value.get('attempt_id') is not None:
                        owner = db.execute('SELECT owner,number FROM workflow_attempts WHERE id=? AND run_id=?',
                                           (value['attempt_id'],run_id)).fetchone()
                        if owner is not None: visible.update(owner=dict(owner)['owner'],number=owner['number'])
                    phases.append(visible)
            return {'format': 'spoq-workflow-view-1', 'cursor': self._bounds(db)[1], 'run': run,
                    'definition': definition, 'routing': {'strategy': 'legacy_unclassified'} if legacy else current['routing'],
                    'phases': phases, 'attempts': pages['attempts']['items'], 'artifacts': pages['artifacts']['items'],
                    'decisions': pages['decisions']['items'], 'participants': participants['items'],
                    'work': self._work(db, current['scope_id']), 'blockers': blockers,
                    'has_more_attempts': pages['attempts']['pagination']['has_more'],
                    'attempt_cursor': pages['attempts']['pagination']['cursor']}

    def events(self, run_id, after=0, limit=100):
        _sequence(after);_limit(limit)
        with self._read() as db:
            current = self._run(db, run_id)
            minimum, maximum = self._bounds(db)
            if after > maximum or minimum and after < minimum - 1:
                return {'events': [], 'cursor': maximum, 'has_more': False, 'reset': True}
            keys = ('run_id', 'phase_id', 'attempt_id', 'outcome', 'decision_id', 'decision', 'artifact_id',
                    'artifact_hash', 'definition_hash', 'specification_hash', 'from', 'to', 'kind', 'title', 'reason')
            safe_payload = "CASE WHEN json_valid(e.payload) THEN e.payload ELSE '{}' END"
            columns = ','.join("substr(CAST(json_extract(" + safe_payload + ",'$." + key + "') AS TEXT),1,1000) AS p_" + key for key in keys)
            rows = db.execute(SCOPE_SQL + f''' SELECT e.sequence,e.node_id,e.kind,substr(e.actor,1,200) AS actor,e.created_at,
                CASE WHEN e.kind LIKE 'workflow.%' THEN json_extract({safe_payload},'$.run_id')=?
                 ELSE e.node_id IN (SELECT id FROM scope) END AS applicable,json_valid(e.payload) AS payload_valid,{columns}
                FROM events e WHERE e.sequence>? ORDER BY e.sequence LIMIT ?''',
                (current['scope_id'], run_id, after, limit)).fetchall()
            items = []
            for raw in rows:
                if not raw['applicable']: continue
                row = dict(raw)
                payload = {key: row.pop('p_' + key) for key in keys if raw['p_' + key] is not None}
                # Drop all unused projection aliases, including fields absent from this event.
                row = {key: value for key, value in row.items() if not key.startswith('p_') and key != 'applicable'}
                valid = row.pop('payload_valid')
                row['payload'] = payload
                if not valid: row['payload_invalid'] = True
                items.append(row)
            cursor = rows[-1]['sequence'] if rows else after
            return {'events': items, 'cursor': cursor, 'has_more': cursor < maximum, 'reset': False}

    def artifact(self, run_id, artifact_id):
        _text(artifact_id, 'Artifact ID')
        with self._read() as db:
            self._run(db, run_id)
            row = db.execute('SELECT ' + ARTIFACT_SQL + ' FROM workflow_artifacts WHERE run_id=? AND id=?', (run_id, artifact_id)).fetchone() if self._workflow_tables(db) else None
            if row is None: raise ValueError('Unknown registered artifact in this workflow run')
            if row['content_bytes'] > MAX_TEXT_BYTES: raise ValueError('Registered artifact exceeds the one MiB rendering limit')
            metadata_size = db.execute('SELECT length(CAST(metadata AS BLOB)) FROM workflow_artifacts WHERE id=?', (artifact_id,)).fetchone()[0]
            if metadata_size > MAX_TEXT_BYTES: raise ValueError('Artifact metadata exceeds the one MiB detail limit')
            result = dict(db.execute('''SELECT id,run_id,attempt_id,scope_id,kind,author,source,content,sha256,metadata,created_at
                FROM workflow_artifacts WHERE run_id=? AND id=?''', (run_id, artifact_id)).fetchone())
            result['metadata'] = json.loads(result['metadata'])
            result['content_bytes'] = row['content_bytes']
            result['render_as'] = 'text'
            return result

    def attempt(self, run_id, attempt_id):
        _text(attempt_id, 'Attempt ID')
        with self._read() as db:
            self._run(db, run_id)
            row = db.execute('SELECT ' + ATTEMPT_SQL + ' FROM workflow_attempts WHERE run_id=? AND id=?', (run_id, attempt_id)).fetchone() if self._workflow_tables(db) else None
            if row is None: raise ValueError('Unknown phase attempt in this workflow run')
            if row['evidence_bytes'] > MAX_TEXT_BYTES: raise ValueError('Attempt evidence exceeds the one MiB detail limit')
            result = {key: row[key] for key in ('id', 'run_id', 'phase_id', 'number', 'status', 'owner', 'lease_until', 'specification_hash', 'created_at', 'updated_at')}
            result['evidence'] = json.loads(db.execute('SELECT evidence FROM workflow_attempts WHERE id=?', (attempt_id,)).fetchone()[0])
            return result

    def node(self, run_id, node_id):
        """Bounded task/Feature acceptance detail, restricted to the run's work scope."""
        _text(node_id, 'Node ID')
        with self._read() as db:
            run = self._run(db, run_id)
            row = db.execute(SCOPE_SQL + ''' SELECT n.id,n.kind,n.parent_id,n.status,substr(n.title,1,16384) AS title,
                length(n.title)>16384 AS title_truncated,length(CAST(n.data AS BLOB)) AS data_bytes,n.revision,n.updated_at
                FROM nodes n JOIN scope s ON s.id=n.id WHERE n.id=?''', (run['scope_id'], node_id)).fetchone()
            if row is None: raise ValueError('Unknown work node in this workflow scope')
            if row['data_bytes'] > MAX_TEXT_BYTES: raise ValueError('Node metadata exceeds the one MiB detail limit')
            result = dict(row);result['title_truncated'] = bool(result['title_truncated'])
            result['data'] = json.loads(db.execute('SELECT data FROM nodes WHERE id=?', (node_id,)).fetchone()[0])
            return result
