---
name: task-validation
description: Validate task YAML definitions before execution with 10 planning-focused metrics (0-100). Use after task creation and before agent-execution. Pass threshold 95+. (project)
---

# Task Validation Skill

Validates task YAML files against quality criteria before wave-based execution. Ensures task definitions are well-formed, clear, and actionable for AI agents.

## When to Use

- After creating or modifying task YAML files in `spoq/epics/*/tasks/`
- Before running `/agent-execution` on an epic
- After epic planning but before execution begins
- When reviewing task quality in code review

## Invocation

```bash
/task-validation <task-file-path>
```

**Examples:**
```bash
/task-validation spoq/epics/shadcn-migration/tasks/04-create-button.yml
/task-validation spoq/epics/knowledge-graph-scientific/tasks/05-arxiv-ingestion.yml
```

## Validation Process

1. **Parse Task YAML** - Load and validate YAML syntax
2. **Check Required Fields** - Ensure all mandatory fields present
3. **Validate References** - Check dependency IDs exist, file paths are valid
4. **Score 10 Metrics** - Each metric scored 0-100
5. **Return Verdict** - PASS (>=95, no metric <80) or FAIL with remediation

## The 10 Metrics

### 1. Structural Completeness (SC)
**Question:** Does the task have all required fields?

| Score | Criteria |
|-------|----------|
| 100 | All required + optional fields present with values |
| 80 | All required fields present, some optional missing |
| 60 | Missing 1 required field |
| 40 | Missing 2 required fields |
| 0 | Missing 3+ required fields or invalid YAML |

**Required Fields:**
- `id` - Unique task identifier (e.g., "04-create-button")
- `title` - Human-readable title
- `epic` - Parent epic name
- `status` - Current status (pending/in_progress/completed/failed)
- `dependencies` - List of task IDs (can be empty `[]`)
- `files_to_touch` - List of file paths to modify
- `acceptance_criteria` - List of testable criteria
- `description` - Detailed task description

**Optional Fields:**
- `priority`, `phase`, `skills_required`, `outputs`

### 2. Requirements Clarity (RC)
**Question:** Is the description specific, measurable, and actionable?

| Score | Criteria |
|-------|----------|
| 100 | Clear objective, numbered steps, code examples where needed |
| 80 | Clear objective and steps, minor ambiguity |
| 60 | Objective present but steps vague |
| 40 | Vague objective, unclear steps |
| 0 | Missing description or incomprehensible |

**Clarity Checklist:**
- Objective clearly states what to accomplish
- Steps are numbered and sequential
- Code examples provided for complex implementations
- Edge cases mentioned where relevant

### 3. Scope Appropriateness (SA)
**Question:** Is the task right-sized for a single agent session?

| Score | Criteria |
|-------|----------|
| 100 | 1-5 files, focused deliverable, ~1-4 hours of focused work |
| 80 | 5-10 files, clear boundary |
| 60 | 10-15 files, scope slightly broad |
| 40 | >15 files or far too broad for one session |
| 0 | Epic-sized task that should be decomposed |

**Right-Sizing Rules:**
- Single conceptual unit of work
- Can be verified independently
- Agent can hold full context in memory

### 4. Dependency Accuracy (DA)
**Question:** Are dependencies valid and acyclic?

| Score | Criteria |
|-------|----------|
| 100 | All dependency IDs exist, no cycles, logical ordering |
| 80 | All IDs valid, ordering could be improved |
| 60 | One dependency ID not found |
| 40 | Multiple invalid IDs or potential cycle |
| 0 | Circular dependency or references non-existent epic |

**Validation Rules:**
- Each dependency ID must match another task's `id` field
- No task can depend on itself (direct cycle)
- No transitive cycles (A->B->C->A)

### 5. File Path Validity (FP)
**Question:** Are file paths syntactically correct and project-appropriate?

| Score | Criteria |
|-------|----------|
| 100 | All paths follow project conventions, extensions match |
| 80 | Paths valid, minor convention deviation |
| 60 | Some paths have typos or wrong extensions |
| 40 | Multiple invalid paths |
| 0 | Most paths invalid or absolute paths used |

**Path Rules:**
- Relative to project root (no leading `/`)
- Match expected extensions (.java, .tsx, .yml)
- Follow project directory structure (code/apps/, tests/, etc.)
- No special characters except `-`, `_`, `.`

### 6. Acceptance Criteria Quality (AC)
**Question:** Are criteria testable and complete?

| Score | Criteria |
|-------|----------|
| 100 | All criteria SMART (Specific, Measurable, Achievable, Relevant, Time-bound) |
| 80 | Criteria testable, minor gaps in coverage |
| 60 | Some criteria vague or untestable |
| 40 | Multiple vague criteria |
| 0 | No criteria or all criteria untestable |

**Quality Indicators:**
- Uses observable behavior ("renders", "returns", "displays")
- Specifies expected values or states
- Can be verified with a test or manual check
- Covers happy path and key edge cases

### 7. Feasibility (FE)
**Question:** Is the task technically achievable?

