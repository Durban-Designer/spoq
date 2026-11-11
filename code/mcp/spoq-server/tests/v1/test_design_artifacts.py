import hashlib
import json

import pytest

from spoq_server.v1.workflows.design import capability_status, validate_artifact


def narrative():
    return '# Plan\n'+'\n'.join('## '+s+'\nReviewable '+s+' content.' for s in ('Scope','Decisions','Assumptions','Risks','Acceptance criteria'))


def test_narrative_is_reviewable_before_decomposition_and_hash_bound():
    content = narrative()
    result = validate_artifact('narrative_plan',content)
    assert result['content'] == content
    assert result['sha256'] == hashlib.sha256(content.encode()).hexdigest()
    assert result['validation']['source_only']
    changed = validate_artifact('narrative_plan',content+'\nRevision2')
    assert changed['sha256'] != result['sha256']
    structured = {'scope':'Goal','decisions':['Use SQLite'],'assumptions':['Local only'],
                  'risks':['Recovery'],'acceptance_criteria':['Tests pass']}
    assert json.loads(validate_artifact('narrative_plan',structured)['content']) == structured


@pytest.mark.parametrize('content', ['https://example.atlassian.net/wiki/plan', '# Plan\n## Scope\nOnly scope.',
    '```markdown\n'+narrative()+'\n```', narrative().replace('Reviewable Risks content.','')])
def test_missing_or_empty_sections_and_link_only_are_not_narrative(content):
    with pytest.raises(ValueError,match='requires nonempty'):
        validate_artifact('narrative_plan',content)


def test_confluence_reference_requires_version_and_reviewed_export():
    metadata = {'confluence':{'url':'https://example.atlassian.net/wiki/plan','version':'7','reviewed_export':True}}
    result = validate_artifact('narrative_plan',narrative(),metadata)
    assert result['metadata'] == metadata
    for change in ({'version':''},{'reviewed_export':False},{'url':'file:///etc/passwd'},{'url':42}):
        with pytest.raises(ValueError):
            validate_artifact('narrative_plan',narrative(),{'confluence':{**metadata['confluence'],**change}})


@pytest.mark.parametrize('kind,content', [('diagram','flowchart TD\n A --> B'),
    ('diagram','```mermaid\nsequenceDiagram\n A->>B: request\n```'),
    ('erd','erDiagram\n USER ||--o{ TASK : owns')])
def test_diagram_source_stays_reviewable_without_claiming_render_verification(kind,content):
    result = validate_artifact(kind,content)
    assert result['content'] == content and result['validation']['syntax_verified'] is False
    assert result['validation']['external_verifier_executed'] is False


@pytest.mark.parametrize('kind,content', [('diagram','https://example.test/image.png'),('erd','flowchart TD\n A-->B'),
    ('erd','erDiagram'),('diagram',{'source':'flowchart TD'}),('diagram','flowchartBogus\n A-->B')])
def test_non_source_or_wrong_diagram_type_rejected(kind,content):
    with pytest.raises(ValueError):
        validate_artifact(kind,content)


def test_algorithm_requires_io_invariants_and_complexity_assumptions():
    value = {'inputs':['Sorted array'],'outputs':['Index or None'],'invariants':['Bounds contain candidates'],
             'complexity':'O(log n) assuming constant-time comparison'}
    assert validate_artifact('algorithm',value)['status'] == 'specified'
    assert validate_artifact('algorithm',json.dumps(value))['status'] == 'specified'
    for field in value:
        with pytest.raises(ValueError,match=field):
            validate_artifact('algorithm',{k:v for k,v in value.items() if k != field})
    markdown = '\n'.join('## '+k+'\n'+str(v) for k,v in value.items())
    assert validate_artifact('algorithm',markdown)


def verifier(exit_code=0):
    return {'tool':'example-solver','version':'1','source':'scripted-test-adapter','command':['example-solver','proof'],
            'exit_code':exit_code,'observed':True,'result':'recorded outcome'}


@pytest.mark.parametrize('status', ['specified','tested','proven','disproven','unverified'])
def test_formal_states_and_supplied_provenance_remain_distinct(status):
    data = {'status':status,'specification':'For all n>=0, n+0=n'}
    if status in {'tested','proven','disproven'}:
        data['verifier'] = verifier(1 if status == 'disproven' else 0)
    if status == 'proven':
        data.update(proof='Proof object bytes/derivation',assumptions=['Integer arithmetic'])
    if status == 'disproven':
        data['counterexample'] = 'Recorded counterexample'
    if status == 'unverified':
        data['reason'] = 'No configured solver'
    result = validate_artifact('formal',data)
    assert result['status'] == status and result['metadata']['formal_status'] == status
    assert result['validation']['provenance'] == 'caller_supplied_not_reexecuted'
    assert result['validation']['external_verifier_executed'] is False


