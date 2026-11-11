# Strategy driver and payloads

Read this when root SPOQ starts/resumes a strategy or a stage receives an invocation.
Keep the same explicit workspace throughout. Paths beginning `.claude/skills/`
are workspace-relative and translated by installation for the current client.
The deterministic helper is `.claude/skills/spoq/scripts/workflow_payload.py`.

## Discover, start and inspect

Call `spoq_workflow_capabilities` for schema, tool inventory and client-driven
execution support. Use `spoq_list_workflows(scope_id=...)` to reuse the active run.
`spoq_route_workflow(inputs=..., strategy=...)` explains the deterministic route.
Start with `spoq_start_workflow(run_id, scope_id, key, inputs, strategy, actor)`.
The scope must already exist. Starting pins the route/definition and registers the
orchestrator; register additional workers through `spoq_register_agent`.

CLI equivalents use `--root <workspace>` on **every** invocation:

```text
spoq workflow list --scope <scope-id> --root <workspace>
spoq workflow route --inputs @route.json --root <workspace>
spoq workflow start <run-id> --scope <scope-id> --inputs @route.json --key <stable-start-key> --root <workspace>
spoq workflow inspect <run-id> --root <workspace>
spoq workflow next <run-id> --agent <agent-id> --key <stable-invocation-key> --ttl 3600 --root <workspace>
```

Use actual context for route inputs: effort small/medium/large/unknown;
uncertainty low/medium/high/unknown; impact low/medium/high/critical/unknown;
coupling low/medium/high/unknown; addons diagram/erd/algorithm/formal booleans.
Unknowns may select PIQARD. `formal_proof_required=true` needs an observed available
proof capability; a written specification is not a proof. Keep explicit user
strategy preference where valid; Classic cannot silently drop requested addons.

A new minimal scope stores the user's goal before routing. Finalize its raw user
inputs deliberately: changing accepted criteria outside an active planning phase
requires explicit resume refresh; changing goal/user inputs requires fresh
successor routing. Derived root planning metadata and child-node/edge writes use
the planning completion-refresh path below.

## Perform one invocation

Persist a distinct operation key for each logical invocation, completion, renewal
or decision. Retry an identical payload with its original key. A new phase or
deliberate recovery is a new request; never recycle one next key across phases.

`spoq_next_workflow_phase` returns IDs, `skill`, `kind`, `inputs`, expected outputs,
input artifact hashes, definition/specification hashes, `token`, lease, revision,
prior artifacts and inspection flags. Read referenced content through
`spoq_workflow_artifact(run_id, artifact_id)`; envelopes contain metadata rather
than unlimited content. Read actual saved criteria with `spoq_workflow_node`.
For execution, use `spoq_compute_dag` and real Task claims; paginate linked work
through `spoq_workflow_work` or `spoq workflow work` when `has_more` is set.

`spoq_renew_workflow_phase` / `spoq workflow renew` renew the current phase lease;
`spoq_renew_claim` renews each Task claim. TTL is at most 3600 seconds. Before
recovering expired work inspect its registered artifacts and receipts. Use
`spoq_next_workflow_phase(recover=true)` or `spoq workflow next --recover`; this
retains the attempt and fences the former owner. `needs_inspection=true` means
inspect ambiguity before repeating side effects, including on the final attempt.
Never spend a new attempt merely because a process or connection restarted.

Complete through `spoq_complete_workflow_phase`, or:

```text
spoq workflow complete <run-id> <attempt-id> --token <token> --agent <agent-id> --key <stable-completion-key> --evidence @evidence.json --outputs @outputs.json --root <workspace>
```

Use the invocation's exact identities and artifact hashes. Evidence includes:

```json
{
  "run_id": "saved-run", "scope_id": "saved-scope", "phase_id": "saved-phase",
  "attempt_id": "saved-attempt", "definition_hash": "copy actual hash",
  "specification_hash": "copy actual hash", "artifact_hashes": {},
  "reviewer": {"agent": "actual reviewer", "review_type": "self_review"},
  "checks_passed": true,
  "observed_checks": [{"check_type": "command", "command": "actual command",
    "exit_code": 0, "source": "actual observation source", "observed": true}],
  "acceptance_results": [{"criterion": "actual criterion", "passed": true}]
}
```

This is a shape example, not evidence to copy as successful. Record real results,
including failures. Non-command observed checks use type review/artifact/tool,
name, boolean passed, source and observed=true. Distinguish self_review,
independent and scripted_adapter; a producer cannot label itself independent.
Keep original command provenance and reviewed artifacts when reusing results.
The server validates submitted observations; it does not authenticate humans,
rerun commands or inspect arbitrary workspace files to prove claims.

Gate phases additionally require all ten named metric scores. Planning passes at
95 average/90 floor; implementation at 95/80, with passing required checks. Run
`.claude/skills/spoq/scripts/score_gate.py` from the workspace for direct stage reviews.
For a workflow gate, submit evidence with scores and no replacement outputs: the
engine computes and stores its gate artifact. A failed required check cannot be
overridden by a high score.

