"""Explicit scripted adapter fixtures, never presented as live model/test results."""
from spoq_server.v1.workflows.evidence import gate_function


def evidence_for(envelope, *, passed=True, stage=None):
    result = {k: envelope[k] for k in ('run_id', 'scope_id', 'phase_id', 'attempt_id',
                                     'definition_hash', 'specification_hash', 'artifact_hashes')}
    result.update(reviewer={'agent': 'fixture-adapter', 'review_type': 'scripted_adapter'},
                  checks_passed=passed,
                  observed_checks=[{'check_type': 'review', 'name': 'Scripted fixture assertion',
                                    'source': 'test adapter (simulated review)', 'observed': True, 'passed': passed}],
                  acceptance_results=[{'criterion': 'Fixture acceptance', 'passed': passed}])
    if stage:
        from importlib.util import spec_from_file_location, module_from_spec
        from pathlib import Path
        import spoq_server
        spec = spec_from_file_location('fixture_gate', Path(spoq_server.__file__).parent / 'data/v1_skills/spoq/scripts/score_gate.py')
        module = module_from_spec(spec); spec.loader.exec_module(module)
        result['scores'] = {name: 96 for name in module.METRICS[stage]}
    return result


def outputs_for(envelope):
    return {name: {'content': {'scope_id': envelope['scope_id'], 'specification_hash': envelope['specification_hash']}}
            if name in {'project_plan', 'implementation'} else {'content': 'Fixture ' + name}
            for name in envelope['expected_outputs']}
