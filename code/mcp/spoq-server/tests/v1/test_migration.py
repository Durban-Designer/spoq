import hashlib
import json
import zipfile
import pytest
from spoq_server.v1.migration import migrate,status,get_store,database_path
from spoq_server.v1.store import Store
from spoq_server.v1.db import transaction
from spoq_server.v1.cli import init,import_snapshot


def test_upgrade_requires_confirmation_and_writes_nothing(legacy):
    before={p:p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    report=migrate(legacy)
    assert report['confirmation_required']
    assert report['preview']['counts']=={'epics':2,'feature_maps':1,'tasks':2}
    assert not database_path(legacy).exists()
    assert all(p.read_bytes()==content for p,content in before.items())
    with pytest.raises(ValueError,match='Convert'): get_store(legacy)


def test_maps_become_plans_and_epics_features_with_both_dags(legacy):
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    plans=[p for p in store.list('project_plan') if p['id']!='workspace']
    assert len(plans)==1 and plans[0]['title']=='Checkout'
    features=store.list('feature',plans[0]['id'])
    assert len(features)==2
    lookup={f['title']:f['id'] for f in features}
    dag=store.dag(plans[0]['id'])
    assert dag['dependencies'][lookup['ui']]==[lookup['api']]
    assert len(store.dag(lookup['api'])['ready'])==1
    assert store.dag(lookup['ui'])['ready']==[]
    assert len(store.list('task'))==2
    assert 'irregular text' in '\n'.join(e['body'] for e in store.journals())
    assert migrate(legacy,confirmed=True)['already_migrated']


def test_backup_and_database_sources_are_byte_exact(legacy):
    before={p.relative_to(legacy).as_posix():p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    report=migrate(legacy,confirmed=True)
    with zipfile.ZipFile(report['backup']) as archive:
        assert set(archive.namelist())==set(before)
        assert all(archive.read(name)==data for name,data in before.items())
    with transaction(database_path(legacy)) as db:
        for row in db.execute('SELECT * FROM legacy_sources'):
            assert row['content']==before[row['path']]
            assert row['sha256']==hashlib.sha256(row['content']).hexdigest()


def test_invalid_dependency_blocks_feature_and_preserves_source(legacy):
    task=legacy/'spoq/epics/active/api/tasks/01-work.yml'
    task.write_text(task.read_text().replace('dependencies: []','dependencies: [missing]'))
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    feature=next(f for f in store.list('feature') if f['title']=='api')
    assert feature['status']=='blocked'
    assert store.dag(feature['id'])['ready']==[]
    assert report['warnings']


def test_missing_feature_dependency_blocks_imported_project_plan(legacy):
    path=legacy/'spoq/maps/active/checkout.md'
    path.write_text(path.read_text().replace('**Dependencies:** api','**Dependencies:** missing'))
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    plan=next(n for n in store.list('project_plan') if n['id']!='workspace')
    assert plan['status']=='blocked' and report['warnings']
    assert all(store.dag(f['id'])['ready']==[] for f in store.list('feature'))


def test_snapshot_roundtrip_restores_dags_and_searchable_journal(store,tmp_path):
    store.create('task','a','A','feature')
    store.journal('SQLite decision',node_id='feature')
    other=Store(tmp_path/'other.db')
    snapshot=store.snapshot()
    assert import_snapshot(other,snapshot)['imported']
    assert other.snapshot()==snapshot
    with pytest.raises(ValueError,match='empty'): import_snapshot(other,snapshot)


def test_noninteractive_init_does_not_silently_convert(legacy,monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty',lambda:False)
    with pytest.raises(ValueError,match='confirmation'): init(legacy,upgrade=True)
    assert not database_path(legacy).exists()


def test_fresh_init_installs_new_guidance_and_gitignore(tmp_path):
    result=init(tmp_path,agents='codex',with_mcp=True,full=True)
    assert result['initialized']
    assert 'Project Plans → Features → Tasks' in (tmp_path/'AGENTS.md').read_text()
    assert '.spoq/' in (tmp_path/'.gitignore').read_text()
    assert (tmp_path/'.codex/config.toml').exists()
    assert len(Store(database_path(tmp_path)).list('task'))==1


def test_snapshot_rejects_containment_cycle_atomically(store,tmp_path):
    snapshot=store.snapshot()
    next(n for n in snapshot['tables']['nodes'] if n['kind']=='project_plan')['parent_id']='plan'
    target=Store(tmp_path/'other.db')
    with pytest.raises(ValueError,match='hierarchy'): import_snapshot(target,snapshot)
    assert target.list()==[]


def test_migrated_provenance_survives_export_import(legacy,tmp_path):
    migrate(legacy,confirmed=True)
    source=Store(database_path(legacy))
    target=Store(tmp_path/'restored.db')
    snapshot=source.snapshot()
    import_snapshot(target,snapshot)
    assert target.snapshot()==snapshot


def test_ancillary_map_documents_are_not_project_plans(legacy):
    folder=legacy/'spoq/maps/active/nested-map'
    folder.mkdir()
    (folder/'HANDOFF.md').write_text('# Handoff\nSome notes')
    assert migrate(legacy)['preview']['counts']['feature_maps']==1


def test_malformed_task_blocks_owning_feature(legacy):
    (legacy/'spoq/epics/active/api/tasks/broken.yml').write_text('invalid: [')
    migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    feature=next(f for f in store.list('feature') if f['title']=='api')
    assert feature['status']=='blocked' and store.dag(feature['id'])['ready']==[]


def test_export_cannot_overwrite_database_through_direct_or_symlink_path(store,tmp_path):
    from spoq_server.v1.cli import write_snapshot
    for path in (store.path,tmp_path/'linked.db'):
        if path!=store.path: path.symlink_to(store.path)
        with pytest.raises(ValueError,match='outside'): write_snapshot(store,path,force=True)
    assert store.get('feature')['title']=='Feature'


def test_shared_epic_membership_blocks_both_plans(legacy):
    path=legacy/'spoq/maps/active/checkout.md'
    (path.parent/'second.md').write_text(path.read_text().replace('Checkout','Second'))
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    assert any('shared' in warning for warning in report['warnings'])
    assert all(store.dag(feature['id'])['ready']==[] for feature in store.list('feature'))


def test_frontmatter_only_map_membership(legacy):
    (legacy/'spoq/maps/active/checkout.md').write_text('---\nslug: checkout\ntitle: Checkout\nepics:\n  - api\n  - slug: ui\n    dependencies: [api]\n---\n# Checkout\n')
    migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    plan=next(p for p in store.list('project_plan') if p['id']!='workspace')
    assert len(store.list('feature',plan['id']))==2
    assert len(store.dag(plan['id'])['waves'])==2


def test_journal_metadata_and_orphan_tasks_are_converted(legacy):
    tasks=legacy/'spoq/epics/active/orphan/tasks'
    tasks.mkdir(parents=True)
    (tasks/'task.yml').write_text('id: orphan\ntitle: Orphan work')
    migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    assert any(t['title']=='Orphan work' for t in store.list('task'))
    assert any(e['agent']=='Old Agent' for e in store.journals())


def test_snapshot_rejects_cross_run_message_thread(store,board,tmp_path):
    first=board.post('run','backend',['qa'],'First',request_key='first')
    board.run('other')
    board.register('other','worker','worker')
    board.register('other','reviewer','reviewer')
    second=board.post('other','worker',['reviewer'],'Second',request_key='second')
    snapshot=store.snapshot()
    next(m for m in snapshot['tables']['messages'] if m['id']==second['id'])['thread_id']=first['thread_id']
    target=Store(tmp_path/'other.db')
    with pytest.raises(ValueError,match='isolation'): import_snapshot(target,snapshot)
    assert target.list()==[]


def test_completed_history_keeps_dependencies_during_migration(legacy):
    folder=legacy/'spoq/epics/active/api/tasks'
    (folder/'01-work.yml').write_text('id: first\ntitle: First\nstatus: completed\n')
    (folder/'02-work.yml').write_text('id: second\ntitle: Second\nstatus: completed\ndependencies: [first]\n')
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    feature=next(f for f in store.list('feature') if f['title']=='api')
    assert len(store.dag(feature['id'])['waves'])==2
    assert feature['status']=='completed' and not report['warnings']


@pytest.mark.parametrize('header',['|','| # prose','|2-','|-2'])
def test_legacy_checkbox_recovery_preserves_description_and_raw_bytes(legacy,header):
    path=legacy/'spoq/epics/active/api/tasks/01-work.yml'
    content=f'id: work\ntitle: Work\nacceptance_criteria:\n  - [ ] Tests pass: all suites\ndescription: {header}\n  - [ ] Keep this narrative verbatim\n'
    path.write_text(content)
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    task=next(t for t in store.list('task') if t['title']=='Work')
    assert task['data']['acceptance_criteria']==['[ ] Tests pass: all suites']
    assert task['data']['description']=='- [ ] Keep this narrative verbatim'+('' if '-' in header else '\n')
    assert path.read_text()==content
    assert any('recovered' in w for w in report['warnings'])


def test_scalar_dependencies_are_preserved_and_blocked(legacy):
    path=legacy/'spoq/epics/active/api/tasks/01-work.yml'
    path.write_text('id: work\ntitle: Work\ndependencies: 123\n')
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    feature=next(f for f in store.list('feature') if f['title']=='api')
    assert feature['status']=='blocked' and report['warnings']
    assert store.list('task',feature['id'])[0]['data']['dependencies']==123


@pytest.mark.parametrize('content',['standalone: 123','sections: [123]','sections: [{items: 123}]','standalone: [123]'])
def test_malformed_tracker_blocks_owning_feature_without_aborting(legacy,content):
    (legacy/'TODO.yml').write_text(content)
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    feature=next(f for f in store.list('feature') if f['title']=='Task tracker')
    assert feature['status']=='blocked' and report['warnings']


def test_string_false_does_not_complete_tracker_task(legacy):
    (legacy/'TODO.yml').write_text('standalone:\n  - title: Still unfinished\n    done: "false"\n')
    report=migrate(legacy,confirmed=True)
    store=Store(database_path(legacy))
    task=next(t for t in store.list('task') if t['title']=='Still unfinished')
    assert task['status']=='pending' and report['warnings']
