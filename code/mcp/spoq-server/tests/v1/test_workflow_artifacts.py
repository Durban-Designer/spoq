"""Actual artifact revisions and human attestations cross the persistence boundary."""
import hashlib
import json

import pytest

from spoq_server.v1.db import transaction, now
from spoq_server.v1.workflows.artifacts import ArtifactRepository, MAX_CONTENT_BYTES
from spoq_server.v1.workflows.decisions import DecisionRepository
from spoq_server.v1.workflows.repository import WorkflowRepository


def fixture(store):
    definition = {'schema_version': 1, 'id': 'piqard-test', 'version': '1.0.0', 'title': 'PIQARD',
                  'entry': 'draft', 'max_transitions': 9,
                  'phases': [{'id': 'draft', 'kind': 'skill', 'skill': 'spoq-discover', 'inputs': [], 'outputs': ['narrative_plan'], 'max_attempts': 3},
                             {'id': 'review', 'kind': 'human', 'skill': None, 'inputs': ['narrative_plan'], 'outputs': ['decision'], 'max_attempts': 3}],
                  'edges': [{'source': 'draft', 'target': 'review'}, {'source': 'review', 'target': 'draft', 'on': 'fail'}]}
    repo = WorkflowRepository(store)
    repo.start('run', 'feature', definition, {}, {'phases': {'draft': {'status': 'passed', 'attempt_id': 'draft-1'}, 'review': {'status': 'waiting_human', 'attempt_id': 'review-1'}}, 'outputs': {}, 'transitions': 0}, 'start')
    with transaction(store.path, write=True) as db:
        current = WorkflowRepository._get(db, 'run')
        for attempt_id, phase, status in [('draft-1', 'draft', 'passed'), ('review-1', 'review', 'waiting_human')]:
            db.execute('INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (attempt_id, 'run', phase, 1, status, 'worker', 'token', 9999999999,
                        current['specification_hash'], '{}', now(), now()))
    return repo, ArtifactRepository(repo), DecisionRepository(repo)


def current_output(repo, artifact_id):
    current = repo.get('run')
    def op(db, run):
        run['state']['outputs']['narrative_plan'] = artifact_id
        return {'state': run['state'], 'status': 'waiting_human', 'event_kind': 'test_output'}
    return repo.mutate('run', 'output-' + artifact_id, current['revision'], 'worker', op, request={'artifact': artifact_id})


@pytest.mark.parametrize('kind', ['narrative_plan', 'diagram', 'erd', 'algorithm', 'formal'])
def test_registered_content_has_provenance_hash_and_persisted_references(store, kind):
    repo, artifacts, decisions = fixture(store)
    content = '# Scope\nReviewed export of a plan with decisions.'
    metadata = {'url': 'https://example.atlassian.net/wiki/pages/123', 'version': '7', 'reviewed_export': True}
    row = artifacts.register('run', 'draft-1', kind, content, 'Alice Smith', source='user', metadata=metadata,
                             key='artifact', expected_revision=1)
    assert row['scope_id'] == 'feature' and row['attempt_id'] == 'draft-1'
    assert row['author'] == 'Alice Smith' and row['source'] == 'user' and row['created_at']
    assert row['sha256'] == hashlib.sha256(content.encode()).hexdigest()
    assert artifacts.get(row['id'])['metadata'] == metadata
    assert artifacts.get(row['id'])['content'] == content
    duplicate = artifacts.register('run', 'draft-1', kind, content, 'Alice Smith', source='user', metadata=metadata,
                                   key='artifact', expected_revision=999)
    assert duplicate == row
    assert len(artifacts.list('run')) == 1
    assert 'content' not in artifacts.list('run')[0]
    with pytest.raises(ValueError, match='different request'):
        artifacts.register('run', 'draft-1', kind, 'Changed bytes', 'Alice Smith', source='user', metadata=metadata,
                           key='artifact', expected_revision=2)


@pytest.mark.parametrize('content', ['', '  ', b'\xff', 'x' * (MAX_CONTENT_BYTES + 1)])
def test_empty_reference_only_invalid_or_oversized_content_rejected(store, content):
    repo, artifacts, decisions = fixture(store)
    with pytest.raises(ValueError):
        artifacts.register('run', 'draft-1', 'narrative_plan', content, 'worker', key='artifact', expected_revision=1,
                           metadata={'url': 'https://example.atlassian.net/wiki/pages/123'})
    assert artifacts.list('run') == []
    assert repo.get('run')['revision'] == 1


def test_artifact_attempt_cannot_cross_runs(store):
    repo, artifacts, decisions = fixture(store)
    definition = repo.get('run')['definition']
    repo.start('other', 'feature', definition, {}, {}, 'start')
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='same workflow run'):
        ArtifactRepository.add(db, 'other', 'draft-1', 'narrative_plan', 'Plan', 'worker')


def test_user_decision_records_exact_revision_and_later_output_invalidates_it(store):
    repo, artifacts, decisions = fixture(store)
    first = artifacts.register('run', 'draft-1', 'narrative_plan', 'Revision one', 'worker', key='first', expected_revision=1)
    current_output(repo, first['id'])
    with transaction(store.path, write=True) as db:
        row = DecisionRepository.add(db, 'run', 'review-1', first['id'], first['sha256'], 'approve', 'Human',
                                     source='user', user_confirmed=True)
    assert row['source'] == 'user' and row['decision'] == 'approve'
    assert row['specification_hash'] == repo.get('run')['specification_hash']
    assert row['artifact_hash'] == first['sha256'] and row['definition_hash'] == repo.get('run')['definition_hash']
    assert decisions.is_current(row['id'])
    second = artifacts.register('run', 'draft-1', 'narrative_plan', 'Revision two', 'worker', key='second', expected_revision=3)
    current_output(repo, second['id'])
    assert not decisions.is_current(row['id'])
    assert decisions.get(row['id'])['artifact_id'] == first['id']
    assert len(artifacts.list('run')) == 2 and len(decisions.list('run')) == 1
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='no longer'):
        DecisionRepository.add(db, 'run', 'review-1', first['id'], first['sha256'], 'approve', 'Human',
                               source='user', user_confirmed=True)


