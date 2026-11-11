# SPOQ stage runtime

Use the same workspace and SQLite store throughout a composed run. Read the
repository's instructions and relevant journal before work. Try `spoq_ping` and
verify its project root and SQLite backend. If MCP is absent, legacy, or rooted
elsewhere, leave that connection alone and use a strategy-capable SPOQ CLI with
`--root <workspace>` on every command. Check `spoq --version`, `spoq doctor`, and `spoq workflow --help`; version alone does not establish strategy support.
If inherited `SPOQ_STORE` selects a legacy backend, set it to `sqlite` only for
these processes. Do not change the user's global configuration.

In the source checkout, use `uv run --project code/mcp/spoq-server spoq ...`.
Otherwise, if no installed 1.x CLI works and uv is available, try
`uv tool run --from 'spoq>=1.1,<2' spoq ...` and verify the resolved version.
If no usable runtime is obtainable, report the missing prerequisite honestly.
Creation initializes an empty store; no MCP restart is required.

If conversion is required, show `spoq_migrate(confirmed=false)` or
`spoq migrate --dry-run --root <workspace>` once and convert after confirmation.
Prior conversion authorization is sufficient. Maps become Project Plans; epics
become Features. Keep discovery moving while a required answer is pending.
Use the new store rather than legacy epic/map tools or direct SQLite writes.

| Purpose | MCP | CLI |
|---|---|---|
| Read nodes | `spoq_list_nodes`, `spoq_get_node` | `spoq list`, `spoq get <id>` |
| Inspect DAG | `spoq_compute_dag` | `spoq dag <scope-id>` |
| Edit metadata | `spoq_edit_node` | `spoq edit <id> --data '<JSON>' --revision <revision>` |
| Run/participant | `spoq_create_run`, `spoq_register_agent` | `spoq run <run-id> --scope <id>`, `spoq agent <run-id> <agent-id> --role orchestrator` |
| Claim/renew | `spoq_claim_task`, `spoq_renew_claim` | `spoq claim <id> --run <run-id> --agent <agent-id>`, `spoq renew-claim <id> <token>` |
| Update Task | `spoq_update_node` | `spoq update <id> <status> --claim-token <token> --evidence '<JSON>'` |
| Coordinate | `spoq_post_message`, `spoq_read_inbox`, `spoq_ack_message`, `spoq_resolve_thread` | `spoq post`, `spoq inbox`, `spoq ack`, `spoq thread`, `spoq resolve` |
| Journal/history | `spoq_append_journal`, `spoq_read_journal`, `spoq_get_history` | `spoq journal '<body>' --node <id>`, `spoq journals --node <id>`, `spoq history <id>` |

Inspect command `--help` for arguments. Use structured tool arguments or safe
shell quoting for JSON, never interpolation of untrusted text. Read fresh revisions
before edits, merge existing metadata, and resolve conflicts by rereading.

## Stage handoff

Each stage returns its name, scope IDs, PASS/FAIL (or blocked), findings, and linked
evidence/journal IDs. Validation records include all ten scores, the unrounded
average and floor, reviewer identity/type, observed command results, and the
specification/artifacts examined. Append them to the SQLite journal linked to the
scope; pass their journal IDs through execution and completion evidence.
No separate Markdown planning authority is created.

Gate results apply to the reviewed scope and state. Changed goals, acceptance
criteria, ownership, or dependencies invalidate affected planning results.
Changed implementation/tests invalidate affected code results. Status changes,
claims, and retry bookkeeping alone do not invalidate a planning review. Reuse
evidence only after comparing the current relevant state to the recorded state.

The root skill bundles `scripts/score_gate.py`. Validation stages run it with
`--stage plan|implementation --input <JSON-file>` after doing the actual review.
Resolve resource paths relative to the skill definition that references them,
then invoke the helper with Python 3; do not assume the workspace is its folder.
Input has exactly the stage's ten named `scores` (numbers 0–100) and boolean
`checks_passed`; output is the computed gate report. Exit 0 means PASS, 1 FAIL,
2 invalid input. This checks arithmetic and thresholds; it does not perform the
review or prove the evidence. Keep reports even on failure.

## Existing SQLite upgrades

Read `spoq_workflow_capabilities` or `spoq workflow upgrade --dry-run --root
<workspace>` before opening a schema-1 store for workflow writes. Show the backup
and schema preview, then use prior authorization or obtain confirmation once.
`spoq_upgrade_workflow(confirmed=true)` or `spoq workflow upgrade --yes --root
<workspace>` performs the consistent backup and upgrade. `spoq init --upgrade`
also prompts; noninteractive clients use --yes only with authorization. Legacy
Markdown conversion produces the current schema in one authorized conversion.
Older binaries reject newer schemas; restoration requires a clean destination.

Managed skill updates archive replaced entrypoints/resources under
`.spoq/legacy-managed-skills/` and UI metadata under
`.spoq/legacy-skill-metadata/`. Custom siblings, invocation policy and unrelated
dependencies remain. Prior customized managed bytes are retained for review; they
are not automatically merged into new procedural instructions. Identical
reinstallation does not create duplicate backups or overwrite unchanged files.
