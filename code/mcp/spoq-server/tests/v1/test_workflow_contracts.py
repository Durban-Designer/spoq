"""The strategy boundary rejects ambiguous or executable declarations."""
import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from spoq_server.v1.workflows.types import (
    ArtifactId, AttemptId, DecisionId, Edge, EventId, Invocation, Phase,
    PhaseId, PhaseResult, PhaseStatus, Predicate, RunId, ScopeId, StrategyDefinition,
)


def definition():
    return {'schema_version': 1, 'id': 'classic', 'version': '1.0.0', 'title': 'Classic SPOQ',
            'entry': 'plan', 'max_transitions': 30,
            'phases': [{'id': 'plan', 'kind': 'skill', 'skill': 'spoq-plan',
                        'inputs': ['goal'], 'outputs': ['plan'],
                        'config': {'nested': {'choices': ['a', 'b']}}}], 'edges': []}


def test_round_trip_is_canonical_and_detached():
    source = definition()
    parsed = StrategyDefinition.from_dict(source)
    digest = parsed.content_hash
    source['phases'][0]['config']['nested']['choices'].append('c')
    assert parsed.content_hash == digest
    exported = parsed.to_dict()
    exported['phases'][0]['config']['nested']['choices'].append('d')
    assert parsed.content_hash == digest
    assert StrategyDefinition.from_dict(parsed.to_dict()).content_hash == digest
    with pytest.raises(TypeError, match='immutable'):
        parsed.phases[0].config['nested']['other'] = True


@pytest.mark.parametrize('change', [
    {'schema_version': 2}, {'schema_version': True}, {'id': 'bad space'},
    {'id': '../escape'}, {'id': 'a' * 129}, {'id': 'λ'}, {'title': ''},
    {'version': 'latest'}, {'entry': 'bad space'}, {'max_transitions': 0},
    {'max_transitions': True}, {'max_transitions': 10001}, {'phases': []},
    {'shell': 'echo unsafe'}, {'phases': 'plan'}, {'edges': {}},
])
def test_invalid_strategy_shape(change):
    source = definition()
    source.update(change)
    with pytest.raises(ValueError):
        StrategyDefinition.from_dict(source)


@pytest.mark.parametrize('change', [
    {'id': 'bad phase'}, {'kind': 'python'}, {'skill': None}, {'inputs': 'goal'},
    {'outputs': 'plan'}, {'outputs': ['plan', 'plan']}, {'max_attempts': 0},
    {'max_attempts': True}, {'max_attempts': 101}, {'config': []},
    {'config': {'value': float('nan')}}, {'config': {'value': 'a' * (1024 * 1024)}},
])
def test_invalid_phase_shape(change):
    source = definition()['phases'][0]
    source.update(change)
    with pytest.raises(ValueError):
        Phase.from_dict(source)


def test_missing_output_declaration_is_rejected():
    source = definition()['phases'][0]
    del source['outputs']
    with pytest.raises(ValueError, match='required keys'):
        Phase.from_dict(source)


def test_default_config_and_budget():
    source = definition()['phases'][0]
    del source['config']
    phase = Phase.from_dict(source)
    assert phase.config == {} and phase.max_attempts == 3


@pytest.mark.parametrize(('op', 'value', 'expected'), [
    ('eq', 'high', True), ('ne', 'high', False), ('in', ['high', 'medium'], True),
    ('truthy', None, True), ('eq', 'low', False),
])
def test_predicates_read_pinned_json(op, value, expected):
    predicate = Predicate.from_dict({'key': 'risk.level', 'op': op, 'value': value})
    assert predicate.evaluate({'risk': {'level': 'high'}}) is expected
    assert Predicate.from_dict(predicate.to_dict()).evaluate({'risk': {'level': 'high'}}) is expected
    assert predicate.evaluate({}) is False


@pytest.mark.parametrize('predicate', [
    {'key': '__import__("os")', 'op': 'truthy'},
    {'key': 'risk', 'op': 'exec', 'value': 'unsafe'},
    {'key': 'risk', 'op': 'in', 'value': 'abc'},
    {'key': 'risk', 'op': 'eq', 'code': 'unsafe'},
])
def test_predicate_cannot_execute_or_select_arbitrary_code(predicate):
    with pytest.raises(ValueError):
        Predicate.from_dict(predicate)


@pytest.mark.parametrize('literal', [[1], {'items': [1, {'nested': [2]}]},
                                    [{'items': ['a', 'b']}, [3, 4]]])
def test_predicate_equality_preserves_nested_json_shape(literal):
    actual = copy.deepcopy(literal)
    assert Predicate('input', 'eq', literal).evaluate({'input': actual})
    assert not Predicate('input', 'ne', literal).evaluate({'input': actual})
    assert not Predicate('input', 'eq', literal).evaluate({'input': {'different': True}})
    assert Predicate('input', 'ne', literal).evaluate({'input': {'different': True}})


