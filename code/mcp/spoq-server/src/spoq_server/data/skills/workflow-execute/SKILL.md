---
name: workflow-execute
description: Run a SPOQ epic as a Claude Code dynamic workflow with deterministic compiled dispatch. Use when running `/workflow-execute @spoq/epics/active/epic-name` to compile an epic's waves into a workflow script (Opus workers, build verify, Sonnet QA, rework/HALT) and execute it on the dynamic-workflow runtime. Claude Code only — degrades to /agent-execution when workflows are unavailable.
---

# Workflow Execution Skill

Compiles a SPOQ epic into a deterministic Claude Code **dynamic-workflow** script and runs it. It is the **Claude-path executor** — a peer of `/agent-execution`, not a replacement. Where `/agent-execution` keeps the dispatch plan in the orchestrating LLM (re-derived every turn), `/workflow-execute` **compiles the plan into code**: the loop, the 95/80 gate, the rework counter, and the HALT live in a `.js` script the runtime drives the same way every run.

## When to Use

Use `/workflow-execute` when **all** of the following hold:
- You are on Claude Code (≥ v2.1.154) with dynamic workflows enabled. (Version and the concurrency/agent caps cited here are per `references/runtime-api.md` — verify against your installed Claude Code build.)
- The epic is in `spoq/epics/active/` and has **passed `/epic-validation`** (the planning gate is a pre-flight boundary — see HaaA below).
- You want deterministic dispatch, runtime-enforced concurrency caps, live `/workflows` phase observability, and a saved rerunnable command.

Prefer **`/agent-execution`** instead when:
- On Qwen/Codex, or dynamic workflows are disabled/unavailable (`/workflow-execute` degrades to it automatically).
- The epic has many `human_required` tasks or expected mid-run human consultation — the runtime forbids mid-run input, so those degrade poorly.

## Epic Directory Structure (3-Tier Lifecycle)

Only epics in `spoq/epics/active/` are executable. `backlog/` is deferred, `complete/` is archived. An epic is `EPIC.md` + `tasks/*.yml`.

## MCP Detection

Call `spoq_ping` once per session:
- success → `MCP_MODE=true` — use `spoq_*` MCP tools for status writeback and conflict detection at runtime.
- failure → `MCP_MODE=false` — the compiler and the emitted script fall back to the bundled Python scripts in `.claude/skills/workflow-execute/scripts/` and in-place YAML edits.

The compiler itself does not require the MCP server — it uses the shared SPOQ engine (`.claude/skills/lib/epic_utils.py`, the same code the MCP server wraps), so the dependency DAG is identical either way.

## Workflow-Runtime Detection (orthogonal to MCP)

`spoq_ping` says nothing about whether the dynamic-workflow runtime exists. These are independent axes. Workflows are unavailable when any of these hold:
1. `disableWorkflows: true` in project/user `settings.json`.
2. `CLAUDE_CODE_DISABLE_WORKFLOWS=1` in the environment.
3. Claude Code older than v2.1.154 (no workflow substrate).

**Invoking this skill is the opt-in.** If you cannot positively confirm workflows are available, **announce the downgrade and delegate to `/agent-execution`** over the same epic — fail-safe to the portable path, never fail-closed.

## Invocation

```
/workflow-execute @spoq/epics/active/<epic-name> [flags]
```

### Arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `--max-retries N` | 3 | Rework attempts per task before HALT |
| `--min-score N` | 95 | QA pass threshold (average) |
| `--min-metric N` | 80 | QA pass threshold (per-metric floor) |
| `--resume` | off | Also re-action `qa`/`failed` carryover (not just `pending`/`rework`/`in_progress`); smart-reviews interrupted work before re-dispatch |
| `--auto-complete` | off | Auto-fire `spoq_complete_epic`; default stops at a human accept gate |

### Examples

```bash
/workflow-execute @spoq/epics/active/my-epic
/workflow-execute @spoq/epics/active/my-epic --max-retries 2 --resume
```

## Workflow

