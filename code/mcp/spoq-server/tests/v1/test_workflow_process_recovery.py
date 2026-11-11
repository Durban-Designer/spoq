"""Forced subprocess termination tests; test-only hooks exercise actual SQLite commits."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
import spoq_server


def driver():
    path=Path(__file__).resolve().parents[5]/'tests/e2e/spoq_v11_workflows.py'
    if not path.is_file():pytest.skip('Repository fixture driver is not present in this source layout')
    spec=importlib.util.spec_from_file_location('_workflow_crash_driver',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('action',['claim','artifact','decision','completion'])
@pytest.mark.parametrize('stage',['before_commit','after_commit'])
def test_real_process_kill_preserves_atomicity_receipts_and_fences(tmp_path,action,stage):
    module=driver()
    result=module.run_fault_case(tmp_path,action,stage,expected_origin=str(Path(spoq_server.__file__).resolve()))
    assert result['passed'] and result['exit_code']!=0
    assert result['instrumentation']=='test-only transaction boundary wrapper'
    if action=='claim':assert result['stale_receipt_refused']
    elif action=='artifact':assert result['registered_artifact_inspected_and_reused']
    elif action=='decision':assert result['committed_human_fixture_replayed_once']
    else:assert result['completed_work_not_reinvoked']


def test_origin_guard_rejects_application_outside_expected_installed_prefix(tmp_path):
    module=driver()
    result=subprocess.run([sys.executable,'-I',str(module.SCRIPT),'--origin',str(tmp_path/'wrong-prefix')],
                          capture_output=True,text=True,env=module.clean_env(),timeout=20)
    assert result.returncode!=0 and 'escaped installed prefix' in result.stderr
    assert not (tmp_path/'.spoq').exists()
