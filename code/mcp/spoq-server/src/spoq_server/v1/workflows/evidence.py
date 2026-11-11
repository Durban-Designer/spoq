"""Strict phase evidence and atomic artifact publication.

These checks validate recorded observations; the server never claims to have run
the caller's commands, reviewed its code, or independently proved its assertions.
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path

from ..db import uid, now, index_document

from .artifacts import ArtifactRepository, parse_artifact, text
from .compiler import compile_definition
from .design import SOURCE_CAPABILITIES, validate_artifact
from .leases import current_artifacts
from .types import canonical_json

GATE_SKILLS = {'spoq-plan-validation': 'plan', 'spoq-validation': 'implementation'}


def validate_phase_contract(phase):
    """A skill label cannot turn a mandatory validator into an unchecked worker."""
    if phase.kind == 'join' and (phase.inputs or phase.outputs):
        raise ValueError('Joins are control-only; artifact inputs and outputs belong to executable phases')
    if phase.kind == 'gate' or phase.skill in GATE_SKILLS:
        if (phase.kind != 'gate' or phase.skill not in GATE_SKILLS
                or phase.config.get('stage') != GATE_SKILLS[phase.skill]):
            raise ValueError('Validation skills require their matching gate kind and stage')


@lru_cache(maxsize=1)
def gate_function():
    helper = Path(__file__).resolve().parents[2] / 'data/v1_skills/spoq/scripts/score_gate.py'
    spec = importlib.util.spec_from_file_location('_spoq_score_gate', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_gate


def validate_evidence(evidence: dict, phase, *, run_id, attempt_id, scope_id,
                      definition_hash, specification_hash, artifact_hashes,
                      outcome='pass', producer_agents=()) -> dict:
    if not isinstance(evidence, dict) or not isinstance(outcome, str) or outcome not in {'pass', 'fail'}:
        raise ValueError('Structured evidence and pass/fail outcome are required')
    validate_phase_contract(phase)
    evidence = json.loads(canonical_json(evidence))
    expected = {'run_id': run_id, 'phase_id': phase.id, 'attempt_id': attempt_id,
                'scope_id': scope_id, 'definition_hash': definition_hash,
                'specification_hash': specification_hash, 'artifact_hashes': artifact_hashes}
    if any(evidence.get(k) != value for k, value in expected.items()):
        raise ValueError('Evidence identity or specification/artifact revision does not match this invocation')
    reviewer = evidence.get('reviewer')
    if (not isinstance(reviewer, dict) or not isinstance(reviewer.get('review_type'), str)
            or reviewer['review_type'] not in {'self_review', 'independent', 'scripted_adapter'}):
        raise ValueError('Reviewer must identify self_review, independent, or scripted_adapter')
    text(reviewer.get('agent'), 'Reviewer identity')
    if reviewer['review_type'] == 'independent' and reviewer['agent'] in producer_agents:
        raise ValueError('An output producer cannot claim to be its independent reviewer')
    checks, acceptance = evidence.get('observed_checks'), evidence.get('acceptance_results')
    if not isinstance(checks, list) or not checks or not isinstance(acceptance, list) or not acceptance:
        raise ValueError('Actual observed checks and acceptance results are required')
    passed = True
    for check in checks:
        if not isinstance(check, dict) or check.get('observed') is not True:
            raise ValueError('Checks must have an observed outcome')
        text(check.get('source'), 'Check source')
        if type(check.get('required', True)) is not bool:
            raise ValueError('Required check marker must be boolean')
        kind = check.get('check_type', 'command')
        if kind == 'command':
            command = check.get('command')
            if not (isinstance(command, str) and command.strip() or isinstance(command, list)
                    and command and all(isinstance(x, str) and x for x in command)):
                raise ValueError('Command checks require the actual command')
            if type(check.get('exit_code')) is not int:
                raise ValueError('Command checks require an observed integer exit code')
            successful = check['exit_code'] == 0
        elif isinstance(kind, str) and kind in {'review', 'artifact', 'tool'}:
            text(check.get('name'), 'Observed check name')
            if type(check.get('passed')) is not bool:
                raise ValueError('Non-command checks require a boolean observed result')
            successful = check['passed']
        else:
            raise ValueError('Unknown check type')
        if check.get('required', True) and not successful:
            passed = False
    for result in acceptance:
        if not isinstance(result, dict) or type(result.get('passed')) is not bool:
            raise ValueError('Acceptance results require criterion and boolean passed')
        text(result.get('criterion'), 'Acceptance criterion', maximum=5000)
        passed = passed and result['passed']
    if phase.kind == 'gate' and phase.config.get('required_checks', True) and not any(c.get('required', True) for c in checks):
        raise ValueError('A quality gate requires at least one required observed check')
    if type(evidence.get('checks_passed')) is not bool:
        raise ValueError('checks_passed must be an explicit boolean')
    passed = passed and evidence['checks_passed'] and outcome == 'pass'
    report = {**evidence, 'checks_passed': passed,
              'provenance': 'caller_supplied_observations_not_reexecuted',
              'reviewer': {**reviewer, 'identity_verification': 'caller_attested'}}
    if phase.kind == 'gate':
        report = gate_function()(phase.config['stage'], report)
        average = phase.config.get('minimum_average', 95)
        minimum = phase.config.get('minimum_metric', 90 if phase.config['stage'] == 'plan' else 80)
        if report['average'] < average or report['minimum'] < minimum:
            report['verdict'] = 'FAIL'
            report['reasons'].append('Definition requires a stricter quality threshold')
    else:
        report['verdict'] = 'PASS' if passed else 'FAIL'
    return report


def complete_phase(runner, run_id, attempt_id, token, actor, *, key, evidence,
                   outputs=None, outcome='pass', expected_revision=None, refresh_spec=False):
    if outputs is not None and not isinstance(outputs, dict):
        raise ValueError('Outputs must be an object keyed by declared output names')
    if type(refresh_spec) is not bool:
        raise ValueError('Specification refresh must be an explicit boolean')
    supplied = {} if outputs is None else outputs
    def publish(db, current, attempt):
        phase = compile_definition(current['definition']).phases[attempt['phase_id']]
        artifacts = current_artifacts(db, current, phase)
        producers = {row['author'] for row in artifacts.values()}
        for row in artifacts.values():
            producers.add(db.execute('SELECT owner FROM workflow_attempts WHERE id=?', (row['attempt_id'],)).fetchone()[0])
        if phase.kind != 'gate':
            producers.add(actor)
        report = validate_evidence(evidence, phase, run_id=run_id, attempt_id=attempt_id,
            scope_id=current['scope_id'], definition_hash=current['definition_hash'],
            specification_hash=current['specification_hash'],
            artifact_hashes={name: row['sha256'] for name, row in artifacts.items()}, outcome=outcome,
            producer_agents=producers)
        report['validation_journal_id'] = uid()
        report['input_specification_hash'] = attempt['specification_hash']
        actual_outcome = 'pass' if report['verdict'] == 'PASS' else 'fail'
        if phase.kind == 'gate':
            if supplied:
                raise ValueError('Gate output is computed from evidence; do not supply a replacement gate artifact')
            values = {name: {'content': canonical_json(report), 'source': 'computed_gate'} for name in phase.outputs}
        else:
            values = supplied
        if values.keys() - set(phase.outputs) or (actual_outcome == 'pass' and set(values) != set(phase.outputs)):
            raise ValueError('A passing phase requires exactly its declared outputs')
        references, output_hashes, validations = {}, {}, {}
        for name, value in values.items():
            if isinstance(value, str):
                value = {'artifact_id': value}
            if not isinstance(value, dict):
                raise ValueError('Output requires content or a registered artifact ID')
            existing = None
            if 'artifact_id' in value:
                if not isinstance(value['artifact_id'], str):
                    raise ValueError('Registered artifact ID must be text')
                row = db.execute('SELECT * FROM workflow_artifacts WHERE id=? AND run_id=?',
                                 (value['artifact_id'], run_id)).fetchone()
                if row is None or row['attempt_id'] != attempt_id or row['kind'] != name:
                    raise ValueError('Registered output belongs to a different invocation or kind')
                existing = parse_artifact(row)
                content, metadata = existing['content'], existing['metadata']
            else:
                content, metadata = value.get('content'), value.get('metadata', {})
            if not isinstance(content, (str, dict)) or not isinstance(metadata, dict):
                raise ValueError('Output content must be text/object and metadata must be an object')
            provider = phase.config.get('provider', name)
            if 'provider' in phase.config and (not isinstance(provider, str) or provider not in SOURCE_CAPABILITIES):
                raise ValueError('Design provider must be one of the bundled source providers')
            if isinstance(provider, str) and provider in SOURCE_CAPABILITIES:
                try:
                    validated = validate_artifact(provider, content, metadata)
                    content, metadata = validated['content'], {**validated['metadata'], 'validation': validated['validation']}
                    validations[name] = validated['validation']
                    if (provider == 'formal' and current['routing']['inputs'].get('formal_proof_required')
                            and actual_outcome == 'pass' and validated['status'] != 'proven'):
                        raise ValueError('Required proof is not reported proven with verifier evidence')
                except ValueError as exc:
                    if actual_outcome == 'pass':
                        raise
                    metadata = {**metadata, 'validation_error': str(exc)}
            if isinstance(content, dict):
                content = canonical_json(content)
            if actual_outcome == 'pass' and name in {'project_plan', 'implementation'}:
                try:
                    link = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ValueError('Work outputs must link the actual scope and specification hash') from exc
                if (not isinstance(link, dict) or link.get('scope_id') != current['scope_id']
                        or link.get('specification_hash') != current['specification_hash']):
                    raise ValueError('Work output does not match the current saved specification')
            if existing is None:
                artifact = ArtifactRepository.add(db, run_id, attempt_id, name, content, actor,
                                                  value.get('source', 'agent'), metadata)
            else:
                artifact = existing
            references[name], output_hashes[name] = artifact['id'], artifact['sha256']
        report.update(output_hashes=output_hashes, output_validation=validations)
        body = canonical_json(report)
        db.execute('INSERT INTO journal_entries VALUES(?,?,?,?,?,?)',
                   (report['validation_journal_id'], current['scope_id'], actor, body,
                    canonical_json({'stage': 'workflow_phase_validation', 'run_id': run_id,
                                    'attempt_id': attempt_id, 'verdict': report['verdict']}), now()))
        index_document(db, report['validation_journal_id'], 'journal', phase.id + ': ' + report['verdict'], body)
        return {'outcome': actual_outcome, 'outputs': references, 'evidence': report}
    return runner._commit(run_id, attempt_id, token, actor, key=key,
        request={'evidence': evidence, 'outputs': supplied, 'outcome': outcome}, publish=publish,
        expected_revision=expected_revision, refresh_spec=refresh_spec)
