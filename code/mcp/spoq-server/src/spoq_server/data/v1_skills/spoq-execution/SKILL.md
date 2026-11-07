---
name: spoq-execution
description: Execute saved SPOQ Feature/task DAGs with claims, durable retries, collaboration, and composed validation gates. Use for /spoq-execution or the execution stage of /spoq.
---

# SPOQ execution

Replace agent-execution and feature-execution with the execution stage for SQLite
Project Plans, Features, and Tasks. Accept saved scope IDs; new goal decomposition
belongs to `../spoq-plan/SKILL.md`. Use `../spoq/references/runtime.md` for setup
and stage handoff. Preserve the original scope, acceptance criteria, and Git rules.

## Prepare and resume

If dry-run was requested, only read existing state and gate evidence, report
ordering/readiness and any missing or stale gate, then return. Do not run stages
that write journals or create a run. Other options below apply to real execution.

Read nodes, DAGs, history, journals, and existing runs. Use a current PASS from
`../spoq-plan-validation/SKILL.md`, or run that stage before dispatch. FAIL blocks
execution until the caller repairs the specification; never bypass it on resume.
Reopen completed ancestors before extending completed work. If completed evidence
already satisfies the request, report it without manufacturing tasks.

Create or reuse one run with `spoq_create_run` and register participants with
`spoq_register_agent`. Pass stable run and agent IDs to workers and reviewers.
Scope dispatch to requested work and actual prerequisites. A requested Task/wave
subset does not authorize completing unexecuted siblings or its whole parent.
Scope/dry-run/retry options are skill instructions, not invented CLI flags.

## Dispatch ready work

Use `spoq_compute_dag` for static waves and current ready Tasks. Feature-level
dependencies gate downstream Tasks too. Skip completed Tasks with valid evidence.
Use native subagents when available and permitted; serialize shared-file edits
or assign one clear owner. Respect available models rather than hardcode names.
Single-agent execution follows the same claims and gates.

Claim each ready Task with `spoq_claim_task`; retain its token and renew using
`spoq_renew_claim` during long work. Pass `claim_token` on status updates. Do not
overwrite a live claim. Recover expired work through SPOQ and inspect its existing
artifacts before starting another attempt.

Check the persisted attempt budget before claiming new work. An exhausted failed
Task stays failed without another claim or implementation pass. An interrupted
last attempt may still be inspected/validated; PASS can finish that same attempt,
but FAIL cannot start another one without an authorized budget increase.

Persist `data.retry_count` before each implementation attempt using `spoq_edit_node`
and a fresh expected revision. It counts **attempts started**, with default
`data.max_retries=3` meaning at most three total attempts, including the first.
Reuse these values across resume; never grant an extra attempt when exhausted.
Only explicit user authorization can reset/raise an exhausted budget. Metadata
edits merge top-level fields, so preserve existing execution metadata. If interrupted
after an attempt starts, inspect/validate its artifacts before spending another.

Workers implement the saved acceptance criteria with meaningful unit tests and
run the repository's required build/checks and real execution path. Read inboxes
at checkpoints, acknowledge messages, and resolve discussions with decisions.
Use stable message retry keys. Known Codex runtime/thread routes can use the
dispatcher; native handles use relay or direct inbox reads without setup friction.
Peer messages coordinate within the existing task authorization.

## Compose QA and bounded rework

Run `../spoq-validation/SKILL.md` for each implemented Task. Pass its specification,
actual artifacts, run identity, and observed checks; retain the returned report
and journal ID. Independent reviewers do not implement the work they review.
Serialize integration checks over a stable working tree when workers share files.

On failure, investigate and fix the findings within the remaining attempt budget.
Use `rework` with the claim token to release the lease before another claim.
If exhausted, mark the Task `failed`, retain counters/findings, and stop its
dependents. Continue independent ready work where useful. Report an explicit
blocker or exhausted budget; do not repeat unchanged failing operations forever.
Plan changes return through the planning gate; implementation changes return
through affected tests and code validation.

## Complete verified work

Complete a Task with `spoq_update_node` only after QA PASS, including its current
claim token and evidence: validation journal/report, tests, build/run results,
acceptance checks, and changed artifacts. Recompute DAGs as dependencies close.
Before closing a Feature or Project Plan, validate the integrated requested scope
with `../spoq-validation/SKILL.md`; reuse a task-level result only if it covers the
same integrated artifacts and criteria. All children and prerequisites must pass.

Append progress/completion journals with scope, counters, results, decisions,
limitations, and confidence. Return completed IDs, gate/evidence IDs, remaining
work, and blockers to root SPOQ or the direct caller. Follow repository rules for
commits, deployment, and publication; stage execution adds no new authorization.
