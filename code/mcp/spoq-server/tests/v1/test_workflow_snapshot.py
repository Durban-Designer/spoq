"""1.1 snapshots preserve provenance and reject corruption before commit."""
import copy
import json
import sqlite3

import pytest

from spoq_server.v1.cli import import_snapshot, write_snapshot
from spoq_server.v1.db import now, transaction
from spoq_server.v1.store import Store
from spoq_server.v1.workflows.artifacts import ArtifactRepository
from spoq_server.v1.workflows.decisions import DecisionRepository
from spoq_server.v1.workflows.repository import WorkflowRepository


def populated(store, *, conditional=False):
    definition = {'schema_version': 1, 'id': 'snapshot', 'version': '1.0.0', 'title': 'Snapshot test',
                  'entry': 'draft', 'max_transitions': 9,
                  'phases': [{'id': 'draft', 'kind': 'skill', 'skill': 'spoq-discover', 'inputs': [], 'outputs': ['narrative_plan'], 'max_attempts': 3},
                             {'id': 'review', 'kind': 'human', 'skill': None, 'inputs': ['narrative_plan'], 'outputs': ['decision'], 'max_attempts': 3,
                              'config': {'artifact_kind': 'narrative_plan'}}],
                  'edges': [{'source': 'draft', 'target': 'review'}, {'source': 'review', 'target': 'draft', 'on': 'fail'}]}
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for
    if conditional:
        definition['edges'][0]['when'] = {'key': 'take_review', 'op': 'eq', 'value': True}
    engine = WorkflowEngine(store)
    engine.start('workflow-run', 'feature', {'uncertainty': 'high', 'take_review': True}, key='start', actor='worker', definition=definition)
    draft = engine.next('workflow-run', 'worker', key='draft')
    narrative = {name: ['Scripted snapshot fixture ' + name]
                 for name in ('scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria')}
    engine.complete('workflow-run', draft['attempt_id'], draft['token'], 'worker', key='drafted',
                    evidence=evidence_for(draft), outputs={'narrative_plan': {'content': narrative,
                        'metadata': {'url': 'https://example.atlassian.net/wiki/123', 'version': '3', 'reviewed_export': True}}})
    review = engine.next('workflow-run', 'worker', key='review')
    artifact = review['inputs']['narrative_plan']
    engine.respond('workflow-run', review['attempt_id'], artifact['id'], artifact['sha256'], 'approve', 'User',
                   key='approve', source='user', user_confirmed=True)
    return engine.repository


def test_v11_snapshot_roundtrips_every_workflow_row_and_event_order(store, tmp_path):
    repo = populated(store)
    snapshot = store.snapshot()
    assert snapshot['format'] == 'spoq-1.1'
    assert len(snapshot['tables']['workflow_definitions']) == 1
    assert len(snapshot['tables']['workflow_attempts']) == 2
    assert len(snapshot['tables']['workflow_artifacts']) == 2
    assert len(snapshot['tables']['workflow_decisions']) == 1
    assert len(snapshot['tables']['workflow_receipts']) == 5
    destination = tmp_path / 'export.json'
    write_snapshot(store, destination)
    target = Store(tmp_path / 'restored' / 'spoq.db')
    assert import_snapshot(target, json.loads(destination.read_text()))['imported']
    assert target.snapshot() == snapshot
    assert WorkflowRepository(target).get('workflow-run')['definition_hash'] == repo.get('workflow-run')['definition_hash']
    decision = DecisionRepository(WorkflowRepository(target)).list('workflow-run')[0]
    assert DecisionRepository(WorkflowRepository(target)).is_current(decision['id'])
    sequences = [e['sequence'] for e in target.snapshot()['tables']['events']]
    assert sequences == sorted(sequences) and len(sequences) == len(set(sequences))


def test_existing_spoq_1_snapshots_import_without_invented_history(store, tmp_path):
    store.journal('Old journal preserved', node_id='feature')
    snapshot = store.snapshot()
    assert snapshot['format'] == 'spoq-1'
    assert not any(k.startswith('workflow_') for k in snapshot['tables'])
    target = Store(tmp_path / 'target' / 'spoq.db')
    import_snapshot(target, snapshot)
    assert target.snapshot() == snapshot
    assert WorkflowRepository(target).list() == []


@pytest.mark.parametrize('corruption', [
    'format', 'tables', 'definition-hash', 'definition-schema', 'run-scope', 'state-status',
    'attempt-phase', 'attempt-count', 'attempt-fence', 'artifact-hash', 'artifact-run',
    'decision-source', 'decision-hash', 'decision-phase', 'receipt-hash', 'receipt-run',
    'output-ref', 'phase-attempt', 'transition-budget', 'nan-state', 'epoch', 'event-run', 'format-type', 'phase-status-type', 'receipt-key', 'passed-blocked', 'attempt-ref-type', 'event-run-type', 'phase-attempt-status', 'passed-no-attempt', 'timestamp-empty', 'timestamp-naive', 'missing-output', 'old-attempt-output', 'missing-approval', 'rejected-approval', 'approval-spec', 'missing-phase'])
