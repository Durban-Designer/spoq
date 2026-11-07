"""Compute SPOQ gate arithmetic from an evidence-based review; no external deps."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


METRICS = {
    'plan': (
        'Vision Clarity', 'Architecture Quality', 'Task Decomposition',
        'Dependency Graph', 'Coverage Completeness', 'Phase Ordering',
        'Scope Coherence', 'Success Criteria Quality', 'Risk Identification',
        'Integration Strategy',
    ),
    'implementation': (
        'Syntactic Correctness', 'Test Existence', 'Test Pass Rate',
        'Requirements Fidelity', 'SOLID Adherence', 'Security', 'Error Handling',
        'Scalability', 'Code Clarity', 'Completeness',
    ),
}


def score_gate(stage: str, report: dict) -> dict:
    if stage not in METRICS:
        raise ValueError('Stage must be plan or implementation')
    if not isinstance(report, dict):
        raise ValueError('Review must be a JSON object')
    scores = report.get('scores')
    if not isinstance(scores, dict) or set(scores) != set(METRICS[stage]):
        raise ValueError('Scores must contain exactly these ten metrics: ' + ', '.join(METRICS[stage]))
    for name, value in scores.items():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f'{name} must be a finite number from 0 to 100')
    checks_passed = report.get('checks_passed')
    if type(checks_passed) is not bool:
        raise ValueError('checks_passed must be an explicit boolean')
    average = math.fsum(scores.values()) / len(scores)
    floor = 90 if stage == 'plan' else 80
    reasons = []
    if average < 95:
        reasons.append('Average is below 95')
    if min(scores.values()) < floor:
        reasons.append(f'A metric is below {floor}')
    if not checks_passed:
        reasons.append('Required checks or acceptance criteria failed')
    return {**report, 'stage': stage, 'average': average, 'minimum': min(scores.values()),
            'threshold': 95, 'floor': floor, 'verdict': 'FAIL' if reasons else 'PASS',
            'reasons': reasons}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=METRICS, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.input.read_text(), object_pairs_hook=_unique_object)
        result = score_gate(args.stage, report)
        encoded = json.dumps(result, allow_nan=False)
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    print(encoded)
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