@pytest.mark.parametrize('actual', [[1, {'a': [2]}], {'items': [1, {'b': [3]}]}])
def test_predicate_membership_preserves_nested_json_shape(actual):
    predicate = Predicate('input', 'in', ['unselected', copy.deepcopy(actual)])
    assert predicate.evaluate({'input': actual})
    assert not predicate.evaluate({'input': {'different': True}})
    assert Predicate.from_dict(predicate.to_dict()).evaluate({'input': actual})


def test_edges_are_round_trippable_and_outcome_limited():
    edge = Edge.from_dict({'source': 'plan', 'target': 'review',
                           'when': {'key': 'design', 'op': 'truthy'}})
    assert edge.on == 'pass'
    assert Edge.from_dict(edge.to_dict()) == edge
    with pytest.raises(ValueError):
        Edge('plan', 'review', 'anything')


def test_nominal_identities_and_invocation_guard():
    assert RunId('same') != AttemptId('same')
    assert len({RunId('same'), PhaseId('same'), AttemptId('same'), ScopeId('same'),
                ArtifactId('same'), DecisionId('same')}) == 6
    values = dict(run_id=RunId('run-1'), scope_id=ScopeId('plan/feature'), phase_id=PhaseId('plan'),
                  attempt_id=AttemptId('attempt-1'), skill='spoq-plan', definition_hash='a' * 64,
                  specification_hash='b' * 64)
    assert Invocation(**values).to_dict()['scope_id'] == 'plan/feature'
    values['attempt_id'] = RunId('attempt-1')
    with pytest.raises(ValueError, match='AttemptId'):
        Invocation(**values)
    with pytest.raises(ValueError):
        EventId(0)
    assert str(PhaseStatus.WAITING_HUMAN) == 'waiting_human'
    assert str(PhaseStatus.SKIPPED) == 'skipped'


def test_packaged_schema_declares_runtime_shape():
    from spoq_server import __file__ as package_file
    schema = json.loads((Path(package_file).parent / 'data/strategies/schema.json').read_text())
    assert schema['properties']['schema_version'] == {'const': 1}
    assert set(schema['$defs']['phase']['properties']['kind']['enum']) == {'skill', 'gate', 'human', 'design', 'join'}
    assert 'outputs' in schema['$defs']['phase']['required']
    assert schema['additionalProperties'] is False


def test_result_identity_and_status_are_typed():
    result = PhaseResult(RunId('run'), PhaseId('plan'), AttemptId('first'), PhaseStatus.PASSED,
                         {'plan': 'artifact-1'}, {'checks_passed': True})
    assert result.to_dict()['status'] == 'passed'
    with pytest.raises(ValueError, match='PhaseStatus'):
        PhaseResult(RunId('run'), PhaseId('plan'), AttemptId('first'), 'passed', {}, {})


@pytest.mark.parametrize('shape', [None, [], {}, [1], {'x': 1}, True, 1, 1.2, 'text'])
@pytest.mark.parametrize('object_kind', ['definition', 'phase', 'edge', 'predicate'])
def test_external_json_shape_mutations_never_escape_as_programming_errors(object_kind, shape):
    """Every declared field may receive hostile JSON; reject it intentionally.

    Some mutations are valid data (for example predicate.value=None). Successful
    parses must still round-trip. All rejected shapes must raise ValueError,
    never leaked TypeError/AttributeError from set membership or len().
    """
    sources = {
        'definition': (definition(), StrategyDefinition.from_dict),
        'phase': (definition()['phases'][0], Phase.from_dict),
        'edge': ({'source': 'plan', 'target': 'review', 'on': 'pass', 'when': None}, Edge.from_dict),
        'predicate': ({'key': 'signal', 'op': 'eq', 'value': True}, Predicate.from_dict),
    }
    source, parse = sources[object_kind]
    instance = parse(source)
    for field in source:
        mutated = copy.deepcopy(source)
        mutated[field] = copy.deepcopy(shape)
        try:
            parsed = parse(mutated)
        except ValueError:
            pass
        else:
            assert parse(parsed.to_dict()).to_dict() == parsed.to_dict()
        try:
            constructed = replace(instance, **{field: copy.deepcopy(shape)})
        except ValueError:
            pass
        else:
            assert parse(constructed.to_dict()).to_dict() == constructed.to_dict()


@pytest.mark.parametrize('factory,field', [(Phase.from_dict, 'kind'), (Edge.from_dict, 'on'),
                                          (Predicate.from_dict, 'op')])
@pytest.mark.parametrize('bad_type', [[], {}, [1], {'x': 1}, None, True, 1])
def test_discriminator_fields_reject_json_containers_with_value_error(factory, field, bad_type):
    examples = {'kind': definition()['phases'][0],
                'on': {'source': 'plan', 'target': 'review'},
                'op': {'key': 'signal', 'op': 'eq'}}
    with pytest.raises(ValueError):
        factory({**examples[field], field: bad_type})


@pytest.mark.parametrize('field', ['phases', 'edges'])
@pytest.mark.parametrize('bad_type', [None, {}, {'phase': 'plan'}, True, 1, 1.2, 'text'])
def test_direct_definition_constructor_rejects_non_arrays(field, bad_type):
    valid = StrategyDefinition.from_dict(definition())
    with pytest.raises(ValueError):
        replace(valid, **{field: bad_type})
