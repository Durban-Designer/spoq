---
name: epic-planning
description: Decompose high-level goals into structured epics with atomic tasks, dependency DAGs, and wave-based phases. Use when planning new features, migrations, or complex initiatives in spoq/epics/.
---

# Epic Planning Skill

Guides agents through decomposing high-level goals into well-structured epics with atomic tasks, dependency graphs, and wave-based phases. Produces artifacts consumed by the `/agent-execution` skill.

## When to Use

Use this skill when:
- Starting a new project or major feature requiring multiple tasks
- Breaking down complex goals into executable work units
- Planning migrations, refactors, or system-wide changes
- Creating work for multi-agent swarm execution
- Identifying critical paths and parallelism opportunities
- Organizing work in `spoq/epics/`

## MCP Detection

Before executing any scripts, check if the SPOQ MCP server is available:

1. Call `spoq_ping` tool
   - **Success** → MCP_MODE=true (use MCP tools for all operations below)
   - **Tool not found / Error** → MCP_MODE=false (use Python scripts as fallback)

This check only runs once per session. All script references below provide both paths.

## Invocation

```bash
/epic-planning                                  # Start interactive planning session
/epic-planning spoq/epics/active/my-epic     # Validate existing epic
/epic-planning --skeleton my-epic               # Generate skeleton in active/
/epic-planning --backlog my-epic                # Generate skeleton in backlog/
/epic-planning --map "Program name"             # Force map mode (multi-epic)
/epic-planning spoq/maps/active/my-map          # Validate existing map
```

**Note**: New epics are created in `spoq/epics/active/` by default. Use `--backlog` to place them in `spoq/epics/backlog/` for deferred work. Epics follow a 3-tier lifecycle:

| Tier | Directory | Purpose |
|------|-----------|---------|
| **Backlog** | `spoq/epics/backlog/` | Planned but not yet ready for execution |
| **Active** | `spoq/epics/active/` | Ready for or currently under execution |
| **Complete** | `spoq/epics/complete/` | Successfully executed and archived |

Use `spoq_promote` and `spoq_demote` MCP tools to move epics between tiers:
```
spoq_promote(epic_slug="my-epic")   # backlog → active
spoq_demote(epic_slug="my-epic")    # active → backlog
```

## Planning Philosophy

Effective epics share these traits:

- **Atomic Tasks**: Each task is 1-4 hours of focused work
- **Clear Dependencies**: No ambiguity about execution order
- **Parallelizable**: Maximize Wave 0 tasks for concurrent execution
- **Verifiable**: Every task has concrete acceptance criteria
- **Self-Contained**: Workers can execute without external communication

## Planning Workflow

### Phase 1: Discovery

Before creating any files, answer these questions:

```markdown
## Goal Analysis

1. **Objective**: What outcome are we achieving? (1-2 sentences)
2. **Scope**: What systems/components are involved?
3. **Constraints**: Time limits, dependencies, technical requirements?
4. **Success Definition**: How do we know when we're done?
5. **Stakeholders**: Who needs this work?
```

### Phase 2: Architecture

Sketch the high-level solution:

```markdown
## Architecture

1. **Components**: List 3-7 major components or subsystems
2. **Data Flow**: How do data/requests move through the system?
3. **Integration Points**: Where does this connect to existing systems?
4. **Risk Areas**: What could go wrong?
```

Create an ASCII diagram:
```
┌─────────────────────────────────────────────────────────┐
│                      SYSTEM LAYER                        │
├─────────────────────────────────────────────────────────┤
│  ┌─────────┐    ┌─────────┐    ┌─────────┐             │
│  │Component│───►│Component│───►│Component│             │
│  │   A     │    │    B    │    │    C    │             │
│  └─────────┘    └─────────┘    └─────────┘             │
└─────────────────────────────────────────────────────────┘
```

### Phase 3: Task Decomposition

Apply the **Atomic Task Rule**:
- Each task = 1-4 hours of work
- One clear deliverable per task
- No task requires another task mid-execution

**Decomposition Checklist:**
```markdown
For each component/feature:
- [ ] What files will be created/modified?
- [ ] What skills are required?
- [ ] What must exist before this can start?
- [ ] How do we verify completion?
- [ ] What could block this task?
```

**Target task counts:**
- Simple epic: 5-10 tasks
- Medium epic: 10-15 tasks
- Complex epic: 15-20 tasks
- Too large? Split into sub-epics or use **map mode**

