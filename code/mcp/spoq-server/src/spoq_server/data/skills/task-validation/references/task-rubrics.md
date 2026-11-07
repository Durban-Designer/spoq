# Task Validation Metric Rubrics

Detailed scoring criteria for each of the 10 task validation metrics. Use these rubrics for consistent, fair evaluation of task YAML definitions.

**Key Principle:** Plans are easier to fix than code. The floor of 90 per metric enforces high-quality definitions before execution.

## 1. Structural Completeness (SC)

**Core Question:** Does the task have all required fields with valid values?

### Required Fields Checklist

| Field | Type | Valid Values |
|-------|------|--------------|
| `id` | string | Pattern: `NN-kebab-case` (e.g., "04-create-button") |
| `title` | string | Human-readable, <100 chars |
| `epic` | string | Matches parent directory name |
| `status` | enum | pending, in_progress, qa, rework, completed, failed |
| `dependencies` | list | Empty `[]` or list of valid task IDs |
| `files_to_touch` | list | Non-empty list of relative paths |
| `acceptance_criteria` | list | Non-empty list of criteria strings |
| `description` | string | Multi-line markdown |

### Scoring Examples

| Scenario | Score |
|----------|-------|
| All 8 required + skills, outputs | 100 |
| All 8 required, no optional fields | 90 |
| Missing one optional but description complete | 85 |
| Missing `acceptance_criteria` | 60 |
| Invalid YAML syntax | 0 |

---

## 2. Requirements Clarity (RC)

**Core Question:** Is the description specific, measurable, and actionable?

### Description Structure

```yaml
description: |
  ## Objective        <- Required: What to accomplish
  [Clear goal statement]

  ## Steps            <- Required: How to accomplish
  1. Step one
  2. Step two

  ## Verification     <- Recommended: How to verify
  [Commands or manual checks]
```

### Scoring Matrix

| Element | Points |
|---------|--------|
| Clear Objective section | 25 |
| Numbered Steps section | 25 |
| Code examples where needed | 25 |
| Verification section | 25 |

### Anti-Patterns (Score Deductions)

| Pattern | Deduction |
|---------|-----------|
| "Do the thing" (no detail) | -40 |
| Steps without order | -20 |
| Missing code examples for complex impl | -15 |
| Ambiguous pronouns ("it", "this") | -10 |

---

## 3. Scope Appropriateness (SA)

**Core Question:** Is the task right-sized for a single agent session?

### Size Guidelines

| Metric | Ideal | Acceptable | Too Large |
|--------|-------|------------|-----------|
| Files to touch | 1-3 | 4-7 | 8+ |
| Acceptance criteria | 3-5 | 6-8 | 9+ |
| Description length | 50-150 lines | 150-300 | 300+ |

### Scope Smell Indicators

| Indicator | Score Impact |
|-----------|--------------|
| Multiple "Create X" in title | -20 |
| 3+ distinct feature areas | -30 |
| "and" in objective (doing two things) | -20 |
| Dependencies could be separate tasks | -15 |

---

## 4. Dependency Accuracy (DA)

**Core Question:** Are dependencies valid and acyclic?

### Validation Rules

1. **ID Existence:** Each dep ID must exist in `tasks/*.yml`
2. **No Self-Reference:** Task cannot depend on itself
3. **No Cycles:** No transitive cycles (A->B->C->A)
4. **Logical Order:** Deps make semantic sense

### Scoring

| Scenario | Score |
|----------|-------|
| All deps valid, logical ordering | 100 |
| All valid, ordering could improve | 90 |
| One typo in dep ID | 70 |
| Multiple invalid IDs | 50 |
| Circular dependency | 0 |

---

## 5. File Path Validity (FP)

**Core Question:** Are file paths syntactically correct and project-appropriate?

### Path Rules