```
┌──────────────────────────────────────────────────────────────────┐
│ 0. PRE-FLIGHT: confirm epic passed /epic-validation + human OK     │
│ 1. spoq_ping → MCP_MODE ; detect workflow runtime → WORKFLOW_MODE  │
│    if WORKFLOW_MODE=false → delegate to /agent-execution and stop   │
│ 2. COMPILE: scripts/compile-workflow.py --epic <path> [flags]       │
│      → .spoq/workflows/<epic>.workflow.js                           │
│ 3. RUN: invoke the Workflow tool with { scriptPath }                │
│ 4. The script drives, per wave (sequential; tasks parallel inside): │
│      detect conflicts → parallel safe workers / serialize the rest  │
│      → files_to_touch guard → build verify → Haiku triage on fail   │
│      → per-task Sonnet QA (95/80) → rework loop → HALT on max-retry  │
│      → spoq_update_task_status writeback after every transition      │
│ 5. COMPLETE: stop at "awaiting accept" (or --auto-complete fires     │
│    spoq_complete_epic: active→complete, map + ROADMAP.yml, journal)  │
└──────────────────────────────────────────────────────────────────┘
```

### Step 2 — Compile

```bash
mkdir -p .spoq/workflows
python3 .claude/skills/workflow-execute/scripts/compile-workflow.py \
  --epic spoq/epics/active/<epic-name> --max-retries 3 --min-score 95 \
  > .spoq/workflows/<epic-name>.workflow.js
```

The compiler parses the epic, computes waves, **hard-errors on any task status outside `VALID_STATUSES`** (catching the `complete` vs `completed` trap), prints an agent-spawn estimate against the 1000-per-run cap, and emits the script. The compiled `.js` is the readable, deterministic, version-controllable artifact — commit it (e.g. under `.spoq/workflows/`).

### Step 3 — Run

Invoke the **Workflow tool** with `{ scriptPath: ".spoq/workflows/<epic-name>.workflow.js" }`. Watch progress with `/workflows`. Iterate by editing the script and re-invoking with the same `scriptPath`; resume an interrupted run with `{ scriptPath, resumeFromRunId }`.

> **Before launching**, add `./init.sh`, `git`, the package manager, and `mcp__spoq__*` to the session tool allowlist so the run is non-interactive (spawned agents auto-approve edits but non-allowlisted shell/MCP calls still prompt). See `references/runtime-api.md`.

## Generated Workflow Shape

See `.claude/skills/workflow-execute/references/runtime-api.md` for the runtime surface. Key encodings (faithful to `/agent-execution`):
- **Epic = sequential `for`-loop; wave = `parallel()` barrier.** Never `pipeline()` — that would let a later wave start before its dependencies finish.
- **Build verify / status writes / conflict detection / QA are all agents** — the workflow script has no filesystem or shell access.
- **The 95/80 gate is a literal JS comparison** on schema-validated numbers; the QA agent inlines the 10-metric rubric and returns JSON (the `/agent-validation` skill emits a human box, not parseable output, so it is **not** called as a slash command here).
- **HALT is a `throw` from the top-level loop**, evaluated after the `parallel()` QA barrier (a throw inside a `parallel()` thunk is swallowed).
- **Status writeback after every transition** (`in_progress` before the worker, `completed`/`failed` after) is the only durable checkpoint across a cold restart.

## File-Write Safety

The runtime gives no file locking, and parallel workers edit one shared tree in `acceptEdits` mode. v1 strategy:
- **Disjoint-file concurrency + serialize.** Before each wave, `spoq_detect_conflicts` (fallback: compare `files_to_touch`) splits the wave into `safe_tasks` (run in `parallel()`) and `conflicting_tasks` (run one-at-a-time). The orchestrator *is* the `orchestrator_merge`.
- **Post-wave guard.** A `git diff --name-only` agent flags edits outside the union of declared `files_to_touch`.

**v1 provides race DETECTION, not race PREVENTION.** `files_to_touch` is a planner *estimate*; a worker touching an undeclared file can still race. `isolation:'worktree'` (per-worker git worktrees + a merge agent) is deliberately **deferred** — the in-script merge is unsolved without filesystem access. Keep epics well-decomposed with disjoint `files_to_touch`.

## Human-as-an-Agent (HaaA) Boundaries