### Phase 3b: Map Detection

After task decomposition, evaluate whether scope warrants a map (multi-epic coordination):

1. Total task count exceeds 20
2. Tasks span 3+ distinct subsystems with no cross-dependencies
3. User provided `--map` flag

If any condition is met, recommend map mode and switch to the Map Mode Workflow below. Otherwise continue to Phase 4.

### Map Mode Workflow

When scope exceeds a single epic, use maps to coordinate multiple epics:

1. **Create map directory**: `spoq/maps/active/<map-slug>/MAP.md` using `.claude/skills/epic-planning/assets/map-template.md`
2. **Define the inter-epic DAG** in MAP.md with epic slugs, dependencies, and dispatch strategy
3. **For each epic in the map**: invoke the standard epic planning workflow (create EPIC.md + task YAMLs in `spoq/epics/active/`)
4. **Validate** with `spoq_validate_map(map_path="spoq/maps/active/<map-slug>")`
5. **Analyze** with `spoq_analyze_map_dag(map_path="spoq/maps/active/<map-slug>")`
6. **Report** results with per-epic breakdown and map-level metrics

**Map invocation:**
```bash
/epic-planning                                    # Standard session
/epic-planning --map "Example application"             # Force map mode
/epic-planning spoq/maps/active/my-map            # Validate existing map
```

**Map MCP tools:**
```
spoq_parse_map(map_path="spoq/maps/active/my-map")
spoq_validate_map(map_path="spoq/maps/active/my-map")
spoq_compute_epic_waves(map_path="spoq/maps/active/my-map")
spoq_analyze_map_dag(map_path="spoq/maps/active/my-map")
spoq_get_map_status(map_path="spoq/maps/active/my-map")
spoq_list_maps()
```

### Phase 4: Dependency Mapping

Create the dependency graph using these patterns:

**Linear Chain** (sequential work):
```
01 → 02 → 03 → 04
```

**Tree** (common pattern):
```
       01
   ┌───┼───┐
   02  03  04
   │   │   │
   05  06  07
   └───┼───┘
       08
```

**DAG** (complex dependencies):
```
01 ──┐
     ├→ 04
02 ──┤
     ├→ 05
03 ──┘
```

**Rules:**
1. No circular dependencies
2. Prefer wide trees over deep chains (maximizes parallelism)
3. Infrastructure/setup tasks have no dependencies (Wave 0)
4. Integration/testing tasks depend on implementation tasks

### Phase 5: Wave Assignment

Assign waves based on dependency depth:
- **Wave 0**: Tasks with zero dependencies (parallelize all)
- **Wave 1**: Tasks depending only on Wave 0
- **Wave 2**: Tasks depending on Wave 1
- Continue until all tasks assigned

**Parallelism metrics:**
- Good: Wave 0 contains 25-40% of total tasks
- Better: Wave 0 + Wave 1 covers 50-70% of tasks
- Optimal: Critical path is a small fraction of total task count

### Phase 6: Critical Path Analysis

Identify the longest dependency chain — the epic cannot finish in fewer
waves than the critical path requires, no matter how many agents run:

```
Critical Path: 01 → 04 → 07 → 10 → 12  (5 tasks, 5 waves minimum)

Total tasks: 12
Critical path length: 5
Parallelism headroom: 7 tasks run alongside the critical path
```

Analyze with:

**MCP_MODE=true:**
```
spoq_analyze_dag(epic_path="spoq/epics/epic-name")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/epic-planning/scripts/analyze-dag.py spoq/epics/epic-name
```

## EPIC.md Template

```markdown
# Epic: [Name]

## Overview

[2-3 sentences: What this accomplishes, why it matters, target outcome]

## Architecture

```
[ASCII diagram showing components and data flow]
```

## Components

### 1. [Component Name]
- Key responsibility
- Files/modules involved

### 2. [Component Name]
- Key responsibility
- Files/modules involved

[Continue for 3-7 components]

## Success Criteria

- [ ] Specific, measurable criterion 1
- [ ] Specific, measurable criterion 2
- [ ] Service/feature works with verification command
[Target: 10-20 criteria]

## Task Dependencies

```
[ASCII DAG showing task relationships]
```

## Dispatch Strategy

**Wave 0 (Parallel):** Tasks XX, YY, ZZ
- [Brief description of this wave's focus]

**Wave 1 (Parallel):** Tasks AA, BB
- [Brief description]

[Continue for all waves]

**Critical Path:** XX → YY → ZZ (N tasks)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Risk 1 | Low/Med/High | Low/Med/High | Strategy |
```

