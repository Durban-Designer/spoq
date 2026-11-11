from copy import deepcopy

import pytest

from spoq_server.v1.workflows.routing import propose_escalation, route


def known(**kwargs):
    return {'effort':'small','uncertainty':'low','impact':'low','coupling':'low',**kwargs}


@pytest.mark.parametrize('inputs,strategy,profile', [
    (known(),'classic','compact'),
    (known(effort='large'),'classic','standard'),
    (known(effort='medium'),'classic','standard'),
    (known(uncertainty='high'),'piqard','standard'),
    (known(effort='small',impact='high'),'piqard','standard'),
    (known(effort='large',uncertainty='high'),'piqard','standard'),
    (known(coupling='high'),'piqard','standard'),
    ({},'piqard','standard'),
    (known(addons={'erd':True}),'piqard','standard'),
    (known(formal_proof_required=True),'piqard','standard'),
])
def test_route_uses_more_than_task_size(inputs,strategy,profile):
    result = route(inputs)
    assert result['strategy'] == strategy and result['profile'] == profile
    assert result['reasons'] and result['policy_version'] == 'spoq-route-1'
    assert result['inputs']['addons'] == result['addons']
    assert result['mandatory_gates']['required_checks'] is True
    assert result['mandatory_gates']['plan'] == {'average':95,'floor':90}
    assert result['mandatory_gates']['implementation'] == {'average':95,'floor':80}
    assert len(result['definition_hash']) == 64


def test_deterministic_snapshot_retains_evidence_and_missing_inputs():
    inputs = {'goal':'Review the data model','effort':'large','evidence':[{'source':'user','quote':'Unknown schema'}]}
    original = deepcopy(inputs)
    result = route(inputs)
    assert result == route(inputs) and inputs == original
    assert result['missing_information'] == ['uncertainty','impact','coupling']
    assert result['input_evidence'] == original['evidence']
    inputs['evidence'].append({'source':'changed'})
    assert result['input_evidence'] == original['evidence']


def test_preference_wins_where_valid_without_weakening_gates():
    assert route(known(),'piqard')['strategy'] == 'piqard'
    overridden = route(known(uncertainty='high'),'classic')
    assert overridden['strategy'] == 'classic'
    assert any('Explicit user' in x for x in overridden['reasons'])
    assert overridden['mandatory_gates']['plan']['floor'] == 90
    with pytest.raises(ValueError,match='cannot drop'):
        route(known(addons={'algorithm':True}),'classic')
    with pytest.raises(ValueError,match='preference'):
        route(known(),'skip-validation')


@pytest.mark.parametrize('inputs', [[], {'effort':4}, {'effort':'ten hours'}, {'uncertainty':True},
    {'impact':'infinite'}, {'coupling':'none'}, {'addons':[]}, {'addons':{'mystery':True}},
    {'addons':{'erd':1}}, {'formal_proof_required':'yes'}, {'capabilities':[]},
    {'goal':4}, {'evidence':'guessed'}, {'impact':float('nan')}])
def test_rejects_invalid_or_ambiguous_inputs(inputs):
    with pytest.raises(ValueError):
        route(inputs)


def test_required_proof_is_preserved_as_requirement_not_silently_disabled():
    result = route(known(formal_proof_required=True,capabilities={}))
    assert result['addons']['formal'] and result['inputs']['formal_proof_required']
    assert not result['inputs']['capabilities']


def test_escalation_is_proposal_at_boundary_and_preserves_route():
    previous = route(known())
    original = deepcopy(previous)
    proposal = propose_escalation(previous,known(uncertainty='high'),at_phase_boundary=True,reason='New domain uncertainty')
    assert previous == original and proposal['status'] == 'proposed'
    assert proposal['proposed_route']['strategy'] == 'piqard'
    assert proposal['requires_explicit_adoption'] and proposal['preserve_history']
    with pytest.raises(ValueError,match='boundary'):
        propose_escalation(previous,known(),at_phase_boundary=False,reason='Do not interrupt a running phase')
    with pytest.raises(ValueError,match='reason'):
        propose_escalation(previous,known(),at_phase_boundary=True,reason='')
