---
name: epic-validation
description: Validate EPIC.md files and task sets with 10 planning-focused metrics (0-100). Use after epic planning and before agent-execution. Pass threshold 95+. (project)
---

# Epic Validation Skill

Validates epic definition files (EPIC.md) and their associated task sets against quality criteria. Ensures epics are well-structured, complete, and ready for wave-based execution.

## When to Use

- After creating or modifying an EPIC.md in `spoq/epics/*/`
- After adding or reordering tasks in an epic
- Before running `/agent-execution` on an epic
- When reviewing epic quality in planning phase

## Invocation

```bash
/epic-validation <epic-directory>
```

**Examples:**
```bash
/epic-validation spoq/epics/shadcn-migration
/epic-validation spoq/epics/knowledge-graph-scientific
```

## Validation Process

1. **Parse EPIC.md** - Load and validate markdown structure
2. **Load Task Set** - Parse all `tasks/*.yml` files
3. **Cross-Reference** - Validate tasks against epic definition
4. **Score 10 Metrics** - Each metric scored 0-100
5. **Return Verdict** - PASS (>=95, no metric <80) or FAIL with remediation

## The 10 Metrics

### 1. Vision Clarity (VC)
**Question:** Is the epic's goal clearly stated?

| Score | Criteria |
|-------|----------|
| 100 | Clear overview with problem statement and solution |
| 80 | Clear overview, minor ambiguity in scope |
| 60 | Overview present but vague |
| 40 | Overview missing key context |
| 0 | No overview or incomprehensible goal |

**Vision Elements:**
- Problem being solved clearly stated
- Solution approach outlined
- Scope boundaries defined
- End state described

### 2. Architecture Quality (AQ)
**Question:** Is the architecture diagram/description clear and complete?

| Score | Criteria |
|-------|----------|
| 100 | ASCII diagram + explanation, all components shown |
| 80 | Diagram present, minor gaps in explanation |
| 60 | Text-only architecture, no diagram |
| 40 | Partial architecture description |
| 0 | No architecture section or misleading |

**Architecture Elements:**
- Component diagram (ASCII or mermaid)
- Component relationships shown
- Data flow indicated
- Integration points marked

### 3. Task Decomposition (TD)
**Question:** Are tasks properly broken down into logical units?

| Score | Criteria |
|-------|----------|
| 100 | Tasks are atomic, independent where possible, complete coverage |
| 80 | Good decomposition, minor overlap |
| 60 | Some tasks too large or overlapping |
| 40 | Significant decomposition issues |
| 0 | Tasks are not properly decomposed |

**Decomposition Rules:**
- Each task has single responsibility
- Tasks are independently verifiable
- No hidden dependencies between parallel tasks
- Work is fully covered (no gaps)

### 4. Dependency Graph (DG)
**Question:** Are task dependencies clear, acyclic, and visualized?

| Score | Criteria |
|-------|----------|
| 100 | ASCII graph, all deps valid, no cycles, optimal ordering |
| 80 | Graph present, deps valid, minor ordering improvements |
| 60 | Text-only deps, all valid |
| 40 | Some invalid deps or missing graph |
| 0 | Circular deps or critically broken graph |

**Graph Requirements:**
- Visual dependency diagram (ASCII preferred)
- All referenced task IDs exist
- No circular dependencies
- Critical path identifiable

### 5. Coverage Completeness (CC)
**Question:** Do tasks fully cover the epic goal?

| Score | Criteria |
|-------|----------|
| 100 | All success criteria mapped to tasks |
| 80 | >90% coverage, minor gaps |
| 60 | 70-90% coverage |
| 40 | 50-70% coverage |
| 0 | <50% coverage or major success criteria uncovered |

**Coverage Mapping:**
- Each success criterion has implementing task(s)
- No orphan success criteria
- No duplicate work across tasks

### 6. Phase Ordering (PO)
**Question:** Does the phase/wave sequence make logical sense?

| Score | Criteria |
|-------|----------|
| 100 | Phases follow logical progression, max parallelism |
| 80 | Good ordering, minor parallelism opportunities missed |
| 60 | Ordering works but inefficient |
| 40 | Some ordering violations |
| 0 | Critical ordering errors (dependent tasks in same wave) |

**Ordering Rules:**
- Foundation tasks before dependent tasks
- Maximum parallelism within constraints
- No phase contains mutually dependent tasks
- Critical path minimized

### 7. Scope Coherence (SC)
**Question:** Do all tasks contribute to the epic goal?

| Score | Criteria |
|-------|----------|
| 100 | All tasks directly serve epic goal |
| 80 | 1 tangential task |
| 60 | 2-3 tangential tasks |
| 40 | Multiple unrelated tasks |
| 0 | Tasks don't align with epic goal |

**Coherence Checks:**
- Each task traceable to success criteria
- No scope creep tasks
- No "nice-to-have" tasks mixed in
- Cleanup tasks are actually necessary

### 8. Success Criteria Quality (SQ)
**Question:** Are success criteria measurable and complete?

| Score | Criteria |
|-------|----------|
| 100 | All criteria SMART, checkboxes for tracking |
| 80 | Criteria measurable, minor gaps |
| 60 | Some criteria vague |
| 40 | Multiple unmeasurable criteria |
| 0 | No success criteria or all vague |

**Quality Indicators:**
- Uses checklist format (- [ ] item)
- Observable outcomes ("X renders", "Y returns")
- Covers all deliverables
- No subjective criteria ("looks good")