def test_invalid_workflow_snapshot_rolls_back_all_tables_and_search(store, tmp_path, corruption):
    populated(store)
    snapshot = copy.deepcopy(store.snapshot())
    t = snapshot['tables']
    if corruption == 'format': snapshot['format'] = 'spoq-unknown'
    elif corruption == 'format-type': snapshot['format'] = []
    elif corruption == 'receipt-key': t['workflow_receipts'][0]['key'] = 'line\nbreak'
    elif corruption == 'timestamp-empty': t['workflow_artifacts'][0]['created_at'] = ''
    elif corruption == 'timestamp-naive': t['workflow_runs'][0]['updated_at'] = '2026-11-08T00:00:00'
    elif corruption == 'tables': t['unexpected'] = []
    elif corruption == 'definition-hash': t['workflow_definitions'][0]['hash'] = 'f' * 64
    elif corruption == 'definition-schema':
        d = json.loads(t['workflow_definitions'][0]['definition']);d['schema_version'] = 999;t['workflow_definitions'][0]['definition'] = json.dumps(d)
    elif corruption == 'run-scope': t['workflow_runs'][0]['scope_id'] = 'plan'
    elif corruption == 'state-status':
        s = json.loads(t['workflow_runs'][0]['state']);s['phases']['draft']['status'] = 'invented';t['workflow_runs'][0]['state'] = json.dumps(s)
    elif corruption == 'attempt-phase': t['workflow_attempts'][0]['phase_id'] = 'unknown'
    elif corruption == 'attempt-count': t['workflow_attempts'][0]['number'] = 900
    elif corruption == 'attempt-fence': t['workflow_attempts'][0].update(status='running', token='')
    elif corruption == 'artifact-hash': t['workflow_artifacts'][0]['content'] += ' modified'
    elif corruption == 'artifact-run': t['workflow_artifacts'][0]['run_id'] = 'unknown'
    elif corruption == 'missing-approval': t['workflow_decisions'] = []
    elif corruption == 'rejected-approval': t['workflow_decisions'][0]['decision'] = 'reject'
    elif corruption == 'approval-spec': t['workflow_decisions'][0]['specification_hash'] = 'f' * 64
    elif corruption == 'old-attempt-output':
        old = copy.deepcopy(t['workflow_attempts'][0]);old.update(id='draft-old',number=2);t['workflow_attempts'].append(old);t['workflow_artifacts'][0]['attempt_id']='draft-old'
    elif corruption == 'decision-source': t['workflow_decisions'][0]['source'] = 'agent'
    elif corruption == 'decision-hash': t['workflow_decisions'][0]['artifact_hash'] = 'f' * 64
    elif corruption == 'decision-phase': t['workflow_decisions'][0]['attempt_id'] = t['workflow_attempts'][0]['id']
    elif corruption == 'receipt-hash': t['workflow_receipts'][0]['fingerprint'] = 'invalid'
    elif corruption == 'receipt-run':
        r = json.loads(t['workflow_receipts'][0]['result']);r['run_id'] = 'other';t['workflow_receipts'][0]['result'] = json.dumps(r)
    elif corruption in {'event-run', 'event-run-type'}:
        e = next(e for e in t['events'] if e['kind'].startswith('workflow.'));p = json.loads(e['payload']);p['run_id'] = [] if corruption == 'event-run-type' else 'other';e['payload'] = json.dumps(p)
    else:
        s = json.loads(t['workflow_runs'][0]['state'])
        if corruption == 'output-ref': s['outputs']['narrative_plan'] = 'unknown'
        elif corruption == 'phase-attempt': s['phases']['draft']['attempt_id'] = t['workflow_attempts'][1]['id']
        elif corruption == 'transition-budget': s['transitions'] = 99999
        elif corruption == 'epoch': s['epoch'] = -1
        elif corruption == 'nan-state': s['fake'] = float('nan')
        elif corruption == 'missing-phase': s['phases'].pop('review')
        elif corruption == 'missing-output': s['outputs'].pop('narrative_plan')
        elif corruption == 'phase-status-type': s['phases']['draft']['status'] = []
        elif corruption == 'passed-blocked': s['phases']['review']['status'] = 'blocked'
        elif corruption == 'attempt-ref-type': s['phases']['draft']['attempt_id'] = []
        elif corruption == 'phase-attempt-status': s['phases']['draft']['status'] = 'running'
        elif corruption == 'passed-no-attempt': s['phases']['draft']['attempt_id'] = None
        t['workflow_runs'][0]['state'] = json.dumps(s)
    target = Store(tmp_path / 'target' / 'spoq.db')
    before = target.snapshot()
    with pytest.raises((ValueError, sqlite3.Error)):
        import_snapshot(target, snapshot)
    assert target.snapshot() == before
    with transaction(target.path) as db:
        assert db.execute('SELECT COUNT(*) FROM search_documents').fetchone()[0] == 0


def test_occupied_target_protects_workflow_and_nonworkflow_work(store, tmp_path):
    populated(store)
    target = Store(tmp_path / 'target' / 'spoq.db')
    target.journal('Existing user work')
    before = target.snapshot()
    with pytest.raises(ValueError, match='empty'):
        import_snapshot(target, store.snapshot())
    assert target.snapshot() == before