Other phases supply exactly the expected outputs, for example
`{"discovery":{"content":"reviewable constraints and decisions","source":"agent"}}`.
A registered artifact ID is also accepted if it belongs to this attempt/kind.
`project_plan` and `implementation` content must be JSON linking the actual
`scope_id` and current `specification_hash`. Include `reviewed_files` mapping
workspace-relative code/test paths to actual SHA-256, `validation_journal_ids`,
and check references in implementation content. Record those hashes before reusing
prior tests/gates; missing or changed files require affected validation again.
The payload helper hashes files and checks reuse without inventing review scores.

```text
python3 .claude/skills/spoq/scripts/workflow_payload.py evidence invocation.json observations.json --output evidence.json
python3 .claude/skills/spoq/scripts/workflow_payload.py work-output invocation.json --root <workspace> --files <code-file> <test-file> --journals <validation-journal-id> --output outputs.json
python3 .claude/skills/spoq/scripts/workflow_payload.py check-files implementation-artifact.json --root <workspace>
```

Use the client's Python 3 interpreter. A stale/missing file makes check-files exit
1; malformed/ambiguous input exits 2. File equality alone does not establish a
matching specification or passing review.

If planning created/edited derived root planning metadata or children while the original user inputs stayed the
same, retain the original invocation/attempt/token and read its fresh hash with
`spoq workflow inspect <run-id> --root <workspace>` or `spoq_inspect_workflow`.
Use the returned `current_specification_hash` in the evidence and work-output JSON,
then complete that original attempt with `refresh_spec=true` / `--refresh-spec`.
Do not call next merely to obtain a fresh hash: dispatch deliberately rejects an
unreviewed changed specification. Retain the original input
hash in provenance. Interrupted planners can recover the same attempt with these
flags. Criteria changes outside active planning use explicit resume refresh; raw user
input/goal changes use a successor. Never quietly rebase an unrelated changed specification.

## Human review and planning-only boundaries

A human phase returns no worker token and has no worker TTL requirement. Present
its exact primary artifact content, ID and SHA-256. Only after the actual user
responds call `spoq_respond_workflow` with source=user, user_confirmed=true,
current attempt/artifact/hash, author, decision, reason, key and fresh expected
revision. CLI:

```text
spoq workflow respond <run-id> <attempt-id> --artifact <artifact-id> --hash <sha256> --decision approve --author <user> --source user --user-confirmed --key <stable-response-key> --revision <revision> --root <workspace>
```

Use reject with the user's findings when appropriate. Waiting/polling does not
consume implementation attempts. Peer messages, automated notifications, prior
approval of another revision and elapsed time never supply user confirmation.
If no answer is available, journal waiting_human and return the saved run/artifact
IDs; do not perform dependent decomposition or implementation.

For planning-only PIQARD, drive discovery/design/review/plan/plan-validation, then
call `spoq_pause_workflow` / `spoq workflow pause` before any execution invocation.
Return the saved scope and current planning gate. Calling the planner as an
already-dispatched plan phase must not create another strategy run or repeat its
human review. All four classic stages remain independently callable.

## Resume, progress and finish

Use `spoq_inspect_workflow` before `spoq_resume_workflow` or `spoq workflow resume`.
Changed acceptance criteria need `refresh_spec=true` / `--refresh-spec`; affected
history remains and budgets are retained. Changed goals require pausing the old
run and starting a new run with fresh inputs. At a safe boundary,
`spoq_propose_workflow_route` / `spoq workflow propose` records a successor proposal;
adoption is explicit. Reusable artifacts are candidates with provenance, never
inherited human approvals or passing gates. Exhausted limits require explicit
user authorization to increase; there is no automatic reset or extra retry.

`spoq_get_workflow` / `spoq workflow show` reads the committed snapshot;
`spoq_workflow_events` replays from its cursor. Global sequence gaps are normal.
A reset requires a fresh snapshot; apply identities once. Paginate older attempts,
artifacts, decisions and participants with `spoq_workflow_history`. A coding client
performs work; polling/relay is supported without universal native push.

For useful visual progress, open `spoq ui --run <run-id> --root <workspace>` once.
In a headless session use `--no-open`; port 0 selects an available loopback port.
It serves packaged assets and escaped registered text, with read-only endpoints;
it cannot approve a checkpoint or launch models. If assets are unavailable report
that fact and continue through the CLI/MCP state rather than claim a working UI.

Before completion, verify actual current file hashes and required checks, validate
the integrated requested scope, resolve discussions, then close only the proven
Tasks/Features/Project Plan. Link returned validation journal IDs in the completion
journal. Reuse unchanged review only after matching saved specification/artifact
and actual file state; record unsupported platforms/accounts as limitations.
