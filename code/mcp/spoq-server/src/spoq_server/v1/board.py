"""Durable, run-scoped conversations and per-recipient delivery outbox."""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import urlparse

from .db import encode, index_document, now, transaction, uid

KINDS = {'question', 'answer', 'handoff', 'blocker', 'decision', 'update', 'review'}


def validate_registration(agent_id, role, runtime='manual', target='', endpoint=''):
    if runtime not in {'manual', 'codex-cli', 'codex-app-server'}:
        raise ValueError('Unsupported runtime')
    if not agent_id.strip() or not role.strip():
        raise ValueError('Agent ID and role are required')
    if runtime != 'manual' and not target:
        raise ValueError('Codex delivery requires a registered thread UUID')
    if runtime == 'codex-app-server':
        parsed = urlparse(endpoint)
        local_ws = (parsed.scheme == 'ws' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
                    and not parsed.username and not parsed.password)
        local_unix = (parsed.scheme == 'unix' and not parsed.netloc and
                      endpoint.startswith('unix:///') and bool(parsed.path))
        if not (local_ws or local_unix):
            raise ValueError('App-server delivery requires a local WebSocket or absolute Unix socket endpoint')


class Board:
    def __init__(self, store):
        self.path = store.path

    def run(self, run_id, scope_id=None):
        with transaction(self.path, write=True) as db:
            existing = db.execute('SELECT scope_id FROM runs WHERE id=?', (run_id,)).fetchone()
            if existing and existing[0] != scope_id:
                raise ValueError('Run already exists with a different scope')
            db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?)', (run_id, scope_id, now()))
        return {'run_id': run_id}

    def register(self, run_id, agent_id, role, runtime='manual', target='', endpoint=''):
        validate_registration(agent_id, role, runtime, target, endpoint)
        with transaction(self.path, write=True) as db:
            db.execute('''INSERT INTO agents VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id,id) DO UPDATE SET
                role=excluded.role,runtime=excluded.runtime,target=excluded.target,
                endpoint=excluded.endpoint,heartbeat=excluded.heartbeat''',
                (run_id, agent_id, role, runtime, target, endpoint, now()))
        return {'run_id': run_id, 'agent_id': agent_id}

    def post(self, run_id, sender, recipients, body, kind='update', thread_id=None,
             subject='', node_id=None, reply_to=None, request_key=None):
        if kind not in KINDS or not body.strip() or len(body) > 100_000:
            raise ValueError('Valid kind and message body of 1–100000 characters required')
        if not request_key:
            raise ValueError('A stable request_key is required for safe retries')
        if not isinstance(recipients, list) or not recipients or any(not isinstance(r, str) for r in recipients):
            raise ValueError('Recipients must be a nonempty list of agent IDs or role selectors')
        with transaction(self.path, write=True) as db:
            if not db.execute('SELECT 1 FROM agents WHERE run_id=? AND id=?', (run_id, sender)).fetchone():
                raise ValueError('Sender must register in this run')
            # Idempotency describes the request, not membership at a later retry.
            payload = [run_id, sender, sorted(set(recipients)), body, kind, thread_id, subject, node_id, reply_to]
            digest = 'v2:' + hashlib.sha256(encode(payload).encode()).hexdigest()
            previous = db.execute('SELECT id,thread_id,fingerprint FROM messages WHERE run_id=? AND sender=? AND request_key=?',
                                  (run_id, sender, request_key)).fetchone()
            if previous and previous['fingerprint'].startswith('v2:'):
                if digest != previous['fingerprint']:
                    raise ValueError('request_key reused with different message content or recipients')
                return {'id': previous['id'], 'thread_id': previous['thread_id'], 'duplicate': True}
            known = {r['id']: r['role'] for r in db.execute('SELECT id,role FROM agents WHERE run_id=?', (run_id,))}
            resolved = set()
            for recipient in recipients:
                if recipient == '*':
                    resolved.update(k for k in known if k != sender)
                elif recipient.startswith('role:'):
                    resolved.update(k for k, role in known.items() if role == recipient[5:] and k != sender)
                elif recipient in known:
                    resolved.add(recipient)
                else:
                    raise ValueError(f'Unknown recipient: {recipient}')
            if not resolved:
                raise ValueError('Message must have at least one recipient')
            if previous:
                legacy_payload = [run_id, sender, sorted(resolved), body, kind, thread_id, subject, node_id, reply_to]
                if hashlib.sha256(encode(legacy_payload).encode()).hexdigest() != previous['fingerprint']:
                    raise ValueError('request_key reused with different message content or recipients')
                return {'id': previous['id'], 'thread_id': previous['thread_id'], 'duplicate': True}
            if reply_to:
                parent = db.execute('SELECT thread_id,run_id FROM messages WHERE id=?', (reply_to,)).fetchone()
                if not parent or parent['run_id'] != run_id:
                    raise ValueError('Reply target must exist in the same run')
                if thread_id and parent['thread_id'] != thread_id:
                    raise ValueError('Reply belongs to a different thread')
                thread_id = parent['thread_id']
            if thread_id:
                thread = db.execute('SELECT * FROM threads WHERE id=? AND run_id=?', (thread_id, run_id)).fetchone()
                if not thread or thread['state'] != 'open':
                    raise ValueError('Thread is missing, in another run, or resolved')
            else:
                thread_id = uid()
                db.execute('INSERT INTO threads(id,run_id,node_id,subject,created_at) VALUES(?,?,?,?,?)',
                           (thread_id, run_id, node_id, subject or body.splitlines()[0][:120], now()))
            message_id = uid()
            db.execute('''INSERT INTO messages(id,run_id,thread_id,sender,kind,body,reply_to,request_key,fingerprint,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (message_id, run_id, thread_id, sender, kind, body, reply_to, request_key, digest, now()))
            db.executemany('INSERT INTO deliveries(message_id,run_id,recipient) VALUES(?,?,?)',
                           [(message_id, run_id, recipient) for recipient in sorted(resolved)])
            index_document(db, message_id, 'message', subject or kind, body)
            return {'id': message_id, 'thread_id': thread_id, 'recipients': sorted(resolved)}

    def inbox(self, run_id, agent_id, limit=50):
        with transaction(self.path) as db:
            return [dict(r) for r in db.execute('''SELECT m.*,d.state FROM messages m JOIN deliveries d
                ON d.message_id=m.id WHERE d.run_id=? AND d.recipient=? AND d.state<>'acknowledged'
                ORDER BY m.sequence LIMIT ?''', (run_id, agent_id, min(max(limit, 1), 500)))]

    def acknowledge(self, run_id, agent_id, message_id):
        with transaction(self.path, write=True) as db:
            result = db.execute('''UPDATE deliveries SET state='acknowledged',acknowledged_at=?,lease_token=NULL,
                lease_until=NULL WHERE run_id=? AND recipient=? AND message_id=?''',
                (now(), run_id, agent_id, message_id))
            if not result.rowcount:
                raise ValueError('No delivery for this agent in this run')
        return {'id': message_id, 'state': 'acknowledged'}

    def thread(self, run_id, thread_id):
        with transaction(self.path) as db:
            row = db.execute('SELECT * FROM threads WHERE id=? AND run_id=?', (thread_id, run_id)).fetchone()
            if not row:
                raise ValueError('Unknown thread in this run')
            return {**dict(row), 'messages': [dict(r) for r in db.execute(
                'SELECT * FROM messages WHERE thread_id=? ORDER BY sequence', (thread_id,))]}

    def resolve(self, run_id, thread_id, resolution):
        if not resolution.strip():
            raise ValueError('Resolution is required')
        with transaction(self.path, write=True) as db:
            if not db.execute("UPDATE threads SET state='resolved',resolution=? WHERE id=? AND run_id=?",
                              (resolution, thread_id, run_id)).rowcount:
                raise ValueError('Unknown thread in this run')
        return {'thread_id': thread_id, 'state': 'resolved'}

    def lease(self, ttl=60):
        with transaction(self.path, write=True) as db:
            # A crash on the last attempt or a final unacknowledged submission
            # must reach a terminal state once its lease/ack deadline expires.
            stamp = time.time()
            db.execute('''UPDATE deliveries SET state='failed',lease_token=NULL,lease_until=NULL,
                last_error=COALESCE(last_error,'Delivery attempt budget exhausted without acknowledgement')
                WHERE attempts>=8 AND state IN ('pending','retry','sending','submitted')
                AND next_attempt<=? AND (lease_until IS NULL OR lease_until<?)''', (stamp, stamp))
            row = db.execute('''SELECT d.*,a.runtime,a.target,a.endpoint,m.body,m.sequence FROM deliveries d
                JOIN agents a ON a.run_id=d.run_id AND a.id=d.recipient
                JOIN messages m ON m.id=d.message_id WHERE a.runtime<>'manual'
                AND d.state IN ('pending','retry','sending','submitted') AND d.attempts<8 AND d.next_attempt<=?
                AND (d.lease_until IS NULL OR d.lease_until<?) ORDER BY m.sequence LIMIT 1''',
                (time.time(), time.time())).fetchone()
            if row is None:
                return None
            token = uid()
            db.execute("UPDATE deliveries SET state='sending',lease_token=?,lease_until=?,attempts=attempts+1 WHERE message_id=? AND recipient=?",
                       (token, time.time()+ttl, row['message_id'], row['recipient']))
            return {**dict(row), 'lease_token': token}

    def finish_delivery(self, delivery, error=None):
        with transaction(self.path, write=True) as db:
            # Fencing token prevents a timed-out sender from overwriting a newer lease or ack.
            db.execute('''UPDATE deliveries SET state=?,last_error=?,submitted_at=?,lease_token=NULL,
                lease_until=NULL,next_attempt=? WHERE message_id=? AND recipient=? AND lease_token=? AND state='sending' ''',
                ('retry' if error and delivery['attempts']<7 else 'failed' if error else 'submitted', error, None if error else now(),
                 time.time()+(min(300, 2**min(delivery['attempts']+1, 8)) if error else 300),
                 delivery['message_id'], delivery['recipient'], delivery['lease_token']))