| Score | Criteria |
|-------|----------|
| 100 | All technologies exist, no external blockers |
| 80 | Feasible with minor assumptions |
| 60 | Requires unverified assumptions |
| 40 | Significant technical uncertainty |
| 0 | Requires impossible or unavailable resources |

**Feasibility Checks:**
- Referenced libraries/frameworks exist
- File paths match existing project structure
- No dependencies on external systems not in scope
- Skills required are realistic for AI agent

### 8. Consistency (CO)
**Question:** Are there contradictions within the task?

| Score | Criteria |
|-------|----------|
| 100 | All sections align, no contradictions |
| 80 | Minor terminology inconsistency |
| 60 | One logical contradiction |
| 40 | Multiple contradictions |
| 0 | Task is internally inconsistent |

**Consistency Checks:**
- `title` matches `description` objective
- `files_to_touch` matches files mentioned in description
- `acceptance_criteria` covers `outputs`
- `dependencies` make sense for the task scope

### 9. Actionability (AO)
**Question:** Can an AI agent execute this task?

| Score | Criteria |
|-------|----------|
| 100 | Agent can execute without clarification |
| 80 | Minor clarification might help |
| 60 | Agent would need to make assumptions |
| 40 | Significant ambiguity requiring human input |
| 0 | Task cannot be executed without major clarification |

**Actionability Markers:**
- Steps are imperative ("Create", "Update", "Add")
- No open-ended research required
- All inputs are specified or discoverable
- Success is objectively determinable

### 10. Verification Clarity (VC)
**Question:** Is it clear how to verify completion?

| Score | Criteria |
|-------|----------|
| 100 | Explicit verification section with commands |
| 80 | Verification clear from acceptance criteria |
| 60 | Verification somewhat implicit |
| 40 | Unclear how to verify |
| 0 | No verification possible |

**Verification Elements:**
- Build command (`npm run build`, `mvn compile`)
- Test command (`npm test`, `mvn test`)
- Manual verification steps if applicable
- Expected output or behavior described

## Pass/Fail Criteria

```
PASS: Total >= 95 AND every metric >= 90
FAIL: Total < 95 OR any metric < 90
```

**Rationale:** Plans are cheap to fix. A 90 floor catches issues before expensive code execution begins.

## Output Format

### On PASS
```
+-------------------------------------------+
| TASK VALIDATION PASSED: 97/100            |
|                                           |
| Task: 04-create-button                    |
| All 10 metrics meet threshold (>=90)      |
| Ready for execution                       |
+-------------------------------------------+
```

### On FAIL (Concise - <20 lines)
```
+-------------------------------------------+
| TASK VALIDATION FAILED: 82/100            |
|                                           |
| Task: 04-create-button                    |
|                                           |
| Failing Metrics:                          |
| * Dependency Accuracy: 60                 |
|   -> dep "03-theme-vars" doesn't exist    |
|   -> correct ID: "03-migrate-theme-vars"  |
| * Verification Clarity: 75                |
|   -> missing test command in Verification |
|                                           |
| Remediation (2 actions):                  |
| 1. Fix dependency ID typo                 |
| 2. Add "npm test" to Verification section |
+-------------------------------------------+
```

## Task YAML Reference Format

```yaml
id: 04-create-button          # Required: unique identifier
title: Create ui/button       # Required: human-readable
epic: shadcn-migration        # Required: parent epic name
status: pending               # Required: pending|in_progress|completed|failed
priority: high                # Optional: low|medium|high
phase: 2                      # Optional: wave/phase number

dependencies:                 # Required: list of task IDs (can be [])
  - 01-install-dependencies
  - 02-create-config-utils

skills_required:              # Optional: agent skill hints
  - react
  - typescript

files_to_touch:               # Required: files to modify
  - code/apps/monitor-ui/src/components/ui/button.tsx

outputs:                      # Optional: expected deliverables
  - shadcn Button component

acceptance_criteria:          # Required: testable criteria
  - Button renders with all size variants
  - Existing tests pass

description: |                # Required: detailed instructions
  ## Objective
  [What to accomplish]

  ## Steps
  1. First step
  2. Second step

  ## Verification
  [How to verify completion]
```

## Integration with Epic Workflow

```
+---------------+     +------------------+     +-------------------+
| Epic Planning | --> | /task-validation | --> | /agent-execution  |
| (Create YAMLs)|     | (Quality Gate)   |     | (Execute Tasks)   |
+---------------+     +------------------+     +-------------------+
                              |
                  +-----------+-----------+
                  |                       |
                  v                       v
           +------------+          +------------+
           | PASS: 95+  |          | FAIL: <95  |
           | Proceed    |          | Fix First  |
           +------------+          +------------+
```

## Relationship to Other Validation Skills

| Skill | Validates | When |
|-------|-----------|------|
| `/task-validation` | Individual task YAML | Before execution |
| `/epic-validation` | EPIC.md + task set | Before execution |
| `/agent-validation` | Completed code work | After execution |

## Logging Integration

On completion, log to `journal.md`:
```yaml
- type: task-validation
  task: 04-create-button
  score: 97/100
  result: PASS
  timestamp: 2026-01-02T10:30:00Z
```
