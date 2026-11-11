"""Compiler rejects unsafe graphs without weakening the independent work DAG."""
from copy import deepcopy

import pytest

from spoq_server.v1.graph import waves
from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.workflows.types import StrategyDefinition


def definition():
    return {
        'schema_version': 1, 'id': 'review-loop', 'version': '1.0.0', 'title': 'Review',
        'entry': 'draft', 'max_transitions': 12,
        'phases': [
            {'id': 'draft', 'kind': 'skill', 'skill': 'spoq-discover', 'inputs': ['goal'],
             'outputs': ['narrative'], 'max_attempts': 3},
            {'id': 'review', 'kind': 'human', 'skill': None, 'inputs': ['narrative'],
             'outputs': ['decision'], 'max_attempts': 3},
            {'id': 'plan', 'kind': 'skill', 'skill': 'spoq-plan', 'inputs': ['narrative', 'decision'],
             'outputs': ['plan'], 'max_attempts': 3}],
        'edges': [{'source': 'draft', 'target': 'review'}, {'source': 'review', 'target': 'plan'},
                  {'source': 'review', 'target': 'draft', 'on': 'fail'}]}


def test_compiles_and_indexes_bounded_revision_loop():
    original = definition()
    compiled = compile_definition(original)
    assert compiled.forward_order == ('draft', 'review', 'plan')
    assert compiled.descendants('draft') == ('review', 'plan')
    assert compiled.descendants('plan') == ()
    assert compiled.loop_edges[0].target == 'draft'
    assert len(compiled.forward_edges) == 2
    assert len(compiled.incoming['draft']) == 1 and not compiled.forward_incoming['draft']
    assert compiled.definition.to_dict() == StrategyDefinition.from_dict(original).to_dict()
    with pytest.raises(TypeError):
        compiled.phases['bad'] = compiled.phases['draft']
    with pytest.raises(ValueError, match='Unknown phase'):
        compiled.descendants('unknown')


@pytest.mark.parametrize('change,error', [
    (lambda d: d['phases'][0].update(skill='os.system'), 'Unknown skill'),
    (lambda d: d['phases'][0].update(outputs=[]), 'required outputs'),
    (lambda d: d['phases'][0].update(inputs=['unproduced']), 'without a forward producer'),
    (lambda d: d['edges'].append({'source': 'plan', 'target': 'ghost'}), 'unknown phase'),
    (lambda d: d['edges'].append({'source': 'plan', 'target': 'review'}), 'Forward control'),
    (lambda d: d['edges'].append({'source': 'draft', 'target': 'plan', 'on': 'fail'}), 'forward ancestor'),
    (lambda d: d['edges'].append(deepcopy(d['edges'][0])), 'Duplicate transitions'),
    (lambda d: d['phases'].append(deepcopy(d['phases'][0])), 'Duplicate phase'),
    (lambda d: d.update(entry='missing'), 'Entry refers'),
    (lambda d: d['edges'].clear(), 'Unreachable'),
    (lambda d: d.update(max_transitions=0), 'max_transitions'),
    (lambda d: d['phases'][0].update(max_attempts=0), 'max_attempts'),
    (lambda d: d['edges'][0].update(on='sometimes'), 'Edge outcome'),
    (lambda d: d['edges'][0].update(when={'key': '__import__("os")', 'op': 'truthy'}), 'Predicate key'),
])
def test_rejects_malformed_or_unbounded_contracts(change, error):
    value = definition()
    change(value)
    with pytest.raises(ValueError, match=error):
        compile_definition(value)


def test_explicit_skill_whitelist_and_typed_input():
    value = definition()
    value['phases'][0]['skill'] = 'custom-discover'
    compiled = compile_definition(StrategyDefinition.from_dict(value),
                                  skills={'custom-discover', 'spoq-plan'})
    assert compiled.definition.id == 'review-loop'


def branch_definition():
    value = definition()
    value['phases'] = [value['phases'][0],
        {'id': 'diagram', 'kind': 'design', 'skill': 'spoq-design', 'inputs': ['narrative'],
         'outputs': ['diagram']},
        {'id': 'join', 'kind': 'join', 'skill': None, 'inputs': [], 'outputs': [],
         'config': {'join': 'selected'}}]
    value['edges'] = [
        {'source': 'draft', 'target': 'diagram', 'when': {'key': 'addons.diagram', 'op': 'truthy'}},
        {'source': 'draft', 'target': 'join'}, {'source': 'diagram', 'target': 'join'}]
    return value


def test_conditional_parallel_join_declares_selected_semantics():
    compiled = compile_definition(branch_definition())
    conditional = compiled.outgoing['draft'][0]
    assert conditional.when.evaluate({'addons': {'diagram': True}})
    assert not conditional.when.evaluate({'addons': {'diagram': False}})
    assert len(compiled.forward_incoming['join']) == 2
    value = branch_definition()
    value['phases'][-1]['config'] = {'join': 'all-ever'}
    with pytest.raises(ValueError, match='selected-input'):
        compile_definition(value)


@pytest.mark.parametrize('stage,floor', [('plan', 90), ('implementation', 80)])
def test_gate_cannot_weaken_threshold_or_required_checks(stage, floor):
    value = definition()
    value['phases'][-1].update(kind='gate', skill='spoq-plan-validation' if stage == 'plan' else 'spoq-validation',
                                config={'stage': stage, 'minimum_average': 95, 'minimum_metric': floor,
                                        'required_checks': True})
    assert compile_definition(value).phases['plan'].config['stage'] == stage
    for update in ({'minimum_average': 94.9}, {'minimum_metric': floor-1}, {'required_checks': False},
                   {'stage': 'unknown'}, {'minimum_average': float('nan')}):
        bad = deepcopy(value)
        bad['phases'][-1]['config'].update(update)
        with pytest.raises(ValueError):
            compile_definition(bad)


def test_fail_self_retry_is_bounded_but_work_graph_stays_acyclic():
    value = definition()
    value['edges'].append({'source': 'plan', 'target': 'plan', 'on': 'fail'})
    assert len(compile_definition(value).loop_edges) == 2
    with pytest.raises(ValueError, match='cycle'):
        waves({'draft': ['review'], 'review': ['draft']})


def test_multiple_output_producers_are_rejected_before_completion_order_can_matter():
    value = branch_definition()
    value['phases'].insert(2, {'id':'second-diagram','kind':'design','skill':'spoq-design',
                             'inputs':['narrative'],'outputs':['diagram']})
    value['edges'] += [{'source':'draft','target':'second-diagram'},
                       {'source':'second-diagram','target':'join'}]
    with pytest.raises(ValueError,match='multiple producers: diagram'):
        compile_definition(value)


@pytest.mark.parametrize('stage', [None, [], {}, False, 1, 1.5, 'unknown'])
def test_malformed_gate_stage_always_raises_value_error(stage):
    value = definition()
    value['phases'][-1].update(kind='gate',skill='spoq-validation',config={'stage':stage})
    with pytest.raises(ValueError,match='Gate stage'):
        compile_definition(value)


@pytest.mark.parametrize('skills', [42, 'spoq-plan', [{}], [None]])
def test_malformed_skill_whitelist_raises_value_error(skills):
    with pytest.raises(ValueError,match='Skill whitelist'):
        compile_definition(definition(),skills=skills)
