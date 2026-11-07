# Claude Code Dynamic-Workflow Runtime API (reference)

The surface `compile-workflow.py` targets. A dynamic workflow is a JavaScript
script Claude Code's runtime executes in an isolated environment, separate from
the conversation; intermediate results stay in script variables and only the
final answer returns to the session. See Anthropic's
[Dynamic Workflows](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code)
and `documents/core/architecture/DYNAMIC_WORKFLOWS_COMPARISON.md`.

> The public blog/docs describe the behavior and phase model but do not print
> the script API. The signatures below are the surface the emitted script uses;
> validate against your installed Claude Code (≥ v2.1.154) before relying on
> any detail not exercised by the generated script.

## Script shape

Every script begins with a pure-literal `meta` export, then the body:

```javascript
export const meta = {
  name: "workflow-execute:<epic>",   // string
  description: "...",                 // string, shown in the permission dialog
  phases: [{ title: "Wave 0" }, ...]  // one entry per phase() group
};
// body — runs in an async context; use await directly
```

`meta` must be a literal (no variables, calls, or interpolation).

## Primitives (globals in the script body)

| Primitive | Purpose |
|---|---|
| `agent(prompt, opts?) → Promise` | Spawn a subagent. Without `schema`, resolves to its final text. With `schema` (a JSON Schema), the subagent is forced to return a validated object. Resolves to `null` if the user skips the agent. |
| `parallel(thunks) → Promise<any[]>` | Run `() => Promise` thunks concurrently. **Barrier**: awaits all. A throwing thunk resolves to `null` in the result array (the call never rejects) — `.filter(Boolean)` before use. |
| `pipeline(items, ...stages) → Promise<any[]>` | Each item flows through all stages independently, **no barrier between stages**. Not used here (see below). |
| `phase(title)` | Start a new progress group; subsequent `agent()` calls are grouped under it. |
| `log(message)` | Emit a narrator line to the user. |

`agent` options: `{ label, phase, schema, model: 'opus'|'sonnet'|'haiku',
isolation: 'worktree', agentType }`. `model` is a tier hint **within the Claude
family** — it is **not** a cross-provider selector (a stage cannot route to
`gpt-5.5`/`qwen3-coder-plus`).

## Constraints the compiled script must respect

- **No filesystem or shell access from the script itself.** Only spawned agents
  read, write, and run commands. The script only coordinates and holds data in
  JS variables. → build verification, status writeback, and conflict detection
  are all `agent()` calls, never inline shell.
- **`parallel()` swallows throws** (a failing thunk → `null`). A hard HALT must
  be thrown from the **outer sequential code**, after collecting `parallel()`
  results — never from inside a thunk.
- **Concurrency cap:** `min(16, cores − 2)` concurrent agents; **1000 agents
  total per run** (a runaway backstop). The compiler prints a spawn estimate.
- **Resume is in-session only.** Completed `agent()` calls return cached results
  on resume, but exiting Claude Code mid-run restarts the script fresh.
  → durability comes only from the `spoq_update_task_status` writeback.
- **No mid-run user input** (only per-agent permission prompts can pause a run).
  → human gates (epic-validation sign-off, `human_required` tasks, mid-run
  consults, the final accept) are run boundaries, not in-run stages.
- **Permissions:** spawned subagents run in `acceptEdits` mode and inherit the
  session tool allowlist; non-allowlisted shell/MCP calls (`./init.sh`, `git`,
  the package manager, `spoq_*`) can still prompt mid-run. Add them to the
  session allowlist before launching for a non-interactive run.
- **No `Date.now()` / `Math.random()` / argless `new Date()`** (they break
  resume). The emitted script uses none.

## Why `for`-loop + `parallel()`, never `pipeline()` for the epic

A SPOQ epic is **waves that must complete before the next begins** (cross-wave
dependencies). `pipeline()` has no inter-stage barrier, so wave-2 tasks could
start while wave-1 is mid-flight — violating the dependency invariant. The epic
is therefore a sequential `for`-loop; each wave fans out with `parallel()`
(the barrier), and build-verify + QA run as explicit steps after the barrier.

## Running and iterating

The skill invokes the **Workflow tool** with `{ scriptPath: "<...>.workflow.js" }`.
Iterate by editing the script and re-invoking with the same `scriptPath`; resume
with `{ scriptPath, resumeFromRunId }`. `/workflows` shows live phase progress
(agent counts, tokens, elapsed) and lets you pause/stop/restart and save the run
as a `/<name>` command.
