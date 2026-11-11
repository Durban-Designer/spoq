from importlib.resources import files
import json

import pytest

from spoq_server.v1.workflows.compiler import compile_definition
from spoq_server.v1.workflows.definitions import get_strategy, list_strategies


@pytest.mark.parametrize('name,profile', [('classic','standard'),('classic','compact'),('piqard','standard')])
def test_builtins_compile_and_all_loops_have_two_finite_limits(name,profile):
    compiled = compile_definition(get_strategy(name,profile))
    assert compiled.definition.max_transitions > 0
    assert all(p.max_attempts == 3 for p in compiled.phases.values())
    assert compiled.loop_edges
    for loop in compiled.loop_edges:
        assert loop.source in compiled.descendants(loop.target)
    assert compiled.forward_order[0] == compiled.definition.entry


@pytest.mark.parametrize('name', ['classic','piqard'])
def test_both_strategies_keep_independent_gates_and_checks(name):
    c = compile_definition(get_strategy(name))
    plan = c.phases['plan-validation']
    implementation = c.phases['implementation-validation']
    assert plan.skill == 'spoq-plan-validation'
    assert plan.config == {'stage':'plan','minimum_average':95,'minimum_metric':90,'required_checks':True}
    assert implementation.skill == 'spoq-validation'
    assert implementation.config == {'stage':'implementation','minimum_average':95,'minimum_metric':80,'required_checks':True}
    assert 'plan-validation' in c.descendants('plan')
    assert 'execute' in c.descendants('plan-validation')
    assert 'implementation-validation' in c.descendants('execute')


def test_compact_does_not_remove_checks_or_mandatory_stages():
    standard = get_strategy('classic')
    compact = get_strategy('classic','compact')
    assert compact.content_hash != standard.content_hash
    assert compact.phases[0].config['profile'] == 'compact'
    assert [p.to_dict() for p in compact.phases[1:]] == [p.to_dict() for p in standard.phases[1:]]
    assert compact.edges == standard.edges


def test_piqard_narrative_human_review_precedes_decomposition():
    c = compile_definition(get_strategy('piqard'))
    assert c.phases['discover'].skill == 'spoq-discover'
    assert c.phases['narrative'].outputs == ('narrative_plan',)
    assert c.phases['review'].kind == 'human'
    assert c.phases['review'].inputs == ('narrative_plan',)
    assert c.phases['review'].config['response_origin'] == 'user'
    assert 'plan' in c.descendants('review')
    assert any(e.source == 'review' and e.target == 'narrative' for e in c.loop_edges)
    assert 'decision' in c.phases['plan'].inputs


def test_design_addons_are_parallel_and_join_before_narrative():
    c = compile_definition(get_strategy('piqard'))
    for name in ('diagram','erd','algorithm','formal'):
        assert c.phases[name].skill == 'spoq-design'
        assert c.phases[name].outputs == (name,)
        selected = next(e for e in c.outgoing['discover'] if e.target == name)
        assert selected.when.evaluate({'addons':{name:True}})
        assert not selected.when.evaluate({'addons':{name:False}})
        assert 'narrative' in c.descendants(name)
        assert not set(('diagram','erd','algorithm','formal')) & set(c.descendants(name))
    assert c.phases['design-join'].config['join'] == 'selected'
    assert len(c.forward_incoming['design-join']) == 5
    assert c.phases['formal'].config['capability_required_input'] == 'formal_proof_required'


def test_inventory_and_packaged_json_are_consistent():
    assert {s['id'] for s in list_strategies()} == {'classic','piqard'}
    for row in list_strategies():
        raw = json.loads((files('spoq_server')/'data'/'strategies'/(row['id']+'.json')).read_text())
        assert raw['id'] == row['id'] and raw['version'] == row['version']
        assert len(row['definition_hash']) == 64


@pytest.mark.parametrize('name,profile', [('ghost','standard'),('../classic','standard'),('piqard','compact'),('classic','skip-gates')])
def test_invalid_strategy_profile_rejected_without_path_access(name,profile):
    with pytest.raises(ValueError,match='Unknown strategy/profile'):
        get_strategy(name,profile)


@pytest.mark.parametrize('value', [None, [], {}, False, 1, 1.5])
def test_malformed_strategy_or_profile_shape_is_value_error(value):
    with pytest.raises(ValueError,match='Unknown strategy/profile'):
        get_strategy(value)
    with pytest.raises(ValueError,match='Unknown strategy/profile'):
        get_strategy('classic',value)
