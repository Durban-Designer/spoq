#!/usr/bin/env python3
"""Publish verified static UI build into Python package data; --check needs no Node.

Run npm ci/test/build in code/apps/spoq-ui first. The Vite build stamp binds only
production inputs; adding independent test cases does not invalidate built assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'code/apps/spoq-ui'
PACKAGE = ROOT / 'code/mcp/spoq-server'
DESTINATION = PACKAGE / 'src/spoq_server/data/ui'
BUILD_FILES = ('index.html', 'package.json', 'package-lock.json', 'tsconfig.json',
               'vite.config.ts', 'scripts/source-hash.mjs')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_input(frontend: Path, name: str, *, directory: bool = False):
    """Reject links in every managed path component before reading an input."""
    components = Path(name).parts
    for index in range(len(components) + 1):
        path = frontend.joinpath(*components[:index])
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError('UI build inputs cannot be symbolic links')
        is_directory = index < len(components) or directory
        if not (stat.S_ISDIR(mode) if is_directory else stat.S_ISREG(mode)):
            raise ValueError('Required production UI build input has an unsafe type')
    return path


def production_fingerprint(frontend: Path):
    build_input(frontend, '', directory=True)
    if any(frontend.glob('.env*')):
        raise ValueError('Managed UI builds do not load private .env files')
    paths = [build_input(frontend, name) for name in BUILD_FILES]
    for folder in ('src', 'public'):
        for path in build_input(frontend, folder, directory=True).rglob('*'):
            relative = path.relative_to(frontend)
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('UI build inputs cannot be symbolic links')
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError('UI build inputs must be regular files or directories')
            if path.name.startswith('.env'):
                raise ValueError('Private environment files cannot be UI assets')
            if (path.is_file() and '__tests__' not in relative.parts
                    and not re.search(r'\.test\.[^.]+$', path.name)
                    and path.name not in {'test-setup.ts', 'fixtures.test-support.ts'}):
                paths.append(path)
    files = {path.relative_to(frontend).as_posix(): digest(path) for path in sorted(paths)}
    return {'files': files, 'source_sha256': hashlib.sha256(canonical(files)).hexdigest()}


def safe_file(root: Path, name: str):
    if (not isinstance(name, str) or not name or '\\' in name or '\x00' in name
            or ':' in name or PurePosixPath(name).is_absolute() or any(p in {'', '.', '..'} for p in name.split('/'))):
        raise ValueError('Invalid managed asset path')
    path = root / name
    candidate = path
    while candidate != root:
        if candidate.is_symlink():
            raise ValueError('Managed assets cannot be symbolic links')
        candidate = candidate.parent
    if root.is_symlink():
        raise ValueError('Managed assets cannot be symbolic links')
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Managed asset is missing or outside its package')
    return path


def verify_build_info(directory: Path, version: str, frontend: Path | None):
    info = json.loads(safe_file(directory, 'build-info.json').read_text())
    if not isinstance(info, dict) or info.get('format') != 'spoq-ui-build-1' or info.get('version') != version:
        raise ValueError('UI build stamp version is stale')
    if frontend is not None:
        current = production_fingerprint(frontend)
        if info.get('files') != current['files'] or info.get('source_sha256') != current['source_sha256']:
            raise ValueError('UI production inputs changed; run the frontend build before packaging')
    return info


def verify_assets(destination: Path, version: str, frontend: Path | None = None):
    manifest = json.loads(safe_file(destination, 'manifest.json').read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {'format', 'version', 'files'}
            or manifest['format'] != 'spoq-ui-assets-1' or manifest['version'] != version
            or not isinstance(manifest['files'], dict) or 'index.html' not in manifest['files']
            or 'manifest.json' in manifest['files']):
        raise ValueError('Invalid UI asset manifest/version')
    for name, expected in manifest['files'].items():
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Invalid UI asset digest')
        if digest(safe_file(destination, name)) != expected:
            raise ValueError('UI asset hash mismatch: ' + name)
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob('*') if path.is_file()}
    if actual != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('UI package has undeclared or missing assets')
    info = verify_build_info(destination, version, frontend)
    return {'verified': True, 'version': version, 'assets': len(manifest['files']),
            'source_sha256': info['source_sha256']}


def bundle(frontend: Path, destination: Path, version: str):
    distribution = frontend / 'dist'
    verify_build_info(distribution, version, frontend)
    if json.loads((frontend / 'package.json').read_text())['version'] != version:
        raise ValueError('Python and frontend package versions differ')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.spoq-ui-build-', dir=destination.parent))
    backup = None
    try:
        files = {}
        for source in sorted(distribution.rglob('*')):
            if source.is_symlink():
                raise ValueError('UI distribution cannot contain symbolic links')
            if not source.is_file():
                continue
            name = source.relative_to(distribution).as_posix()
            if name == 'manifest.json':
                raise ValueError('Vite output cannot replace the package asset manifest')
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files[name] = digest(target)
        (staging / 'manifest.json').write_text(json.dumps({'format': 'spoq-ui-assets-1',
            'version': version, 'files': files}, indent=2, sort_keys=True) + '\n')
        result = verify_assets(staging, version, frontend)
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix='.spoq-ui-old-', dir=destination.parent))
            backup.rmdir()
            destination.rename(backup)
        try:
            staging.rename(destination)
        except BaseException:
            if backup is not None:
                backup.rename(destination)
            raise
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify current sources and packaged assets without rebuilding')
    args = parser.parse_args(argv)
    version = tomllib.loads((PACKAGE / 'pyproject.toml').read_text())['project']['version']
    try:
        result = verify_assets(DESTINATION, version, FRONTEND) if args.check else bundle(FRONTEND, DESTINATION, version)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f'UI build error: {exc}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
