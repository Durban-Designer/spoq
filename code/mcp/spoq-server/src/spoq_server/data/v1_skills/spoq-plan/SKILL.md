---
name: spoq-plan
description: Plan or refine a feature or project with SPOQ, saving a validated Project Plan and Feature/task DAGs. Use for /spoq-plan and planning-only requests; /spoq carries work through implementation.
---

# SPOQ plan

Turn the user's goal into executable work in SPOQ's SQLite store. This replaces
`epic-planning`, `feature-planning`, and `project-planning` for SPOQ 1.0.
Finish with a saved, validated plan; implementation belongs to `/spoq`.

## Start with the goal

Use the request and repository context already available. Inspect relevant code,
repository instructions, tests, and prior work before asking for information.
If no goal or existing work is specified, ask only: “What would you like to build
or improve?” Ask further questions only when an answer changes scope or correctness.
Choose routine implementation details yourself and state material assumptions.

## Connect without making setup the user's job

Use `../spoq/references/runtime.md` for MCP/CLI setup, migration, and stage
handoffs. Keep the same workspace throughout. Missing MCP provisioning is not a
reason to stop when the CLI is usable; conversion confirmation is needed only
when not already authorized.

## Shape and save the work

Read existing nodes and relevant journal entries first. Reuse the intended plan
and Feature; do not create duplicates on a repeat invocation. Use stable, readable
IDs such as `checkout`, `checkout/api`, and `checkout/api/contract`.
If the request extends completed work, reopen its completed ancestors from the
Project Plan down before editing dependencies or adding children. Leave unrelated
completed work alone; a repeat invocation is not itself a reason to reopen anything.

- A **Project Plan** contains Features and their dependencies.
- A **Feature** contains one DAG of atomic Tasks. There is no epic/story/map layer.
- Each Task has one outcome and enough context for another agent to execute it.
  A small request may need only one Feature and one Task; do not inflate counts.

Store goals, descriptions, scope boundaries, assumptions, file ownership,
acceptance criteria, and concrete verification commands in node `data`.
Put external tracker IDs/URLs in `data.external_refs` when supplied. Inspect the
actual test/build setup; do not invent successful checks or arbitrary time estimates.
For multi-Feature work, connect Feature dependencies as well as each task DAG.

Use `spoq_create_project_plan`, `spoq_create_feature`, `spoq_create_task`,
`spoq_edit_node`, and `spoq_add_dependency`. CLI equivalents are `spoq create`,
`spoq list`, `spoq get`, `spoq edit`, `spoq depend`, and `spoq undepend`, each
with `--root <workspace>`. Read prior evidence with `spoq journals --node <id>`
and `spoq history <id>`. Use a structured tool argument or a safely quoted JSON
argument for metadata; never interpolate untrusted text into shell commands.

## Validate before finishing

Run `../spoq-plan-validation/SKILL.md` on the saved scope. It checks the Project
Plan's Feature DAG and each affected Feature's task DAG, acceptance coverage,
ownership, verification, and the ten-metric planning gate (average ≥95, floor ≥90).
Fix concrete findings and rerun affected checks before declaring readiness.
Bound repeated plan repairs to three passes; if still failing, journal the exact
findings and return FAIL rather than loop or begin implementation.

Append a linked planning entry with `spoq_append_journal` or `spoq journal ...
--node <id> --root <workspace>`. Leave implementation Tasks pending.
Report saved IDs, task/wave counts, assumptions, and the planning gate's verdict
and journal ID. A direct planning-only call can continue later with
`/spoq <saved-id>`. When root SPOQ invoked this stage, hand the same IDs and gate
evidence back so it can continue immediately. This stage never implements code.

## Strategy invocation

When dispatched by a saved strategy, read `../spoq/references/workflows.md` and
retain the supplied run/scope/phase/attempt IDs, input hashes and phase lease.
Do not create another run or recursively dispatch the root flow. Direct invocation
without a workflow envelope keeps this stage independently usable.

For PIQARD, an actual revision-bound narrative approval must precede decomposition;
never infer it from an agent message. A direct PIQARD planning-only request uses
the strategy driver through planning validation, then pauses before execution.
During an existing plan phase, save the intended root metadata and child DAGs
without changing the user's goal. Read the current specification before completion
and follow the explicit planning-refresh contract. Return a project_plan JSON
artifact linking scope/specification and the planning journal IDs. This stage
never implements code, even when another stage may run afterward.
