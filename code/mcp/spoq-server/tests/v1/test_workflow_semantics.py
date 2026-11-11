"""Executable normative examples, separate from downstream runner tests."""
from pathlib import Path
import re

import pytest

from spoq_server.v1.workflows.types import PhaseStatus, StrategyDefinition, evidence_matches


DOC = Path(__file__).resolve().parents[5] / 'documents/core/architecture/SPOQ_1_1_STRATEGIES.md'


def examples():
    return re.findall(r'```python\n(.*?)```', DOC.read_text(), re.S)


def test_normative_examples_execute_actual_contracts():
    blocks = examples()
    assert len(blocks) == 3
    namespace = {}
    for block in blocks:
        exec(compile(block, str(DOC), 'exec'), namespace)
    definition = namespace['loop_example']
    assert isinstance(definition, StrategyDefinition)
    fail_edges = [edge for edge in definition.edges if edge.on == 'fail']
    assert [(edge.source, edge.target) for edge in fail_edges] == [('review', 'draft')]
    assert definition.max_transitions < 100
    assert len({phase.id for phase in definition.phases}) == 3


@pytest.mark.parametrize('changed', ['definition_hash', 'specification_hash', 'artifact_hashes'])
def test_any_reviewed_revision_change_invalidates_identity(changed):
    current = {'definition_hash': 'a' * 64, 'specification_hash': 'b' * 64,
               'artifact_hashes': {'plan': 'c' * 64}}
    reviewed = dict(current)
    reviewed[changed] = {'plan': 'd' * 64} if changed == 'artifact_hashes' else 'd' * 64
    assert evidence_matches(current, **current)
    assert not evidence_matches(reviewed, **current)


def test_waiting_is_not_a_failure_or_completion():
    assert PhaseStatus.WAITING_HUMAN != PhaseStatus.FAILED
    assert PhaseStatus.WAITING_HUMAN != PhaseStatus.PASSED
    assert PhaseStatus.SKIPPED != PhaseStatus.PASSED


def test_normative_scope_and_trust_boundaries_remain_explicit():
    text = DOC.read_text()
    for required in ['Project Plans → Features → Tasks', 'forward DAG', 'max_transitions',
                     'max_attempts', 'waiting_human', 'provenance boundary',
                     'not operating-system authentication', 'legacy_unclassified',
                     'state and events together', 'required check fails']:
        # Markdown wrapping should not affect prose checks.
        assert required in ' '.join(text.split())
