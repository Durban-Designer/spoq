# Epic Validation Metric Rubrics

Detailed scoring criteria for each of the 10 epic validation metrics. Use these rubrics for consistent, fair evaluation of EPIC.md files and their task sets.

**Key Principle:** Plans are easier to fix than code. The floor of 90 per metric enforces high-quality planning before wave-based execution.

## 1. Vision Clarity (VC)

**Core Question:** Is the epic's goal clearly stated?

### Required Elements

| Element | Description | Points |
|---------|-------------|--------|
| Problem Statement | What issue is being solved | 25 |
| Solution Approach | High-level how | 25 |
| Scope Boundaries | What's in/out of scope | 25 |
| End State | What success looks like | 25 |

### Scoring

| Scenario | Score |
|----------|-------|
| All 4 elements clear in Overview | 100 |
| 3 elements present, 1 implicit | 90 |
| 2 elements present | 70 |
| Only problem or solution stated | 50 |
| No clear goal | 0 |

### Good Example

```markdown
## Overview

Migrate the Wyrd monitor-ui from its custom component system
to shadcn/ui. This modernizes the UI with consistent patterns,
improved accessibility, and reduced custom CSS.

**In Scope:** All ui components, layout, and form elements
**Out of Scope:** Backend changes, new features
**Success:** All components render, tests pass, dark theme preserved
```

---

## 2. Architecture Quality (AQ)

**Core Question:** Is the architecture diagram/description clear and complete?

### Required Elements

| Element | Points |
|---------|--------|
| Visual diagram (ASCII/mermaid) | 40 |
| Component relationships | 20 |
| Data flow arrows | 20 |
| Integration points marked | 20 |

### Scoring

| Scenario | Score |
|----------|-------|
| ASCII diagram + explanations | 100 |
| Diagram present, minor gaps | 90 |
| Text-only but comprehensive | 75 |
| Partial architecture | 60 |
| No architecture section | 0 |

### Diagram Template

```
+------------------------------------------------------+
|                     [Epic Name]                       |
+------------------------------------------------------+
|  [Component A]     [Component B]     [Component C]   |
|       |                 |                 |          |
|       +--------+--------+--------+--------+          |
|                |                 |                   |
|          [Shared Layer]   [Integration Point]        |
+------------------------------------------------------+
```

---

## 3. Task Decomposition (TD)

**Core Question:** Are tasks properly broken down into logical units?

### Decomposition Rules

| Rule | Violation Impact |
|------|------------------|
| Single responsibility per task | -20 |
| Tasks independently verifiable | -15 |
| No hidden dependencies between parallel tasks | -25 |
| Complete coverage (no gaps) | -30 |

### Scoring

| Scenario | Score |
|----------|-------|
| Atomic tasks, clear boundaries, full coverage | 100 |
| Good breakdown, minor overlap | 90 |
| Some tasks too large | 75 |
| Significant decomposition issues | 60 |
| Tasks not properly decomposed | 0 |

### Right-Sized Task Indicators

- 1-5 files per task
- 3-5 acceptance criteria
- 1-4 hours of focused work
- Clear start/end points

---

## 4. Dependency Graph (DG)

**Core Question:** Are task dependencies clear, acyclic, and visualized?

### Requirements

| Requirement | Points |
|-------------|--------|
| Visual dependency diagram | 30 |
| All referenced IDs exist | 30 |
| No circular dependencies | 30 |
| Critical path identifiable | 10 |

### Scoring

| Scenario | Score |
|----------|-------|
| ASCII graph, valid deps, optimal ordering | 100 |
| Graph present, valid deps, minor improvements | 90 |
| Text-only deps, all valid | 80 |
| Missing graph or invalid deps | 60 |
| Circular dependencies | 0 |

### Graph Template

```
       +-----+     +-----+     +-----+
       | 01  |     | 02  |     | 03  |  <- Phase 1 (parallel)
       +--+--+     +--+--+     +--+--+
          |           |           |
          +-----------+-----------+
                      |
                      v
              +-------+-------+
              |               |
           +--+--+         +--+--+
           | 04  |         | 05  |     <- Phase 2 (parallel)
           +-----+         +-----+
```

---

## 5. Coverage Completeness (CC)

**Core Question:** Do tasks fully cover the epic goal?

### Coverage Mapping

Each success criterion MUST map to at least one task:

```
Success Criteria          -> Implementing Task(s)
-------------------------------------------
"Button renders"         -> 04-create-button
"Tests pass"             -> 04-create-button, 17-cleanup
"Dark theme preserved"   -> 03-migrate-theme
```

### Scoring

| Coverage | Score |
|----------|-------|
| 100% criteria mapped | 100 |
| >95% coverage | 95 |
| 90-95% coverage | 90 |
| 80-90% coverage | 75 |
| <80% coverage | 50 |
| Major criteria uncovered | 0 |

---

