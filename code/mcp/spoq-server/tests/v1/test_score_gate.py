"""Gate arithmetic and actual installed command behavior, independent of an LLM."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from spoq_server.agents import AGENTS
from spoq_server.v1.cli import init


SCRIPT = Path(__file__).parents[2]/'src/spoq_server/data/v1_skills/spoq/scripts/score_gate.py'
spec = importlib.util.spec_from_file_location('spoq_score_gate', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def report(stage, value=100, checks=True):
    return {'scores': dict.fromkeys(gate.METRICS[stage], value), 'checks_passed': checks}


@pytest.mark.parametrize('stage,floor', [('plan',90),('implementation',80)])
def test_both_thresholds_and_hard_checks_are_required(stage, floor):
    passing = report(stage,95)
    assert gate.score_gate(stage, passing)['verdict']=='PASS'
    low_average = report(stage,94.999)
    assert gate.score_gate(stage, low_average)['verdict']=='FAIL'
    low_metric = report(stage)
    low_metric['scores'][gate.METRICS[stage][0]]=floor-1
    result = gate.score_gate(stage,low_metric)
    assert result['average']>95
    assert result['verdict']=='FAIL'
    low_metric['scores'][gate.METRICS[stage][0]]=floor
    assert gate.score_gate(stage,low_metric)['verdict']=='PASS'
    assert gate.score_gate(stage,report(stage,checks=False))['verdict']=='FAIL'


@pytest.mark.parametrize('value', [-1,101,True,'100',None,float('nan'),float('inf')])
def test_rejects_invalid_score_values(value):
    data=report('plan')
    data['scores']['Vision Clarity']=value
    with pytest.raises(ValueError,match='finite number'):
        gate.score_gate('plan',data)


def test_rejects_missing_or_duplicate_metrics_and_implicit_checks(tmp_path):
    data=report('plan')
    del data['scores']['Vision Clarity']
    with pytest.raises(ValueError,match='exactly'):
        gate.score_gate('plan',data)
    data['scores']['Wrong name']=100
    with pytest.raises(ValueError,match='exactly'):
        gate.score_gate('plan',data)
    for value in [None,1,'true']:
        data=report('plan')
        data['checks_passed']=value
        with pytest.raises(ValueError,match='explicit boolean'):
            gate.score_gate('plan',data)
    path=tmp_path/'duplicate.json'
    path.write_text('{"scores":{},"scores":{},"checks_passed":true}')
    result=subprocess.run([sys.executable,str(SCRIPT),'--stage','plan','--input',str(path)],capture_output=True,text=True)
    assert result.returncode==2
    assert 'Duplicate JSON key' in result.stderr
    invalid_extra=report('plan')
    invalid_extra['confidence']=float('nan')
    path.write_text(json.dumps(invalid_extra))
    result=subprocess.run([sys.executable,str(SCRIPT),'--stage','plan','--input',str(path)],capture_output=True,text=True)
    assert result.returncode==2
    assert 'error' in json.loads(result.stderr)


@pytest.mark.parametrize('agent', ['claude','codex','qwen','cursor'])
def test_installed_gate_runs_without_package_dependencies(tmp_path,agent):
    init(tmp_path,agents=agent)
    script=tmp_path/AGENTS[agent].commands_root/'spoq/scripts/score_gate.py'
    path=tmp_path/'review.json'
    for passed in [True,False]:
        path.write_text(json.dumps(report('implementation',checks=passed)))
        result=subprocess.run([sys.executable,'-I','-S',str(script),'--stage','implementation','--input',str(path)],capture_output=True,text=True)
        assert result.returncode==(0 if passed else 1),result.stderr
        computed=json.loads(result.stdout)
        assert computed['verdict']==('PASS' if passed else 'FAIL')
        assert computed['floor']==80
    path.write_text('[]')
    result=subprocess.run([sys.executable,str(script),'--stage','plan','--input',str(path)],capture_output=True,text=True)
    assert result.returncode==2
    assert json.loads(result.stderr)['error']=='Review must be a JSON object'