@pytest.mark.parametrize('source,confirmed', [('agent', True), ('peer', True), ('notification', True), ('user', False), ('user', 'yes')])
def test_peer_or_inferred_actions_cannot_satisfy_human_response(store, source, confirmed):
    repo, artifacts, decisions = fixture(store)
    row = artifacts.register('run', 'draft-1', 'narrative_plan', 'Plan', 'worker', key='artifact', expected_revision=1)
    current_output(repo, row['id'])
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='user-originated'):
        DecisionRepository.add(db, 'run', 'review-1', row['id'], row['sha256'], 'approve', 'Human',
                               source=source, user_confirmed=confirmed)
    assert decisions.list('run') == []


def test_changed_specification_or_wrong_artifact_hash_rejects_response(store):
    repo, artifacts, decisions = fixture(store)
    row = artifacts.register('run', 'draft-1', 'narrative_plan', 'Plan', 'worker', key='artifact', expected_revision=1)
    current_output(repo, row['id'])
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='revision does not match'):
        DecisionRepository.add(db, 'run', 'review-1', row['id'], 'f' * 64, 'approve', 'Human', source='user', user_confirmed=True)
    store.edit('feature', {'acceptance_criteria': ['Different goal']})
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='Specification changed'):
        DecisionRepository.add(db, 'run', 'review-1', row['id'], row['sha256'], 'approve', 'Human', source='user', user_confirmed=True)


def test_nonhuman_or_completed_attempt_cannot_accept_human_response(store):
    repo, artifacts, decisions = fixture(store)
    row = artifacts.register('run', 'draft-1', 'narrative_plan', 'Plan', 'worker', key='artifact', expected_revision=1)
    current_output(repo, row['id'])
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='active waiting_human'):
        DecisionRepository.add(db, 'run', 'draft-1', row['id'], row['sha256'], 'approve', 'Human', source='user', user_confirmed=True)


def test_wrong_current_output_cannot_approve_a_different_review_input(store):
    repo, artifacts, decisions = fixture(store)
    right = artifacts.register('run', 'draft-1', 'narrative_plan', 'Narrative', 'worker', key='right', expected_revision=1)
    current_output(repo, right['id'])
    wrong = artifacts.register('run', 'draft-1', 'discovery', 'Wrong content to review', 'worker', key='wrong', expected_revision=3)
    def wrong_output(db, current):
        current['state']['outputs']['discovery'] = wrong['id']
        return {'state': current['state'], 'status': current['status'], 'event_kind': 'test_output'}
    repo.mutate('run', 'wrong-output', 4, 'worker', wrong_output, request={})
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='required review input'):
        DecisionRepository.add(db, 'run', 'review-1', wrong['id'], wrong['sha256'], 'approve', 'Human', source='user', user_confirmed=True)
    assert decisions.list('run') == []


def test_reworked_human_attempt_invalidates_old_response_even_when_artifact_unchanged(store):
    repo, artifacts, decisions = fixture(store)
    artifact = artifacts.register('run', 'draft-1', 'narrative_plan', 'Plan', 'worker', key='artifact', expected_revision=1)
    current_output(repo, artifact['id'])
    with transaction(store.path, write=True) as db:
        row = DecisionRepository.add(db, 'run', 'review-1', artifact['id'], artifact['sha256'], 'approve', 'Human', source='user', user_confirmed=True)
    assert decisions.is_current(row['id'])
    def rework(db, current):
        current['state']['phases']['review'] = {'status': 'queued', 'attempt_id': None}
        return {'state': current['state'], 'status': 'running', 'event_kind': 'rework'}
    repo.mutate('run', 'rework', 3, 'worker', rework, request={})
    assert not decisions.is_current(row['id'])
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='active waiting_human'):
        DecisionRepository.add(db, 'run', 'review-1', artifact['id'], artifact['sha256'], 'approve', 'Human', source='user', user_confirmed=True)


@pytest.mark.parametrize('decision', [[], {}, None, False, 1, '', 'maybe'])
def test_malformed_decision_json_has_deliberate_validation_error(store, decision):
    repo, artifacts, decisions = fixture(store)
    row = artifacts.register('run', 'draft-1', 'narrative_plan', 'Plan', 'worker', key='artifact', expected_revision=1)
    current_output(repo, row['id'])
    with transaction(store.path, write=True) as db, pytest.raises(ValueError, match='approve or reject'):
        DecisionRepository.add(db, 'run', 'review-1', row['id'], row['sha256'], decision, 'Human', source='user', user_confirmed=True)


def test_list_projects_metadata_without_materializing_content_in_python(store, monkeypatch):
    repo, artifacts, decisions = fixture(store)
    text = 'Résumé ' * 2000
    row = artifacts.register('run', 'draft-1', 'narrative_plan', text, 'worker', key='artifact', expected_revision=1)
    import spoq_server.v1.workflows.artifacts as module
    original = module.parse_artifact
    def metadata_only(raw):
        # The SQL projection itself must omit content, rather than loading up to
        # 500MiB of text and dropping it only after building a Python object.
        assert 'content' not in raw.keys()
        return original(raw)
    monkeypatch.setattr(module, 'parse_artifact', metadata_only)
    listed = artifacts.list('run')
    assert listed[0]['content_bytes'] == len(text.encode())
    assert listed[0]['sha256'] == row['sha256'] and 'content' not in listed[0]
