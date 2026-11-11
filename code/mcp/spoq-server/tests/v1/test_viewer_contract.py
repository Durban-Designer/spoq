"""Contract fixtures are checked without pretending to exercise the future UI."""
import copy
import json
from pathlib import Path

import pytest

from spoq_server.v1.workflows.types import validate_viewer_snapshot


def fixture():
    root = Path(__file__).resolve().parents[5]
    return json.loads((root / 'tests/fixtures/spoq-1.1/viewer-contract.json').read_text())


def test_review_snapshot_retains_definition_attempt_and_work_identities():
    value = validate_viewer_snapshot(fixture())
    assert value['run']['status'] == 'waiting_human'
    assert value['routing']['reasons']
    assert value['definition']['edges'][1]['on'] == 'fail'
    assert value['phases'][0]['id'] != value['attempts'][0]['id']
    assert value['work']['nodes'][0]['kind'] == 'project_plan'
    assert not any(k in value for k in ('percent_complete', 'predicted_cost'))


@pytest.mark.parametrize('field', ['cursor', 'routing', 'work', 'attempts', 'decisions', 'blockers'])
def test_missing_projection_is_rejected(field):
    value = fixture()
    del value[field]
    with pytest.raises(ValueError):
        validate_viewer_snapshot(value)


@pytest.mark.parametrize('cursor', [-1, True, '42', 2**63])
def test_cursor_is_an_ordered_nonnegative_sqlite_identity(cursor):
    value = fixture()
    value['cursor'] = cursor
    with pytest.raises(ValueError):
        validate_viewer_snapshot(value)


@pytest.mark.parametrize('status', ['queued', 'running', 'waiting_human', 'blocked', 'failed', 'passed', 'skipped', 'paused'])
def test_all_visible_states_are_explicit(status):
    value = fixture()
    value['phases'][0]['status'] = status
    assert validate_viewer_snapshot(value)['phases'][0]['status'] == status


def test_unknown_state_or_nonfinite_projection_is_rejected():
    value = fixture()
    value['phases'][0]['status'] = 'probably_done'
    with pytest.raises(ValueError):
        validate_viewer_snapshot(value)
    value = fixture()
    value['routing']['cost'] = float('nan')
    with pytest.raises(ValueError):
        validate_viewer_snapshot(value)


def test_legacy_runs_can_report_unknown_provenance_without_fake_attempts():
    value = fixture()
    value['run']['provenance'] = 'legacy_unclassified'
    for key in ('phases', 'attempts', 'artifacts', 'decisions'):
        value[key] = []
    value['definition'] = {}
    value['routing'] = {'strategy': 'legacy_unclassified'}
    assert validate_viewer_snapshot(copy.deepcopy(value)) == value
