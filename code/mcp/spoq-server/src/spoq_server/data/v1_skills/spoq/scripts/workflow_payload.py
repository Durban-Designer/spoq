"""Build truthful workflow payloads and compare actual reviewed files; stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

IDENTITIES = ('run_id', 'scope_id', 'phase_id', 'attempt_id', 'definition_hash',
              'specification_hash', 'artifact_hashes')


def decode(content):
    if len(content.encode()) > 1024 * 1024:
        raise ValueError('JSON input exceeds one MiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def finite(value):
        raise ValueError('JSON numbers must be finite: ' + value)
    return json.loads(content, object_pairs_hook=unique, parse_constant=finite)


def load(path):
    with Path(path).open('rb') as handle:
        content = handle.read(1024 * 1024 + 1)
    value = decode(content.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def within(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Reviewed files must be inside the explicit workspace')
    if not path.is_file():
        raise ValueError('Reviewed file does not exist: ' + str(value))
    return path


def work_output(envelope, root, names, journals, kind='implementation', current_spec=False):
    if kind not in envelope.get('expected_outputs', []):
        raise ValueError('Output kind is not declared by this invocation')
    if not isinstance(names, list) or len(names) > 500 or kind == 'implementation' and not names:
        raise ValueError('Implementation needs actual reviewed files (at most 500 per manifest)')
    root = Path(root).resolve()
    paths = [within(root, name) for name in names]
    specification = envelope.get('current_specification_hash') if current_spec else envelope.get('specification_hash')
    if not isinstance(specification, str) or not specification:
        raise ValueError('A current invocation specification hash is required')
    content = {'scope_id': envelope['scope_id'], 'specification_hash': specification,
               'reviewed_files': {path.relative_to(root).as_posix(): digest(path) for path in paths},
               'validation_journal_ids': journals}
    return {kind: {'content': content, 'source': 'agent'}}


def build_evidence(envelope, observation, current_spec=False):
    if not all(name in envelope for name in IDENTITIES):
        raise ValueError('Invocation is missing identity/hash fields')
    for name in ('reviewer', 'checks_passed', 'observed_checks', 'acceptance_results'):
        if name not in observation:
            raise ValueError('Missing actual observation: ' + name)
    if type(observation['checks_passed']) is not bool:
        raise ValueError('checks_passed must be an explicit boolean')
    if not isinstance(observation['observed_checks'], list) or not observation['observed_checks']:
        raise ValueError('Actual observed checks are required')
    if not isinstance(observation['acceptance_results'], list) or not observation['acceptance_results']:
        raise ValueError('Actual acceptance results are required')
    result = {**observation, **{name: envelope[name] for name in IDENTITIES}}
    if current_spec:
        if not envelope.get('current_specification_hash'):
            raise ValueError('Missing current specification hash for explicit refresh')
        result['specification_hash'] = envelope['current_specification_hash']
    return result


def check_files(artifact, root):
    if 'implementation' in artifact:
        artifact = artifact['implementation']
    if 'content' in artifact:
        artifact = artifact['content']
        if isinstance(artifact, str):
            artifact = decode(artifact)
    if not isinstance(artifact, dict):
        raise ValueError('Expected implementation artifact content')
    files = artifact.get('reviewed_files')
    if not isinstance(files, dict) or not files or len(files) > 500:
        raise ValueError('No bounded reviewed_files manifest; validation cannot be reused')
    root = Path(root).resolve()
    changed = []
    for name, expected in files.items():
        try:
            path = within(root, name)
            if not isinstance(expected, str) or digest(path) != expected:
                changed.append(name)
        except (ValueError, OSError):
            changed.append(name)
    return {'matches': not changed, 'changed_or_missing': changed,
            'checked_files': len(files), 'scope_id': artifact.get('scope_id'),
            'specification_hash': artifact.get('specification_hash'),
            'note': 'File equality alone does not establish matching scope, passing checks or review provenance.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    evidence = commands.add_parser('evidence')
    evidence.add_argument('envelope');evidence.add_argument('observations');evidence.add_argument('--current-spec', action='store_true');evidence.add_argument('--output', required=True)
    output = commands.add_parser('work-output')
    output.add_argument('envelope');output.add_argument('--root', required=True);output.add_argument('--files', nargs='*', default=[]);output.add_argument('--journals', nargs='*', default=[]);output.add_argument('--kind', choices=['project_plan', 'implementation'], default='implementation');output.add_argument('--current-spec', action='store_true');output.add_argument('--output', required=True)
    compare = commands.add_parser('check-files')
    compare.add_argument('artifact');compare.add_argument('--root', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'evidence':
            value = build_evidence(load(args.envelope), load(args.observations), args.current_spec)
        elif args.action == 'work-output':
            value = work_output(load(args.envelope), args.root, args.files, args.journals, args.kind, args.current_spec)
        else:
            value = check_files(load(args.artifact), args.root)
            print(json.dumps(value))
            return 0 if value['matches'] else 1
        Path(args.output).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
