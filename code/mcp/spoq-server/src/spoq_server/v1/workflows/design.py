"""Reviewable planning/design output contracts, never an automatic proof claim.

These validators inspect supplied content/provenance. They do not run a diagram
parser, external solver, model, or verifier and record that distinction explicitly.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from .types import canonical_json

NARRATIVE_SECTIONS = ('scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria')
ALGORITHM_SECTIONS = ('inputs', 'outputs', 'invariants', 'complexity')
FORMAL_STATUSES = frozenset({'specified', 'tested', 'proven', 'disproven', 'unverified'})
SOURCE_CAPABILITIES = frozenset({'narrative_plan', 'diagram', 'erd', 'algorithm', 'formal'})


def _nonempty(value) -> bool:
    return ((isinstance(value, str) and bool(value.strip()))
            or (isinstance(value, list) and bool(value) and all(isinstance(x, str) and x.strip() for x in value)))


def _sections(text: str) -> dict[str, str]:
    """Headings inside fenced blocks cannot satisfy narrative requirements."""
    result: dict[str, str] = {}
    current = None
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence is not None:
            if marker:
                run, suffix = marker.groups()
                if run[0] == fence[0] and len(run) >= fence[1] and not suffix.strip():
                    fence = None
            continue
        if marker:
            run, suffix = marker.groups()
            # A backtick info string cannot contain another backtick.
            if run[0] != '`' or '`' not in suffix:
                fence = (run[0], len(run))
            continue
        heading = re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if heading:
            current = re.sub(r'[^a-z0-9]+', '_', heading.group(1).lower()).strip('_')
            if current in {'acceptance', 'success_criteria'}:
                current = 'acceptance_criteria'
            if current == 'complexity_assumptions':
                current = 'complexity'
            result.setdefault(current, '')
        elif current is not None:
            result[current] += line + '\n'
    return result


def _structured(content: str | dict, sections: tuple[str, ...], label: str) -> dict:
    if isinstance(content, str) and content.lstrip().startswith('{'):
        try:
            parsed = json.loads(content)
            content = parsed if isinstance(parsed, dict) else content
        except json.JSONDecodeError:
            pass
    values = content if isinstance(content, dict) else _sections(content)
    missing = [name for name in sections if not _nonempty(values.get(name))]
    if missing:
        raise ValueError(label + ' requires nonempty sections: ' + ', '.join(missing))
    return values


def _verifier(value: dict, *, successful: bool = True) -> dict:
    if not isinstance(value, dict):
        raise ValueError('Formal evidence requires recorded verifier metadata')
    for name in ('tool', 'version', 'source', 'result'):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError('Verifier requires tool, version, source and result')
    command = value.get('command')
    if not ((isinstance(command, str) and command.strip()) or
            (isinstance(command, list) and command and all(isinstance(x, str) and x for x in command))):
        raise ValueError('Verifier requires the observed command')
    if type(value.get('exit_code')) is not int or value.get('observed') is not True:
        raise ValueError('Verifier requires an observed integer exit_code')
    if successful and value['exit_code'] != 0:
        raise ValueError('Failed verifier cannot establish tested/proven evidence')
    return value


def validate_artifact(kind: str, content: str | dict, metadata: dict | None = None) -> dict:
    """Validate source contracts and return immutable-storage-ready text + metadata.

    A verified-looking source object cannot substitute for runtime gate evidence or
    a revision-bound human decision. Formal verifier reports remain caller supplied.
    """
    if not isinstance(kind, str) or kind not in SOURCE_CAPABILITIES:
        raise ValueError('Unknown design artifact kind')
    if not isinstance(content, (str, dict)):
        raise ValueError('Artifact content must be text or a JSON object')
    metadata = {} if metadata is None else json.loads(canonical_json(metadata))
    if not isinstance(metadata, dict):
        raise ValueError('Artifact metadata must be an object')
    if isinstance(content, dict):
        content = json.loads(canonical_json(content))
        text = canonical_json(content)
    else:
        text = content
    if not text.strip() or len(text.encode()) > 1024 * 1024:
        raise ValueError('Design content must be nonempty and at most one MiB')
    reference = metadata.get('confluence')
    if reference is not None:
        if not isinstance(reference, dict):
            raise ValueError('Confluence reference must be an object')
        if not isinstance(reference.get('url'), str):
            raise ValueError('Confluence URL must be text')
        parsed = urlparse(reference['url'])
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or not _nonempty(reference.get('version')):
            raise ValueError('Confluence reference requires URL and version')
        if reference.get('reviewed_export') is not True:
            raise ValueError('Confluence requires attached reviewed export content; a link alone is insufficient')
    status = 'specified'
    validation = {'contract': kind, 'source_only': True, 'external_verifier_executed': False}
    if kind == 'narrative_plan':
        _structured(content, NARRATIVE_SECTIONS, 'Narrative plan')
    elif kind in {'diagram', 'erd'}:
        if not isinstance(content, str):
            raise ValueError('Diagram/ERD must contain reviewable Mermaid text source')
        source = re.sub(r'^\s*```(?:mermaid)?\s*\n', '', content).strip()
        source = re.sub(r'\n```\s*$', '', source).strip()
        kinds = ('erDiagram',) if kind == 'erd' else (
            'flowchart', 'graph', 'sequenceDiagram', 'classDiagram', 'stateDiagram',
            'erDiagram', 'gitGraph', 'mindmap', 'timeline', 'journey', 'pie', 'C4Context')
        first = source.split('\n', 1)[0].split(' ', 1)[0]
        if first not in {*kinds, 'stateDiagram-v2'} or (kind == 'erd' and first != 'erDiagram') or '\n' not in source or not source.split('\n', 1)[1].strip():
            raise ValueError('Diagram/ERD requires a declared Mermaid type and nonempty source body')
        validation['syntax_verified'] = False
    elif kind == 'algorithm':
        _structured(content, ALGORITHM_SECTIONS, 'Algorithm specification')
    else:
        if isinstance(content, str):
            try:
                formal = json.loads(canonical_json(json.loads(content)))
            except json.JSONDecodeError as exc:
                raise ValueError('Formal evidence must be a JSON object') from exc
        else:
            formal = content
        if (not isinstance(formal, dict) or not isinstance(formal.get('status'), str)
                or formal['status'] not in FORMAL_STATUSES):
            raise ValueError('Formal status must be specified, tested, proven, disproven or unverified')
        if not _nonempty(formal.get('specification')):
            raise ValueError('Formal evidence requires a reviewable specification')
        status = formal['status']
        if status in {'tested', 'proven', 'disproven'}:
            _verifier(formal.get('verifier'), successful=status != 'disproven')
        if status == 'proven':
            if not _nonempty(formal.get('proof')) or not isinstance(formal.get('assumptions'), list):
                raise ValueError('Proven evidence requires proof content and explicit assumptions')
            if any(not isinstance(item, str) or not item.strip() for item in formal['assumptions']):
                raise ValueError('Proof assumptions must be strings')
        if status == 'disproven' and not _nonempty(formal.get('counterexample')):
            raise ValueError('Disproven evidence requires a counterexample')
        if status == 'unverified' and not _nonempty(formal.get('reason')):
            raise ValueError('Unverified evidence requires a reason')
        validation['provenance'] = 'caller_supplied_not_reexecuted'
        metadata['formal_status'] = status
    return {'kind': kind, 'content': text, 'metadata': metadata,
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'status': status,
            'validation': validation}


def capability_status(kind: str, capabilities: dict, *, required: bool = False) -> dict:
    """Distinguish unavailable required tools from optional omitted providers.

    Text/source providers are available locally. Proof requires an explicitly
    observed formal_proof capability; merely writing a specification needs none.
    """
    if not isinstance(kind, str) or not kind or not isinstance(capabilities, dict) or type(required) is not bool:
        raise ValueError('Capability name, observed mapping and boolean required flag are required')
    value = capabilities.get(kind, kind in SOURCE_CAPABILITIES)
    if isinstance(value, dict):
        value = value.get('available', False)
    if type(value) is not bool:
        raise ValueError('Capability availability must be boolean')
    if value:
        return {'status': 'ready', 'reason': 'Capability is available: ' + kind}
    return {'status': 'blocked' if required else 'skipped',
            'reason': ('Required capability unavailable: ' if required else 'Optional capability unavailable: ') + kind}