def test_derived_indexes_and_ui_assets_are_not_authoritative_snapshot_rows(store):
    populated(store)
    tables = store.snapshot()['tables']
    assert not any(k.startswith(('search_', 'embedding_', 'ui_')) for k in tables)


def test_historical_human_approval_survives_later_legitimate_specification_revision(store, tmp_path):
    repo = populated(store)
    decision = DecisionRepository(repo).list('workflow-run')[0]
    store.create('task', 'new-task', 'Decomposed after review', 'feature')
    actual = repo.get('workflow-run')['current_specification_hash']
    def refresh(db, current):
        return {'state': current['state'], 'status': current['status'], 'specification_hash': actual, 'event_kind': 'specification_rebased'}
    repo.mutate('workflow-run', 'rebase', repo.get('workflow-run')['revision'], 'worker', refresh, request={'specification_hash': actual})
    assert decision['specification_hash'] != actual
    target = Store(tmp_path / 'restored' / 'spoq.db')
    import_snapshot(target, store.snapshot())
    assert target.snapshot() == store.snapshot()
    assert DecisionRepository(WorkflowRepository(target)).get(decision['id'])['specification_hash'] == decision['specification_hash']


def runtime_gate(store):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for, outputs_for
    engine = WorkflowEngine(store)
    engine.start('runtime','feature',{'uncertainty':'low'},strategy='classic')
    plan = engine.next('runtime','orchestrator',key='plan')
    engine.complete('runtime',plan['attempt_id'],plan['token'],'orchestrator',key='planned',
                    evidence=evidence_for(plan),outputs=outputs_for(plan))
    gate = engine.next('runtime','orchestrator',key='gate')
    engine.complete('runtime',gate['attempt_id'],gate['token'],'orchestrator',key='gated',
                    evidence=evidence_for(gate,stage='plan'))
    return engine, gate


def assert_rejected_atomically(snapshot, tmp_path, match=None):
    target=Store(tmp_path/'rejected'/'spoq.db');before=target.snapshot()
    with pytest.raises(ValueError,match=match):import_snapshot(target,snapshot)
    assert target.snapshot()==before
    with transaction(target.path) as db:
        assert db.execute('SELECT COUNT(*) FROM search_documents').fetchone()[0]==0


def test_actual_runtime_passed_gate_roundtrips_and_stale_scope_still_requires_refresh(store,tmp_path):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from spoq_server.v1.workflows.queries import ReadModel
    engine,gate=runtime_gate(store)
    target=Store(tmp_path/'restored'/'spoq.db');import_snapshot(target,store.snapshot())
    assert target.snapshot()==store.snapshot()
    assert WorkflowEngine(target).next('runtime','orchestrator',key='after-import')['phase_id']=='execute'
    # Editing saved work without refreshing the run makes historical reports
    # stale. Import must preserve their original identities, then deny dispatch.
    store.create('task','new-task','Changed scope after gate','feature')
    stale=Store(tmp_path/'stale'/'spoq.db');import_snapshot(stale,store.snapshot())
    assert ReadModel(stale).snapshot('runtime')['run']['stale_specification']
    with pytest.raises(ValueError,match='Specification changed'):
        WorkflowEngine(stale).next('runtime','orchestrator',key='cannot-advance-stale')


@pytest.mark.parametrize('tamper',['zero-scores','arbitrary-report','optional-only','output-hashes','arithmetic',
                                  'input-hashes','self-independent','specification','journal-missing','journal-scope','journal-report',
                                  'computed-provenance','verified-reviewer','gate-source','work-input-scope'])
def test_current_passed_gate_evidence_cannot_be_forged_in_snapshot(store,tmp_path,tamper):
    engine,gate=runtime_gate(store);snapshot=copy.deepcopy(store.snapshot());tables=snapshot['tables']
    attempt=next(row for row in tables['workflow_attempts'] if row['id']==gate['attempt_id'])
    report=json.loads(attempt['evidence'])
    journal=next(row for row in tables['journal_entries'] if row['id']==report['validation_journal_id'])
    if tamper=='zero-scores':report['scores']={key:0 for key in report['scores']}
    elif tamper=='arbitrary-report':report={'passed':True}
    elif tamper=='optional-only':
        for check in report['observed_checks']:check['required']=False
    elif tamper=='output-hashes':report['output_hashes']={}
    elif tamper=='arithmetic':report['average']=100
    elif tamper=='input-hashes':report['artifact_hashes']={}
    elif tamper=='self-independent':report['reviewer']={'agent':'orchestrator','review_type':'independent'}
    elif tamper=='specification':attempt['specification_hash']='f'*64
    elif tamper=='computed-provenance':report['provenance']='server_executed_and_verified'
    elif tamper=='verified-reviewer':report['reviewer']['identity_verification']='os_authenticated'
    elif tamper=='gate-source':next(row for row in tables['workflow_artifacts'] if row['kind']=='plan_gate')['source']='agent'
    elif tamper=='work-input-scope':
        import hashlib
        row=next(row for row in tables['workflow_artifacts'] if row['kind']=='project_plan')
        body=json.loads(row['content']);body['scope_id']='other';row['content']=json.dumps(body);row['sha256']=hashlib.sha256(row['content'].encode()).hexdigest()
        report['artifact_hashes']['project_plan']=row['sha256']
    elif tamper=='journal-missing':tables['journal_entries'].remove(journal)
    elif tamper=='journal-scope':journal['node_id']='plan'
    elif tamper=='journal-report':
        body=json.loads(journal['body']);body['scores']={key:0 for key in body['scores']};journal['body']=json.dumps(body)
    if tamper in {'zero-scores','optional-only','computed-provenance','verified-reviewer','work-input-scope'}:
        # Forge a self-consistent artifact/journal too. Shape checks and matching
        # hashes alone must not let an invalid computed gate or provenance pass.
        import hashlib
        artifact=next(row for row in tables['workflow_artifacts'] if row['kind']=='plan_gate')
        body={key:value for key,value in report.items() if key not in {'output_hashes','output_validation'}}
        artifact['content']=json.dumps(body);artifact['sha256']=hashlib.sha256(artifact['content'].encode()).hexdigest()
        report['output_hashes']['plan_gate']=artifact['sha256']
        journal['body']=json.dumps(report)
    attempt['evidence']=json.dumps(report)
    assert_rejected_atomically(snapshot,tmp_path)


