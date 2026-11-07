---
name: team-execution
description: Orchestrate wave-based agent teams with persona-specialized workers. Use when running /team-execution @spoq/epics/epic-name to execute multi-task epics with Agent Teams, inter-agent messaging, and context-preserving rework.
---

# Team Execution Skill

Coordinates parallel agent team execution on epics in `spoq/epics/`. Uses Claude Code Agent Teams for persona-specialized workers, proactive shared-file conflict detection, inter-agent communication, and context-preserving rework loops.

## When to Use

Use this skill when:
- You have an epic in `spoq/epics/active/` ready for execution
- You want persona-specialized agents (frontend, backend, infra, docs, testing)
- You need inter-agent communication and context-preserving rework
- You want proactive shared-file conflict detection before each wave

Use `/agent-execution` instead if you want the simpler disconnected-agent approach.

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
/team-execution spoq/epics/epic-name
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--dry-run` | false | Show execution plan with persona assignments without running |
| `--max-retries N` | 3 | Max rework attempts per task |
| `--min-score N` | 95 | Minimum QA score to pass |
| `--wave N` | all | Execute only specific wave |
| `--task ID` | all | Execute only specific task |
| `--resume` | false | Resume interrupted epic from last checkpoint |

### Examples

```bash
# Execute entire epic with agent teams
/team-execution spoq/epics/shadcn-migration

# Dry-run to see wave plan + persona assignments
/team-execution spoq/epics/shadcn-migration --dry-run

# Execute only wave 2
/team-execution spoq/epics/shadcn-migration --wave 2

# Resume after interruption
/team-execution spoq/epics/shadcn-migration --resume
```

## MANDATORY: Agent Validation After Every Task

**NEVER skip `/agent-validation`.** Every single task MUST be validated after build verification passes — no exceptions, no shortcuts, no "it looks fine so I'll skip QA."

Why this is non-negotiable:
- Workers routinely produce code that compiles and renders correctly but **fails on tests, styling conventions, or completeness** — issues only caught by the 10-metric scoring system.
- Skipping validation creates compounding technical debt: unwritten tests, inconsistent styling, missing accessibility attributes — all of which cost far more to fix later.
- The validation step is cheap (Sonnet sub-agent, <1 minute per task). The rework cost of skipping it is 5-10x higher when issues surface post-merge.

**The orchestrator MUST run `/agent-validation` for every task that passes build verification. If you find yourself thinking "this task is simple enough to skip QA" — that is exactly when you need it most.**

## Workflow

```
Phase 1: PLAN                          Phase 2: EXECUTE (per wave)
┌─────────────────────┐               ┌──────────────────────────────────┐
│ 1. Parse epic        │               │ 1. detect-shared-files.py        │
│ 2. build-dep-graph   │               │ 2. TeamCreate (epic-wave-N)      │
│ 3. assign-personas   │               │ 3. Spawn persona teammates       │
│ 4. Explore teammates │               │ 4. TaskCreate + assign per task  │
│    (optional recon)  │               │ 5. Monitor via TaskList/messages │
│ 5. Dry-run summary   │               │ 6. Build verification            │
└─────────┬───────────┘               │ 7. QA via /agent-validation      │
          │                            │    (MANDATORY - NEVER SKIP)      │
          ▼                            │ 8. Rework via SendMessage        │
  ┌───────────────┐                    │ 9. Shutdown team + journal       │
  │ Epic validated │                    └──────────────────────────────────┘
  └───────────────┘
