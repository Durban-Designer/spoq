from pathlib import Path
import pytest
from spoq_server.v1.store import Store
from spoq_server.v1.board import Board


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path/'.spoq/spoq.db')
    value.create('project_plan','plan','Project Plan')
    value.create('feature','feature','Feature','plan')
    return value


@pytest.fixture
def board(store):
    value=Board(store)
    value.run('run','feature')
    for name,role in [('orchestrator','orchestrator'),('backend','worker'),('frontend','worker'),('qa','reviewer')]:
        value.register('run',name,role)
    return value


@pytest.fixture
def legacy(tmp_path):
    for slug in ('api','ui'):
        path=tmp_path/'spoq/epics/active'/slug
        (path/'tasks').mkdir(parents=True)
        (path/'EPIC.md').write_text(f'---\nslug: {slug}\ntitle: {slug}\n---\n# {slug}\n')
        (path/'tasks/01-work.yml').write_text(f'id: work\ntitle: {slug} work\nstatus: pending\ndependencies: []\n')
    maps=tmp_path/'spoq/maps/active'
    maps.mkdir(parents=True)
    (maps/'checkout.md').write_text('# Map: Checkout\n\n## Epics\n\n### api\n**Dependencies:** none\n\n### ui\n**Dependencies:** api\n')
    (tmp_path/'journal.md').write_text('# Journal\n---\nagent: Old Agent\n---\n## Summary\nFixed a difficult bug.\n---\nSome irregular text.\n')
    return tmp_path
