"""Versioned, transactional local persistence. No database connection is shared."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE nodes(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('project_plan','feature','task')),
 parent_id TEXT REFERENCES nodes(id), title TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', data TEXT NOT NULL DEFAULT '{}',
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE INDEX node_parent ON nodes(parent_id,kind);
CREATE TABLE edges(
 scope_id TEXT NOT NULL REFERENCES nodes(id),
 node_id TEXT NOT NULL REFERENCES nodes(id), dependency_id TEXT NOT NULL REFERENCES nodes(id),
 PRIMARY KEY(scope_id,node_id,dependency_id), CHECK(node_id<>dependency_id));
CREATE TABLE events(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT REFERENCES nodes(id),
 kind TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE journal_entries(
 id TEXT PRIMARY KEY, node_id TEXT REFERENCES nodes(id), agent TEXT NOT NULL,
 body TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE legacy_sources(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content BLOB NOT NULL);
CREATE TABLE runs(id TEXT PRIMARY KEY, scope_id TEXT REFERENCES nodes(id), created_at TEXT NOT NULL);
CREATE TABLE agents(
 run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, role TEXT NOT NULL,
 runtime TEXT NOT NULL, target TEXT NOT NULL, endpoint TEXT NOT NULL DEFAULT '',
 heartbeat TEXT NOT NULL, PRIMARY KEY(run_id,id));
CREATE TABLE threads(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), node_id TEXT REFERENCES nodes(id),
 subject TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', resolution TEXT,
 created_at TEXT NOT NULL);
CREATE TABLE messages(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 run_id TEXT NOT NULL REFERENCES runs(id), thread_id TEXT NOT NULL REFERENCES threads(id),
 sender TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
 reply_to TEXT REFERENCES messages(id), request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(run_id,sender,request_key),
 FOREIGN KEY(run_id,sender) REFERENCES agents(run_id,id));
CREATE TABLE deliveries(
 message_id TEXT NOT NULL REFERENCES messages(id), run_id TEXT NOT NULL,
 recipient TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until REAL,
 next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT, submitted_at TEXT, acknowledged_at TEXT,
 PRIMARY KEY(message_id,recipient), FOREIGN KEY(run_id,recipient) REFERENCES agents(run_id,id));
CREATE INDEX delivery_pending ON deliveries(state,next_attempt,lease_until);
CREATE TABLE claims(
 task_id TEXT PRIMARY KEY REFERENCES nodes(id), run_id TEXT NOT NULL,
 agent_id TEXT NOT NULL, token TEXT NOT NULL, expires_at REAL NOT NULL,
 FOREIGN KEY(run_id,agent_id) REFERENCES agents(run_id,id));
CREATE TABLE search_documents(
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, kind TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, content_hash TEXT NOT NULL,
 UNIQUE(source_id,kind));
CREATE VIRTUAL TABLE documents_fts USING fts5(title,body,content='search_documents',content_rowid='id');
CREATE TRIGGER search_insert AFTER INSERT ON search_documents BEGIN
 INSERT INTO documents_fts(rowid,title,body) VALUES(new.id,new.title,new.body); END;
CREATE TRIGGER search_delete AFTER DELETE ON search_documents BEGIN
 INSERT INTO documents_fts(documents_fts,rowid,title,body) VALUES('delete',old.id,old.title,old.body); END;
CREATE TRIGGER search_update AFTER UPDATE ON search_documents BEGIN
 INSERT INTO documents_fts(documents_fts,rowid,title,body) VALUES('delete',old.id,old.title,old.body);
 INSERT INTO documents_fts(rowid,title,body) VALUES(new.id,new.title,new.body); END;
CREATE TABLE embedding_spaces(id TEXT PRIMARY KEY, model TEXT NOT NULL, dimensions INTEGER NOT NULL,
 pipeline TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE embedding_chunks(space_id TEXT NOT NULL REFERENCES embedding_spaces(id),
 row_id INTEGER NOT NULL, document_id INTEGER NOT NULL REFERENCES search_documents(id),
 content_hash TEXT NOT NULL, chunk_text TEXT NOT NULL, PRIMARY KEY(space_id,row_id));
"""


# Preserve schema-1 SQL for upgrade fixtures; existing databases are never
# upgraded by initialize(). Only a fresh database receives the current schema.
BASE_SCHEMA = SCHEMA
from .workflows.schema import WORKFLOW_SCHEMA
SCHEMA += WORKFLOW_SCHEMA


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def uid() -> str:
    return str(uuid.uuid4())


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db


@contextmanager
def transaction(path: Path, *, write: bool = False):
    db = connect(path)
    try:
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError('Database is newer than this SPOQ installation; upgrade SPOQ.')
        if version == 0:
            # executescript starts its own transaction; serialize schema creation.
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA +
                                 f'\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')
            except sqlite3.OperationalError:
                db.rollback()
                if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                    raise
    finally:
        db.close()


def index_document(db, source_id: str, kind: str, title: str, body: str):
    digest = hashlib.sha256((title + '\n' + body).encode()).hexdigest()
    db.execute('''INSERT INTO search_documents(source_id,kind,title,body,content_hash)
        VALUES(?,?,?,?,?) ON CONFLICT(source_id,kind) DO UPDATE SET
        title=excluded.title,body=excluded.body,content_hash=excluded.content_hash''',
        (source_id, kind, title, body, digest))


def event(db, node_id, kind, actor, payload):
    db.execute('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
               (node_id, kind, actor, encode(payload), now()))
