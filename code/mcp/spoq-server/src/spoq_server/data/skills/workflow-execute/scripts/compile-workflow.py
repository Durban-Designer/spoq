#!/usr/bin/env python3
"""Compile a SPOQ epic into a Claude Code dynamic-workflow script.

`/workflow-execute` runs a SPOQ epic on Claude Code's dynamic-workflow
runtime instead of hand-rolled Task-tool dispatch. The determinism lives in
the emitted JavaScript, not in an LLM re-deriving the plan each session: this
script reads the epic (via the shared SPOQ engine in ``lib/epic_utils.py`` —
the same code the MCP server wraps), computes dependency waves, and emits a
self-contained ``.js`` the runtime executes.

The emitted script faithfully mirrors ``agent-execution``'s semantics:

    for each wave (sequential, NOT pipeline — cross-wave deps must hold):
        split wave into disjoint-file `safe` tasks and `conflicting` tasks
        parallel() the safe workers (the barrier); serialize the rest
        one serialized build-verify agent  (the script has no shell access)
        on build failure -> Haiku triage maps errors to files_to_touch
        per-task QA (10-metric rubric, gate 95/80) -> rework loop -> HALT
        write status back to disk after every transition (durability)

Usage:
    python3 compile-workflow.py --epic spoq/epics/active/my-epic > my-epic.workflow.js
    python3 compile-workflow.py --epic <path> --max-retries 3 --min-score 95 --resume
    python3 compile-workflow.py --epic <path> --auto-complete    # skip the human accept gate

Design notes / honest limits (see references/runtime-api.md and
documents/core/architecture/DYNAMIC_WORKFLOWS_COMPARISON.md):
  * v1 provides race DETECTION (post-wave build + a files_to_touch guard),
    not race PREVENTION. spoq_detect_conflicts only reasons over *declared*
    files_to_touch; isolation:'worktree' is deliberately NOT used in v1.
  * QA is inlined as a rubric the QA agent scores and returns as JSON — the
    `/agent-validation` skill emits a human-readable box, not parseable JSON.
  * Runtime resume is in-session only; cross-session durability comes ONLY
    from the spoq_update_task_status writeback this script emits.
  * The task-cascade 85-cap is a PLANNING-gate rule (epic-validation), applied
    before execution; it is intentionally not recomputed per-wave here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Shared SPOQ engine: scripts/ -> workflow-execute/ -> skills/ -> lib/
_LIB = Path(__file__).resolve().parent.parent.parent / "lib"
sys.path.insert(0, str(_LIB))

from epic_utils import compute_waves, group_waves, parse_epic  # noqa: E402

# Canonical write-side status set (mirrors task_tools.VALID_STATUSES). A task
# carrying anything else (e.g. the stale 'complete' instead of 'completed')
# would be silently treated as non-actionable, so we fail loud instead.
VALID_STATUSES = {"pending", "in_progress", "qa", "rework", "completed", "failed"}
ACTIONABLE_STATUSES = {"pending", "rework", "in_progress"}
# On --resume, also re-action tasks that a prior run left mid-flight: 'qa' (worker
# finished but never validated — the main wave flow has no QA-only path, so re-run
# worker+QA) and 'failed' (halted after max-retries — a deliberate resume re-attempts
# it). Without this, a plain --resume silently SKIPS those tasks (they are not in
# ACTIONABLE_STATUSES), which is how a mid-QA HALT loses 'qa'/'failed' work on resume.
# 'completed' is intentionally excluded so finished tasks stay skipped.
RESUME_ACTIONABLE_STATUSES = ACTIONABLE_STATUSES | {"qa", "failed"}


# =============================================================================
# Prompt rendering (Python mirror of assets/prompts/*.md, kept in code so the
# compiler need not ship a JS template engine)
# =============================================================================

def render_worker(task: dict, meta: dict, task_map: dict) -> str:
    """Render the base Opus worker prompt for a task (rework feedback is
    appended at runtime inside the emitted JS).

    The full task ``description`` and the epic overview/architecture are NOT
    inlined; the worker is an Opus agent with filesystem access and is told to
    read the authoritative task YAML and EPIC.md directly. This keeps the
    compiled script small (the Workflow tool caps scriptPath at 512KB — inlining
    every richly-specified task's description across all workers blows it) and
    avoids render-vs-source drift."""
    epic_path = meta.get("epic_path", "")
    task_path = f"{epic_path}/tasks/{task['id']}*.yml" if epic_path else f"{task['id']}*.yml"
    epic_md = f"{epic_path}/EPIC.md" if epic_path else "EPIC.md"
    crit = task.get("acceptance_criteria", []) or []
    files = task.get("files_to_touch", []) or []
    deps = task.get("dependencies", []) or []
    crit_block = "\n".join(f"- [ ] {c}" for c in crit) or "- [ ] (none specified)"
    files_block = "\n".join(f"- `{f}`" for f in files) or "- (none specified)"
    if deps:
        dep_lines = []
        for d in deps:
            dep_files = (task_map.get(d, {}) or {}).get("files_to_touch", []) or []
            produced = f" (produced: {', '.join(dep_files)})" if dep_files else ""
            dep_lines.append(f"- {d}{produced}")
        deps_block = (
            "The following dependency tasks are complete; build on their outputs:\n"
            + "\n".join(dep_lines)
        )
    else:
        deps_block = "No dependencies — this is a Wave 0 task."
    return f"""You are executing task **{task['id']}** from epic **{meta.get('epic_name', '')}**.

## Task: {task.get('title', task['id'])}

## Authoritative task specification (READ THIS FIRST)

Read the complete task definition from `{task_path}`. That YAML is the source of
truth: follow its objective, prerequisites, context, steps, code sketches,
verification, and error handling exactly. The Acceptance Criteria and Files to
Modify are reproduced below for convenience, but if anything differs, the YAML
on disk wins.

## Acceptance Criteria

{crit_block}

## Files to Modify (stay strictly within this set)

{files_block}

## Epic Context

Read `{epic_md}` for the epic Overview and Architecture. Do not rely on memory;
consult it whenever a cross-task type, interface, or seam is unclear.

## Dependencies

{deps_block}

## Instructions

1. Execute the task steps exactly as described.
2. Verify each acceptance criterion as you complete it.
3. Create or update unit tests for any code changes.
4. **Stay within the declared Files to Modify.** If you must touch a file not
   listed, do NOT silently edit it — finish what you can and report it under
   "Out-of-scope edits" so the orchestrator can reconcile.
5. Document blockers clearly.

## Anti-Loop Rules (MANDATORY)

- Max 3 attempts for any install/build command; check before installing
  (grep package.json) and trust a clean exit code.
- Do not re-run the same failing command more than 3 times — report and stop.
- If stuck, emit `AGENT ERROR: <reason>` and return rather than spinning.

## Output Format

```
## Summary
[1-2 sentences]

## Files Modified
- `path` - [what changed]

## Tests
- `path` - [tests added/updated]

## Acceptance Criteria Status
- [x] Criterion - verified by [how]

## Out-of-scope edits (if any)
- `path` - [why it was necessary]

## Issues (if any)
- [issue]
```"""


# The 10-metric agent-validation rubric, inlined so the QA agent returns
# parseable JSON instead of agent-validation's human-readable box.
QA_RUBRIC = """You are validating completed work for ONE task. Be rigorous but fair.

First run pre-validation on the working tree (only what applies to this repo):
  - lint (e.g. `npm run lint`), types (`npx tsc --noEmit`), build (`npm run build`).
  Any pre-validation failure forces Syntactic Correctness = 0 and an overall FAIL.

Then score these 10 metrics 0-100 (equal weight):
  1. Syntactic Correctness  2. Test Existence  3. Test Pass Rate
  4. Requirements Fidelity   5. SOLID Adherence 6. Security
  7. Error Handling          8. Scalability     9. Code Clarity
  10. Completeness (no TODO/stubs)
Security auto-zeros on: SQL/command injection, eval on user input, hardcoded secrets.

PASS = average >= the configured min-score AND every metric >= the configured min-metric.
Remediation, on FAIL, MUST be <= 20 lines: failing metrics with file:line refs and
at most 5 numbered action items.

Return ONLY a JSON object: {"average": <number>, "min_metric": <number>,
"per_metric": {"<name>": <number>, ...}, "remediation": "<string, empty if PASS>"}."""


# =============================================================================
# Code generation
# =============================================================================

def _js(value) -> str:
    """Embed a Python value as a JS literal (json is a valid JS subset)."""
    return json.dumps(value, ensure_ascii=False)


def emit_workflow(meta: dict, waves: list[dict], opts: argparse.Namespace) -> str:
    """Emit the full dynamic-workflow .js for the parsed epic."""
    epic_name = meta.get("epic_name", "epic")
    phase_titles = [f"Wave {w['wave']}" for w in waves]
    total_actionable = sum(
        1 for w in waves for t in w["tasks"] if t["actionable"]
    )
    description = (
        f"SPOQ epic execution: {len(waves)} waves, "
        f"{total_actionable} actionable tasks, gate "
        f"{opts.min_score}/{opts.min_metric}, max-retries {opts.max_retries}"
    )

    return f"""\
// AUTO-GENERATED by workflow-execute/scripts/compile-workflow.py — do not hand-edit.
// Source epic: {opts.epic}
// Regenerate with: /workflow-execute @{opts.epic}
export const meta = {{
  name: {_js(f"workflow-execute:{epic_name}")},
  description: {_js(description)},
  phases: {_js([{"title": t} for t in phase_titles])}
}};

// ---- compiler-injected constants ----
const EPIC_PATH     = {_js(opts.epic)};
const MAX_RETRIES   = {opts.max_retries};
const MIN_SCORE     = {opts.min_score};
const MIN_METRIC    = {opts.min_metric};
const AUTO_COMPLETE = {_js(bool(opts.auto_complete))};
const RESUME        = {_js(bool(opts.resume))};

// Full wave plan with per-task base worker prompts pre-rendered.
const WAVES = {_js(waves)};

// ---- schemas: agents return validated JSON the script branches on in JS ----
const BUILD_SCHEMA = {{ type: "object", additionalProperties: false,
  required: ["passed", "failing_output"],
  properties: {{ passed: {{ type: "boolean" }}, failing_output: {{ type: "string" }} }} }};
const TRIAGE_SCHEMA = {{ type: "object", additionalProperties: false,
  required: ["failing_tasks", "passing_tasks", "root_cause", "error_type"],
  properties: {{ failing_tasks: {{ type: "array", items: {{ type: "string" }} }},
    passing_tasks: {{ type: "array", items: {{ type: "string" }} }},
    root_cause: {{ type: "string" }}, error_type: {{ type: "string" }},
    affected_files: {{ type: "array", items: {{ type: "string" }} }} }} }};
const QA_SCHEMA = {{ type: "object", additionalProperties: false,
  required: ["average", "min_metric", "remediation"],
  properties: {{ average: {{ type: "number" }}, min_metric: {{ type: "number" }},
    per_metric: {{ type: "object" }}, remediation: {{ type: "string" }} }} }};
const CONFLICT_SCHEMA = {{ type: "object", additionalProperties: false,
  required: ["safe_tasks", "conflicting_tasks"],
  properties: {{ safe_tasks: {{ type: "array", items: {{ type: "string" }} }},
    conflicting_tasks: {{ type: "array", items: {{ type: "string" }} }} }} }};

const QA_RUBRIC = {_js(QA_RUBRIC)};

// ---- disk-touch helpers: the script has NO filesystem access, so a cheap
//      agent calls the SPOQ MCP tool (fallback: edit the task YAML in place) ----
async function setStatus(taskId, status, notes, retry) {{
  // Completion is gated behind the human accept (AUTO_COMPLETE), so the
  // epic_complete signal is intentionally not consumed — no schema/return needed.
  const retryClause = (retry === undefined) ? "" :
    ` Also set retry_count: ${{retry}} in the task YAML so the retry budget survives a cold restart.`;
  return agent(
    `Update SPOQ task status. If the spoq MCP server is available call ` +
    `spoq_update_task_status(epic_path=${{JSON.stringify(EPIC_PATH)}}, ` +
    `task_id=${{JSON.stringify(taskId)}}, status=${{JSON.stringify(status)}}, ` +
    `notes=${{JSON.stringify(notes || "")}}); otherwise edit ` +
    `${{EPIC_PATH}}/tasks/${{taskId}}*.yml in place, setting status: ${{status}} ` +
    `and appending the note to progress_notes.` + retryClause,
    {{ label: `status:${{taskId}}:${{status}}`, model: "haiku" }});
}}

function reworkPrompt(task, feedback, attempt) {{
  return task.prompt +
    `\\n\\n## Previous Attempt Feedback (Retry ${{attempt}}/${{MAX_RETRIES}})\\n\\n` +
    `Your previous implementation did not pass QA. Address these issues:\\n\\n` +
    feedback;
}}

function qaPrompt(task) {{
  return `${{QA_RUBRIC}}\\n\\nTASK: ${{task.id}} — ${{task.title}}\\n` +
    `TASK FILE: ${{EPIC_PATH}}/tasks/${{task.id}}*.yml\\n` +
    `Identify changed files via \\`git status --porcelain=v1\\` (this surfaces ` +
    `staged renames as R, untracked NEW files as ??, and modifications as M; ` +
    `plain \\`git diff --name-only\\` MISSES staged renames and untracked files, ` +
    `so do NOT rely on it) and score against the ` +
    `task's requirements. min-score=${{MIN_SCORE}}, min-metric=${{MIN_METRIC}}.`;
}}

async function buildVerify(label) {{
  return agent(
    `Run ./init.sh from the repository root to verify the build. Report exit ` +
    `status as {{passed}}, and on failure include the error tail in ` +
    `{{failing_output}}. Do NOT fix anything — verification only.`,
    {{ label, model: "haiku", schema: BUILD_SCHEMA }});
}}

// =================== epic = sequential for-loop over waves ===================
let halted = null;
for (const wave of WAVES) {{
  phase(`Wave ${{wave.wave}}`);
  const tasks = wave.tasks.filter(t => t.actionable);
  if (tasks.length === 0) {{ log(`Wave ${{wave.wave}}: no actionable tasks, skipping`); continue; }}

  if (RESUME) {{
    // Smart-review any carryover with prior-run work on disk before re-dispatching.
    // Anything not 'pending' (in_progress / qa / failed / rework) may have partial
    // edits from a halted run — a fresh 'pending' task has none, so skip it.
    const carry = tasks.filter(t => t.status !== "pending")
      .map(t => `${{t.id}} (${{t.status}})`);
    if (carry.length) {{
      await agent(`Smart-review carryover from a prior interrupted run for tasks ` +
        `${{carry.join(", ")}} in ${{EPIC_PATH}} (status shown in parens: in_progress = ` +
        `worker mid-flight, qa = worker finished but never validated, failed = halted ` +
        `after max-retries). Run git status --porcelain / git diff, lint, build. If ` +
        `partial work is coherent, leave it so the re-dispatched worker builds on it; ` +
        `if broken, git restore the affected paths so the worker restarts clean. ` +
        `Report what you did.`,
        {{ label: `resume-review:wave${{wave.wave}}`, model: "haiku" }});
    }}
  }}

  // ---- file-write safety: run disjoint-file tasks concurrently, serialize the rest ----
  const conflict = await agent(
    `If the spoq MCP server is available, call spoq_detect_conflicts(` +
    `epic_path=${{JSON.stringify(EPIC_PATH)}}, wave=${{wave.wave}}) and return its ` +
    `{{safe_tasks, conflicting_tasks}}. Otherwise, given these tasks and their ` +
    `files_to_touch ${{JSON.stringify(tasks.map(t => ({{id: t.id, files: t.files_to_touch}})))}}, ` +
    `compute the same: a task is "conflicting" if any of its files_to_touch is ` +
    `shared with another task in this list; the rest are "safe".`,
    {{ label: `conflicts:wave${{wave.wave}}`, model: "haiku", schema: CONFLICT_SCHEMA }});
  const safeIds = new Set(conflict && conflict.safe_tasks ? conflict.safe_tasks : tasks.map(t => t.id));
  const safe   = tasks.filter(t => safeIds.has(t.id));
  const serial = tasks.filter(t => !safeIds.has(t.id));
  if (serial.length) log(`Wave ${{wave.wave}}: serializing ${{serial.length}} file-conflicting task(s)`);

  // ---- (a) dispatch workers: safe in parallel (the barrier), conflicting one-at-a-time ----
  await Promise.all(safe.map(t => setStatus(t.id, "in_progress", "worker dispatched")));
  await parallel(safe.map(t => async () =>
    agent(t.prompt, {{ label: t.id, phase: `Wave ${{wave.wave}}`, model: "opus" }})));
  for (const t of serial) {{
    await setStatus(t.id, "in_progress", "worker dispatched (serialized: file conflict)");
    await agent(t.prompt, {{ label: t.id, phase: `Wave ${{wave.wave}}`, model: "opus" }});
  }}

  // ---- post-wave files_to_touch guard: catch undeclared (race-prone) edits ----
  const declared = [].concat(...tasks.map(t => t.files_to_touch || []));
  const guard = await agent(
    `Run \\`git status --porcelain=v1\\` at the repo root (this catches staged ` +
    `renames and untracked files, which \\`git diff --name-only\\` misses). ` +
    `Return {{ok, stray}} where ` +
    `stray = changed files NOT in this declared set: ${{JSON.stringify(declared)}}. ` +
    `ok=true iff stray is empty.`,
    {{ label: `guard:wave${{wave.wave}}`, model: "haiku",
       schema: {{ type: "object", additionalProperties: false, required: ["ok", "stray"],
         properties: {{ ok: {{ type: "boolean" }}, stray: {{ type: "array", items: {{ type: "string" }} }} }} }} }});
  if (guard && guard.ok === false) {{
    log(`Wave ${{wave.wave}}: WARNING undeclared edits outside files_to_touch: ${{(guard.stray || []).join(", ")}}`);
  }}

  // ---- (b) build verification: single serialized agent (no shell in-script).
  //      A skipped/failed verify agent resolves to null -> treat as could-not-verify. ----
  const build = await buildVerify(`build:wave${{wave.wave}}`);
  let failing = new Set();
  let buildFeedback = "";
  if (!build || !build.passed) {{
    // ---- (c) Haiku triage: map build errors to tasks' files_to_touch ----
    const triage = await agent(
      `The build failed (or could not be verified) after Wave ${{wave.wave}}. Build output:\\n` +
      `${{(build && build.failing_output) || "(build agent returned no output)"}}\\n\\n` +
      `Tasks and files: ${{JSON.stringify(tasks.map(t => ({{id: t.id, files: t.files_to_touch}})))}}\\n` +
      `A task is "failing" if any of its files appears in the error. Return ` +
      `{{failing_tasks, passing_tasks, root_cause, error_type, affected_files}}. ` +
      `Empty failing_tasks => the error is unrelated to this wave.`,
      {{ label: `triage:wave${{wave.wave}}`, model: "haiku", schema: TRIAGE_SCHEMA }});
    failing = new Set((triage && triage.failing_tasks) || []);
    // Preserve the diagnosis so the rework worker gets the root cause, not a generic string.
    buildFeedback = `Build failed after this wave.\\nroot_cause: ${{(triage && triage.root_cause) || "unknown"}}\\n` +
      `error_type: ${{(triage && triage.error_type) || "unknown"}}\\n` +
      `affected_files: ${{((triage && triage.affected_files) || []).join(", ")}}\\n\\n` +
      `Build output:\\n${{(build && build.failing_output) || ""}}`;
  }}

  // ---- (d) QA per task in parallel; index results by id so a swallowed (null)
  //      thunk becomes a forced FAIL below, never a silent pass through the gate ----
  const qaList = await parallel(tasks.map(t => async () => {{
    if (failing.has(t.id)) {{
      await setStatus(t.id, "qa", "build triage flagged — routing to rework");
      return {{ id: t.id, passed: false, feedback: buildFeedback }};
    }}
    await setStatus(t.id, "qa", "entering validation");
    const qa = await agent(qaPrompt(t), {{ label: `${{t.id}}:qa`, model: "sonnet", schema: QA_SCHEMA }});
    if (!qa) return {{ id: t.id, passed: false, feedback: "QA agent returned no result (skipped/failed) — forcing rework" }};
    const passed = qa.average >= MIN_SCORE && qa.min_metric >= MIN_METRIC;
    return {{ id: t.id, passed, feedback: qa.remediation || "" }};
  }}));
  const qaById = new Map(qaList.filter(Boolean).map(r => [r.id, r]));

  // ---- (e)+(f) rework loop + fail-fast HALT. Iterate `tasks` (NOT the filtered
  //      QA list) so a missing/null QA result becomes a forced rework, not a pass.
  //      attempt starts from the persisted retry_count so the budget survives resume. ----
  for (const t of tasks) {{
    const r = qaById.get(t.id) || {{ passed: false, feedback: "QA result missing (agent skipped) — forcing rework" }};
    let passed = r.passed, feedback = r.feedback, attempt = t.retry_count || 0;
    while (!passed && attempt < MAX_RETRIES) {{
      attempt++;
      await setStatus(t.id, "rework", `retry ${{attempt}}/${{MAX_RETRIES}}: ${{(feedback || "").slice(0, 160)}}`, attempt);
      await agent(reworkPrompt(t, feedback, attempt), {{ label: `${{t.id}}:rework${{attempt}}`, model: "opus" }});
      const rb = await buildVerify(`build:${{t.id}}:r${{attempt}}`);
      const qa = await agent(qaPrompt(t), {{ label: `${{t.id}}:qa:r${{attempt}}`, model: "sonnet", schema: QA_SCHEMA }});
      passed = !!(rb && rb.passed) && !!qa && qa.average >= MIN_SCORE && qa.min_metric >= MIN_METRIC;
      feedback = (qa && qa.remediation) || feedback;
    }}
    if (!passed) {{
      await setStatus(t.id, "failed", `HALT: failed QA after ${{MAX_RETRIES}} retries`, attempt);
      halted = t.id;
      break;
    }}
    await setStatus(t.id, "completed", "QA passed");
  }}

  if (halted) {{
    // fail-fast: do not start later waves with unmet dependencies
    throw new Error(`HALT EPIC: ${{halted}} failed after ${{MAX_RETRIES}} retries — human intervention required`);
  }}

  await agent(`Append a journal.md wave-summary entry (YAML frontmatter: agent, ` +
    `start_time, end_time, confidence, session_type: execution, files_modified) for ` +
    `Wave ${{wave.wave}} of ${{EPIC_PATH}} — tasks ${{tasks.map(t => t.id).join(", ")}} passed QA.`,
    {{ label: `journal:wave${{wave.wave}}`, model: "haiku" }});
}}

// ---- epic completion: gated behind human accept unless --auto-complete ----
if (!halted) {{
  if (AUTO_COMPLETE) {{
    await agent(`All tasks passed QA. If the spoq MCP server is available call ` +
      `spoq_complete_epic(epic_path=${{JSON.stringify(EPIC_PATH)}}) to move the epic ` +
      `active->complete, update the parent map and ROADMAP.yml; then write a final ` +
      `journal.md entry. Return a summary.`, {{ label: "complete-epic", model: "haiku" }});
    return {{ status: "complete", epic: EPIC_PATH }};
  }}
  log(`All tasks passed QA. Awaiting human accept/merge before completing the epic. ` +
    `Review the diff, then run: /workflow-execute @${{EPIC_PATH}} --auto-complete  ` +
    `(or spoq_complete_epic manually).`);
  return {{ status: "awaiting-accept", epic: EPIC_PATH }};
}}
"""


# =============================================================================
# CLI
# =============================================================================

def build_waves(parsed: dict, resume: bool = False, epic_path: str = "") -> list[dict]:
    """Compute waves and attach pre-rendered worker prompts."""
    actionable_statuses = RESUME_ACTIONABLE_STATUSES if resume else ACTIONABLE_STATUSES
    tasks = parsed.get("tasks", [])
    if not tasks:
        raise SystemExit("Error: no tasks found in epic")

    bad = sorted({
        t.get("status", "pending") for t in tasks
        if t.get("status", "pending") not in VALID_STATUSES
    })
    if bad:
        raise SystemExit(
            f"Error: task status(es) not in VALID_STATUSES {sorted(VALID_STATUSES)}: "
            f"{bad}. (Did a fixture use 'complete' instead of 'completed'?)"
        )

    meta = {
        "epic_name": parsed.get("epic_name", "epic"),
        "epic_path": epic_path,
        "overview": parsed.get("metadata", {}).get("overview", ""),
        "architecture": parsed.get("metadata", {}).get("architecture", ""),
    }
    task_map = {t["id"]: t for t in tasks}
    wave_groups = group_waves(compute_waves(tasks))

    waves = []
    for wave_num in sorted(wave_groups):
        wave_tasks = []
        for tid in sorted(wave_groups[wave_num]):
            t = task_map[tid]
            status = t.get("status", "pending")
            wave_tasks.append({
                "id": tid,
                "title": t.get("title", tid),
                "status": status,
                "retry_count": t.get("retry_count", 0),
                "files_to_touch": t.get("files_to_touch", []),
                "actionable": status in actionable_statuses,
                "prompt": render_worker(t, meta, task_map),
            })
        waves.append({"wave": wave_num, "tasks": wave_tasks})
    return waves


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile a SPOQ epic into a dynamic-workflow script.")
    ap.add_argument("--epic", required=True, help="Path to the epic directory")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--min-score", type=int, default=95)
    ap.add_argument("--min-metric", type=int, default=80)
    ap.add_argument("--resume", action="store_true", help="Emit a smart-review step for in_progress carryover")
    ap.add_argument("--auto-complete", action="store_true",
                    help="Auto-fire spoq_complete_epic instead of stopping at a human accept gate")
    ap.add_argument("--out", default="-", help="Output path for the .js (default: stdout)")
    opts = ap.parse_args()

    parsed = parse_epic(Path(opts.epic), validate=True)
    if "error" in parsed:
        raise SystemExit(f"Error: {parsed['error']}")

    waves = build_waves(parsed, resume=opts.resume, epic_path=str(opts.epic).rstrip("/"))
    actionable = sum(1 for w in waves for t in w["tasks"] if t["actionable"])

    # Rough agent-spawn estimate (against the runtime's 1000-per-run hard cap).
    per_task = 4  # in_progress + qa + completed + (build/triage/guard share)
    est = actionable * (per_task + opts.max_retries * 2) + len(waves) * 4 + 2
    print(f"[compile] {parsed['epic_name']}: {len(waves)} waves, "
          f"{actionable} actionable tasks, ~{est} agent spawns "
          f"(runtime cap 1000)", file=sys.stderr)
    if est > 800:
        print(f"[compile] WARNING estimate {est} approaches the 1000-agent cap; "
              f"consider splitting the epic or reducing --max-retries.", file=sys.stderr)
    if actionable == 0:
        print("[compile] NOTE: 0 actionable tasks — the emitted workflow is a no-op "
              "(epic already complete, or use --resume on an interrupted run).", file=sys.stderr)

    js = emit_workflow({"epic_name": parsed["epic_name"]}, waves, opts)
    if opts.out == "-":
        sys.stdout.write(js)
    else:
        Path(opts.out).write_text(js, encoding="utf-8")
        print(f"[compile] wrote {opts.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
