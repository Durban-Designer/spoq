"""Public source keeps legacy filesystem selection explicit and fail-fast."""
import json
import os
import subprocess
import sys

import pytest

from spoq_server.config import VALID_STORES, build_store, load_config


@pytest.mark.parametrize('value', [None, 'fs', '  FS  '])
def test_filesystem_selection_uses_requested_root(monkeypatch, tmp_path, value):
    if value is None:
        monkeypatch.delenv('SPOQ_STORE', raising=False)
    else:
        monkeypatch.setenv('SPOQ_STORE', value)
    cfg = load_config()
    assert cfg.store_backend == 'fs'
    store = build_store(cfg, root=tmp_path)
    assert store.root == tmp_path
    assert store is build_store(cfg, root=tmp_path)
    assert VALID_STORES == ('fs',)


@pytest.mark.parametrize('value', ['api', 'redis', 'invalid'])
def test_unsupported_backend_rejected_without_creating_state(tmp_path, value):
    result = subprocess.run([sys.executable, '-m', 'spoq_server', 'doctor'],
                            cwd=tmp_path, env={**os.environ, 'SPOQ_STORE': value},
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert 'SPOQ_STORE must be sqlite or fs' in result.stderr
    assert not (tmp_path / '.spoq').exists()


def test_legacy_stdio_server_reports_filesystem_backend(tmp_path):
    code = '''import json
from spoq_server.server import active_backend, get_store
from spoq_server.server import spoq_ping
print(json.dumps({'backend': active_backend(), 'ping': json.loads(spoq_ping()),
                  'same': get_store() is get_store()}))'''
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env={**os.environ, 'SPOQ_STORE': 'fs', 'SPOQ_PROJECT_ROOT': str(tmp_path)},
                            text=True, capture_output=True, check=True)
    observed = json.loads(result.stdout)
    assert observed['backend'] == 'fs'
    assert observed['same']
    assert observed['ping']['status'] == 'ok'