@pytest.mark.parametrize('change', [
    {'verifier':None}, {'verifier':verifier(1)}, {'proof':''}, {'assumptions':'implicit'},
    {'verifier':{**verifier(),'observed':False}}, {'verifier':{**verifier(),'command':''}},
    {'verifier':{**verifier(),'source':''}}])
def test_proof_claim_without_successful_recorded_verifier_and_proof_rejected(change):
    data = {'status':'proven','specification':'Invariant','proof':'Proof artifact','assumptions':[], 'verifier':verifier(),**change}
    with pytest.raises(ValueError):
        validate_artifact('formal',data)


def test_unavailable_required_capability_blocks_optional_skip_and_specification_is_local():
    assert capability_status('formal_proof',{},required=True)['status'] == 'blocked'
    assert capability_status('formal_proof',{},required=False)['status'] == 'skipped'
    assert capability_status('formal_proof',{'formal_proof':{'available':True,'tool':'z3'}})['status'] == 'ready'
    assert capability_status('formal',{})['status'] == 'ready'
    assert capability_status('erd',{'erd':False})['status'] == 'skipped'
    with pytest.raises(ValueError):
        capability_status('formal_proof',{'formal_proof':'guessed'})


@pytest.mark.parametrize('kind,content,metadata', [('unknown','text',{}),('formal','not json',{}),
    ('formal',{'status':'proven','specification':'x'},{}),('narrative_plan',narrative(),[]),
    ('algorithm',[],{}),('diagram',' '*4,{})])
def test_malformed_artifacts_rejected(kind,content,metadata):
    with pytest.raises(ValueError):
        validate_artifact(kind,content,metadata)


def test_formal_text_json_rejects_nonfinite_nested_values():
    with pytest.raises(ValueError):
        validate_artifact('formal','{\"status\":\"specified\",\"specification\":\"x\",\"value\":NaN}')


@pytest.mark.parametrize('opening,not_closing,closing', [
    ('````markdown','```','````'),
    ('~~~~markdown','~~~','~~~~'),
    ('````markdown','````not-a-close','````'),
    ('```markdown','~~~','```'),
])
def test_headings_still_inside_fence_never_satisfy_narrative(opening,not_closing,closing):
    with pytest.raises(ValueError,match='requires nonempty'):
        validate_artifact('narrative_plan',opening+'\n'+not_closing+'\n'+narrative()+'\n'+closing)
    assert validate_artifact('narrative_plan',opening+'\nignored\n'+closing+'\n'+narrative())


@pytest.mark.parametrize('value', [None, [], {}, False, 1, 1.5, 'unknown'])
def test_json_shaped_kind_status_and_capability_fail_as_value_error(value):
    with pytest.raises(ValueError):
        validate_artifact(value,'text')
    with pytest.raises(ValueError):
        validate_artifact('formal',{'status':value,'specification':'Invariant'})
    if value != 'unknown':
        with pytest.raises(ValueError):
            capability_status(value,{})


def _json_paths(value,prefix=()):
    if isinstance(value,dict):
        for key,child in value.items():
            yield prefix+(key,)
            yield from _json_paths(child,prefix+(key,))
    elif isinstance(value,list):
        for key,child in enumerate(value):
            yield prefix+(key,)
            yield from _json_paths(child,prefix+(key,))


def test_formal_and_reference_json_field_sweep_never_leaks_python_type_errors():
    from copy import deepcopy
    valid={'status':'proven','specification':'Invariant','proof':'Derivation','assumptions':['Integers'],
           'verifier':verifier()}
    metadata={'confluence':{'url':'https://example.test/plan','version':'1','reviewed_export':True}}
    cases=0
    for path in _json_paths({'content':valid,'metadata':metadata}):
        for shape in (None,[],{},False,1,1.5,'invalid'):
            mutated=deepcopy({'content':valid,'metadata':metadata})
            target=mutated
            for key in path[:-1]:
                target=target[key]
            target[path[-1]]=shape
            try:
                validate_artifact('formal',mutated['content'],mutated['metadata'])
            except ValueError:
                pass
            cases+=1
    assert cases>=100