## Task YAML Template

```yaml
id: XX-task-slug
title: Human-readable Task Title
epic: epic-name
status: pending
priority: critical|high|medium|low
phase: N

dependencies:
  - XX-other-task

skills_required:
  - skill-name

files_to_touch:
  - path/to/file1.java
  - path/to/file2.ts

outputs:
  - Concrete deliverable 1
  - Service running at endpoint

acceptance_criteria:
  - [ ] Criterion with verification command
  - [ ] Another criterion

description: |
  ## Objective

  [One sentence: what this task accomplishes]

  ## Prerequisites

  - Tool or service that must exist
  - Configuration that must be set

  ## Steps

  1. **Step description**
     ```bash
     exact command to run
     ```
     Expected output or next action

  2. **Next step**
     - Sub-step a
     - Sub-step b

  ## Verification

  ```bash
  # Command that proves completion
  expected output
  ```

  ## Error Handling

  If X fails:
  ```bash
  recovery command
  ```
```

## Interactive Planning Session

When starting `/epic-planning`, follow this sequence:

### Step 1: Gather Requirements
```
I'll help you plan an epic. Let's start with the basics:

1. **Goal**: What are you trying to accomplish?
2. **Scope**: Which systems/components are involved?
3. **Timeline**: Any deadlines or constraints?
4. **Existing Work**: Related tasks or prior planning?
```

### Step 2: Identify Components
```
Based on your goal, I've identified these components:
1. [Component A] - [responsibility]
2. [Component B] - [responsibility]
3. [Component C] - [responsibility]

Does this breakdown match your understanding?
Should we add/remove/rename any components?
```

### Step 3: Draft Tasks
```
For each component, I'll propose atomic tasks:

## Component A
- Task: [description] (~X hours)
- Task: [description] (~X hours)

## Component B
- Task: [description] (~X hours)

Total: N tasks across M waves
Critical path: ~X hours

Shall I proceed with generating the full epic?
```

### Step 4: Generate Artifacts

#### Step 4a: Create Epic Directory and EPIC.md

Create the directory structure and write EPIC.md yourself (the orchestrator):

1. `mkdir -p spoq/epics/active/epic-name/tasks`
2. Write `spoq/epics/active/epic-name/EPIC.md` using the template from `assets/epic-template.md`

EPIC.md **must** exist before dispatching sub-agents. They reference its overview for description context.

#### Step 4b: Dispatch Parallel Task YAML Writers (4+ tasks)

When the epic contains **4 or more tasks**, spawn one sub-agent per task YAML file.

```
Task(subagent_type="general-purpose", model="sonnet", run_in_background=True)
```

**CRITICAL DISPATCH RULES:**

1. **Always use `subagent_type="general-purpose"`**. Do NOT use Bash sub-agents — they lack Write tool permissions and will fail, causing a slow sequential fallback that takes 8-30x longer. General-purpose agents have access to the Write tool needed to create YAML files.

2. **Emit ALL Task tool calls in a single message.** Every sub-agent must be dispatched in one response — not one-at-a-time across multiple turns. Claude can include multiple `Task` tool calls in a single message block, and that is what you MUST do. Dispatching N tasks means N tool calls in one message. This eliminates the round-trip delay between dispatches and cuts total wall-clock time from O(N * latency) to O(latency).

All tasks are dispatched simultaneously (not wave-by-wave) because writing YAML files to disk has zero inter-task dependencies. Wave structure is encoded inside each file's `phase` and `dependencies` fields.

**Sub-agent prompt template:**

```
You are a task YAML writer for epic "{{epic-name}}".

## Your Job
Write exactly ONE task YAML file to disk.

## Output File
Write to: spoq/epics/active/{{epic-name}}/tasks/{{task-id}}.yml

## Task Data
- id: {{task-id}}
- title: {{task-title}}
- epic: {{epic-name}}
- status: pending
- priority: {{priority}}
- phase: {{phase-number}}
- dependencies: {{dependency-list}}
- files_to_touch: {{files-list}}
- acceptance_criteria: {{criteria-list}}
- description: {{full-description}}

## Epic Context
{{epic-overview-paragraph}}

## Template Reference
Follow .claude/skills/epic-planning/assets/task-template.yml exactly.
Include Objective, Prerequisites, Steps, Verification, Error Handling sections.

## Rules
- Write ONLY the specified YAML file
- Do not modify any other files
- Ensure valid, parseable YAML
- Return: "Wrote {{task-id}}.yml (N lines)"
```

