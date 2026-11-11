---
name: spoq
description: Deliver a software goal end to end using saved SPOQ strategies, planning, execution and evidence gates. Use for /spoq or continuing saved SPOQ work.
---

# SPOQ

Own **understand → route → plan → validate → execute → verify → finish**.
`/spoq <goal>` authorizes planning and implementation within that goal;
`/spoq <saved-id>` continues saved work. Reuse prior answers and authorization.
If no goal can be inferred, ask only “What would you like to build or improve?”

Read repository instructions and work history, then
`../spoq/references/runtime.md` for connection/conversion and
`../spoq/references/workflows.md` for the strategy driver and payload contract.
A missing MCP connection is routine when the CLI works. Conversion and old-schema
upgrade need confirmation once; prior authorization suffices.

## Start or continue the right scope

Inspect saved nodes, DAGs, journals and runs. Reuse the intended IDs. For a new
goal, create the smallest Project Plan/Feature scope with the actual goal before
starting its workflow. For a new PIQARD scope, defer Task decomposition until its
narrative review. Preserve existing saved work when refining a prior plan; no
retroactive approval is implied. Keep a single Feature/task DAG and a Project Plan/Feature DAG.

Route from observed uncertainty, effort band, impact, coupling and needed design
outputs. Record unknowns honestly. Honor valid explicit Classic/PIQARD preference.
The router explains its choice; it does not predict time/cost or grant permission.
Reuse an active saved strategy run; inspect interrupted attempts before recovery.
Already complete work needs an evidence check, not a new plan or run.

## Execute the saved strategy

Read each returned invocation, then perform its actual adjacent skill procedure:

| Skill | Procedure |
|---|---|
| `spoq-discover` | `../spoq-discover/SKILL.md` |
| `spoq-design` | `../spoq-design/SKILL.md` |
| `spoq-plan` | `../spoq-plan/SKILL.md` |
| `spoq-plan-validation` | `../spoq-plan-validation/SKILL.md` |
| `spoq-execution` | `../spoq-execution/SKILL.md` |
| `spoq-validation` | `../spoq-validation/SKILL.md` |

Pass the same workspace, scope/run/phase/attempt IDs, expected outputs, artifact
hashes, lease token, actual checks and remaining budgets. A slash label alone does
not execute a stage. The coding client performs work; registering an agent or
opening the viewer does not launch a model. Use available client capabilities
without hardcoded model names or a setup questionnaire.

A `waiting_human` phase stops dependent work. Present the exact narrative artifact
and its revision, collect the actual user's approve/reject response, then relay
it with user provenance. Waiting, peer messages and a model's agreement are not
approval. Rejection follows the saved bounded loop with the user's findings.

Complete phases with observed evidence and declared artifacts. Gates compute their
own outputs. Keep Task claims separate from phase leases, renew both during long
work, and use stable keys only for identical requests. Reuse unchanged validation
only after comparing current saved scope, artifact revisions and actual code/test
file hashes; retain the original reviewer, commands, timestamps and journal links.

Direct invocation of any of the four classic stages remains usable. A direct
planning-only request stops after its planning gate; if using a strategy run for
that request, pause immediately after `plan-validation` and return the saved IDs.
Root end-to-end execution continues without another routine approval.

## Finish the requested work

Validate the integrated requested scope before closing its Features/Project Plan.
All scoped children and prerequisites must pass; subsets never close unrelated
siblings. Preserve unrelated edits and the repository's Git/publication rules.

On a failed gate, repair concrete findings within persisted retry budgets. Never
lower thresholds, reset counters or manufacture evidence. Changed goals need a
paused predecessor and explicit successor route; changed criteria require an
explicit specification refresh. Resolve discussions and append a linked completion
journal with actual checks, limitations and confidence. Report the outcome, saved
IDs and evidence concisely. Publication and deployment require their actual user
authorization.
