"""Explicit, backed-up upgrades for local workflow persistence.

Schema diagnosis opens a read-only connection. Existing schema-1 databases remain
usable by the 1.0 APIs until the owner explicitly upgrades. SQLite's backup API,
not a copy of a potentially live WAL file, captures the pre-upgrade database.
https://www.sqlite.org/backup.html
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

VERSION = 2
WORKFLOW_TABLES = ('workflow_definitions', 'workflow_runs', 'workflow_attempts',
                   'workflow_artifacts', 'workflow_decisions', 'workflow_receipts')
WORKFLOW_SCHEMA = """
CREATE TABLE workflow_definitions(
 hash TEXT PRIMARY KEY, id TEXT NOT NULL, version TEXT NOT NULL,
 definition TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE workflow_runs(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), scope_id TEXT NOT NULL REFERENCES nodes(id),
 definition_hash TEXT NOT NULL REFERENCES workflow_definitions(hash),
 routing TEXT NOT NULL, specification_hash TEXT NOT NULL, state TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','waiting_human','passed','failed','blocked','paused')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE workflow_attempts(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
 phase_id TEXT NOT NULL, number INTEGER NOT NULL CHECK(number>=1),
 status TEXT NOT NULL CHECK(status IN ('queued','running','waiting_human','passed','failed','skipped','blocked','paused')),
 owner TEXT NOT NULL, token TEXT NOT NULL, lease_until REAL NOT NULL CHECK(lease_until>=0),
 specification_hash TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(run_id,phase_id,number));
CREATE UNIQUE INDEX workflow_attempt_active ON workflow_attempts(run_id,phase_id)
 WHERE status IN ('running','waiting_human');
CREATE TABLE workflow_artifacts(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
 attempt_id TEXT NOT NULL REFERENCES workflow_attempts(id), scope_id TEXT NOT NULL REFERENCES nodes(id),
 kind TEXT NOT NULL, author TEXT NOT NULL, source TEXT NOT NULL,
 content TEXT NOT NULL, sha256 TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX workflow_artifact_run ON workflow_artifacts(run_id,created_at,id);
CREATE TABLE workflow_decisions(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
 attempt_id TEXT NOT NULL REFERENCES workflow_attempts(id), artifact_id TEXT NOT NULL REFERENCES workflow_artifacts(id),
 artifact_hash TEXT NOT NULL, specification_hash TEXT NOT NULL, definition_hash TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='user'), author TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('approve','reject')), reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX workflow_decision_run ON workflow_decisions(run_id,created_at,id);
CREATE TABLE workflow_receipts(
 run_id TEXT NOT NULL REFERENCES workflow_runs(run_id), key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,key));
"""


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)


def schema_status(path: Path) -> dict:
    path = Path(path).resolve()
    exists = path.is_file()
    version = 0
    if exists:
        with closing(readonly(path)) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > VERSION:
        raise ValueError('Database is newer than this SPOQ installation; upgrade SPOQ.')
    return {'database': str(path), 'database_exists': exists, 'from_version': version,
            'to_version': VERSION, 'upgrade_required': exists and version == 1,
            'confirmation_required': exists and version == 1,
            'backup_directory': str(path.parent / 'backups'),
            'restore_policy': 'Stop clients and restore the backup into a clean destination; old binaries reject schema 2.'}


def require_workflow_schema(path: Path) -> None:
    report = schema_status(path)
    if report['from_version'] != VERSION:
        raise ValueError('Workflow storage requires schema 2. Preview and confirm `spoq workflow upgrade` first.')


def apply_workflow_schema(db: sqlite3.Connection) -> None:
    # No executescript: it commits an existing transaction before executing DDL.
    for statement in WORKFLOW_SCHEMA.split(';'):
        if statement.strip():
            db.execute(statement)


def upgrade(path: Path, *, confirmed: bool = False) -> dict:
    from ..db import connect, now, uid
    from ..locking import migration_lock
    path = Path(path).resolve()
    report = schema_status(path)
    if not confirmed or not report['upgrade_required']:
        return {**report, 'upgraded': False}
    with migration_lock(path.parent / 'schema-upgrade.lock'):
        db = connect(path)
        backup_path = None
        try:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version == VERSION:
                db.rollback()
                return {**schema_status(path), 'upgraded': False}
            if version != 1:
                raise ValueError('Only schema 1 can be upgraded to schema 2')
            backup_path = path.parent / 'backups' / ('schema-1-to-2-' + uid() + '.sqlite3')
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            # The writer transaction prevents another writer from committing between
            # this committed read snapshot and schema publication. It performs no
            # writes until backup finishes, so the separate read handle is safe.
            source = readonly(path)
            target = sqlite3.connect(backup_path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            apply_workflow_schema(db)
            db.execute(f'PRAGMA user_version={VERSION}')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Foreign-key integrity check failed during upgrade')
            db.execute('INSERT INTO meta(key,value) VALUES(?,?)',
                       ('schema-2-upgrade', now()))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    return {**schema_status(path), 'from_version': 1, 'upgraded': True, 'backup': str(backup_path)}


def restore_backup(backup: Path, destination: Path, *, confirmed: bool = False) -> dict:
    """Publish a verified restored DB without overwriting a live/occupied target."""
    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    if not backup.is_file():
        raise ValueError('Backup does not exist')
    if destination.exists() or any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm')):
        raise ValueError('Restoration requires a clean destination; stop clients and preserve the old database first')
    with closing(readonly(backup)) as source:
        if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or source.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup integrity check failed')
        version = source.execute('PRAGMA user_version').fetchone()[0]
        if version not in (1, VERSION):
            raise ValueError('Unsupported backup schema')
        result = {'backup': str(backup), 'destination': str(destination), 'schema_version': version,
                  'confirmation_required': not confirmed, 'restored': False}
        if not confirmed:
            return result
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.spoq-restore-', dir=destination.parent)
        os.close(descriptor)
        stage = Path(temporary)
        try:
            target = sqlite3.connect(stage)
            try:
                source.backup(target)
            finally:
                target.close()
            with stage.open('rb') as file:
                os.fsync(file.fileno())
            os.link(stage, destination)  # Atomic publication, never replacement.
        finally:
            stage.unlink(missing_ok=True)
            for suffix in ('-wal', '-shm'):
                Path(str(stage) + suffix).unlink(missing_ok=True)
    return {**result, 'confirmation_required': False, 'restored': True}
