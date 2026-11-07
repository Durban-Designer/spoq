# SPOQ Validation Framework

> Historical methodology reference. For the SQLite 1.x entity model and current
> commands, see [SPOQ 1.0](../../operational/SPOQ_1.md). Model names and old
> epic/map examples below describe the original paper implementation.

This document provides a deep-dive into SPOQ's dual validation gate system.

## Overview

SPOQ employs two validation gates:

| Gate | When | Purpose | Threshold |
|------|------|---------|-----------|
| **Planning** | Before execution | Ensure epic is well-defined | 95 avg / 90 min |
| **Code** | After execution | Ensure work meets standards | 95 avg / 80 min |

## Planning Validation (Pre-Execution)

### Purpose

Catch planning issues before expensive execution begins. A poorly-defined epic wastes agent time and produces low-quality results.

### 10 Planning Metrics

| Metric | Description | Weight |
|--------|-------------|--------|
| **Vision Clarity** | Is the epic goal clear and achievable? | Equal |
| **Architecture Quality** | Is the system design sound? | Equal |
| **Task Decomposition** | Are tasks atomic and right-sized (1-4 hours)? | Equal |
| **Dependency Graph** | Are dependencies correct and acyclic? | Equal |
| **Coverage Completeness** | Does the epic cover all requirements? | Equal |
| **Phase Ordering** | Are waves correctly assigned? | Equal |
| **Scope Coherence** | Does the epic have clear boundaries? | Equal |
| **Success Criteria Quality** | Are acceptance criteria SMART? | Equal |
| **Risk Identification** | Are risks identified and mitigated? | Equal |
| **Integration Strategy** | Is the merge/deployment plan clear? | Equal |

### Scoring Scale

Each metric is scored 0-100:

| Score | Meaning |
|-------|---------|
| 0-60 | Unacceptable - major issues |
| 60-80 | Needs improvement - notable gaps |
| 80-90 | Acceptable - minor issues |
| 90-95 | Good - meets expectations |
| 95-100 | Excellent - exceeds expectations |

### Pass Criteria

- **Average score**: ≥ 95
- **Minimum per-metric**: ≥ 90

If either threshold fails, the epic should be revised before execution.

### Common Planning Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| Vague vision | Score < 90 on Vision Clarity | Add specific deliverables |
| Large tasks | Score < 90 on Task Decomposition | Split into 1-4 hour chunks |
| Circular deps | Score < 90 on Dependency Graph | Review and break cycles |
| Untestable criteria | Score < 90 on Success Criteria | Add measurable conditions |

## Code Validation (Post-Execution)

### Purpose

Verify that completed work meets quality standards before integration.

### 10 Code Metrics

| Metric | Description | Threshold |
|--------|-------------|-----------|
| **Syntactic Correctness** | Does code compile/parse? | ≥ 80 |
| **Test Existence** | Do tests exist for new code? | ≥ 80 |
| **Test Pass Rate** | What % of tests pass? | ≥ 80 |
| **Requirements Fidelity** | Does code meet acceptance criteria? | ≥ 80 |
| **SOLID Adherence** | Does code follow SOLID principles? | ≥ 80 |
| **Security** | Are there obvious vulnerabilities? | ≥ 80 |
| **Error Handling** | Are errors handled gracefully? | ≥ 80 |
| **Scalability** | Will code perform at scale? | ≥ 80 |
| **Code Clarity** | Is code readable and documented? | ≥ 80 |
| **Completeness** | Is the deliverable fully implemented? | ≥ 80 |

### Pass Criteria

- **Average score**: ≥ 95
- **Minimum per-metric**: ≥ 80

Note: Code validation has a lower per-metric threshold (80 vs 90) because some metrics are harder to achieve perfectly.

### Common Code Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| No tests | Test Existence < 80 | Add unit tests |
| Failing tests | Test Pass Rate < 80 | Fix tests or code |
| Missing features | Requirements Fidelity < 80 | Implement missing parts |
| Security holes | Security < 80 | Address vulnerabilities |

