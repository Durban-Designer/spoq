"""Release payload, version provenance and generic-runtime dependency boundaries.

Archive checks run when the built distribution pair is present. The same tests
also run against a genuinely installed package from an unrelated directory.
"""
from __future__ import annotations

import ast
from datetime import datetime
from email.parser import BytesParser
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile

from importlib.metadata import version
from importlib.resources import files
from packaging.version import Version
import pytest
import spoq_server


PACKAGE = Path(str(files('spoq_server')))
RELEASE_VERSION = spoq_server.__version__
WHEEL_NAME = f'spoq-{RELEASE_VERSION}-py3-none-any.whl'
SDIST_NAME = f'spoq-{RELEASE_VERSION}.tar.gz'
CHECKOUT = next((p for p in Path(__file__).resolve().parents
                 if (p / 'code/mcp/spoq-server/pyproject.toml').is_file()), None)
SPOQ_SKILLS = {'spoq', 'spoq-plan', 'spoq-plan-validation', 'spoq-execution',
               'spoq-validation', 'spoq-discover', 'spoq-design'}
PAYLOAD_DIRS = ('data/strategies', 'data/v1_skills', 'data/ui')
BLOCKED_IMPORTS = ('spoq_server.stores', 'spoq_server.horizon', 'horizon', 'pinpoint')


def safe_release_path(name):
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith('/') or '\\' in name or ':' in name
            or any(p in {'.', '..', '.spoq', '.venv', 'venv', 'node_modules', '__pycache__',
                         '.git', '.aws', '.ssh', 'credentials'} for p in parts)
            or any(p == '.env' or p.startswith('.env.') and p != '.env.example' for p in parts)
            or parts[-1] in {'auth.json', 'credentials.json', 'credentials.toml', 'journal.md'}
            or re.search(r'\.(?:db|sqlite|sqlite3|pyc|pem)(?:-(?:wal|shm|journal))?$', parts[-1])):
        raise ValueError('Private, generated or unsafe distribution path: ' + name)


def archive_files(path):
    result = {}
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                safe_release_path(member.filename)
                if member.external_attr >> 16 & 0o170000 == 0o120000:
                    raise ValueError('Distribution links are forbidden')
                result[member.filename] = archive.read(member)
    else:
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                safe_release_path(member.name)
                if not member.isfile():
                    raise ValueError('Distribution links and special files are forbidden')
                result[member.name] = archive.extractfile(member).read()
    return result