def test_gate_artifact_rehashed_content_must_still_agree_with_attempt_and_journal(store,tmp_path):
    import hashlib
    engine,gate=runtime_gate(store);snapshot=copy.deepcopy(store.snapshot());tables=snapshot['tables']
    attempt=next(row for row in tables['workflow_attempts'] if row['id']==gate['attempt_id']);report=json.loads(attempt['evidence'])
    artifact=next(row for row in tables['workflow_artifacts'] if row['kind']=='plan_gate')
    body=json.loads(artifact['content']);body['scores'][next(iter(body['scores']))]=100
    artifact['content']=json.dumps(body);artifact['sha256']=hashlib.sha256(artifact['content'].encode()).hexdigest()
    report['output_hashes']['plan_gate']=artifact['sha256'];attempt['evidence']=json.dumps(report)
    journal=next(row for row in tables['journal_entries'] if row['id']==report['validation_journal_id'])
    j=json.loads(journal['body']);j['output_hashes']=report['output_hashes'];journal['body']=json.dumps(j)
    assert_rejected_atomically(snapshot,tmp_path,match='Gate artifact does not agree')


@pytest.mark.parametrize('tamper',['orphan-active','counter-gap','epoch-above-transitions','completed-above-transitions',
                                  'missing-ready','routing-inputs','routing-hash'])
def test_runtime_snapshot_state_counters_routing_and_fences_are_validated(store,tmp_path,tamper):
    engine,gate=runtime_gate(store);snapshot=copy.deepcopy(store.snapshot());tables=snapshot['tables']
    run=tables['workflow_runs'][0];state=json.loads(run['state']);routing=json.loads(run['routing'])
    if tamper=='orphan-active':
        row=copy.deepcopy(tables['workflow_attempts'][0]);row.update(id='orphan',number=2,status='running');tables['workflow_attempts'].append(row)
    elif tamper=='counter-gap':tables['workflow_attempts'][0]['number']=2
    elif tamper=='epoch-above-transitions':state['epoch']=state['transitions']+1
    elif tamper=='completed-above-transitions':state['transitions']=1
    elif tamper=='missing-ready':state['phases']['plan'].pop('ready')
    elif tamper=='routing-inputs':routing['inputs']=[]
    elif tamper=='routing-hash':routing['definition_hash']='f'*64
    run['state']=json.dumps(state);run['routing']=json.dumps(routing)
    assert_rejected_atomically(snapshot,tmp_path)


@pytest.mark.parametrize('tamper',['validator-role','join-inputs','join-outputs'])
def test_import_compiler_shape_does_not_replace_runtime_phase_contracts(store,tmp_path,tamper):
    from spoq_server.v1.workflows.definitions import get_strategy
    from spoq_server.v1.workflows.types import StrategyDefinition
    runtime_gate(store);snapshot=copy.deepcopy(store.snapshot())
    definition=get_strategy('piqard').to_dict();definition['id']='invalid-unused-definition'
    if tamper=='validator-role':
        next(phase for phase in definition['phases'] if phase['id']=='plan-validation')['kind']='skill'
    elif tamper=='join-inputs':
        next(phase for phase in definition['phases'] if phase['id']=='design-join')['inputs']=['discovery']
    else:
        next(phase for phase in definition['phases'] if phase['id']=='design-join')['outputs']=['fabricated_output']
    typed=StrategyDefinition.from_dict(definition)
    snapshot['tables']['workflow_definitions'].append({'hash':typed.content_hash,'id':typed.id,'version':typed.version,
                                                      'definition':json.dumps(definition),'created_at':now()})
    assert_rejected_atomically(snapshot,tmp_path,match='gate kind|control-only')


