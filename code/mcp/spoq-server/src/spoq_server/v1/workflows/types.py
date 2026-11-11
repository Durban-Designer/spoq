"""Versioned, non-executable strategy and client contracts.

This module validates shape, not graph topology. The compiler validates reachability,
branches and gates. Definition hashing uses canonical JSON and never runtime state.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?\Z")
PHASE_KINDS = frozenset({'skill', 'gate', 'human', 'design', 'join'})


def identifier(value: Any, label: str = 'identifier') -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f'Invalid {label}: expected an ASCII identifier (1–128 characters)')
    return value


def _object(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f'Expected object with required keys {sorted(required)} and optional keys {sorted(optional)}')
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer between {minimum} and {maximum}')
    return value


def _json(value: Any) -> Any:
    try:
        # Reject NaN, Infinity, arbitrary Python objects and non-JSON config values.
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 1024 * 1024:
            raise ValueError('JSON payload exceeds one MiB')
        return json.loads(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError('Expected finite JSON data') from exc


class _FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError('Strategy definition data is immutable; create a new revision')

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_json(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class EntityId:
    """Nominal identities compare by both concrete type and value, never just text."""
    value: str
    kind: ClassVar[str] = 'entity'

    def __post_init__(self):
        identifier(self.value, self.kind + ' ID')

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class RunId(EntityId):
    kind: ClassVar[str] = 'run'


@dataclass(frozen=True)
class PhaseId(EntityId):
    kind: ClassVar[str] = 'phase'


@dataclass(frozen=True)
class AttemptId(EntityId):
    kind: ClassVar[str] = 'attempt'


@dataclass(frozen=True)
class ScopeId(EntityId):
    kind: ClassVar[str] = 'scope'


@dataclass(frozen=True)
class ArtifactId(EntityId):
    kind: ClassVar[str] = 'artifact'


@dataclass(frozen=True)
class DecisionId(EntityId):
    kind: ClassVar[str] = 'decision'


@dataclass(frozen=True)
class EventId:
    sequence: int

    def __post_init__(self):
        _integer(self.sequence, 'event sequence', 1, 2**63 - 1)


class PhaseStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    WAITING_HUMAN = 'waiting_human'
    PASSED = 'passed'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    BLOCKED = 'blocked'
    PAUSED = 'paused'


class RunStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    WAITING_HUMAN = 'waiting_human'
    PASSED = 'passed'
    FAILED = 'failed'
    BLOCKED = 'blocked'
    PAUSED = 'paused'


@dataclass(frozen=True)
class Predicate:
    """Only read pinned route inputs. Keys never select functions or Python syntax."""
    key: str
    op: str
    value: Any = None

    def __post_init__(self):
        if not isinstance(self.key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*', self.key):
            raise ValueError('Predicate key must be a dotted route-input name')
        if not isinstance(self.op, str) or self.op not in {'eq', 'ne', 'in', 'truthy'}:
            raise ValueError('Unknown predicate operator')
        if self.op == 'in' and not isinstance(self.value, list):
            raise ValueError('The in predicate requires a JSON array')
        object.__setattr__(self, 'value', _freeze(_json(self.value)))

    @classmethod
    def from_dict(cls, value: dict) -> Predicate:
        _object(value, {'key', 'op'}, {'value'})
        return cls(value['key'], value['op'], value.get('value'))

    def to_dict(self) -> dict:
        return {'key': self.key, 'op': self.op, 'value': _json(self.value)}

    def evaluate(self, inputs: dict) -> bool:
        current: Any = inputs
        for segment in self.key.split('.'):
            if not isinstance(current, dict) or segment not in current:
                return False
            current = current[segment]
        if self.op == 'truthy':
            return bool(current)
        # Definition literals are deeply frozen. Restore their JSON shape before
        # equality/membership: a frozen array tuple must still equal a JSON list.
        expected = _json(self.value)
        if self.op == 'eq':
            return current == expected
        if self.op == 'ne':
            return current != expected
        return current in expected


@dataclass(frozen=True)
class Phase:
    id: str
    kind: str
    skill: str | None
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    max_attempts: int = 3
    config: dict = field(default_factory=dict)

    def __post_init__(self):
        identifier(self.id, 'phase ID')
        if not isinstance(self.kind, str) or self.kind not in PHASE_KINDS:
            raise ValueError('Unknown phase kind')
        if self.skill is not None:
            identifier(self.skill, 'skill')
        if self.kind in {'skill', 'gate', 'design'} and not self.skill:
            raise ValueError('Executable phases require a skill')
        for label, names in (('input', self.inputs), ('output', self.outputs)):
            if not isinstance(names, (tuple, list)):
                raise ValueError(f'Phase {label}s must be an array')
            for name in names:
                identifier(name, label)
            if len(set(names)) != len(names):
                raise ValueError(f'Duplicate phase {label}')
        _integer(self.max_attempts, 'max_attempts', 1, 100)
        if not isinstance(self.config, dict):
            raise ValueError('Phase config must be an object')
        object.__setattr__(self, 'config', _freeze(_json(self.config)))
        object.__setattr__(self, 'inputs', tuple(self.inputs))
        object.__setattr__(self, 'outputs', tuple(self.outputs))

    @classmethod
    def from_dict(cls, value: dict) -> Phase:
        _object(value, {'id', 'kind', 'skill', 'inputs', 'outputs'}, {'max_attempts', 'config'})
        if not isinstance(value['inputs'], list) or not isinstance(value['outputs'], list):
            raise ValueError('Phase inputs and outputs must be arrays')
        return cls(value['id'], value['kind'], value['skill'], tuple(value['inputs']), tuple(value['outputs']),
                   value.get('max_attempts', 3), _json(value.get('config', {})))

    def to_dict(self) -> dict:
        return {'id': self.id, 'kind': self.kind, 'skill': self.skill, 'inputs': list(self.inputs),
                'outputs': list(self.outputs), 'max_attempts': self.max_attempts, 'config': _json(self.config)}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    on: str = 'pass'
    when: Predicate | None = None

    def __post_init__(self):
        identifier(self.source, 'edge source')
        identifier(self.target, 'edge target')
        if not isinstance(self.on, str) or self.on not in {'pass', 'fail', 'always'}:
            raise ValueError('Edge outcome must be pass, fail, or always')
        if self.when is not None and not isinstance(self.when, Predicate):
            raise ValueError('Edge predicate must be a Predicate')

    @classmethod
    def from_dict(cls, value: dict) -> Edge:
        _object(value, {'source', 'target'}, {'on', 'when'})
        return cls(value['source'], value['target'], value.get('on', 'pass'),
                   Predicate.from_dict(value['when']) if value.get('when') is not None else None)

    def to_dict(self) -> dict:
        return {'source': self.source, 'target': self.target, 'on': self.on,
                'when': self.when.to_dict() if self.when is not None else None}


@dataclass(frozen=True)
class StrategyDefinition:
    schema_version: int
    id: str
    version: str
    title: str
    phases: tuple[Phase, ...]
    edges: tuple[Edge, ...]
    entry: str
    max_transitions: int

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError('Unsupported strategy schema version')
        identifier(self.id, 'strategy ID')
        identifier(self.entry, 'entry phase')
        if not isinstance(self.version, str) or not VERSION.fullmatch(self.version):
            raise ValueError('Strategy version must be semantic version text')
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 500:
            raise ValueError('Strategy title is required (at most 500 characters)')
        if (not isinstance(self.phases, (tuple, list)) or not self.phases
                or len(self.phases) > 256 or any(not isinstance(p, Phase) for p in self.phases)):
            raise ValueError('Strategies require 1–256 typed phases')
        if (not isinstance(self.edges, (tuple, list)) or len(self.edges) > 2048
                or any(not isinstance(e, Edge) for e in self.edges)):
            raise ValueError('Strategies allow at most 2048 typed edges')
        _integer(self.max_transitions, 'max_transitions', 1, 10000)
        object.__setattr__(self, 'phases', tuple(self.phases))
        object.__setattr__(self, 'edges', tuple(self.edges))

    @classmethod
    def from_dict(cls, value: dict) -> StrategyDefinition:
        _object(value, {'schema_version', 'id', 'version', 'title', 'phases', 'edges', 'entry', 'max_transitions'})
        if not isinstance(value['phases'], list) or not isinstance(value['edges'], list):
            raise ValueError('Strategy phases and edges must be arrays')
        return cls(value['schema_version'], value['id'], value['version'], value['title'],
                   tuple(Phase.from_dict(v) for v in value['phases']), tuple(Edge.from_dict(v) for v in value['edges']),
                   value['entry'], value['max_transitions'])

    def to_dict(self) -> dict:
        return {'schema_version': self.schema_version, 'id': self.id, 'version': self.version, 'title': self.title,
                'phases': [p.to_dict() for p in self.phases], 'edges': [e.to_dict() for e in self.edges],
                'entry': self.entry, 'max_transitions': self.max_transitions}

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class Invocation:
    run_id: RunId
    scope_id: ScopeId
    phase_id: PhaseId
    attempt_id: AttemptId
    skill: str | None
    definition_hash: str
    specification_hash: str
    inputs: dict = field(default_factory=dict)

    def __post_init__(self):
        for name, expected in (('run_id', RunId), ('scope_id', ScopeId), ('phase_id', PhaseId), ('attempt_id', AttemptId)):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f'{name} requires {expected.__name__}')
        if self.skill is not None:
            identifier(self.skill, 'skill')
        for value in (self.definition_hash, self.specification_hash):
            if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
                raise ValueError('Definition/specification hashes must be SHA-256 hex')
        if not isinstance(self.inputs, dict):
            raise ValueError('Invocation inputs must be an object')
        _json(self.inputs)

    def to_dict(self) -> dict:
        return {'run_id': str(self.run_id), 'scope_id': str(self.scope_id), 'phase_id': str(self.phase_id),
                'attempt_id': str(self.attempt_id), 'skill': self.skill, 'definition_hash': self.definition_hash,
                'specification_hash': self.specification_hash, 'inputs': _json(self.inputs)}


@dataclass(frozen=True)
class PhaseResult:
    run_id: RunId
    phase_id: PhaseId
    attempt_id: AttemptId
    status: PhaseStatus
    outputs: dict
    evidence: dict

    def __post_init__(self):
        for name, expected in (('run_id', RunId), ('phase_id', PhaseId), ('attempt_id', AttemptId)):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f'{name} requires {expected.__name__}')
        if not isinstance(self.status, PhaseStatus):
            raise ValueError('Result status requires PhaseStatus')
        if not isinstance(self.outputs, dict) or not isinstance(self.evidence, dict):
            raise ValueError('Result outputs and evidence must be objects')
        _json(self.outputs)
        _json(self.evidence)

    def to_dict(self) -> dict:
        return {'run_id': str(self.run_id), 'phase_id': str(self.phase_id),
                'attempt_id': str(self.attempt_id), 'status': self.status.value,
                'outputs': _json(self.outputs), 'evidence': _json(self.evidence)}


def evidence_matches(evidence: dict, *, definition_hash: str, specification_hash: str,
                     artifact_hashes: dict[str, str]) -> bool:
    """Revision identity check; this does not establish a review or passing checks."""
    return (isinstance(evidence, dict) and evidence.get('definition_hash') == definition_hash
            and evidence.get('specification_hash') == specification_hash
            and evidence.get('artifact_hashes') == artifact_hashes)


def validate_viewer_snapshot(value: dict) -> dict:
    """Shape check shared by contract fixtures; runtime builds this atomically."""
    required = {'format', 'cursor', 'run', 'definition', 'phases', 'attempts', 'artifacts',
                'decisions', 'participants', 'work', 'routing', 'blockers'}
    _object(value, required, {'has_more_attempts', 'attempt_cursor'})
    if value['format'] != 'spoq-workflow-view-1':
        raise ValueError('Unsupported viewer snapshot format')
    _integer(value['cursor'], 'cursor', 0, 2**63 - 1)
    for name in ('run', 'definition', 'work', 'routing'):
        if not isinstance(value[name], dict):
            raise ValueError(f'{name} must be an object')
    for name in ('phases', 'attempts', 'artifacts', 'decisions', 'participants', 'blockers'):
        if not isinstance(value[name], list):
            raise ValueError(f'{name} must be an array')
    for phase in value['phases']:
        if not isinstance(phase, dict) or not {'id', 'status'} <= phase.keys():
            raise ValueError('Phase read models require id and status')
        identifier(phase['id'], 'phase ID')
        if phase['status'] not in PhaseStatus:
            raise ValueError('Unknown phase read-model status')
    _json(value)
    return value