def payload(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for directory in PAYLOAD_DIRS for p in sorted((path / directory).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def find_distribution_pair(directory, *, explicit=False):
    directories = [directory] if explicit else sorted({p.parent for p in directory.rglob(WHEEL_NAME)})
    pairs = [(d / WHEEL_NAME, d / SDIST_NAME) for d in directories]
    complete = [pair for pair in pairs if all(p.is_file() for p in pair)]
    if not complete:
        if explicit:
            raise ValueError('Explicit distribution directory lacks the required wheel/sdist pair')
        return None
    # Prefer the newest complete pair, with a stable path tie-breaker. An
    # incomplete current build must not hide the existing usable pair.
    return max(complete, key=lambda pair: (min(p.stat().st_mtime_ns for p in pair), pair[0].as_posix()))


@pytest.fixture(scope='module')
def distribution_pair():
    configured = os.environ.get('SPOQ_DISTRIBUTION_DIR')
    directory = Path(configured) if configured else (CHECKOUT / 'code/mcp/spoq-server/dist' if CHECKOUT else None)
    if directory is None:
        pytest.skip('Distribution artifacts are checked by the release job, outside this installed source layout')
    try:
        pair = find_distribution_pair(directory, explicit=bool(configured))
    except ValueError as exc:
        pytest.fail(str(exc))
    if pair is None:
        pytest.skip('Build the wheel/sdist pair before running release artifact checks')
    return [(path, archive_files(path)) for path in pair]


def test_current_ci_pair_is_discovered_deterministically(tmp_path):
    for directory, timestamp in [('1.1.0', 1), ('release-ci', 3), ('incomplete', 99)]:
        parent = tmp_path / directory
        parent.mkdir()
        names = [WHEEL_NAME, SDIST_NAME]
        for name in names[:1] if directory == 'incomplete' else names:
            path = parent / name
            path.write_bytes(b'Fixture name only; no archive parsing in discovery')
            os.utime(path, ns=(timestamp, timestamp))
    expected = (tmp_path / 'release-ci' / WHEEL_NAME, tmp_path / 'release-ci' / SDIST_NAME)
    assert find_distribution_pair(tmp_path) == expected
    assert find_distribution_pair(tmp_path) == expected


def test_explicit_incomplete_distribution_pair_cannot_silently_skip(tmp_path):
    (tmp_path / WHEEL_NAME).write_bytes(b'Incomplete fixture')
    with pytest.raises(ValueError, match='required wheel/sdist pair'):
        find_distribution_pair(tmp_path, explicit=True)


def test_current_installed_package_has_all_declared_public_resources():
    assert spoq_server.__version__ == version('spoq') == RELEASE_VERSION
    actual = payload(PACKAGE)
    assert {name.split('/')[2] for name in actual
            if name.startswith('data/v1_skills/') and name.endswith('/SKILL.md')} == SPOQ_SKILLS | {'agent-collaboration'}
    for skill in SPOQ_SKILLS:
        assert f'data/v1_skills/{skill}/SKILL.md' in actual
        assert f'data/v1_skills/{skill}/agents/openai.yaml' in actual
    assert 'data/v1_skills/spoq/scripts/score_gate.py' in actual
    assert 'data/v1_skills/spoq/scripts/workflow_payload.py' in actual
    assert 'data/v1_skills/spoq/references/workflows.md' in actual
    assert 'data/v1_skills/spoq/references/runtime.md' in actual
    assert {name for name in actual if name.startswith('data/strategies/')} == {
        'data/strategies/classic.json', 'data/strategies/piqard.json', 'data/strategies/schema.json'}
    manifest = json.loads(actual['data/ui/manifest.json'])
    assert manifest['version'] == RELEASE_VERSION
    assert {name.removeprefix('data/ui/') for name in actual if name.startswith('data/ui/')} == set(manifest['files']) | {'manifest.json'}


def test_wheel_sdist_payloads_match_the_actual_installed_and_checkout_resources(distribution_pair):
    installed = payload(PACKAGE)
    for path, archive in distribution_pair:
        prefix = 'spoq_server/' if path.suffix == '.whl' else f'spoq-{RELEASE_VERSION}/src/spoq_server/'
        bundled = {name.removeprefix(prefix): body for name, body in archive.items()
                   if name.startswith(prefix) and any(name.removeprefix(prefix).startswith(d + '/') for d in PAYLOAD_DIRS)}
        assert bundled == installed
    if CHECKOUT:
        assert installed == payload(CHECKOUT / 'code/mcp/spoq-server/src/spoq_server')


def test_distribution_metadata_identifies_the_intended_release(distribution_pair):
    for path, archive in distribution_pair:
        metadata_name = f'spoq-{RELEASE_VERSION}.dist-info/METADATA' if path.suffix == '.whl' else f'spoq-{RELEASE_VERSION}/PKG-INFO'
        metadata = BytesParser().parsebytes(archive[metadata_name])
        assert metadata['Name'] == 'spoq' and metadata['Version'] == RELEASE_VERSION
        assert metadata['Requires-Python'] == '>=3.12'
        if path.suffix == '.whl':
            entry_points = next(body.decode() for name, body in archive.items()
                                if name.endswith('/entry_points.txt'))
            assert 'spoq = spoq_server.cli:main' in entry_points


def test_built_metadata_links_to_the_public_curated_repository(distribution_pair):
    for path, archive in distribution_pair:
        name = (f'spoq-{RELEASE_VERSION}.dist-info/METADATA' if path.suffix == '.whl'
                else f'spoq-{RELEASE_VERSION}/PKG-INFO')
        metadata = BytesParser().parsebytes(archive[name])
        urls = dict(value.split(', ', 1) for value in metadata.get_all('Project-URL', []))
        assert urls['Repository'] == 'https://github.com/Durban-Designer/spoq'
        assert not any('gitlab.com' in value for value in metadata.get_all('Project-URL', []))


@pytest.mark.parametrize('name', ['../secret', '/private/key', 'spoq_server/.spoq/spoq.db',
                                 'node_modules/private/index.js', 'data/auth.json',
                                 '.aws/credentials', '.env.production', 'data/private.pem',
                                 'data/session.sqlite-wal', 'data/__pycache__/module.pyc'])
def test_distribution_guard_rejects_private_generated_and_escaped_paths(name):
    with pytest.raises(ValueError):
        safe_release_path(name)


def test_distribution_guard_allows_public_templates_and_resources():
    for name in ('src/spoq_server/data/strategies/piqard.json', 'tests/fixtures/public-sample.json',
                 'src/spoq_server/data/v1_skills/spoq/SKILL.md', '.env.example'):
        safe_release_path(name)


def imported_modules(source, package):
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = '.' * node.level + (node.module or '')
            base = importlib.util.resolve_name(name, package) if node.level else name
            result.add(base)
            result.update(base + '.' + alias.name for alias in node.names if alias.name != '*')
    return result


def blocked(module):
    return any(module == prefix or module.startswith(prefix + '.') for prefix in BLOCKED_IMPORTS)


def test_relative_private_adapter_import_is_detected_structurally():
    imports = imported_modules('from ...stores.api import ApiStore\nimport horizon.client as client',
                               'spoq_server.v1.workflows')
    assert 'spoq_server.stores.api' in imports and any(blocked(name) for name in imports)
    assert not any(blocked(name) for name in imported_modules('from ..store import Store', 'spoq_server.v1.workflows'))


def test_generic_workflow_import_graph_has_no_private_adapter_dependency():
    pending = ['spoq_server.v1.workflows.' + path.stem for path in (PACKAGE / 'v1/workflows').glob('*.py')]
    visited = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        relative = module.removeprefix('spoq_server.').replace('.', '/')
        path = PACKAGE / (relative + '.py')
        package_module = False
        if not path.is_file():
            path = PACKAGE / relative / '__init__.py'
            package_module = True
        if not path.is_file():
            continue
        package = module if package_module else module.rpartition('.')[0]
        imports = imported_modules(path.read_text(), package)
        assert not any(blocked(name) for name in imports), (module, sorted(imports))
        pending.extend(name for name in imports if name.startswith('spoq_server.'))
    assert 'spoq_server.v1.store' in visited and 'spoq_server.v1.workflows.viewer' in visited


def test_isolated_generic_engine_and_viewer_work_with_private_adapters_blocked(tmp_path):
    script = '''
import importlib,importlib.abc,json,sys
from pathlib import Path
class BlockPrivate(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='spoq_server.stores' or fullname.startswith(('spoq_server.stores.','horizon','pinpoint')):
            raise ImportError('Private adapter intentionally blocked: '+fullname)
sys.meta_path.insert(0,BlockPrivate())
try:importlib.import_module('spoq_server.stores.api')
except ImportError as exc:assert 'intentionally blocked' in str(exc)
else:raise AssertionError('Private import guard did not execute')
import spoq_server
assert Path(spoq_server.__file__).resolve()==Path(sys.argv[2]).resolve()
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.definitions import get_strategy
from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.workflows.viewer import create_server
root=Path(sys.argv[1]);store=Store(root/'.spoq/spoq.db')
store.create('project_plan','generic-plan','Generic fixture plan')
store.create('feature','generic','Standalone generic fixture','generic-plan')
for name in ('classic','piqard'):assert compile_definition(get_strategy(name)).forward_order
WorkflowEngine(store).start('generic-run','generic',{'uncertainty':'low'},strategy='classic')
server=create_server(root,port=0);server.server_close()
assert not any(name=='spoq_server.stores' or name.startswith(('spoq_server.stores.','horizon','pinpoint')) for name in sys.modules)
print(json.dumps({'origin':str(Path(spoq_server.__file__).resolve()),'generic_engine_and_viewer':'passed'}))
'''
    env = {key: value for key, value in os.environ.items()
           if key not in {'PYTHONPATH', 'SPOQ_PROJECT_ROOT', 'SPOQ_STORE', 'VIRTUAL_ENV', 'HORIZON_API_TOKEN'}}
    result = subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), str(PACKAGE / '__init__.py')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['generic_engine_and_viewer'] == 'passed'


def checkout():
    if CHECKOUT is None:
        pytest.skip('Website and repository-only metadata are checked in the source checkout release job')
    return CHECKOUT


def public_ui_import(specifier, source, app):
    if specifier.startswith('.'):
        return (source.parent / specifier).resolve().is_relative_to(app.resolve())
    return specifier in {'react', 'react-dom/client', '@xyflow/react', '@xyflow/react/dist/style.css'}


def test_ui_import_guard_rejects_private_and_escaped_dependencies(tmp_path):
    source = tmp_path / 'public-app/src/App.tsx'
    app = tmp_path / 'public-app'
    assert public_ui_import('./Status', source, app)
    assert public_ui_import('react', source, app)
    assert not public_ui_import('../../private/adapter', source, app)
    assert not public_ui_import('@pinpoint/horizon', source, app)
    assert not public_ui_import('/home/private/credentials', source, app)


def test_ui_production_imports_stay_in_the_public_local_app():
    app = checkout() / 'code/apps/spoq-ui'
    examined = 0
    for path in (app / 'src').glob('*'):
        if (path.suffix not in {'.ts', '.tsx'} or '.test.' in path.name
                or path.name in {'test-setup.ts', 'fixtures.test-support.ts'}):
            continue
        examined += 1
        imports = re.findall(r'''\b(?:from\s*|import\s*(?:\(\s*)?)["']([^"']+)["']''', path.read_text())
        assert all(public_ui_import(name, path, app) for name in imports), (path.name, imports)
    assert examined > 10


def test_python_and_contributor_viewer_versions_and_locks_align():
    root = checkout()
    project = tomllib.loads((root / 'code/mcp/spoq-server/pyproject.toml').read_text())
    lock = tomllib.loads((root / 'code/mcp/spoq-server/uv.lock').read_text())
    expected = project['project']['version']
    assert expected == RELEASE_VERSION
    assert project['project']['urls']['Repository'] == 'https://github.com/Durban-Designer/spoq'
    assert next(p['version'] for p in lock['package'] if p['name'] == 'spoq') == expected
    package = json.loads((root / 'code/apps/spoq-ui/package.json').read_text())
    locked = json.loads((root / 'code/apps/spoq-ui/package-lock.json').read_text())
    assert package['version'] == locked['version'] == locked['packages']['']['version'] == expected
    assert not (root / 'code/spoq-website').exists()


def test_generated_sessions_are_ignored_without_hiding_e2e_source():
    root = checkout()
    generated = 'tests/e2e/results/spoq-1.1-viewer/session-fixture/report.json'
    ignored = subprocess.run(['git', 'check-ignore', '--no-index', generated], cwd=root, capture_output=True, text=True)
    assert ignored.returncode == 0 and ignored.stdout.strip() == generated
    source = subprocess.run(['git', 'check-ignore', '--no-index', 'tests/e2e/spoq_v11_viewer.py'],
                            cwd=root, capture_output=True, text=True)
    assert source.returncode == 1 and not source.stdout