**Model choice: sonnet** - task YAML writing is structured template expansion, not complex reasoning. Equivalent quality at lower cost compared to opus for this use case.

#### Step 4c: Wait and Verify

1. Collect all `TaskOutput` results from the background sub-agents
2. Verify the expected file count matches the number of tasks planned in Step 3
3. Run structural validation:
   **MCP_MODE=true:**
   ```
   spoq_validate_epic(epic_path="spoq/epics/active/epic-name")
   ```

   **MCP_MODE=false (fallback):**
   ```bash
   python3 .claude/skills/epic-planning/scripts/validate-epic.py spoq/epics/active/epic-name
   ```
4. **On failure**: retry the failed task(s) sequentially (max 1 retry per task), then fallback to writing the YAML directly as the orchestrator

#### Step 4 Fallback: Sequential Mode (1-3 tasks)

For small epics with **3 or fewer tasks**, skip parallel dispatch entirely. The overhead exceeds the benefit. Write all task YAML files yourself (the orchestrator) as a sequential operation:

1. `spoq/epics/active/epic-name/tasks/01-task-name.yml`
2. `spoq/epics/active/epic-name/tasks/02-task-name.yml`
3. ...continue for all tasks

### Step 5: Update ROADMAP.yml

Add the new epic to `spoq/ROADMAP.yml`:
- Add the epic entry under the appropriate tier (`backlog` or `active`)
- Set status to `pending`
- Include task count

### Step 6: Auto-Trigger Validation

**IMPORTANT**: After generating all artifacts, AUTOMATICALLY invoke epic-validation:

```
Epic created at spoq/epics/active/epic-name/
Added to ROADMAP.yml under appropriate tier

Automatically running epic validation...
```

Then invoke: `/epic-validation @spoq/epics/active/epic-name`

This ensures every new epic passes the 10-metric quality gate (95 avg / 90 min) before execution. Do NOT skip this step - validation is mandatory after planning.

### Step 7: Report Results
After validation completes, summarize:
```
Epic Planning Complete!

Epic: epic-name
Tasks: N tasks across M waves
Critical Path: ~X hours

Validation: [PASS/FAIL] (score: XX.X)

Next steps:
- If PASS: Run /agent-execution @spoq/epics/active/epic-name
- If FAIL: Address issues and re-run /epic-validation
```

## Quality Checklist

### Before Finalizing

**Epic Level:**
- [ ] Overview clearly states objective and value
- [ ] Architecture diagram shows data/control flow
- [ ] Success criteria are specific and measurable (10-20 items)
- [ ] Dependency graph has no cycles
- [ ] Dispatch strategy identifies all waves
- [ ] Critical path is identified and documented

**Task Level:**
- [ ] Every task has unique ID matching filename
- [ ] Task titles are action-oriented ("Create X", "Implement Y")
- [ ] Dependencies reference existing task IDs only
- [ ] `files_to_touch` lists actual file paths
- [ ] Acceptance criteria include verification commands
- [ ] Description has Objective, Steps, Verification sections
- [ ] No task exceeds ~4 hours of focused work

**DAG Level:**
- [ ] No circular dependencies
- [ ] Wave 0 has 25%+ of tasks (parallelism)
- [ ] Critical path is documented
- [ ] All paths terminate at a leaf task

## Helper Scripts

### validate-epic.py

Validates epic structure and dependencies:

**MCP_MODE=true:**
```
spoq_validate_epic(epic_path="spoq/epics/epic-name")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/epic-planning/scripts/validate-epic.py spoq/epics/epic-name
```

Checks:
- EPIC.md exists and has required sections
- All task YAMLs parse correctly
- Dependencies reference valid task IDs
- No dependency cycles
- Phase assignments are consistent

### analyze-dag.py

Computes critical path and parallelism metrics:

**MCP_MODE=true:**
```
spoq_analyze_dag(epic_path="spoq/epics/epic-name")
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/epic-planning/scripts/analyze-dag.py spoq/epics/epic-name
```

Output:
- Critical path (longest dependency chain)
- Parallelism score (Wave 0 breadth)
- Per-wave task grouping
- Task ordering for execution

### generate-skeleton.py

Creates epic directory structure from interactive input:

