"""Compile restricted control graphs; work DAG scheduling stays cycle-free.

Only failed phases may backtrack to a forward ancestor. The runner is responsible
for persisting and enforcing both finite budgets; compilation never runs skills.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from ..graph import waves
from .types import Edge, Phase, StrategyDefinition, canonical_json

KNOWN_SKILLS = frozenset({
    'spoq-plan', 'spoq-plan-validation', 'spoq-execution', 'spoq-validation',
    'spoq-discover', 'spoq-design',
})
EXTERNAL_INPUTS = frozenset({'goal', 'scope', 'routing', 'context'})


@dataclass(frozen=True)
class CompiledStrategy:
    definition: StrategyDefinition
    phases: Mapping[str, Phase]
    incoming: Mapping[str, tuple[Edge, ...]]
    outgoing: Mapping[str, tuple[Edge, ...]]
    forward_order: tuple[str, ...]
    forward_edges: tuple[Edge, ...]
    loop_edges: tuple[Edge, ...]

    def descendants(self, phase_id: str) -> tuple[str, ...]:
        """Forward descendants, excluding the phase itself, in topological order."""
        if phase_id not in self.phases:
            raise ValueError(f'Unknown phase: {phase_id}')
        found: set[str] = set()
        pending = [phase_id]
        while pending:
            current = pending.pop()
            for edge in self.outgoing[current]:
                if edge.on != 'fail' and edge.target not in found:
                    found.add(edge.target)
                    pending.append(edge.target)
        return tuple(p for p in self.forward_order if p in found)

    @property
    def forward_incoming(self) -> Mapping[str, tuple[Edge, ...]]:
        return MappingProxyType({p: tuple(e for e in edges if e.on != 'fail')
                                 for p, edges in self.incoming.items()})


def compile_definition(definition: StrategyDefinition | dict,
                       skills: Iterable[str] | None = None) -> CompiledStrategy:
    """Validate topology/contracts and return immutable deterministic indexes.

    Optional skills is an explicit caller capability whitelist, never importable
    code. Unknown names in a definition otherwise fail against bundled skills.
    """
    if isinstance(definition, dict):
        definition = StrategyDefinition.from_dict(definition)
    if not isinstance(definition, StrategyDefinition):
        raise ValueError('Expected a typed strategy or definition object')
    if skills is None:
        known = KNOWN_SKILLS
    else:
        try:
            if isinstance(skills, (str, bytes)):
                raise TypeError('Skill whitelist must contain names, not characters')
            supplied_skills = tuple(skills)
            if any(not isinstance(skill, str) for skill in supplied_skills):
                raise TypeError('Skill names must be text')
            known = frozenset(supplied_skills)
        except TypeError as exc:
            raise ValueError('Skill whitelist must be an iterable of skill names') from exc
    phases = {phase.id: phase for phase in definition.phases}
    if len(phases) != len(definition.phases):
        raise ValueError('Duplicate phase IDs')
    if definition.entry not in phases:
        raise ValueError('Entry refers to an unknown phase')
    output_owners: dict[str, str] = {}
    for phase in definition.phases:
        for output in phase.outputs:
            if output in output_owners:
                raise ValueError(f'Output name has multiple producers: {output}; qualify the output names')
            output_owners[output] = phase.id
        if phase.skill is not None and phase.skill not in known:
            raise ValueError(f'Unknown skill: {phase.skill}')
        if phase.kind != 'join' and not phase.outputs:
            raise ValueError(f'Phase {phase.id} must declare required outputs')
        if phase.kind == 'join' and (phase.config.get('join') != 'selected' or phase.skill is not None):
            raise ValueError('Joins require selected-input semantics and no executable skill')
        if phase.kind == 'human' and (not phase.inputs or phase.skill is not None):
            raise ValueError('Human phases require reviewed inputs and no executable skill')
        if phase.kind == 'gate':
            stage = phase.config.get('stage')
            if not isinstance(stage, str) or stage not in {'plan', 'implementation'}:
                raise ValueError('Gate stage must be plan or implementation')
            floor = 90 if stage == 'plan' else 80
            for key, minimum in (('minimum_average', 95), ('minimum_metric', floor)):
                value = phase.config.get(key, minimum)
                if type(value) not in (int, float) or not minimum <= value <= 100:
                    raise ValueError(f'Gate {key} cannot weaken the SPOQ threshold')
            if phase.config.get('required_checks', True) is not True:
                raise ValueError('Gates cannot disable required checks')
    incoming: dict[str, list[Edge]] = {p: [] for p in phases}
    outgoing: dict[str, list[Edge]] = {p: [] for p in phases}
    signatures: set[str] = set()
    for edge in definition.edges:
        if edge.source not in phases or edge.target not in phases:
            raise ValueError('Transition refers to an unknown phase')
        signature = canonical_json(edge.to_dict())
        if signature in signatures:
            raise ValueError('Duplicate transitions')
        signatures.add(signature)
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    forward = tuple(e for e in definition.edges if e.on != 'fail')
    loops = tuple(e for e in definition.edges if e.on == 'fail')
    dependencies = {p: [e.source for e in incoming[p] if e.on != 'fail'] for p in phases}
    if dependencies[definition.entry]:
        raise ValueError('Entry cannot have incoming forward transitions')
    try:
        order = tuple(p for wave in waves(dependencies) for p in wave)
    except ValueError as exc:
        raise ValueError('Forward control graph must be a DAG; use bounded fail backedges') from exc
    reachable = {definition.entry}
    for phase_id in order:
        if phase_id in reachable:
            reachable.update(e.target for e in outgoing[phase_id] if e.on != 'fail')
    if reachable != phases.keys():
        raise ValueError('Unreachable phases: ' + ', '.join(sorted(phases.keys() - reachable)))
    result = CompiledStrategy(definition, MappingProxyType(phases),
                              MappingProxyType({p: tuple(incoming[p]) for p in phases}),
                              MappingProxyType({p: tuple(outgoing[p]) for p in phases}),
                              order, forward, loops)
    for edge in loops:
        if edge.target != edge.source and edge.source not in result.descendants(edge.target):
            raise ValueError('Fail transitions must return to a forward ancestor')
    # An input can come from external routing context or a forward ancestor.
    for phase in definition.phases:
        ancestors = {p for p in phases if phase.id in result.descendants(p)}
        supplied = EXTERNAL_INPUTS | {output for p in ancestors for output in phases[p].outputs}
        if set(phase.inputs) - supplied:
            raise ValueError(f'Phase {phase.id} has inputs without a forward producer: '
                             + ', '.join(sorted(set(phase.inputs) - supplied)))
    return result