## Validation Process

### Planning Validation Flow

```
┌─────────────────────────────────────────┐
│         /epic-validation                │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   Load EPIC.md and task/*.yml files     │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   Score each of 10 planning metrics     │
│   (Sonnet reviewer agent)               │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   Calculate average and minimum         │
└─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
    ┌───────┐               ┌───────┐
    │ PASS  │               │ FAIL  │
    │ ≥95/90│               │ <95/90│
    └───────┘               └───────┘
        │                       │
        ▼                       ▼
   Execute epic            Revise and
                           re-validate
```

### Code Validation Flow

```
┌─────────────────────────────────────────┐
│         /agent-validation               │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   Identify completed tasks from journal │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   For each task:                        │
│   - Read deliverables                   │
│   - Run tests                           │
│   - Check acceptance criteria           │
│   - Score 10 code metrics               │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│   Aggregate scores across tasks         │
└─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
    ┌───────┐               ┌───────┐
    │ PASS  │               │ FAIL  │
    │ ≥95/80│               │ <95/80│
    └───────┘               └───────┘
        │                       │
        ▼                       ▼
   Integrate code          Fix issues and
                           re-validate
```

## Reviewer Agent Behavior

### Scoring Guidelines

The reviewer agent (Sonnet) follows these guidelines:

1. **Be objective**: Base scores on evidence, not opinion
2. **Be consistent**: Same issues = same deductions
3. **Be specific**: Cite specific problems in feedback
4. **Be constructive**: Suggest fixes, not just criticisms

### Score Justification

Each score includes:
- Numeric value (0-100)
- Brief explanation
- Specific issues found (if any)
- Suggestions for improvement

Example:
```
Metric: Test Existence
Score: 85
Explanation: Tests exist for 4 of 5 new functions.
Issues: Missing test for validateConfig() function.
Suggestion: Add unit test covering validation edge cases.
```

## Threshold Calibration

### Why 95/90 and 95/80?

These thresholds were empirically calibrated:

- **95 average**: Ensures overall high quality
- **90 planning minimum**: Catches serious planning gaps
- **80 code minimum**: Allows flexibility for hard-to-perfect metrics

### Adjusting Thresholds

For different contexts, thresholds can be adjusted:

| Context | Planning | Code |
|---------|----------|------|
| Production code | 95/90 | 95/80 |
| Internal tools | 90/85 | 90/75 |
| Prototypes | 85/80 | 85/70 |

**Warning**: Lowering thresholds reduces quality guarantees.

## Integration with Journal

Validation results are recorded in the journal:

```yaml
---
agent: Sonnet Reviewer
session_type: validation
task: epic-validation
epic: my-epic
---

## Validation Results

| Metric | Score |
|--------|-------|
| Vision Clarity | 98 |
| Architecture Quality | 95 |
| ...

**Average**: 96.2
**Minimum**: 93
**Result**: PASS
```

## Failure Recovery

When validation fails:

### Planning Validation Failure

1. Review low-scoring metrics
2. Address specific issues cited
3. Update EPIC.md and/or task YAMLs
4. Re-run validation
5. Repeat until passing

### Code Validation Failure

1. Review failed metrics
2. Fix code/test issues
3. Re-run affected tests
4. Re-validate
5. Repeat until passing

## Limitations

### Known Limitations

1. **LLM-as-judge bias**: Reviewer may have blind spots
2. **No inter-rater reliability**: Single reviewer per validation
3. **Metric overlap**: Some metrics correlate (not independent)
4. **Gaming risk**: Agents may optimize for metrics over quality

### Mitigations

- Cross-validate critical work with human review
- Rotate reviewer prompts to reduce bias
- Supplement with automated checks (linting, coverage)
- Review generated tests for meaningful assertions