@pytest.mark.parametrize('tamper',['skipped-selected','passed-unselected'])
def test_passed_run_branch_state_matches_pinned_predicates(store,tmp_path,tamper):
    from spoq_server.v1.workflows.types import StrategyDefinition
    populated(store, conditional=tamper == 'passed-unselected');snapshot=copy.deepcopy(store.snapshot());tables=snapshot['tables']
    run=tables['workflow_runs'][0];state=json.loads(run['state'])
    if tamper=='skipped-selected':
        state['phases']['review'].update(status='skipped',attempt_id=None)
        state['outputs'].pop('decision')
    else:
        routing=json.loads(run['routing']);routing['inputs']['take_review']=False
        run['routing']=json.dumps(routing)
    run['state']=json.dumps(state)
    assert_rejected_atomically(snapshot,tmp_path,match='branch selection')


def test_real_piqard_approval_before_decomposition_and_current_gate_survive_roundtrip(store,tmp_path):
    from test_workflow_checkpoints import waiting,reply
    from workflow_support import evidence_for,outputs_for
    engine,review=waiting(store);approved=reply(engine,review)
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    engine=WorkflowEngine(store)
    old_hash=review['specification_hash']
    plan=engine.next('r','orchestrator',key='plan')
    store.create('task','decomposed','Task added after narrative approval','feature')
    plan['specification_hash']=engine.get('r')['current_specification_hash']
    engine.complete('r',plan['attempt_id'],plan['token'],'orchestrator',key='planned',
                    evidence=evidence_for(plan),outputs=outputs_for(plan),refresh_spec=True)
    gate=engine.next('r','orchestrator',key='gate')
    engine.complete('r',gate['attempt_id'],gate['token'],'orchestrator',key='gated',evidence=evidence_for(gate,stage='plan'))
    target=Store(tmp_path/'restored'/'spoq.db');import_snapshot(target,store.snapshot())
    assert target.snapshot()==store.snapshot()
    decision=DecisionRepository(WorkflowRepository(target)).get(approved['decision_id'])
    assert decision['specification_hash']==old_hash!=WorkflowRepository(target).get('r')['specification_hash']


def planned_runtime(store):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for, outputs_for
    engine = WorkflowEngine(store)
    engine.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    call = engine.next('r', 'orchestrator', key='first')
    engine.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='planned',
                    evidence=evidence_for(call), outputs=outputs_for(call))
    return engine, call


@pytest.mark.parametrize('tamper', [
    'empty', 'wrong-identity', 'wrong-spec', 'wrong-inputs', 'missing-checks', 'failed-check',
    'false-acceptance', 'wrong-verdict', 'fake-provenance', 'fake-reviewer', 'self-independent',
    'wrong-output-hash', 'wrong-output-validation', 'missing-journal', 'wrong-journal', 'journal-scope',
])
def test_current_passed_skill_requires_actual_structured_evidence_and_journal(store, tmp_path, tamper):
    _, call = planned_runtime(store)
    snapshot = copy.deepcopy(store.snapshot()); tables = snapshot['tables']
    attempt = next(row for row in tables['workflow_attempts'] if row['id'] == call['attempt_id'])
    report = json.loads(attempt['evidence'])
    journal = next(row for row in tables['journal_entries'] if row['id'] == report['validation_journal_id'])
    if tamper == 'empty': report = {}
    elif tamper == 'wrong-identity': report['attempt_id'] = 'other'
    elif tamper == 'wrong-spec': report['specification_hash'] = 'a' * 64
    elif tamper == 'wrong-inputs': report['artifact_hashes'] = {'invented': 'a' * 64}
    elif tamper == 'missing-checks': report['observed_checks'] = []
    elif tamper == 'failed-check': report['observed_checks'][0]['passed'] = False
    elif tamper == 'false-acceptance': report['acceptance_results'][0]['passed'] = False
    elif tamper == 'wrong-verdict': report['verdict'] = 'FAIL'
    elif tamper == 'fake-provenance': report['provenance'] = 'server_executed'
    elif tamper == 'fake-reviewer': report['reviewer']['identity_verification'] = 'os_authenticated'
    elif tamper == 'self-independent': report['reviewer'] = {'agent': 'orchestrator', 'review_type': 'independent'}
    elif tamper == 'wrong-output-hash': report['output_hashes'] = {}
    elif tamper == 'wrong-output-validation': report['output_validation'] = {'invented': {'source_only': True}}
    elif tamper == 'missing-journal': tables['journal_entries'].remove(journal)
    elif tamper == 'wrong-journal': journal['body'] = '{}'
    elif tamper == 'journal-scope': journal['node_id'] = 'plan'
    attempt['evidence'] = json.dumps(report)
    assert_rejected_atomically(snapshot, tmp_path)


def rehash_current_output(snapshot, output, content):
    """Keep hashes and journal consistent, so semantics must reject the content."""
    import hashlib
    tables = snapshot['tables']
    artifact = next(row for row in tables['workflow_artifacts'] if row['kind'] == output)
    artifact['content'] = content
    artifact['sha256'] = hashlib.sha256(content.encode()).hexdigest()
    attempt = next(row for row in tables['workflow_attempts'] if row['id'] == artifact['attempt_id'])
    report = json.loads(attempt['evidence']); report['output_hashes'][output] = artifact['sha256']
    attempt['evidence'] = json.dumps(report)
    next(row for row in tables['journal_entries'] if row['id'] == report['validation_journal_id'])['body'] = json.dumps(report)