| Rule | Valid Example | Invalid Example |
|------|---------------|-----------------|
| Relative paths | `code/apps/foo/src/Bar.java` | `/home/user/code/Bar.java` |
| Correct extension | `Button.tsx` | `Button.ts` (for React) |
| Project structure | `code/apps/*/src/**` | `src/apps/*/code/**` |
| No special chars | `my-component.tsx` | `my component.tsx` |

### Scoring

| Scenario | Score |
|----------|-------|
| All paths valid, follow conventions | 100 |
| Minor convention deviation | 90 |
| 1 path with typo or wrong extension | 75 |
| Multiple invalid paths | 50 |
| Absolute paths used | 0 |

---

## 6. Acceptance Criteria Quality (AC)

**Core Question:** Are criteria testable and complete?

### SMART Criteria Format

Each criterion should be:
- **S**pecific: "Button renders" not "UI works"
- **M**easurable: "3 variants" not "multiple variants"
- **A**chievable: Within task scope
- **R**elevant: Directly related to task goal
- **T**estable: Can verify with code or observation

### Examples

**GOOD (Score: 100):**
- "Button renders with all size variants (sm, md, lg)"
- "Loading state shows spinner and disables button"
- "Existing Button.test.tsx passes after updates"

**BAD (Score: 50):**
- "Button looks good" (subjective)
- "Works correctly" (vague)
- "Performance is acceptable" (unmeasurable)

---

## 7. Feasibility (FE)

**Core Question:** Is the task technically achievable?

### Feasibility Checklist

| Check | Points |
|-------|--------|
| Referenced libraries exist | 25 |
| File paths match project structure | 25 |
| No external system dependencies | 25 |
| Skills match AI agent capabilities | 25 |

### Red Flags

| Flag | Score Impact |
|------|--------------|
| References non-existent library | -40 |
| Requires human-only action | -100 |
| Depends on unavailable API | -40 |
| Requires real-time human input | -40 |

---

## 8. Consistency (CO)

**Core Question:** Are there contradictions within the task?

### Consistency Checks

| Check | Score Impact if Failed |
|-------|------------------------|
| title matches description objective | -15 |
| files_to_touch matches description | -20 |
| acceptance_criteria covers outputs | -15 |
| dependencies align with scope | -10 |

---

## 9. Actionability (AO)

**Core Question:** Can an AI agent execute this task?

### Actionability Indicators

| Indicator | Points |
|-----------|--------|
| Imperative verbs ("Create", "Update", "Add") | 25 |
| All inputs specified or discoverable | 25 |
| No open-ended research required | 25 |
| Success objectively determinable | 25 |

### Agent Blockers

| Blocker | Score Impact |
|---------|--------------|
| "Research best approach" | -30 |
| "Consult with team" | -50 |
| "Design the architecture" (no guidance) | -30 |
| Placeholder TODOs in steps | -20 |

---

## 10. Verification Clarity (VC)

**Core Question:** Is it clear how to verify completion?

### Verification Elements

| Element | Points |
|---------|--------|
| Build command specified | 25 |
| Test command specified | 25 |
| Manual verification steps | 25 |
| Expected output described | 25 |

### Template

```yaml
## Verification

```bash
cd code/apps/monitor-ui
npm test -- Button.test.tsx
npm run build
```

Expected: All tests pass, build succeeds without warnings.
```

---

## Pass Thresholds

```
PASS: Total >= 95 AND every metric >= 90
FAIL: Total < 95 OR any metric < 90
```

**Rationale:** Plans are cheap to fix. A 90 floor catches issues before expensive code execution begins.

## Remediation Priority

When multiple metrics fail, fix in this order:

1. **Structural Completeness** (can't validate incomplete tasks)
2. **Dependency Accuracy** (affects execution ordering)
3. **File Path Validity** (affects agent navigation)
4. **Requirements Clarity** (agent needs clear instructions)
5. **Acceptance Criteria** (defines success)
6. **Scope Appropriateness** (right-sizing)
7. **Consistency** (no contradictions)
8. **Feasibility** (achievable work)
9. **Actionability** (agent can execute)
10. **Verification Clarity** (polish)