```

## Execution Instructions

When this skill is invoked, follow these steps exactly:

### Step 0: Parse Arguments

Parse the invocation arguments:
```
/team-execution <epic-path> [--dry-run] [--max-retries N] [--min-score N] [--wave N] [--task ID] [--resume]
```

Set defaults:
- `max_retries = 3`
- `min_score = 95`
- `dry_run = false`
- `resume = false`

### Step 1: Parse Epic

**MCP_MODE=true:**
```
spoq_parse_epic(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/agent-execution/scripts/parse-epic.py <epic-path>
```

This outputs JSON with parsed EPIC.md context and all task YAMLs. Capture the output.

If `--resume` is set, filter to tasks with status `pending`, `in_progress`, `rework`, plus `qa` (worker finished but never validated) and `failed` (re-attempted using its remaining `retry_count` budget — see Resume Protocol). Only `completed` is skipped.

### Step 2: Compute Waves

**MCP_MODE=true:**
```
spoq_generate_execution_plan(epic_path="<epic-path>", resume=<resume>)
```
The MCP path combines parsing and wave computation into a single call. Pass `resume=true` on a `--resume` run so `qa`/`failed` carryover is flagged actionable.

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/agent-execution/scripts/build-dependency-graph.py [--resume] < parsed-epic.json
```

This outputs wave assignments and execution plan. Capture the output.

### Step 3: Assign Personas

**MCP_MODE=true:**
```
spoq_assign_personas(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/team-execution/scripts/assign-personas.py < parsed-epic.json
```

This outputs `{task_id: persona_name}` mapping. Capture the output.

### Step 4: Display Plan

Show the user:
1. Wave structure with task assignments
2. Persona assignments per task
3. Critical path (if relevant)

If `--dry-run` is set, STOP HERE and display the plan without executing.

### Step 5: Execute Waves

For each wave N (in order), execute the wave execution protocol below.

If `--wave N` is set, only execute that specific wave.
If `--task ID` is set, only execute that specific task within its wave.

---

## Wave Execution Protocol

For each wave N:

### 5.1: Detect Shared File Conflicts

Run conflict detection on the wave's tasks:

**MCP_MODE=true:**
```
spoq_detect_conflicts(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
echo '<wave_tasks_json>' | python3 .claude/skills/team-execution/scripts/detect-shared-files.py
```

Capture the conflict report. If conflicts exist:
- Note which files are shared and which tasks touch them
- These files will be passed to teammates as `{{shared_files}}` — agents must NOT modify them
- The orchestrator (you) will merge shared file changes after all tasks complete

### 5.2: Create Team

```
TeamCreate(team_name="{epic-name}-wave-{N}")
```

### 5.3: Create Tasks

For each task in the wave, create a Claude Code task:

```
TaskCreate(
  subject="Execute {task_id}: {task_title}",
  description="{full task description with acceptance criteria}",
  activeForm="Executing {task_id}"
)
```

### 5.4: Spawn Persona Teammates

For each task, select the persona prompt template from `assets/prompts/persona-{name}.md` and spawn a teammate:

```
Task(
  subagent_type="general-purpose",
  team_name="{epic-name}-wave-{N}",
  name="worker-{task-id}",
  model="opus",
  mode="bypassPermissions",
  prompt=<persona prompt with all variables filled in>
)
```

**CRITICAL DISPATCH RULE: Emit ALL Task tool calls for a wave in a single message.** Every teammate must be dispatched in one response — not one-at-a-time across multiple turns. Dispatching N teammates means N `Task` tool calls in one message. This eliminates the round-trip delay between dispatches and cuts total wall-clock time from O(N * latency) to O(latency).

**Variable substitution**: Read the persona prompt template and replace all `{{variables}}` with actual values from the parsed task and epic metadata.

**Shared files**: If the conflict report identified shared files for this task, include them as `{{shared_files}}` in the prompt. Otherwise omit that section.

### 5.5: Assign Task Ownership

```
TaskUpdate(taskId=<task_id>, owner="worker-{task-id}", status="in_progress")
```

### 5.6: Monitor Progress

- Teammates send messages automatically when they complete work or encounter blockers
- Use TaskList periodically to check overall progress
- Respond to teammate messages as needed (clarify requirements, unblock issues)
- If a teammate reports being stuck, help resolve or escalate

### 5.7: Build Verification

Once all teammates report completion:

1. Update task YAML status to `qa`:
   - Read each task YAML file
   - Update `status: qa` and `last_update: <timestamp>`

2. Run build verification:
   ```bash
   ./init.sh
   ```
   Or if no init.sh exists:
   ```bash
   npm run build 2>&1 || echo "BUILD_FAILED"
   ```

3. **On build failure**:
   - Spawn a Haiku investigation teammate:
     ```
     Task(
       subagent_type="general-purpose",
       team_name="{epic-name}-wave-{N}",
       name="investigator",
       model="haiku",
       prompt="Analyze this build failure output and identify which task(s) caused it..."
     )
     ```
   - Based on investigation, identify failing task(s)
   - Send rework feedback via `SendMessage` to the failing task's worker
   - Passing tasks proceed to QA

### 5.8: QA Validation (MANDATORY — NEVER SKIP)

**This step is NON-NEGOTIABLE.** Every task that passes build verification MUST go through `/agent-validation`. Do not mark any task as `completed` without a passing QA score. Do not rationalize skipping this step for "simple" tasks — simple tasks are where styling inconsistencies, missing tests, and accessibility gaps hide undetected.

For each task that passes build verification:

Run `/agent-validation` (the agent-validation skill) with the task context. This invokes a Sonnet sub-agent for 10-metric scoring.

- **PASS** (average >= `min_score`, all metrics >= 80): Mark task as `completed`
- **FAIL**: Queue for rework with feedback

**Common failure modes caught ONLY by validation:**
- Missing unit tests (TE metric) — workers frequently skip tests unless explicitly prompted
- Styling deviations (CC metric) — e.g., using raw Tailwind classes instead of project-specific theme tokens
- Incomplete acceptance criteria (RF/CO metrics) — partial implementations that compile but don't satisfy requirements

### 5.9: Rework (Context-Preserving)

For tasks that fail QA:

1. **Send rework feedback to existing teammate** (preserves context):
   ```
   SendMessage(
     type="message",
     recipient="worker-{task-id}",
     content="QA feedback: {remediation details}. Please address these issues.",
     summary="QA rework for {task-id}"
   )
   ```

2. The teammate receives the feedback and can fix issues with full context from their first pass.

3. After rework, re-run build verification and QA.

4. **Max retries**: If a task fails QA `max_retries` (3) times:
   - Mark task as `failed` and persist `retry_count = max_retries` so the budget survives a restart
   - HALT epic execution
   - Escalate to a human. A `--resume` re-dispatches the task once more, but since `retry_count` is already at `max_retries` it will not loop — if it fails again it stays `failed` until a human intervenes (or resets `retry_count`). Same 3-attempt-then-escalate contract as `/agent-execution` and `/workflow-execute`.

### 5.10: Merge Shared File Changes

After all tasks in the wave complete (pass QA):

1. Review each teammate's "Deferred Changes" output for shared files
2. Apply changes to shared files in a consistent order (lowest task ID first)
3. Re-run build verification to confirm merged changes work

### 5.11: Shutdown Team

Send shutdown requests to all teammates:
```
SendMessage(type="shutdown_request", recipient="worker-{task-id}", content="Wave complete, shutting down")
```

After all teammates confirm shutdown:
```
TeamDelete()
```

### 5.12: Journal Entry

Write a wave completion journal entry to `journal.md`:

```yaml
---
agent: Team Execution Overseer
start_time: <wave_start_UTC>
end_time: <wave_end_UTC>
confidence: <0.0-1.0>
session_type: team_execution
epic: <epic-name>
wave: <N>
tasks_completed: <count>
tasks_failed: <count>
tasks_total: <count>
personas_used: [frontend, backend, ...]
---

## Wave N Summary

Completed N tasks using agent teams with persona specialization.

## Tasks Completed
- {task_id} ({persona}) - QA: {score}/100

## Shared File Merges
- {file} - merged changes from {task_ids}

## Next Steps
- Wave N+1: Tasks {ids}
```

Use `spoq_get_timestamp()` (MCP_MODE=true) or `python3 .claude/skills/journal-tracker/scripts/get-time.py` (fallback) for accurate UTC timestamps.

### 5.13: Update Task YAMLs

For each completed task, update the YAML file:
```yaml
status: completed
last_update: <timestamp>
last_agent: worker-{task-id}
persona: <persona-name>
```

For failed tasks:
```yaml
status: failed
retry_count: <N>
last_update: <timestamp>
last_agent: worker-{task-id}
persona: <persona-name>
```

---

## Task Status State Machine

```
pending → in_progress → qa → completed
                     ↓    ↓
                  rework → (back to in_progress via SendMessage)
                     ↓
                   failed (after max_retries → HALT EPIC)
```

## Epic Completion

When ALL tasks in ALL waves pass validation:

### 1. Mark Epic Complete
All task YAML files should have `status: completed`.

### 2. Auto-Move to Complete Folder
```bash
mv spoq/epics/active/epic-name spoq/epics/complete/epic-name
```

### 3. Update ROADMAP.yml
Update the epic's entry in `spoq/ROADMAP.yml` to reflect its completed status.

### 4. Final Journal Entry
```yaml
---
agent: Team Execution Overseer
session_type: epic_completion
epic: <epic-name>
status: COMPLETE
total_tasks: N
total_waves: M
personas_used: [frontend, backend, ...]
---

## Epic Completed

All N tasks passed validation using agent teams.
Epic moved to spoq/epics/complete/
```

### 5. Report Success
```
Epic Execution Complete!

Epic: epic-name
Location: spoq/epics/complete/epic-name
Tasks: N/N passed
Waves: M executed
Personas: frontend (3), backend (2), fullstack (1)

The epic has been archived to the complete folder.
```

## Resumability (Agent Handoff)

### State Persistence

Each task YAML tracks execution state:
```yaml
id: 03-implement-api
status: in_progress
retry_count: 1
last_agent: worker-03-implement-api
last_update: 2026-01-25T10:30:00Z
persona: backend
progress_notes: |
  - Completed API route setup
  - Working on validation logic
```

### Resume Protocol

When `--resume` is set:
1. Scan task YAML files for non-completed statuses
2. Skip completed tasks
3. Re-queue `pending`, `in_progress`, `rework`, and `qa` tasks
4. Re-attempt `failed` tasks using their remaining retry budget: `retry_count` counts toward `max_retries` (3) and persists across resumes, so a task gets at most 3 attempts total before it stays `failed` and is escalated to a human. Reset `retry_count` to 0 to grant a fresh budget.
5. Run smart review on partial work before continuing
6. Maintain persona assignments from previous run

## Persona Assignment

The `assign-personas.py` script scores each task against 6 persona profiles:

```
Score = (skill_matches × 2) + (file_pattern_matches × 1)
```

| Persona | Trigger Skills | Trigger File Patterns |
|---------|---------------|----------------------|
| Frontend | react, nextjs, tailwind, css, accessibility | src/components/, *.tsx, *.css |
| Backend | java, spring, nestjs, postgresql, api, graphql | src/service/, src/api/, *.java |
| Infrastructure | terraform, docker, aws, ci-cd | infrastructure/, Dockerfile |
| Documentation | latex, markdown, technical-writing | documents/, *.tex, *.md |
| Testing | jest, playwright, e2e, pytest | *.test.*, tests/, e2e/ |
| Full-Stack | (fallback when no score > 0) | (any) |

Rules are configurable in `assets/config/persona-rules.yml`.

## Shared File Conflict Detection

The `detect-shared-files.py` script identifies files touched by multiple tasks within a wave:

```bash
echo '[{"id":"01","files_to_touch":["Header.tsx"]},{"id":"02","files_to_touch":["Header.tsx","Page.tsx"]}]' | \
  python3 .claude/skills/team-execution/scripts/detect-shared-files.py
```

Output:
```json
{
  "conflicts": [{"file": "Header.tsx", "tasks": ["01", "02"], "resolution": "orchestrator_merge"}],
  "safe_tasks": [],
  "conflicting_tasks": ["01", "02"]
}
```

## Agent Roles

### Opus Workers (per task, persona-specialized)
- Execute task steps with domain expertise
- Respect shared file boundaries
- Communicate blockers via SendMessage
- Receive rework feedback with full context preserved

### Haiku Investigator (on build failure)
- Analyze build output
- Cross-reference errors with task `files_to_touch`
- Identify specific failing task(s)
- Allow passing tasks to proceed to QA

### Sonnet QA (via /agent-validation)
- 10-metric scoring system
- Pass threshold: >=95 overall, >=80 per metric
- Concise remediation feedback (<=20 lines)

## Advantages Over agent-execution

1. **Context-preserving rework** — SendMessage to existing teammate vs spawning new agent
2. **Persona specialization** — Domain expertise baked into prompts
3. **Proactive conflict detection** — Prevents concurrent edits to shared files
4. **Inter-agent communication** — Teammates can coordinate on shared concerns
5. **Graceful shutdown** — No orphaned background processes
6. **Better observability** — TaskList + automatic message delivery vs TaskOutput polling

## Known Failure Modes

### Runaway Retry Loops (CRITICAL)

**Prevention**: All persona prompts include anti-loop rules:
- Maximum 3 retries for any install command
- Check before installing
- Trust success (exit code 0 = done)

### Lock File Contention

**Prevention**: Same as agent-execution — designate ONE task per epic for dependency installation.

### Shared File Race Conditions

**Prevention**: `detect-shared-files.py` runs before each wave. Agents are instructed to skip shared files. Orchestrator merges after wave completion.

### Skipped Validation (CRITICAL — LEARNED THE HARD WAY)

**Symptom**: Orchestrator skips `/agent-validation` because "the build passes and it looks correct."

**Reality**: In the agent-teams-page epic (Feb 2026), all 5 tasks compiled and built cleanly. The orchestrator skipped QA validation. When validation was run retroactively, **all 5 tasks failed** — every single one had missing tests (TE: 0/100), and one had a styling deviation (using raw Tailwind `text-muted-foreground` instead of project-standard `text-spoq-muted`). This required writing 58 tests and fixing 3 test-related bugs after the fact.

**Prevention**: Rule #1 in IMPORTANT Rules. The mandatory validation callout at the top of this document. The `NEVER SKIP` annotations on Step 5.8. A passing build is necessary but NOT sufficient — validation catches tests, styling, accessibility, and completeness issues that compilation cannot.

## Scripts

### assign-personas.py

**MCP_MODE=true:**
```
spoq_assign_personas(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/team-execution/scripts/assign-personas.py < parsed-epic.json
# Output: {"task-01": "frontend", "task-02": "backend", ...}

python3 .claude/skills/team-execution/scripts/assign-personas.py --verbose < parsed-epic.json
# Output: detailed scores per persona per task
```

### detect-shared-files.py

**MCP_MODE=true:**
```
spoq_detect_conflicts(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
echo '<wave_tasks_json>' | python3 .claude/skills/team-execution/scripts/detect-shared-files.py
# Output: conflict report with safe_tasks and conflicting_tasks
```

### Reused Scripts (from agent-execution)

**MCP_MODE=true:**
```
spoq_parse_epic(epic_path="<epic-path>")
spoq_generate_execution_plan(epic_path="<epic-path>")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/agent-execution/scripts/parse-epic.py <epic-path>
python3 .claude/skills/agent-execution/scripts/build-dependency-graph.py < parsed-epic.json
```

## Dependencies

- **agent-execution skill**: Reuses `parse-epic.py` and `build-dependency-graph.py`
- **agent-validation skill**: QA scoring and remediation
- **journal-tracker skill**: Progress logging
- **lib/epic_utils.py**: Shared epic parsing utilities
- `./init.sh` or `npm run build`: Build verification

## IMPORTANT Rules

1. **NEVER skip agent-validation** — Every task MUST pass `/agent-validation` before being marked `completed`. This is the #1 rule. No task is "too simple" to validate. A build that compiles is NOT the same as code that meets quality standards. Tests, styling, accessibility, and completeness are only caught by the 10-metric QA gate.
2. **Never skip build verification** — Always run build between waves
3. **Parallel agents only within waves** — Cross-wave dependencies must be respected
4. **In-place status updates** — Persist state to survive interruptions
5. **Compact feedback** — QA remediation must be <=20 lines for context efficiency
6. **Fail-fast on max_retries** — Don't continue with a broken task
7. **Journal every wave** — Maintain audit trail for XAI/meta-orchestration
8. **Auto-move on completion** — Move epic to `complete/` folder when all tasks pass
9. **Respect shared file boundaries** — Agents must not edit files flagged as shared
10. **Prefer rework over respawn** — Use SendMessage for rework to preserve context
11. **Shutdown teams gracefully** — Always send shutdown_request before TeamDelete