@pytest.mark.parametrize('content', ['{}', 'not JSON', '{"scope_id":"other","specification_hash":"wrong"}'])
def test_rehashed_skill_work_output_must_still_link_exact_scope_and_specification(store, tmp_path, content):
    planned_runtime(store); snapshot = copy.deepcopy(store.snapshot())
    rehash_current_output(snapshot, 'project_plan', content)
    assert_rejected_atomically(snapshot, tmp_path, match='Work-output|JSON')


@pytest.mark.parametrize('registered', [False, 'empty', 'custom'])
@pytest.mark.parametrize('kind,valid,invalid', [
    ('narrative_plan', {key: ['Fixture ' + key] for key in ('scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria')}, {}),
    ('diagram', 'flowchart TD\n A-->B', 'arbitrary source'),
    ('erd', 'erDiagram\n USER ||--o{ TASK : owns', 'flowchart TD\n A-->B'),
    ('algorithm', {key: ['Fixture ' + key] for key in ('inputs', 'outputs', 'invariants', 'complexity')}, {}),
    ('formal', {'status': 'specified', 'specification': 'x >= 0'}, {'status': 'proven', 'specification': 'x >= 0'}),
])
def test_rehashed_passed_design_output_still_obeys_runtime_source_contract(store, tmp_path, kind, valid, invalid, registered):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for
    definition = {'schema_version': 1, 'id': 'design-snapshot', 'version': '1.0.0', 'title': 'Design source fixture',
                  'entry': 'design', 'max_transitions': 3,
                  'phases': [{'id': 'design', 'kind': 'design', 'skill': 'spoq-design', 'inputs': [],
                              'outputs': [kind], 'max_attempts': 1, 'config': {'provider': kind}}], 'edges': []}
    engine = WorkflowEngine(store); engine.start('r', 'feature', definition=definition)
    call = engine.next('r', 'orchestrator', key='design')
    if registered:
        # Registered bytes and raw metadata remain immutable; runtime validates
        # pretty JSON/fenced Mermaid without backfilling derived metadata.
        raw = json.dumps(valid, indent=2) if isinstance(valid, dict) else '```mermaid\n' + valid + '\n```\n'
        raw_metadata = {} if registered == 'empty' else {
            'note': 'Immutable client metadata', 'validation': {'client_label': 'stale'}, 'formal_status': 'old client label'}
        artifact = ArtifactRepository(engine.repository).register('r', call['attempt_id'], kind, raw,
            'fixture-adapter', key='register', expected_revision=engine.get('r')['revision'], metadata=raw_metadata)
        output = {'artifact_id': artifact['id']}
    else:
        output = {'content': valid}
    engine.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='designed',
                    evidence=evidence_for(call), outputs={kind: output})
    if registered:
        assert ArtifactRepository(engine.repository).get(artifact['id'])['metadata'] == raw_metadata
        assert ArtifactRepository(engine.repository).get(artifact['id'])['content'] == raw
    control = Store(tmp_path / 'control' / 'spoq.db'); import_snapshot(control, store.snapshot())
    assert control.snapshot() == store.snapshot()
    snapshot = copy.deepcopy(store.snapshot())
    rehash_current_output(snapshot, kind, json.dumps(invalid) if isinstance(invalid, dict) else invalid)
    assert_rejected_atomically(snapshot, tmp_path)


@pytest.mark.parametrize('tamper', [
    'scope', 'phase', 'attempt', 'definition', 'revision-zero', 'revision-future', 'revision-type',
    'missing-envelope', 'kind', 'skill', 'config', 'expected-outputs', 'status', 'token-type', 'token-fence',
    'lease', 'flag', 'input-scope', 'input-hashes', 'prior-artifact', 'work', 'invocation-spec',
] + ['missing:' + field for field in ('phase_id', 'kind', 'skill', 'token', 'attempt_id', 'expected_outputs', 'config', 'status', 'scope_id')])
def test_invocation_receipt_cannot_replay_a_forged_envelope_after_import(store, tmp_path, tamper):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    engine = WorkflowEngine(store); engine.start('r', 'feature', strategy='classic')
    engine.next('r', 'orchestrator', key='first')
    snapshot = copy.deepcopy(store.snapshot()); tables = snapshot['tables']
    receipt = next(row for row in tables['workflow_receipts'] if row['key'] == 'first')
    result = json.loads(receipt['result'])
    if tamper.startswith('missing:'): result.pop(tamper.split(':', 1)[1])
    elif tamper == 'scope': result['scope_id'] = 'other/private'
    elif tamper == 'phase': result['phase_id'] = 'invented'
    elif tamper == 'attempt': result['attempt_id'] = 'missing'
    elif tamper == 'definition': result['definition_hash'] = 'a' * 64
    elif tamper == 'revision-zero': result['revision'] = 0
    elif tamper == 'revision-future': result['revision'] = 1000
    elif tamper == 'revision-type': result['revision'] = True
    elif tamper == 'missing-envelope': result.pop('inputs')
    elif tamper == 'kind': result['kind'] = 'human'
    elif tamper == 'skill': result['skill'] = 'arbitrary-command'
    elif tamper == 'config': result['config'] = {'provider': 'invented'}
    elif tamper == 'expected-outputs': result['expected_outputs'] = ['invented']
    elif tamper == 'status': result['status'] = 'passed'
    elif tamper == 'token-type': result['token'] = []
    elif tamper == 'token-fence': result['token'] = 'forged-token'
    elif tamper == 'lease': result['lease_until'] = -1
    elif tamper == 'flag': result['needs_inspection'] = 'yes'
    elif tamper == 'input-scope': result['inputs']['scope'] = 'other'
    elif tamper == 'input-hashes': result['artifact_hashes'] = {'invented': 'a' * 64}
    elif tamper == 'prior-artifact': result['prior_artifacts'] = [{'id': 'missing'}]
    elif tamper == 'work': result['work'] = {'scope_id': 'other'}
    elif tamper == 'invocation-spec': result['specification_hash'] = 'a' * 64
    receipt['result'] = json.dumps(result)
    assert_rejected_atomically(snapshot, tmp_path)


