"""Schema changes must not publish partial state or discard the 1.0 store."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from spoq_server.v1.db import BASE_SCHEMA, initialize, connect
from spoq_server.v1.store import Store
from spoq_server.v1.workflows import schema


def old_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(BASE_SCHEMA + ';PRAGMA user_version=1;')
    store = Store(path)
    store.create('project_plan', 'plan', 'Preserved plan')
    store.journal('Preserve board, claims and journal data', node_id='plan')
    return store


def test_diagnosis_is_read_only_and_old_store_stays_usable(tmp_path):
    path = tmp_path / 'missing' / 'spoq.db'
    assert not schema.schema_status(path)['database_exists']
    assert not path.parent.exists()
    store = old_database(path)
    before = path.read_bytes()
    preview = schema.upgrade(path)
    assert preview['from_version'] == 1 and preview['to_version'] == 2
    assert preview['upgrade_required'] and preview['confirmation_required'] and not preview['upgraded']
    assert preview['backup_directory'] == str(path.parent / 'backups')
    assert path.read_bytes() == before and not (path.parent / 'backups').exists()
    assert Store(path).get('plan')['title'] == 'Preserved plan'
    with pytest.raises(ValueError, match='confirm'):
        schema.require_workflow_schema(path)


def test_atomic_upgrade_and_consistent_backup_restore(tmp_path):
    path = tmp_path / 'one' / 'spoq.db'
    store = old_database(path)
    before = store.snapshot()
    result = schema.upgrade(path, confirmed=True)
    assert result['upgraded'] and result['from_version'] == 1
    schema.require_workflow_schema(path)
    assert Store(path).get('plan')['title'] == 'Preserved plan'
    with closing(connect(path)) as db, db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert set(schema.WORKFLOW_TABLES) <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    backup = Path(result['backup'])
    with closing(sqlite3.connect(backup)) as db, db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    restored = tmp_path / 'recovered' / 'spoq.db'
    assert not schema.restore_backup(backup, restored)['restored']
    assert not restored.exists()
    assert schema.restore_backup(backup, restored, confirmed=True)['restored']
    assert Store(restored).snapshot() == before
    with pytest.raises(ValueError, match='clean destination'):
        schema.restore_backup(backup, restored, confirmed=True)
    assert not schema.upgrade(path, confirmed=True)['upgraded']


def test_failed_ddl_leaves_original_schema_usable(tmp_path, monkeypatch):
    path = tmp_path / 'spoq.db'
    store = old_database(path)
    before = store.snapshot()
    original = schema.apply_workflow_schema
    def fail(db):
        original(db)
        raise RuntimeError('injected failure before version commit')
    monkeypatch.setattr(schema, 'apply_workflow_schema', fail)
    with pytest.raises(RuntimeError, match='injected'):
        schema.upgrade(path, confirmed=True)
    assert schema.schema_status(path)['from_version'] == 1
    assert Store(path).snapshot() == before
    with closing(sqlite3.connect(path)) as db, db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_runs'").fetchone()


def test_killed_process_rolls_back_ddl(tmp_path):
    path = tmp_path / 'spoq.db'
    store = old_database(path)
    code = '''import os,sys
from pathlib import Path
from spoq_server.v1.workflows import schema
def die(db):
 db.execute('CREATE TABLE partial_upgrade(id INTEGER)')
 os._exit(74)
schema.apply_workflow_schema=die
schema.upgrade(Path(sys.argv[1]),confirmed=True)
'''
    p = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, text=True, timeout=20)
    assert p.returncode == 74, p.stderr
    assert schema.schema_status(path)['from_version'] == 1
    assert Store(path).get('plan')['title'] == 'Preserved plan'
    with closing(sqlite3.connect(path)) as db, db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='partial_upgrade'").fetchone()
    assert schema.upgrade(path, confirmed=True)['upgraded']


def test_concurrent_open_or_upgrade_never_sees_partial_schema(tmp_path):
    path = tmp_path / 'spoq.db'
    old_database(path)
    def run(n):
        try:
            if n % 2:
                Store(path).get('plan')
            else:
                schema.upgrade(path, confirmed=True)
            return 'ok'
        except ValueError as exc:
            assert 'Another process' in str(exc)
            return 'locked'
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(run, range(12)))
    assert 'ok' in outcomes
    schema.require_workflow_schema(path)
    with closing(connect(path)) as db, db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_fresh_schema_and_future_binary_guard(tmp_path):
    path = tmp_path / 'fresh.db'
    initialize(path)
    schema.require_workflow_schema(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA user_version=3')
    with pytest.raises(ValueError, match='newer'):
        Store(path)
    with pytest.raises(ValueError, match='newer'):
        schema.schema_status(path)


def test_restore_rejects_corrupt_or_unsupported_backup(tmp_path):
    backup = tmp_path / 'bad.db'
    backup.write_bytes(b'not sqlite')
    with pytest.raises(sqlite3.DatabaseError):
        schema.restore_backup(backup, tmp_path / 'restored.db', confirmed=True)
    backup.unlink()
    with closing(sqlite3.connect(backup)) as db, db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError, match='Unsupported'):
        schema.restore_backup(backup, tmp_path / 'restored.db', confirmed=True)


def test_actual_v1_initializer_rejects_new_schema(tmp_path):
    # Frozen 1.0 db module from the repository's pre-1.1 release, not a simulated
    # version check. No installed-package/network dependency in this regression.
    import importlib.util
    source = Path(__file__).parents[1] / 'fixtures' / 'v1_0_db.py'
    spec = importlib.util.spec_from_file_location('spoq_1_0_db', source)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    path = tmp_path / 'spoq.db'
    old.initialize(path)
    assert schema.schema_status(path)['from_version'] == 1
    assert schema.upgrade(path, confirmed=True)['upgraded']
    with pytest.raises(ValueError, match='newer'):
        old.initialize(path)
