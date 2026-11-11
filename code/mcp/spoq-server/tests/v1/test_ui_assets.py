"""Production asset provenance, failure protection and actual Node-free HTTP startup."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
from urllib.request import urlopen
import zipfile

import pytest

from spoq_server import __version__
from spoq_server.v1.workflows.viewer import load_assets

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / 'code/scripts/build-spoq-ui.py'


@pytest.fixture
def builder():
    if not SCRIPT.is_file():
        pytest.skip('Contributor builder is outside the installed package')
    spec = importlib.util.spec_from_file_location('spoq_ui_builder', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def frontend(tmp_path, builder):
    path = tmp_path / 'frontend'
    for filename in builder.BUILD_FILES:
        file = path / filename
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('{}')
    (path / 'package.json').write_text(json.dumps({'version': __version__}))
    (path / 'src').mkdir()
    (path / 'src/main.ts').write_text('const local = true;')
    (path / 'public').mkdir()
    (path / 'public/icon.svg').write_text('<svg/>')
    dist = path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<!doctype html><title>Fixture UI</title>')
    (dist / 'app.js').write_text('console.log("fixture");')
    info = {'format': 'spoq-ui-build-1', 'version': __version__, **builder.production_fingerprint(path)}
    (dist / 'build-info.json').write_text(json.dumps(info))
    return path


def test_bundle_and_verification_match_production_source_stamp(frontend, builder, tmp_path):
    destination = tmp_path / 'managed-ui'
    result = builder.bundle(frontend, destination, __version__)
    assert result['verified'] and result['assets'] == 3
    assert builder.verify_assets(destination, __version__, frontend) == result
    assert set(json.loads((destination / 'manifest.json').read_text())) == {'format', 'version', 'files'}
    assert 'manifest.json' not in json.loads((destination / 'manifest.json').read_text())['files']


@pytest.mark.parametrize('change', ['source', 'missing-dist', 'version', 'env', 'symlink'])
def test_stale_or_unsafe_build_cannot_replace_existing_assets(frontend, builder, tmp_path, change):
    destination = tmp_path / 'managed-ui'
    builder.bundle(frontend, destination, __version__)
    before = {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    if change == 'source':
        (frontend / 'src/main.ts').write_text('const changed = true;')
    elif change == 'missing-dist':
        (frontend / 'dist/build-info.json').unlink()
    elif change == 'version':
        info = json.loads((frontend / 'dist/build-info.json').read_text())
        info['version'] = '0.0.0'
        (frontend / 'dist/build-info.json').write_text(json.dumps(info))
    elif change == 'env':
        (frontend / '.env.local').write_text('PRIVATE=fixture')
    else:
        (frontend / 'src/main.ts').unlink()
        (frontend / 'src/main.ts').symlink_to(frontend / 'package.json')
    with pytest.raises((ValueError, OSError)):
        builder.bundle(frontend, destination, __version__)
    assert {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob('*') if p.is_file()} == before


def test_test_additions_and_unrelated_root_files_do_not_stale_production_build(frontend, builder, tmp_path):
    destination = tmp_path / 'managed-ui'
    builder.bundle(frontend, destination, __version__)
    (frontend / 'src/later.test.tsx').write_text('test-only fixture')
    (frontend / 'tests/e2e').mkdir(parents=True)
    (frontend / 'tests/e2e/later.test.ts').write_text('downstream verification')
    (frontend / 'private-review-notes.txt').write_text('not a production build input')
    assert builder.verify_assets(destination, __version__, frontend)['verified']
    assert not any('private' in name or '/tests/' in name or '.test.' in name for name in builder.production_fingerprint(frontend)['files'])


def node_fingerprint(frontend):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed only to verify the contributor fingerprint parity')
    module = (ROOT / 'code/apps/spoq-ui/scripts/source-hash.mjs').as_uri()
    script = f'import {{sourceFingerprint}} from {json.dumps(module)}; console.log(JSON.stringify(sourceFingerprint(process.argv[1])));'
    return subprocess.run([node, '--input-type=module', '-e', script, str(frontend)],
                          capture_output=True, text=True, timeout=10)


def test_python_and_node_fingerprint_the_same_production_inputs(frontend, builder):
    (frontend / 'src/__tests__').mkdir()
    (frontend / 'src/__tests__/ignored.ts').write_text('test-only input')
    result = node_fingerprint(frontend)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == builder.production_fingerprint(frontend)


@pytest.mark.parametrize('backend', ['python', 'node'])
@pytest.mark.parametrize('target', ['', 'src', 'public', 'package.json', 'scripts', 'scripts/source-hash.mjs'])
def test_linked_input_roots_files_and_parents_cannot_stamp_outside_data(frontend, builder, tmp_path, backend, target):
    path = frontend / target
    outside = tmp_path / 'outside'
    path.rename(outside)
    if outside.is_dir():
        (outside / 'private.ts').write_text('outside sentinel must never be stamped')
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    stamp = (frontend / 'dist/build-info.json').read_bytes()
    if backend == 'python':
        with pytest.raises(ValueError, match='symbolic links'):
            builder.production_fingerprint(frontend)
    else:
        result = node_fingerprint(frontend)
        assert result.returncode != 0
        assert 'symbolic links' in result.stderr
        assert not result.stdout
    assert (frontend / 'dist/build-info.json').read_bytes() == stamp


@pytest.mark.parametrize('backend', ['python', 'node'])
@pytest.mark.parametrize('target', ['index.html', 'src'])
def test_build_inputs_have_the_declared_regular_file_or_directory_type(frontend, builder, backend, target):
    path = frontend / target
    if path.is_dir():
        shutil.rmtree(path)
        path.write_text('directory replaced by file')
    else:
        path.unlink()
        path.mkdir()
    if backend == 'python':
        with pytest.raises(ValueError, match='unsafe type'):
            builder.production_fingerprint(frontend)
    else:
        result = node_fingerprint(frontend)
        assert result.returncode != 0
        assert 'unsafe type' in result.stderr


@pytest.mark.parametrize('change', ['hash', 'missing', 'extra', 'path', 'windows-path', 'self-hash', 'invalid-digest'])
def test_manifest_corruption_is_rejected(frontend, builder, tmp_path, change):
    destination = tmp_path / 'managed-ui'
    builder.bundle(frontend, destination, __version__)
    path = destination / 'manifest.json'
    manifest = json.loads(path.read_text())
    if change == 'hash':
        (destination / 'app.js').write_text('changed')
    elif change == 'missing':
        (destination / 'app.js').unlink()
    elif change == 'extra':
        (destination / 'undeclared.txt').write_text('unexpected')
    elif change == 'path':
        manifest['files']['../outside.txt'] = 'a' * 64
    elif change == 'windows-path':
        manifest['files']['C:/outside.txt'] = 'a' * 64
    elif change == 'self-hash':
        manifest['files']['manifest.json'] = 'a' * 64
    else:
        manifest['files']['app.js'] = 'not-a-digest'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        builder.verify_assets(destination, __version__, frontend)


def test_actual_packaged_ui_has_verified_local_assets_and_no_test_data():
    root, manifest = load_assets()
    assert manifest['version'] == __version__ == '1.1.0'
    assert {'index.html', 'build-info.json', 'licenses.txt', 'spoq.svg'} <= manifest['files'].keys()
    html = (root / 'index.html').read_text()
    assert 'https://' not in html and 'http://' not in html
    for name in manifest['files']:
        if name.endswith('.js'):
            content = (root / name).read_text()
            assert 'fixture-worker' not in content and '/example/project' not in content
    info = json.loads((root / 'build-info.json').read_text())
    assert not any('.test.' in name or name.startswith('tests/') for name in info['files'])


def test_actual_wheel_and_sdist_include_the_exact_same_verified_asset_set():
    base = ROOT / 'code/mcp/spoq-server/dist'
    wheels = list(base.rglob(f'spoq-{__version__}-*.whl'))
    sdists = list(base.rglob(f'spoq-{__version__}.tar.gz'))
    if not wheels or not sdists:
        pytest.skip('Distribution pair is checked in the artifact release job')
    wheel, sdist = max(wheels, key=lambda p: p.stat().st_mtime), max(sdists, key=lambda p: p.stat().st_mtime)
    needle = 'spoq_server/data/ui/'
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = {name.split(needle, 1)[1]: archive.read(name) for name in archive.namelist() if needle in name and not name.endswith('/')}
    with tarfile.open(sdist) as archive:
        sdist_files = {member.name.split(needle, 1)[1]: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile() and needle in member.name}
    root, manifest = load_assets()
    expected = {name: (root / name).read_bytes() for name in [*manifest['files'], 'manifest.json']}
    assert wheel_files == sdist_files == expected


def test_real_cli_serves_every_packaged_asset_with_node_absent_from_path(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'SPOQ_STORE', 'SPOQ_PROJECT_ROOT', 'VIRTUAL_ENV'}}
    env['PATH'] = ''
    process = subprocess.Popen([sys.executable, '-m', 'spoq_server', 'ui', '--root', str(tmp_path), '--port', '0', '--no-open'],
                               cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    received = queue.Queue()
    reader = threading.Thread(target=lambda: received.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        line = received.get(timeout=20)
        assert line, process.stderr.read()
        launch = json.loads(line)
        assert launch['read_only'] and launch['project_root'] == str(tmp_path)
        with urlopen(launch['url'] + '/api/health', timeout=5) as response:
            assert json.load(response)['version'] == __version__
        with urlopen(launch['url'] + '/manifest.json', timeout=5) as response:
            manifest = json.load(response)
        for name, expected in manifest['files'].items():
            with urlopen(launch['url'] + '/' + name, timeout=5) as response:
                assert hashlib.sha256(response.read()).hexdigest() == expected
        with urlopen(launch['url'] + '/api/runs', timeout=5) as response:
            assert json.load(response)['runs'] == []
        assert not (tmp_path / '.spoq').exists()
    finally:
        process.terminate()
        process.communicate(timeout=10)