@pytest.mark.parametrize('tamper', ['artifact-scope', 'artifact-hash', 'artifact-kind', 'human-token', 'human-lease'])
def test_human_receipt_inputs_retain_exact_scoped_immutable_artifacts(store, tmp_path, tamper):
    populated(store); snapshot = copy.deepcopy(store.snapshot())
    receipt = next(row for row in snapshot['tables']['workflow_receipts'] if row['key'] == 'review')
    result = json.loads(receipt['result'])
    artifact = result['inputs']['narrative_plan']
    if tamper == 'artifact-scope': artifact['scope_id'] = 'other'
    elif tamper == 'artifact-hash': artifact['sha256'] = 'a' * 64
    elif tamper == 'artifact-kind': artifact['kind'] = 'discovery'
    elif tamper == 'human-token': result['token'] = 'worker-fence'
    else: result['lease_until'] = 9999999999
    receipt['result'] = json.dumps(result)
    assert_rejected_atomically(snapshot, tmp_path)


def test_recovered_and_completed_invocation_receipts_preserve_old_fences_but_cannot_advance(store, tmp_path):
    from unittest.mock import patch
    import time
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for, outputs_for
    engine = WorkflowEngine(store); engine.start('r', 'feature', strategy='classic')
    first = engine.next('r', 'orchestrator', key='first', ttl=1)
    with patch('spoq_server.v1.workflows.leases.time.time', return_value=time.time() + 2):
        recovered = engine.next('r', 'orchestrator', key='recover', recover=True)
    assert first['attempt_id'] == recovered['attempt_id'] and first['token'] != recovered['token']
    completed = engine.complete('r', recovered['attempt_id'], recovered['token'], 'orchestrator', key='planned',
                                evidence=evidence_for(recovered), outputs=outputs_for(recovered))
    target = Store(tmp_path / 'restored' / 'spoq.db'); import_snapshot(target, store.snapshot())
    assert target.snapshot() == store.snapshot()
    restored = WorkflowEngine(target)
    assert restored.next('r', 'orchestrator', key='first', ttl=1) == first
    assert restored.next('r', 'orchestrator', key='recover', recover=True) == recovered
    assert restored.complete('r', recovered['attempt_id'], recovered['token'], 'orchestrator', key='planned',
                             evidence=evidence_for(recovered), outputs=outputs_for(recovered)) == completed
    with pytest.raises(ValueError, match='Stale'):
        restored.complete('r', first['attempt_id'], first['token'], 'orchestrator', key='stale',
                          evidence=evidence_for(first), outputs=outputs_for(first))
    assert restored.next('r', 'orchestrator', key='after-restored')['phase_id'] == 'plan-validation'


def test_task_scoped_execution_receipt_survives_task_completion_and_roundtrip(store, tmp_path):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for, outputs_for
    store.create('task', 'task', 'Task-scoped fixture', 'feature')
    definition = {'schema_version': 1, 'id': 'execution-snapshot', 'version': '1.0.0', 'title': 'Task scope fixture',
                  'entry': 'execute', 'max_transitions': 3,
                  'phases': [{'id': 'execute', 'kind': 'skill', 'skill': 'spoq-execution', 'inputs': ['scope'],
                              'outputs': ['implementation'], 'max_attempts': 1}], 'edges': []}
    engine = WorkflowEngine(store); engine.start('r', 'task', definition=definition)
    call = engine.next('r', 'orchestrator', key='execute')
    assert call['work']['ready_tasks'] == ['task']
    claim = store.claim('task', 'r', 'orchestrator')
    store.update('task', 'completed', evidence={'fixture': 'explicit scripted check'}, claim_token=claim['token'])
    engine.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='executed',
                    evidence=evidence_for(call), outputs=outputs_for(call))
    target = Store(tmp_path / 'restored' / 'spoq.db'); import_snapshot(target, store.snapshot())
    assert target.snapshot() == store.snapshot()
    # Historical work status/counts need not equal today's completed graph.
    assert WorkflowEngine(target).next('r', 'orchestrator', key='execute') == call
    for tamper in ('scope', 'ready', 'remaining'):
        snapshot = copy.deepcopy(store.snapshot())
        receipt = next(row for row in snapshot['tables']['workflow_receipts'] if row['key'] == 'execute')
        result = json.loads(receipt['result'])
        if tamper == 'scope': result['work']['scope_id'] = 'feature'
        elif tamper == 'ready': result['work']['ready_tasks'] = ['feature']
        else: result['work']['remaining_tasks'] = ['not-present']
        receipt['result'] = json.dumps(result)
        assert_rejected_atomically(snapshot, tmp_path / tamper)