**MCP_MODE=true:**
```
spoq_generate_skeleton(name="my-epic", task_count=10)
```

**MCP_MODE=false (fallback):**
```bash
python3 .claude/skills/epic-planning/scripts/generate-skeleton.py --name "my-epic" --tasks 10
```

Creates:
- `spoq/epics/my-epic/EPIC.md` (template)
- `spoq/epics/my-epic/tasks/01-placeholder.yml`
- ... placeholder task files

## Integration with Other Skills

### Complete Workflow

```
+----------------+     +------------------+     +------------------+
| /epic-planning | --> | /epic-validation | --> | /task-validation |
| (Create Epic)  |     | (Epic Quality)   |     | (Per-Task Check) |
+----------------+     +------------------+     +------------------+
                                                       |
                                              +--------+--------+
                                              |                 |
                                              v                 v
                                       +------------+    +------------+
                                       | All PASS   |    | Any FAIL   |
                                       | Execute    |    | Fix First  |
                                       +------------+    +------------+
                                              |
                                              v
                                   +-------------------+
                                   | /agent-execution  |
                                   +-------------------+
                                              |
                                              v
                                   +-------------------+
                                   | /agent-validation |
                                   | (Code Quality QA) |
                                   +-------------------+
```

### epic-validation

After creating an epic, validate with:
```bash
/epic-validation spoq/epics/epic-name
```

Validates EPIC.md + task set with 10 planning metrics:
- Vision Clarity, Architecture Quality, Task Decomposition
- Dependency Graph, Coverage Completeness, Phase Ordering
- Scope Coherence, Success Criteria Quality
- Risk Identification, Integration Strategy

**Pass threshold:** >=95 overall, >=90 per metric

### task-validation

Validate individual tasks with:
```bash
/task-validation spoq/epics/epic-name/tasks/04-create-button.yml
```

Validates task YAML with 10 metrics:
- Structural Completeness, Requirements Clarity, Scope Appropriateness
- Dependency Accuracy, File Path Validity, Acceptance Criteria Quality
- Feasibility, Consistency, Actionability, Verification Clarity

**Pass threshold:** >=95 overall, >=90 per metric

### agent-execution

After validation passes, execute with:
```bash
/agent-execution spoq/epics/epic-name
```

Spawns Opus workers per wave, runs build verification, and QA scoring.

### agent-validation

Post-execution code quality validation:
- 10 code quality metrics (Syntactic, Tests, SOLID, Security, etc.)
- Pass threshold: >=95 overall, >=80 per metric
- Rework loop if fails

### journal-tracker

Log planning sessions:
```yaml
session_type: planning
epic: epic-name
tasks_created: N
critical_path_hours: X
```

## Common Mistakes

### Too Granular
**Bad:** 50 tasks for a simple feature
**Good:** 8-12 tasks covering logical units

### Too Vague
**Bad:** "Implement the backend"
**Good:** "Create UserService with CRUD operations"

### Missing Dependencies
**Bad:** Task 5 assumes Task 3 output exists but doesn't list it
**Good:** Explicit dependencies: `dependencies: [03-user-model]`

### Circular Dependencies
**Bad:** A → B → C → A
**Good:** Run `validate-epic.py` before committing

### No Verification Steps
**Bad:** Description ends at "implement the feature"
**Good:** Includes `## Verification` with commands to prove completion

## IMPORTANT Rules

1. **Atomic Tasks**: Each task produces one deliverable (1-4 hours)
2. **No Orphans**: Every non-Wave-0 task has dependencies
3. **Verify Before Commit**: Always run `validate-epic.py`
4. **Document Assumptions**: State what must exist before epic starts
5. **Include Verification**: Every acceptance criterion has a check
6. **Maximize Parallelism**: Design for concurrent execution
7. **Update When Reality Changes**: Epics are living documents
8. **Archive Completed Epics**: Move to `spoq/epics/complete/`
9. **General-Purpose Sub-Agents Only**: Always use `subagent_type="general-purpose"` when spawning task YAML writers. Never use Bash sub-agents — they lack file Write permissions and will fail.

## Wyrd Integration

- **Location**: `spoq/epics/` (per 5-category structure)
- **Archive**: `spoq/epics/complete/` for completed epics
- **Execution**: Use with `/agent-execution` skill
- **Tracking**: Log to `journal.md` using `/journal-tracker` skill
- **Validation**: Tasks compatible with `/agent-validation` metrics
