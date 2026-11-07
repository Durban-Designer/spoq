"""Regression tests for the workflow-execute compiler (compile-workflow.py).

The compiler is a standalone script (run via /workflow-execute), so these drive
it as a subprocess exactly the way the skill does. They guard the 512KB
scriptPath cap: render_worker() must NOT inline each task's full description or
the epic overview/architecture — it points the Opus worker at the on-disk task
YAML and EPIC.md instead. Inlining made a richly-specified 23-task epic compile
to 683KB and the Workflow tool rejected it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Exercise the compiler shipped in the package; no private workspace required.
import spoq_server
_SRC_SKILLS = Path(spoq_server.__file__).parent / "data" / "skills"
_COMPILER = _SRC_SKILLS / "workflow-execute" / "scripts" / "compile-workflow.py"

# The Workflow tool hard-caps scriptPath; the compiler exists to stay under it.
SCRIPT_CAP_BYTES = 512 * 1024

pytestmark = pytest.mark.skipif(
    not _COMPILER.exists(),
    reason="source .claude/skills compiler not present (running outside the source repo)",
)


def _compile(epic_path: Path, *extra: str) -> str:
    """Run compile-workflow.py and return the emitted JS (raises on non-zero)."""
    result = subprocess.run(
        [sys.executable, str(_COMPILER), "--epic", str(epic_path), *extra],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"compiler failed: {result.stderr}"
    return result.stdout


class TestCompileWorkflow:
    def test_compiles_to_valid_script(self, fixture_epic_path):
        js = _compile(fixture_epic_path)
        assert "export const meta" in js
        # Waves must be a parallel() barrier, never pipeline() (cross-wave deps).
        assert "parallel(" in js
        assert "pipeline(" not in js

    def test_worker_prompt_points_at_task_yaml_not_inlined(self, fixture_epic_path):
        js = _compile(fixture_epic_path)
        # The worker is told to read the authoritative sources from disk...
        assert "Read the complete task definition from" in js
        assert "tasks/01-setup" in js
        assert "EPIC.md" in js

    def test_large_description_does_not_blow_the_cap(self, tmp_epic_copy):
        """A richly-specified task must not inflate the compiled script: the
        regression that produced a 683KB (>512KB) script for a 23-task epic."""
        sentinel = "ZZUNIQUE_SENTINEL_ZZ"
        huge = (sentinel + " ") * 20_000  # ~420KB of description in ONE task

        task_file = tmp_epic_copy / "tasks" / "01-setup.yml"
        data = yaml.safe_load(task_file.read_text())
        data["description"] = huge
        task_file.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        js = _compile(tmp_epic_copy)

        # The giant description is read from disk at runtime, never inlined.
        assert sentinel not in js
        assert len(js.encode("utf-8")) < SCRIPT_CAP_BYTES