def test_required_formal_proof_cannot_be_downgraded_in_a_rehashed_passed_snapshot(store, tmp_path):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from workflow_support import evidence_for
    definition = {'schema_version': 1, 'id': 'proof-snapshot', 'version': '1.0.0', 'title': 'Required proof fixture',
                  'entry': 'proof', 'max_transitions': 3,
                  'phases': [{'id': 'proof', 'kind': 'design', 'skill': 'spoq-design', 'inputs': [],
                              'outputs': ['formal'], 'max_attempts': 1, 'config': {'provider': 'formal'}}], 'edges': []}
    engine = WorkflowEngine(store)
    engine.start('r', 'feature', {'formal_proof_required': True}, definition=definition)
    call = engine.next('r', 'orchestrator', key='proof')
    proof = {'status': 'proven', 'specification': 'x = x', 'proof': 'Reflexivity', 'assumptions': [],
             'verifier': {'tool': 'fixture-verifier', 'version': '1', 'source': 'scripted fixture, not an actual solver',
                          'result': 'recorded fixture success', 'command': ['fixture-verifier'], 'exit_code': 0, 'observed': True}}
    engine.complete('r', call['attempt_id'], call['token'], 'orchestrator', key='proven',
                    evidence=evidence_for(call), outputs={'formal': {'content': proof}})
    target = Store(tmp_path / 'control' / 'spoq.db'); import_snapshot(target, store.snapshot())
    assert target.snapshot() == store.snapshot()
    snapshot = copy.deepcopy(store.snapshot())
    rehash_current_output(snapshot, 'formal', json.dumps({'status': 'specified', 'specification': 'x = x'}))
    artifact = next(row for row in snapshot['tables']['workflow_artifacts'] if row['kind'] == 'formal')
    metadata = json.loads(artifact['metadata']); metadata['formal_status'] = 'specified'; artifact['metadata'] = json.dumps(metadata)
    assert_rejected_atomically(snapshot, tmp_path, match='Required proof')


@pytest.mark.parametrize('producer_phase', ['review', 'draft'])
def test_receipt_input_cannot_substitute_an_undeclared_auxiliary_artifact(store, tmp_path, producer_phase):
    from spoq_server.v1.workflows.artifacts import parse_artifact
    populated(store)
    with transaction(store.path, write=True) as db:
        # Auxiliary notes are valid stored artifacts. They are not phase outputs.
        attempt = db.execute("SELECT id FROM workflow_attempts WHERE phase_id=?", (producer_phase,)).fetchone()[0]
        note = ArtifactRepository.add(db, 'workflow-run', attempt, 'narrative_plan', 'Auxiliary note', 'worker')
        descriptor = parse_artifact(db.execute('SELECT * FROM workflow_artifacts WHERE id=?', (note['id'],)).fetchone())
    descriptor['content_bytes'] = len(descriptor.pop('content').encode())
    control = Store(tmp_path / 'auxiliary-control' / 'spoq.db'); import_snapshot(control, store.snapshot())
    assert control.snapshot() == store.snapshot()
    snapshot = copy.deepcopy(store.snapshot())
    receipt = next(row for row in snapshot['tables']['workflow_receipts'] if row['key'] == 'review')
    result = json.loads(receipt['result']); result['inputs']['narrative_plan'] = descriptor
    result['artifact_hashes']['narrative_plan'] = descriptor['sha256']; receipt['result'] = json.dumps(result)
    assert_rejected_atomically(snapshot, tmp_path, match='passed declared output producer|published output')


def test_real_piqard_rejection_revision_and_paused_response_history_roundtrips(store, tmp_path):
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from test_workflow_checkpoints import waiting, reply, narrative
    from workflow_support import evidence_for
    runner, first = waiting(store); reply(runner, first, 'reject')
    engine = WorkflowEngine(store)
    draft = engine.next('r', 'orchestrator', key='narrative-v2')
    engine.complete('r', draft['attempt_id'], draft['token'], 'orchestrator', key='drafted-v2',
                    evidence=evidence_for(draft), outputs={'narrative_plan': {'content': narrative('two')}})
    second = engine.next('r', 'orchestrator', key='review-v2')
    engine.pause('r', 'orchestrator', key='pause')
    approved = reply(engine, second, key='approve-v2')
    assert approved['status'] == 'paused'
    engine.resume('r', 'orchestrator', key='resume')
    target = Store(tmp_path / 'restored' / 'spoq.db'); import_snapshot(target, store.snapshot())
    assert target.snapshot() == store.snapshot()
    restored = WorkflowEngine(target)
    assert restored.next('r', 'orchestrator', key='review') == first
    assert restored.next('r', 'orchestrator', key='review-v2') == second
    assert reply(restored, second, key='approve-v2') == approved
    with pytest.raises(ValueError): reply(restored, first, key='stale-old-approval')
    assert restored.next('r', 'orchestrator', key='decompose')['phase_id'] == 'plan'