## 6. Phase Ordering (PO)

**Core Question:** Does the phase/wave sequence make logical sense?

### Ordering Rules

| Rule | Violation Impact |
|------|------------------|
| Foundation before dependents | -30 |
| Maximum parallelism exploited | -10 |
| No mutual deps in same phase | -40 |
| Critical path minimized | -10 |

### Scoring

| Scenario | Score |
|----------|-------|
| Optimal ordering, max parallelism | 100 |
| Good ordering, minor parallelism missed | 90 |
| Works but inefficient | 75 |
| Some ordering violations | 60 |
| Critical violations | 0 |

### Phase Strategy Example

```
Phase 1 (Parallel): Foundation - Tasks 01, 02, 03
  -> No dependencies, can run simultaneously

Phase 2 (Parallel): Primitives - Tasks 04, 05, 06, 07
  -> Depend on Phase 1, independent of each other

Phase 3 (Sequential): Integration - Task 08
  -> Requires multiple Phase 2 outputs
```

---

## 7. Scope Coherence (SC)

**Core Question:** Do all tasks contribute to the epic goal?

### Coherence Checks

| Check | Points |
|-------|--------|
| Each task traceable to success criteria | 40 |
| No scope creep tasks | 30 |
| No "nice-to-have" mixed in | 20 |
| Cleanup tasks justified | 10 |

### Red Flags

| Flag | Score Impact |
|------|--------------|
| Task unrelated to overview | -25 |
| "While we're at it" additions | -15 |
| Feature creep in task descriptions | -20 |

---

## 8. Success Criteria Quality (SQ)

**Core Question:** Are success criteria measurable and complete?

### SMART Format

Each criterion should be:
- **S**pecific: Observable behavior
- **M**easurable: Quantifiable or binary
- **A**chievable: Within scope
- **R**elevant: Contributes to goal
- **T**estable: Can verify completion

### Scoring

| Scenario | Score |
|----------|-------|
| All criteria SMART, checkbox format | 100 |
| Criteria measurable, minor gaps | 90 |
| Some criteria vague | 75 |
| Multiple unmeasurable | 60 |
| No criteria or all subjective | 0 |

### Good vs Bad

**GOOD:**
```markdown
- [ ] All components render without console errors
- [ ] Page load time < 2s on 3G connection
- [ ] 4 existing tests updated and passing
```

**BAD:**
```markdown
- [ ] UI looks modern
- [ ] Performance is good enough
- [ ] Everything works
```

---

## 9. Risk Identification (RI)

**Core Question:** Are potential blockers and risks identified?

### Risk Categories

| Category | Example |
|----------|---------|
| Technical | Library version conflicts |
| Dependency | External API availability |
| Scope | Unclear requirements |
| Resource | Skill gaps |

### Scoring

| Scenario | Score |
|----------|-------|
| Risks section with mitigations | 100 |
| Risks mentioned, implicit mitigations | 90 |
| Some risks noted, no mitigations | 75 |
| Risks not addressed | 60 |
| Critical risks ignored | 0 |

### Risk Table Template

```markdown
## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Radix version conflict | High | Medium | Pin versions |
| Dark theme drift | Medium | Low | Visual tests |
| Build time increase | Low | High | Monitor CI |
```

---

## 10. Integration Strategy (IS)

**Core Question:** Is it clear how tasks merge and integrate?

### Integration Elements

| Element | Points |
|---------|--------|
| Build verification between waves | 30 |
| Integration test points identified | 30 |
| Merge strategy for parallel work | 20 |
| Final verification described | 20 |

### Scoring

| Scenario | Score |
|----------|-------|
| Clear integration points, verification steps | 100 |
| Integration implicit but clear | 90 |
| Some integration points unclear | 75 |
| Integration strategy missing | 60 |
| Tasks cannot integrate as designed | 0 |

### Integration Points Template

```markdown
## Integration Strategy

**Between Waves:**
- Run `./init.sh` to verify build
- Execute component tests

**Merge Strategy:**
- Tasks create separate files (no merge conflicts)
- Shared dependencies installed in Phase 1

**Final Verification:**
- Full test suite: `npm test`
- Production build: `npm run build`
- Visual smoke test in browser
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

1. **Vision Clarity** (can't validate unclear goals)
2. **Dependency Graph** (affects execution ordering)
3. **Coverage Completeness** (ensures goal is achievable)
4. **Task Decomposition** (right-sized work units)
5. **Phase Ordering** (efficient execution)
6. **Success Criteria Quality** (defines done)
7. **Architecture Quality** (guides implementation)
8. **Scope Coherence** (no wasted effort)
9. **Risk Identification** (proactive planning)
10. **Integration Strategy** (polish)

## Validation Cascade Note

When `/epic-validation` runs, it also validates each task with `/task-validation`. If any individual task scores <95, the epic's overall score is capped at 85, triggering a FAIL.
