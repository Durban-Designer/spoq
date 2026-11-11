"""Domain operations with task state and history committed together."""
from __future__ import annotations

import json
import base64
import time
from pathlib import Path

from .db import encode, event, index_document, initialize, now, transaction, uid
from .graph import waves

STATUSES = {'pending', 'in_progress', 'qa', 'rework', 'completed', 'failed', 'blocked'}
PARENTS = {'project_plan': None, 'feature': 'project_plan', 'task': 'feature'}


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        initialize(self.path)

    @staticmethod
    def _get(db, node_id):
        row = db.execute('SELECT * FROM nodes WHERE id=?', (node_id,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown node: {node_id}')
        result = dict(row)
        result['data'] = json.loads(result['data'])
        return result

    def get(self, node_id):
        with transaction(self.path) as db:
            return self._get(db, node_id)

    def list(self, kind='', parent_id=''):
        with transaction(self.path) as db:
            return [self._get(db, r[0]) for r in db.execute(
                "SELECT id FROM nodes WHERE (?='' OR kind=?) AND (?='' OR parent_id=?) ORDER BY id",
                (kind, kind, parent_id, parent_id))]

    def create(self, kind, node_id, title, parent_id=None, data=None, status='pending', actor='user'):
        if (not isinstance(kind,str) or kind not in PARENTS or not isinstance(status,str) or status not in STATUSES
                or not isinstance(node_id,str) or not node_id.strip() or not isinstance(title,str) or not title.strip()
                or (data is not None and not isinstance(data,dict))):
            raise ValueError('Valid kind, status, ID, and title are required')
        with transaction(self.path, write=True) as db:
            expected = PARENTS[kind]
            if expected and (not parent_id or self._get(db, parent_id)['kind'] != expected):
                raise ValueError(f'{kind} requires a {expected} parent')
            if parent_id and self._get(db,parent_id)['status']=='completed':
                raise ValueError('Reopen the completed parent before adding work')
            if not expected and parent_id:
                raise ValueError('A Project Plan has no parent')
            db.execute('INSERT INTO nodes(id,kind,parent_id,title,status,data,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (node_id, kind, parent_id, title, status, encode(data or {}), now()))
            event(db, node_id, 'created', actor, {'kind': kind})
            index_document(db, node_id, kind, title, encode(data or {}))
            return self._get(db, node_id)

    @staticmethod
    def _graph(db, scope_id):
        scope = Store._get(db, scope_id)
        if scope['kind'] == 'task':
            raise ValueError('Tasks cannot contain a DAG')
        children = [dict(r) for r in db.execute('SELECT id,status FROM nodes WHERE parent_id=? ORDER BY id', (scope_id,))]
        dependencies = {r['id']: [] for r in children}
        for r in db.execute('SELECT node_id,dependency_id FROM edges WHERE scope_id=? ORDER BY dependency_id', (scope_id,)):
            dependencies[r[0]].append(r[1])
        return dependencies, {r['id']: r['status'] for r in children}

    def depend(self, node_id, dependency_id, actor='user'):
        with transaction(self.path, write=True) as db:
            node, dependency = self._get(db, node_id), self._get(db, dependency_id)
            scope = node['parent_id']
            if not scope or scope != dependency['parent_id'] or node['kind'] != dependency['kind']:
                raise ValueError('Dependencies must connect siblings in the same Feature or Project Plan')
            if node['status']=='completed' or self._get(db,scope)['status']=='completed':
                raise ValueError('Reopen completed work before changing dependencies')
            dependencies, _ = self._graph(db, scope)
            dependencies[node_id].append(dependency_id)
            waves(dependencies)  # reject cycles before modifying persistent state
            db.execute('INSERT OR IGNORE INTO edges VALUES(?,?,?)', (scope, node_id, dependency_id))
            event(db, node_id, 'dependency_added', actor, {'dependency': dependency_id})

    def remove_dependency(self, node_id, dependency_id, actor='user'):
        with transaction(self.path,write=True) as db:
            node,dependency=self._get(db,node_id),self._get(db,dependency_id)
            if not node['parent_id'] or node['parent_id']!=dependency['parent_id']:
                raise ValueError('Dependencies must connect siblings')
            if node['status']=='completed' or self._get(db,node['parent_id'])['status']=='completed':
                raise ValueError('Reopen completed work before changing dependencies')
            removed=db.execute('DELETE FROM edges WHERE scope_id=? AND node_id=? AND dependency_id=?',
                               (node['parent_id'],node_id,dependency_id)).rowcount
            if removed: event(db,node_id,'dependency_removed',actor,{'dependency':dependency_id})
            return {'removed':bool(removed)}

    @staticmethod
    def _gates_open(db, node_id):
        pending = [node_id]
        visited = set()
        while pending:
            current = Store._get(db, pending.pop())
            if current['id'] in visited:
                continue
            visited.add(current['id'])
            if current['data'].get('migration_errors'):
                return False
            for dependency in db.execute('''SELECT n.id,n.status FROM edges e JOIN nodes n
                    ON n.id=e.dependency_id WHERE e.node_id=?''', (current['id'],)):
                if dependency['status']!='completed':
                    return False
                pending.append(dependency['id'])
            if current['parent_id']:
                parent = Store._get(db, current['parent_id'])
                if parent['status'] in {'blocked','completed','failed'}:
                    return False
                pending.append(parent['id'])
        return True

    @staticmethod
    def _ready(db, node_id):
        node = Store._get(db, node_id)
        abandoned = node['status']=='in_progress' and not db.execute(
            'SELECT 1 FROM claims WHERE task_id=? AND expires_at>?', (node_id, time.time())).fetchone()
        return bool((node['status'] in {'pending', 'rework', 'failed'} or abandoned) and Store._gates_open(db, node_id))

    def dag(self, scope_id):
        with transaction(self.path) as db:
            dependencies, statuses = self._graph(db, scope_id)
            scope = self._get(db, scope_id)
            errors = scope['data'].get('migration_errors', [])
            return {'scope_id': scope_id, 'dependencies': dependencies, 'waves': waves(dependencies),
                    'statuses': statuses, 'ready': [] if errors else [k for k in dependencies if self._ready(db, k)],
                    'errors': errors}

    def update(self, node_id, status, actor='user', expected_revision=None, evidence=None, claim_token=None):
        if status not in STATUSES:
            raise ValueError('Invalid status')
        with transaction(self.path, write=True) as db:
            node = self._get(db, node_id)
            if expected_revision is not None and expected_revision != node['revision']:
                raise ValueError('Revision conflict; reload the node before updating')
            if status!='completed':
                parent_id=node['parent_id']
                while parent_id:
                    parent=self._get(db,parent_id)
                    if parent['status']=='completed':
                        raise ValueError('Reopen completed ancestors before reopening their work')
                    parent_id=parent['parent_id']
            claim = db.execute('SELECT * FROM claims WHERE task_id=?', (node_id,)).fetchone()
            if claim_token is not None and claim is None:
                raise ValueError('Stale claim token: this claim has been released')
            if claim and (claim['token'] != claim_token or claim['expires_at'] <= time.time()):
                raise ValueError('A current claim token is required; stale workers cannot update this task')
            if status == 'in_progress' and node['status'] != 'in_progress' and not self._ready(db, node_id):
                raise ValueError('Dependencies or migration errors prevent starting this node')
            if status == 'completed':
                if not self._gates_open(db, node_id):
                    raise ValueError('Dependencies or ancestor gates must be completed/resolved first')
                if node['data'].get('migration_errors'):
                    raise ValueError('Resolve migration errors before completing this node')
                if db.execute("SELECT 1 FROM nodes WHERE parent_id=? AND status<>'completed'", (node_id,)).fetchone():
                    raise ValueError('All children must be completed first')
                if node['kind'] == 'task' and not evidence:
                    raise ValueError('Task completion requires validation evidence')
                if db.execute("SELECT 1 FROM edges e JOIN nodes n ON n.id=e.dependency_id WHERE e.node_id=? AND n.status<>'completed'", (node_id,)).fetchone():
                    raise ValueError('Dependencies must be completed first')
            db.execute('UPDATE nodes SET status=?,revision=revision+1,updated_at=? WHERE id=?', (status, now(), node_id))
            event(db, node_id, 'status_changed', actor, {'from': node['status'], 'to': status, 'evidence': evidence})
            if claim and status != 'in_progress':
                db.execute('DELETE FROM claims WHERE task_id=?', (node_id,))
            return self._get(db, node_id)

    def journal(self, body, agent='user', node_id=None, metadata=None, entry_id=None):
        if not body.strip():
            raise ValueError('Journal body is required')
        entry_id = entry_id or uid()
        with transaction(self.path, write=True) as db:
            db.execute('INSERT INTO journal_entries VALUES(?,?,?,?,?,?)',
                       (entry_id, node_id, agent, body, encode(metadata or {}), now()))
            index_document(db, entry_id, 'journal', body.splitlines()[0][:200], body)
        return {'id': entry_id}

    def journals(self, node_id='', limit=50):
        with transaction(self.path) as db:
            return [dict(r) for r in db.execute("SELECT * FROM journal_entries WHERE (?='' OR node_id=?) ORDER BY created_at DESC LIMIT ?",
                                              (node_id, node_id, min(max(limit, 1), 500)))]

    def history(self, node_id):
        with transaction(self.path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM events WHERE node_id=? ORDER BY sequence', (node_id,))]

    def edit(self, node_id, data, title=None, expected_revision=None, actor='user'):
        if not isinstance(data,dict):
            raise ValueError('Node metadata must be an object')
        with transaction(self.path, write=True) as db:
            node = self._get(db, node_id)
            if expected_revision is not None and node['revision'] != expected_revision:
                raise ValueError('Revision conflict')
            merged = {**node['data'], **data}
            title = title if title is not None else node['title']
            if not title.strip(): raise ValueError('Title is required')
            db.execute('UPDATE nodes SET title=?,data=?,revision=revision+1,updated_at=? WHERE id=?',
                       (title, encode(merged), now(), node_id))
            event(db, node_id, 'edited', actor, {'fields': sorted(data), 'title': title})
            index_document(db, node_id, node['kind'], title, encode(merged))
            return self._get(db, node_id)

    def claim(self, task_id, run_id, agent_id, ttl=300):
        if not 1 <= ttl <= 3600:
            raise ValueError('Claim TTL must be between 1 and 3600 seconds')
        with transaction(self.path, write=True) as db:
            node = self._get(db, task_id)
            if node['kind'] != 'task':
                raise ValueError('Only Tasks can be claimed')
            active = db.execute('SELECT * FROM claims WHERE task_id=?', (task_id,)).fetchone()
            if active and active['expires_at'] > time.time():
                raise ValueError('Task is already claimed')
            # Expired in-progress work may be reclaimed, but dependency gates still apply.
            if node['status'] == 'in_progress' and active:
                db.execute("UPDATE nodes SET status='rework' WHERE id=?", (task_id,))
            if not self._ready(db, task_id):
                raise ValueError('Task is not ready')
            token = uid()
            db.execute('INSERT OR REPLACE INTO claims VALUES(?,?,?,?,?)', (task_id, run_id, agent_id, token, time.time()+ttl))
            db.execute("UPDATE nodes SET status='in_progress',revision=revision+1,updated_at=? WHERE id=?", (now(), task_id))
            event(db, task_id, 'claimed', agent_id, {'run_id': run_id, 'token': token})
            return {'task_id': task_id, 'token': token, 'ttl': ttl}

    def renew_claim(self, task_id, token, ttl=300):
        if not 1 <= ttl <= 3600:
            raise ValueError('Claim TTL must be between 1 and 3600 seconds')
        with transaction(self.path, write=True) as db:
            if not db.execute('UPDATE claims SET expires_at=? WHERE task_id=? AND token=? AND expires_at>?',
                              (time.time()+ttl, task_id, token, time.time())).rowcount:
                raise ValueError('Claim has expired or is owned by another worker')
        return {'task_id': task_id, 'ttl': ttl}

    def snapshot(self):
        with transaction(self.path) as db:
            tables = ('nodes', 'edges', 'events', 'journal_entries', 'runs', 'agents', 'threads', 'messages', 'deliveries', 'claims', 'meta', 'legacy_sources')
            from .workflows.schema import WORKFLOW_TABLES
            has_workflows = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_runs'").fetchone()
            include_workflows = bool(has_workflows and any(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in WORKFLOW_TABLES))
            if include_workflows:
                tables += WORKFLOW_TABLES
            result = {t: [dict(r) for r in db.execute(f'SELECT * FROM {t}')] for t in tables}
            for row in result['legacy_sources']:
                row['content'] = base64.b64encode(row['content']).decode('ascii')
            return {'format': 'spoq-1.1' if include_workflows else 'spoq-1', 'tables': result}