The runtime forbids mid-run user input, so every HaaA touchpoint is a **run boundary**, with on-disk YAML status as the durable handoff:
1. **Epic-validation sign-off (95/90):** a pre-flight boundary. Do **not** compile/launch for an epic that has not cleared `/epic-validation` + human approval.
2. **`human_required: true` tasks:** scan the epic before compiling. If any task sets this, do not compile a fully-autonomous run for the wave containing it — surface the human action and let `spoq_update_task_status` gate the next run. (The bundled example leaves this field commented out, and the compiler does not yet parse it — always scan the live epic yourself.)
3. **Mid-run agent→human consultation:** has no in-run equivalent. A worker hitting a genuine consultation need should HALT and surface the question (treated like a max-retries HALT), then resume after the human answers.
4. **Final accept:** unless `--auto-complete`, the run stops at "awaiting accept" so a human reviews the diff before the epic is moved `active→complete`.

## Task Status State Machine

`pending → in_progress → qa → completed`; branches `rework → in_progress` and `failed → HALT`. Persisted in-place in each task YAML (`status`, `last_update`, `progress_notes`) via `spoq_update_task_status` so a cold restart can `--resume`. Statuses are exactly `VALID_STATUSES = {pending, in_progress, qa, rework, completed, failed}`.

## Resumability

Runtime resume is **in-session only**; cross-session durability comes from the disk writeback. On a cold restart, re-invoke with `--resume`: the recompiled script skips only on-disk `completed` tasks and re-actions everything else — `pending`/`rework`/`in_progress` plus `qa` (worker finished but never validated → re-run worker+QA) and `failed` (halted after max-retries → deliberate re-attempt). Any non-`pending` carryover is smart-reviewed (git status/diff, lint, build) before continuing or rolling it back. A re-attempted `failed` task continues from its persisted `retry_count` toward `max_retries` (3), so it gets at most 3 attempts total before it stays `failed` and HALTs for human escalation. `/agent-execution` and `/team-execution` follow the same 3-attempt-then-escalate contract.

## Agent Roles

| Role | Model | Job |
|------|-------|-----|
| Worker | Opus | Task execution + tests |
| Reviewer | Sonnet | 10-metric QA (95/80) |
| Investigator | Haiku | Build-failure triage, status writes, conflict/guard checks |

(`model` is a tier hint within the Claude family — the dynamic-workflow runtime is Claude-only.)

## Scripts

| Script | MCP mode | Fallback |
|--------|----------|----------|
| `scripts/compile-workflow.py` | uses shared `lib/` engine | same (no MCP needed to compile) |
| `scripts/parse-epic.py` | — | parse epic to JSON when MCP unavailable |
| `scripts/build-dependency-graph.py` | — | compute waves when MCP unavailable |

> **Note:** the emitted workflow template lives inside `compile-workflow.py` (not a separate `.js.tmpl`) so codegen and the template cannot drift.

## Known Limitations

- **Claude-only.** Dynamic workflows are a Claude Code feature; this skill is intentionally not ported to Qwen/Codex (a stage cannot route to their models). Use `/agent-execution` there.
- **Skill→workflow dispatch is LLM-mediated.** Determinism is real *inside* the compiled `.js`; the skill still relies on the orchestrator actually compiling and running it.
- **Cost.** Every status/build/triage/QA/guard step is a separate agent spawn — more spawns than `/agent-execution`. The compiler prints an estimate and warns near the 1000-agent cap; split large epics.
- **Race detection, not prevention** (see File-Write Safety).

## IMPORTANT Rules

1. Never compile/launch an epic that has not passed `/epic-validation`.
2. Never use `isolation:'worktree'` in v1 — it is unsupported (no merge agent).
3. Always keep `spoq_update_task_status` writeback — it is the only cold-restart durability.
4. Default to the human accept gate; only `--auto-complete` when explicitly requested.
5. If you find a bug while executing, fix it on the spot (project rule).

## Epic Completion

On all tasks passing: without `--auto-complete`, stop at "awaiting accept". With it (or as a follow-up human-triggered run), `spoq_complete_epic` moves the epic `active→complete`, updates the parent map and `ROADMAP.yml`, and writes a final `journal.md` entry. The last `completed` writeback returns `epic_complete: true` as the trigger.
