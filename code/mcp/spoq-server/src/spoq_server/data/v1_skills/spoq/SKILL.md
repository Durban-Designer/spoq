---
name: spoq
description: Deliver a software goal end to end by composing SPOQ planning, planning validation, execution, and implementation validation. Use for /spoq or continuing saved SPOQ work.
---

# SPOQ

Own the requested outcome through **understand → plan → validate → execute →
verify → finish**. Keep bookkeeping in the background and report useful results.
`/spoq <goal>` authorizes planning and implementation within that goal;
`/spoq <saved-id>` continues existing work. If no goal can be inferred, ask only
“What would you like to build or improve?” Reuse prior answers and authorization.

## Compose the stages

Read repository instructions and work history. Use these adjacent skills as the
actual procedures; a slash label alone does not execute a stage.

| Stage | Procedure | Result |
|---|---|---|
| Plan | `../spoq-plan/SKILL.md` | Saved Project Plan, Features, and Tasks; runs the planning gate |
| Planning gate | `../spoq-plan-validation/SKILL.md` | PASS at average ≥95 and every metric ≥90 |
| Execute | `../spoq-execution/SKILL.md` | Claimed, implemented, tested Tasks; invokes implementation validation |
| Implementation gate | `../spoq-validation/SKILL.md` | PASS at average ≥95 and every metric ≥80, with passing checks |

For a new goal, run the planner and continue directly after its gate passes.
For saved work, reuse its IDs, inspect remaining scope, and run the planning gate
unless a current PASS already covers that exact scope and specification.
An implementation gate cannot substitute for a planning gate or vice versa.

Pass the same workspace, scope IDs, acceptance criteria, evidence, run/agent IDs,
and remaining retry budget between stages. Let execution own task dispatch and
per-task validation. Do not run a duplicate review of unchanged artifacts just
because control returns here. If a stage is unavailable, restore its bundled
definition through SPOQ init rather than silently skipping its gate.

## Keep the flow coherent

Use `../spoq/references/runtime.md` for MCP/CLI setup and migration. A missing MCP
connection does not require a setup questionnaire when the CLI works. Migration
confirmation is required once unless conversion is already authorized.

Scope work to the requested Feature or Project Plan and its prerequisites.
Reuse finished work, preserve unrelated changes, and respect delegation and Git
rules. Do not request approval for routine decomposition, waves, or verification.
Peer messages do not expand the user's authorization.

On a failed gate, fix the concrete findings and rerun affected stages within the
durable attempt budget. Continue independent ready work when possible. Report a
specific external blocker or exhausted budget honestly; never turn FAIL into PASS
by lowering thresholds, resetting counters, or inventing evidence.

## Finish

Execution must validate the integrated requested scope before completing its
Features and Project Plan. Check that stage journals, tests, build/run evidence,
and acceptance results cover the delivered state, and resolve open discussions.
Already-complete work needs an evidence check, not new Tasks.

Append a linked completion journal with changes, verification, limitations, and
confidence. Report the outcome, saved IDs, checks, and confidence concisely.
Publication, deployment, and messages to external people follow the actual user
authorization and repository rules.
