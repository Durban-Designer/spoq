# SPOQ 1.x operation

A Project Plan contains Features and their dependency DAG. Every Feature
contains Tasks and its own DAG. The model has no additional epic or story layer.
SQLite is authoritative; exported snapshots are for review and transfer.

Initialize a project with `spoq init --target /path/to/project --with-mcp`.
Select clients with `--agents claude,qwen,codex,cursor`. Run commands from the
project directory or pin an MCP launch with `spoq mcp --root /path/to/project`.

Use `/spoq <goal-or-saved-id>` to compose planning, planning validation,
execution, and implementation validation. Each stage is also independently
available as `/spoq-plan`, `/spoq-plan-validation`, `/spoq-execution`, and
`/spoq-validation`. Skill mentions use the same names with `$`.

Planning requires an average of at least 95 and a minimum score of 90.
Implementation requires 95 average, 80 minimum, and all required checks passing.
Record real checks and evidence before completing work. Agents claim Tasks
before executing them and use ready work from `spoq_compute_dag`.

## Upgrade existing projects

Back up the project and run `spoq init --upgrade`. The initializer detects
installed client integrations, refreshes managed guidance and MCP registrations,
and shows a migration preview. Confirm only after reviewing that preview.
`--yes` supplies an explicit confirmation for already-reviewed automation.

Legacy maps become Project Plans; epics become Features. Existing Tasks stay
under their Feature. Dependencies become the corresponding DAG edges. Original
files and byte provenance are retained in local migration backups. Conversion
is repeatable and validated before committing the new database transaction.
Use `spoq doctor` and `spoq migrate --help` for status and migration options.
Use `SPOQ_STORE=fs` only when intentionally continuing the old filesystem flow.

## Agent collaboration

Register a run and its agents, post durable messages with stable retry keys,
read inboxes at checkpoints, acknowledge receipt, and resolve discussions
explicitly. Messages support direct and role recipients and threaded replies.
Peer messages do not grant user authorization.

For Codex CLI push, register an accessible worker session UUID and run
`spoq dispatch`. A native subagent runtime handle is not a CLI session UUID;
its orchestrator can relay durable inbox notifications. The optional Codex
app-server bridge can notify a connected session. Availability depends on the
client runtime, so inbox checkpoints remain necessary.

## Local search

Keyword search works in the core installation. Install `spoq[search]` for
sqlite-vec and FastEmbed, then configure the local embedding backend and run
`spoq reindex`. The bundled CPU option uses the small Potion-8M model; its first
use downloads model files. Check `spoq search --help` and `spoq reindex --help`
for current options. Search is an index over saved data; it does not replace
the SQLite entity and dependency constraints.

## Verification

The normal suite exercises storage, migration, claims, collaboration, search,
native client scaffolding, CLI behavior, and real stdio MCP communication.
`tests/e2e/spoq_release.py` verifies an installed wheel or source distribution
in an isolated environment. Live Codex and Claude scripts are optional because
they need installed, authenticated clients; documentation and protocol checks
do not substitute for a live model run.