### 9. Risk Identification (RI)
**Question:** Are potential blockers and risks identified?

| Score | Criteria |
|-------|----------|
| 100 | Risks section with mitigations |
| 80 | Risks mentioned, implicit mitigations |
| 60 | Some risks noted, no mitigations |
| 40 | Risks not addressed |
| 0 | Critical risks ignored |

**Risk Categories:**
- Technical risks (new technology, complex integration)
- Dependency risks (external systems, APIs)
- Scope risks (unclear requirements, changing needs)
- Resource risks (availability, skills)

### 10. Integration Strategy (IS)
**Question:** Is it clear how tasks merge and integrate?

| Score | Criteria |
|-------|----------|
| 100 | Clear integration points, verification steps between phases |
| 80 | Integration implicit but clear |
| 60 | Some integration points unclear |
| 40 | Integration strategy missing |
| 0 | Tasks cannot be integrated as designed |

**Integration Elements:**
- Build verification between waves (`./init.sh`)
- Integration test points identified
- Merge strategy for parallel work
- Final verification described

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
| EPIC VALIDATION PASSED: 96/100            |
|                                           |
| Epic: shadcn-migration                    |
| Tasks: 17 | Phases: 6                     |
| All 10 metrics meet threshold (>=90)      |
| Ready for execution                       |
+-------------------------------------------+
```

### On FAIL (Concise - <20 lines)
```
+-------------------------------------------+
| EPIC VALIDATION FAILED: 84/100            |
|                                           |
| Epic: shadcn-migration                    |
|                                           |
| Failing Metrics:                          |
| * Dependency Graph: 60                    |
|   -> task 08 depends on non-existent 07a  |
|   -> no visual dependency diagram         |
| * Risk Identification: 75                 |
|   -> no risks section in EPIC.md          |
|                                           |
| Remediation (3 actions):                  |
| 1. Fix dep in 08-card.yml: 07a -> 07      |
| 2. Add ASCII dependency diagram to EPIC   |
| 3. Add ## Risks section with mitigations  |
+-------------------------------------------+
```

## EPIC.md Reference Format

```markdown
# Epic: [Epic Name]

## Overview

[Problem statement and solution approach]
[Scope boundaries]
[End state description]

## Architecture

[ASCII diagram showing component relationships]
[Component descriptions]
[Integration points]

## Component Mapping (optional)

| Current | Target | Migration Type |
|---------|--------|----------------|
| ...     | ...    | ...            |

## Dependencies (optional)

[External dependencies like npm packages]

## Success Criteria

- [ ] Criterion 1 (testable, measurable)
- [ ] Criterion 2
- [ ] ...

## Task Dependencies

[ASCII diagram showing task relationships]
[Wave/phase assignments]

## Dispatch Strategy

**Phase 1:** Tasks X, Y, Z - [Description]
**Phase 2:** Tasks A, B, C - [Description]
...

## Risks (recommended)

| Risk | Impact | Mitigation |
|------|--------|------------|
| ...  | ...    | ...        |
```

## Integration with Workflow

```
+---------------+     +------------------+     +------------------+
| Epic Planning | --> | /epic-validation | --> | /task-validation |
| (Create EPIC) |     | (Epic Quality)   |     | (Per-Task Check) |
+---------------+     +------------------+     +------------------+
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
```

## Validation Cascade

When validating an epic, the skill automatically:

1. Validates EPIC.md structure
2. Loads all tasks from `tasks/*.yml`
3. Validates each task with `/task-validation` metrics
4. Cross-references tasks against epic
5. Computes aggregate score

If any individual task fails validation (<95), the epic validation score is capped at 85, triggering a FAIL.

## Relationship to Other Validation Skills

| Skill | Validates | Scope |
|-------|-----------|-------|
| `/epic-validation` | EPIC.md + all tasks | Epic-level planning |
| `/task-validation` | Single task YAML | Task-level definition |
| `/agent-validation` | Completed code | Post-execution code quality |

## Common Issues and Fixes

### Missing Dependency Graph
```markdown
## Task Dependencies

BEFORE (text-only):
Tasks 1-3 have no deps. Tasks 4-7 depend on 1-3.

AFTER (visual):
```
      +-----+     +-----+     +-----+
      | 01  |     | 02  |     | 03  |
      +--+--+     +--+--+     +--+--+
         |           |           |
         +-----------+-----------+
                     |
    +----------------+----------------+
    |        |       |       |        |
 +--+--+  +--+--+ +--+--+ +--+--+  +--+--+
 | 04  |  | 05  | | 06  | | 07  |  | ... |
 +-----+  +-----+ +-----+ +-----+  +-----+
```
```

### Vague Success Criteria
```markdown
BEFORE (vague):
- [ ] App looks good
- [ ] Performance is acceptable

AFTER (measurable):
- [ ] All components render without console errors
- [ ] Page load time < 2s on 3G connection
```

### Missing Risk Section
```markdown
## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Radix/shadcn version conflict | High | Pin versions in package.json |
| Dark theme color drift | Medium | Create visual regression tests |
| Build time increase | Low | Monitor with CI metrics |
```

## Logging Integration

On completion, log to `journal.md`:
```yaml
- type: epic-validation
  epic: shadcn-migration
  score: 96/100
  tasks_validated: 17
  result: PASS
  timestamp: 2026-01-02T10:30:00Z
```
