---
name: agent-execution
description: Orchestrate parallel sub-agent swarms on automation epics. Use when running `/agent-execution @spoq/epics/epic-name` to execute multi-task epics with Opus workers and Sonnet QA.
---

# Agent Execution Skill

Coordinates parallel sub-agent execution on epics in `spoq/epics/`. Manages waves of Opus workers, build verification, and Sonnet QA with automatic rework loops.

## When to Use

Use this skill when:
- You have an epic in `spoq/epics/active/` ready for execution
- You want parallel sub-agents to complete multiple tasks
- You need automated QA with the agent-validation skill
- You want wave-based execution with dependency management

## Epic Directory Structure (3-Tier Lifecycle)

Epics follow a 3-tier lifecycle managed through directory placement:

| Tier | Directory | Purpose |
|------|-----------|---------|
| **Backlog** | `spoq/epics/backlog/` | Planned but not yet ready for execution |
| **Active** | `spoq/epics/active/` | Ready for or currently under execution |
| **Complete** | `spoq/epics/complete/` | Successfully executed and archived |

Only epics in `active/` are eligible for execution. Use `spoq_promote` and `spoq_demote` to move epics between backlog and active tiers.

## MCP Detection

Before executing any scripts, check if the SPOQ MCP server is available:

1. Call `spoq_ping` tool
   - **Success** → MCP_MODE=true (use MCP tools for all operations below)
   - **Tool not found / Error** → MCP_MODE=false (use Python scripts as fallback)

This check only runs once per session. All script references below provide both paths.

## Invocation

```bash
/agent-execution spoq/epics/epic-name
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--dry-run` | false | Show execution plan without running |
| `--max-retries N` | 3 | Max rework attempts per task |
| `--min-score N` | 95 | Minimum QA score to pass |
| `--wave N` | all | Execute only specific wave |
| `--task ID` | all | Execute only specific task |

### Examples

```bash
# Execute entire epic
/agent-execution spoq/epics/shadcn-migration

# Dry-run to see wave plan
/agent-execution spoq/epics/shadcn-migration --dry-run

# Execute only wave 2
/agent-execution spoq/epics/shadcn-migration --wave 2

# Execute single task
/agent-execution spoq/epics/shadcn-migration --task 05-create-badge

# Stricter QA threshold
/agent-execution spoq/epics/shadcn-migration --min-score 98
```

## Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AGENT EXECUTION FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. PARSE EPIC                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ MCP: spoq_parse_epic(epic_path)                                      │   │
│   │ Fallback: parse-epic.py → Read EPIC.md + tasks/*.yml                 │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│   2. COMPUTE WAVES                 ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ MCP: spoq_generate_execution_plan(epic_path)                         │   │
│   │ Fallback: build-dependency-graph.py → Topological sort → Waves       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│   3. EXECUTE WAVES (loop)          ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  FOR each wave:                                                      │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ a. Spawn Opus Workers (parallel, background)                 │    │   │
│   │  │    - One Task tool per task                                  │    │   │
│   │  │    - Model: opus                                             │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ b. Wait for Completion (TaskOutput)                          │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ c. Build Verification (./init.sh)                            │    │   │
│   │  │    PASS → continue to QA                                     │    │   │
│   │  │    FAIL → spawn Investigation Agent (Haiku)                  │    │   │
│   │  │           → identify failing tasks → mark for rework         │    │   │
│   │  │           → passing tasks proceed to QA                      │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ d. QA with /agent-validation (parallel, for passing tasks)   │    │   │
│   │  │    - Uses 10-metric scoring (≥95 to pass)                    │    │   │
│   │  │    - Returns concise remediation on failure                  │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ e. Process Results                                           │    │   │
│   │  │    PASS (≥95, all metrics ≥80) → mark completed              │    │   │
│   │  │    FAIL → queue for rework with feedback                     │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────┐    │   │
│   │  │ f. Rework Loop (if needed)                                   │    │   │
│   │  │    Re-spawn Opus with QA feedback                            │    │   │
│   │  │    max_retries exceeded → HALT EPIC                          │    │   │
│   │  └─────────────────────────────────────────────────────────────┘    │   │
│   │                              │                                       │   │
│   │  Journal entry for wave → Continue to next wave                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│   4. FINAL SUMMARY                 ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ Report: tasks completed, failed, overall completion rate            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Task Status State Machine

```
pending → in_progress → qa → completed
                     ↓    ↓
                  rework → (back to in_progress)
                     ↓
                   failed (after max_retries → HALT EPIC)
```

Status updates are written in-place to task YAML files.

## Resumability (Agent Handoff)

When an agent is interrupted mid-execution, another agent can seamlessly resume:

### State Persistence

Each task YAML tracks execution state:
```yaml
id: 03-implement-api
status: in_progress       # Current state
retry_count: 1            # Number of rework attempts
last_agent: opus-worker-3 # Last agent working on this
last_update: 2026-01-25T10:30:00Z
progress_notes: |
  - Completed API route setup
  - Working on validation logic
  - Blocked: waiting for schema from task 02
```

### Resume Protocol

When resuming an interrupted epic:

1. **Scan Task Status**
   ```bash
   grep -l "status: in_progress" spoq/epics/active/epic-name/tasks/*.yml
   ```

2. **Read Progress Notes**
   Check `progress_notes` field for where the previous agent left off.

3. **Smart Review Before Continuing**
   Run a quick validation on any partially completed work:
   ```
   Before resuming task 03-implement-api:
   - Check: Does the code compile?
   - Check: Are there uncommitted changes?
   - Check: What was the last git commit?
   ```

4. **Continue or Rollback**
   - If partial work is valid: continue from progress_notes
   - If partial work is broken: rollback and restart task

### Resume Command

```bash
/agent-execution @spoq/epics/active/epic-name --resume
```

The `--resume` flag (actionable statuses are `pending`, `rework`, `in_progress`, plus `qa` and `failed`):
- Skips completed tasks (status: completed)
- Picks up in_progress tasks from last checkpoint
- Re-dispatches rework tasks
- Re-runs `qa` tasks (worker finished but never validated)
- **Re-attempts `failed` tasks using their remaining retry budget.** A task carries `retry_count` toward `max_retries` (default 3); each resume continues that same count, so a task gets **at most 3 attempts total before it stays `failed` and is escalated to a human** (HALT). To grant a fresh budget, reset `retry_count` to 0.
- Runs smart review before continuing

> Pass `resume=True` to `spoq_generate_execution_plan` (or `--resume` to `build-dependency-graph.py`) so `qa`/`failed` carryover is flagged actionable. This matches `/workflow-execute` and `/team-execution` — all three re-attempt `failed` tasks up to the 3-attempt cap before escalating.

### Progress Checkpoints

Agents should update `progress_notes` after each significant step:

```yaml
progress_notes: |
  [2026-01-25T10:15:00Z] Started task
  [2026-01-25T10:20:00Z] Created API route file
  [2026-01-25T10:25:00Z] Added request validation
  [2026-01-25T10:30:00Z] Working on response formatting
```

This allows seamless handoff between agents.

### Smart Review on Resume

Before continuing interrupted work, run these checks:

1. **Code State**
   ```bash
   git status                    # Check for uncommitted changes
   git diff --stat               # See what changed
   npm run lint 2>&1 | head -20  # Quick lint check
   npx tsc --noEmit 2>&1 | head -20  # Quick TS check
   ```

2. **Build State**
   ```bash
   npm run build 2>&1 || echo "BUILD_BROKEN"
   ```

3. **Test State**
   ```bash
   npm test 2>&1 | tail -10      # Check test status
   ```

If any check fails, document the issue and either fix it or rollback before continuing.

## Agent Roles

### Opus Workers (per task)
- Execute task steps from YAML description
- Verify acceptance criteria
- Update/create tests as needed
- Return summary of work completed

### Haiku Investigator (on build failure)
- Analyze `./init.sh` output
- Cross-reference errors with task `files_to_touch`
- Identify specific failing task(s)
- Allow passing tasks to proceed to QA

### Sonnet QA (via /agent-validation)
- 10-metric scoring system
- Pass threshold: ≥95 overall, ≥80 per metric
- Concise remediation feedback (≤20 lines)

## Epic/Task Format Reference

### Epic Structure
```
spoq/epics/epic-name/
├── EPIC.md          # Architecture, dependencies, dispatch strategy
└── tasks/
    ├── 01-task.yml  # Phase 1 task
    ├── 02-task.yml  # Phase 1 task
    ├── 03-task.yml  # Phase 2 task (depends on 01, 02)
    └── ...
```

### Task YAML Format
```yaml
id: 01-task-name
title: Human-readable title
epic: epic-name
status: pending          # pending | in_progress | qa | rework | completed | failed
priority: high
phase: 1

dependencies: []         # List of task IDs that must complete first

files_to_touch:
  - path/to/file1.java
  - path/to/file2.java

acceptance_criteria:
  - Criterion 1
  - Criterion 2

description: |
  ## Objective
  [What this task accomplishes]

  ## Steps
  1. Step one
  2. Step two

  ## Verification
  [How to verify completion]
```

## Parallelism Model

Tasks within the same wave have no inter-dependencies and execute in parallel:

```
Wave 1: [Task 01] [Task 02] [Task 03]  ← Parallel Opus agents
        ────────────────────────────
                    │
                    ▼
              ./init.sh
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   [QA Task 01] [QA Task 02] [QA Task 03]  ← Parallel Sonnet agents
        └───────────┼───────────┘
                    │
                    ▼
Wave 2: [Task 04] [Task 05]  ← Depends on Wave 1 completion
```

**CRITICAL DISPATCH RULE: Emit ALL Task tool calls for a wave in a single message.** Every worker agent within a wave must be dispatched in one response — not one-at-a-time across multiple turns. Dispatching N tasks means N `Task` tool calls in one message. This eliminates the round-trip delay between dispatches and cuts total wall-clock time from O(N * latency) to O(latency). The same rule applies when spawning parallel QA agents.

## Journal Integration

After each wave, a journal entry is written to `journal.md`:

```yaml
---
agent: Agent Execution Overseer
start_time: 2026-01-02T10:00:00Z
end_time: 2026-01-02T11:30:00Z
confidence: 0.95
session_type: epic_execution
epic: shadcn-migration
wave: 2
tasks_completed: 3
tasks_failed: 0
tasks_total: 5
---

## Wave 2 Summary

Completed 3 tasks in parallel. Build passed. All QA scores ≥95.

## Tasks Completed
- 04-create-button (QA: 97/100)
- 05-create-badge (QA: 96/100)
- 06-create-progress (QA: 98/100)

## Next Steps
- Wave 3: Tasks 07, 08, 09
```

## Error Handling

### Build Failure
1. Spawn Haiku investigation agent
2. Parse error output + git diff
3. Identify failing task(s) by `files_to_touch`
4. Mark only those tasks for rework
5. Passing tasks proceed to QA

### QA Failure
1. Receive remediation feedback (≤20 lines)
2. Queue task for rework with feedback
3. Re-spawn Opus with:
   - Original task YAML
   - QA feedback as additional context
   - Retry count (N of max_retries)

### Max Retries Exceeded
1. Mark task as `failed` (persist `retry_count = max_retries` so the budget survives a restart)
2. HALT epic execution immediately
3. Report status and escalate to a human

A `failed` task has used its full 3-attempt budget. A plain `--resume` re-dispatches it for one more pass but, because `retry_count` is already at `max_retries`, it will not loop — if it fails again it stays `failed` and the human must intervene (or reset `retry_count` to grant a fresh budget). This is the same escalation contract as `/workflow-execute` and `/team-execution`.

## Scripts

### parse-epic.py

**MCP_MODE=true:**
```
spoq_parse_epic(epic_path="spoq/epics/epic-name")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/agent-execution/scripts/parse-epic.py spoq/epics/epic-name
```
Outputs JSON with parsed EPIC.md context and all task YAMLs.

### build-dependency-graph.py

**MCP_MODE=true:**
```
spoq_generate_execution_plan(epic_path="spoq/epics/epic-name")
```
The MCP path combines parsing and execution plan generation into a single call.

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/agent-execution/scripts/build-dependency-graph.py < parsed-epic.json
```
Outputs wave assignments and critical path analysis.

## Dependencies

- **agent-validation skill**: QA scoring and remediation
- **journal-tracker skill**: Progress logging
- `./init.sh`: Build verification
- Task YAML format: See `spoq/epics/README.md`

## IMPORTANT Rules

1. **Never skip build verification** - Always run `./init.sh` between waves
2. **Parallel agents only within waves** - Cross-wave dependencies must be respected
3. **In-place status updates** - Persist state to survive interruptions
4. **Compact feedback** - QA remediation must be ≤20 lines for context efficiency
5. **Fail-fast on max_retries** - Don't continue with a broken task
6. **Journal every wave** - Maintain audit trail for XAI/meta-orchestration
7. **Auto-move on completion** - Move epic to `complete/` folder when all tasks pass

## Epic Completion

When ALL tasks in an epic pass validation:

### 1. Mark Epic Complete
Update all task YAML files with `status: completed`.

### 2. Auto-Move to Complete Folder
```bash
# Move from active to complete
mv spoq/epics/active/epic-name spoq/epics/complete/epic-name
```

### 3. Update ROADMAP.yml
Update the epic's entry in `spoq/ROADMAP.yml` to reflect its completed status.

### 4. Final Journal Entry
```yaml
---
agent: Agent Execution Overseer
session_type: epic_completion
epic: epic-name
status: COMPLETE
total_tasks: N
total_waves: M
---

## Epic Completed

All N tasks passed validation. Epic moved to spoq/epics/complete/
```

### 5. Report Success
```
Epic Execution Complete!

Epic: epic-name
Location: spoq/epics/complete/epic-name
Tasks: N/N passed
Waves: M executed

The epic has been archived to the complete folder.
```

## Known Failure Modes

### Runaway Retry Loops (CRITICAL)

**Symptom**: Sub-agent runs the same command (e.g., `npm install sonner`) hundreds of times, consuming millions of tokens.

**Root Cause**: Agent gets stuck in error-handling retry logic when:
- A dependency is already installed (returns success but agent doesn't recognize it)
- A transient error causes the agent to retry indefinitely
- Lock file contention prevents npm from completing

**Prevention**: Sub-agents MUST follow these rules:

1. **Maximum 3 retries for any install command** - If `npm install`, `pip install`, or similar fails 3 times, STOP and report the error
2. **Check before installing** - Verify if dependency exists before attempting install:
   ```bash
   # Good: Check first
   grep -q '"sonner"' package.json && echo "Already installed" || npm install sonner

   # Bad: Blind install loop
   npm install sonner  # If this "fails", don't retry 100 times
   ```
3. **Trust success** - If install command exits 0, it succeeded. Don't re-run.
4. **Report, don't spin** - If stuck, return error to orchestrator instead of retrying

**Detection**: Orchestrator should monitor for:
- Same command appearing 5+ times in agent output
- Token usage exceeding expected bounds (>500k for simple tasks)
- Agent runtime exceeding 10 minutes for straightforward tasks

### Lock File Contention

**Symptom**: Multiple agents fail with "ELOCK" or similar when running npm/yarn concurrently.

**Prevention**:
1. Designate ONE task per epic to handle dependency installation (e.g., Task 01)
2. Other tasks should assume dependencies are installed
3. If task needs to verify, use read-only checks: `grep package.json`, not `npm install`

### Build Directory Conflicts

**Symptom**: Agents fail with "ENOENT .next" or webpack cache errors.

**Prevention**:
1. Only one agent should run build commands at a time
2. If build fails, clean first: `rm -rf .next && npm run build`
3. Wave orchestrator should serialize build verification

## Sub-Agent Guidelines

Include these instructions when spawning worker agents:

```markdown
## CRITICAL: Avoid Infinite Loops

When executing this task:

1. **Install commands**: Maximum 3 attempts. If still failing, STOP and report the error.
2. **Build commands**: If build fails, try cleaning once. If still fails, STOP and report.
3. **Never repeat the same failing command** more than 3 times.
4. **Check before installing**: Use `grep package.json` to verify if dependency exists.
5. **Trust success**: If a command exits with code 0, it worked. Move on.

If you find yourself in a loop, STOP IMMEDIATELY and return:
"AGENT ERROR: Stuck in retry loop on [command]. Manual intervention required."
```

## Improvements for Future Versions

### Planned Enhancements

1. **Agent Timeout**: Kill agents that exceed N minutes (configurable)
2. **Loop Detection**: Monitor for repeated commands and auto-terminate
3. **Token Budget**: Set max token usage per agent, terminate on exceed
4. **Dependency Lock**: Serialize all `npm install` commands across agents
5. **Health Checks**: Periodic heartbeat/progress verification
6. **Graceful Shutdown**: Allow orchestrator to signal agents to stop

### Metrics to Track

- Tokens per task (detect outliers)
- Commands per agent (detect loops)
- Time to completion per task
- Retry count distribution
- Failure modes categorization
