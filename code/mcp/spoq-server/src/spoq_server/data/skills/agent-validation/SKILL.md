---
name: agent-validation
description: Validate sub-agent work against task definitions with 10-metric scoring (0-100). Use after Opus completes work and code compiles. Invokes Sonnet sub-agent for review. Pass threshold 95+. (project)
---

# Agent Validation Skill

Validates completed work from sub-agents using a structured 10-metric scoring system. Designed for the Opus→compile→Sonnet wave structure.

## When to Use

- After a sub-agent (typically Opus) completes a task
- After code successfully compiles/builds
- Before marking work as complete or merging
- When you need quality assurance on agent-generated code

## Invocation

```
/agent-validation <task-file-path>
```

**Examples:**
```bash
/agent-validation spoq/epics/knowledge-graph/task-01.yml
/agent-validation docs/tasks/implement-feature-x.md
```

## Pre-Validation Checks (Required)

**IMPORTANT**: Before scoring metrics, run these checks on TypeScript/JavaScript codebases:

### 1. Lint Check
```bash
# Detect if lint is available and run it
if [ -f "package.json" ]; then
  npm run lint 2>&1 || echo "LINT_ERRORS_FOUND"
fi
```

### 2. TypeScript Check
```bash
# Run TypeScript compiler in check mode (no emit)
if [ -f "tsconfig.json" ]; then
  npx tsc --noEmit 2>&1 || echo "TS_ERRORS_FOUND"
fi
```

### 3. Build Verification
```bash
# Verify the project builds successfully
if [ -f "package.json" ]; then
  npm run build 2>&1 || echo "BUILD_ERRORS_FOUND"
fi
```

**If any pre-validation check fails:**
- Syntactic Correctness (SC) metric automatically scores 0
- Validation fails immediately
- Report specific lint/TS errors with file:line references
- Agent must fix errors before re-validation

### Pre-Validation Failure Output
```
PRE-VALIDATION FAILED

Lint Errors (3):
  src/components/Header.tsx:15 - 'foo' is assigned but never used
  src/utils/api.ts:42 - Missing return type on function
  src/pages/index.tsx:8 - Unexpected any. Specify a different type

TypeScript Errors (1):
  src/services/auth.ts:23 - Type 'string' is not assignable to type 'number'

Fix these errors before proceeding with full validation.
```

## Validation Process

1. **Run Pre-Validation Checks** - Lint, TypeScript, Build (must pass)
2. **Read Task Definition** - Parse YAML/MD file for requirements
3. **Identify Affected Files** - Cross-reference task spec with `git diff`
4. **Score 10 Metrics** - Each metric scored 0-100
5. **Calculate Total** - Weighted average (equal weights)
6. **Return Verdict** - PASS (≥95, no metric <80) or FAIL with remediation

## The 10 Metrics

### 1. Syntactic Correctness (SC)
**Question:** Does the code compile/parse without errors?

| Score | Criteria |
|-------|----------|
| 100 | Compiles cleanly, no warnings |
| 80 | Compiles with minor warnings |
| 60 | Compiles with significant warnings |
| 0 | Does not compile |

### 2. Test Existence (TE)
**Question:** Does new code have corresponding unit tests?

| Score | Criteria |
|-------|----------|
| 100 | All new public methods/classes have tests |
| 80 | >80% coverage of new code |
| 60 | >50% coverage |
| 40 | Some tests exist but incomplete |
| 0 | No tests for new functionality |

### 3. Test Pass Rate (TP)
**Question:** Do all tests pass?

| Score | Criteria |
|-------|----------|
| 100 | All tests pass |
| 80 | >95% pass rate |
| 60 | >80% pass rate |
| 0 | Critical tests failing |

### 4. Requirements Fidelity (RF)
**Question:** Does implementation match the task specification?

| Score | Criteria |
|-------|----------|
| 100 | All requirements implemented correctly |
| 80 | Core requirements met, minor gaps |
| 60 | Major requirements met, some missing |
| 40 | Partial implementation |
| 0 | Does not address requirements |

### 5. SOLID Adherence (SA)
**Question:** Does the code follow SOLID principles?

| Score | Criteria |
|-------|----------|
| 100 | Exemplary SOLID compliance |
| 80 | Minor violations (e.g., slightly large class) |
| 60 | Moderate violations |
| 40 | Significant violations |
| 0 | Monolithic, tightly coupled code |

**SOLID Checklist:**
- **S**ingle Responsibility: One reason to change per class
- **O**pen/Closed: Open for extension, closed for modification
- **L**iskov Substitution: Subtypes replaceable for base types
- **I**nterface Segregation: Focused interfaces over fat ones
- **D**ependency Inversion: Depend on abstractions

### 6. Security (SE)
**Question:** Are there security vulnerabilities?

| Score | Criteria |
|-------|----------|
| 100 | No vulnerabilities, follows security best practices |
| 80 | Minor issues (e.g., missing input length limit) |
| 60 | Moderate issues needing attention |
| 40 | Significant vulnerabilities present |
| 0 | Critical vulnerabilities (injection, auth bypass, secrets in code) |

**Security Checklist:**
- No SQL/command injection vectors
- Input validation at boundaries
- No hardcoded secrets/credentials
- Proper authentication/authorization checks
- Safe deserialization practices

### 7. Error Handling (EH)
**Question:** Does code handle failures gracefully?

| Score | Criteria |
|-------|----------|
| 100 | Comprehensive error handling, clear messages |
| 80 | Good coverage, minor gaps |
| 60 | Basic error handling present |
| 40 | Inconsistent error handling |
| 0 | No error handling, crashes on bad input |

### 8. Scalability (SC)
**Question:** Will this code scale appropriately?

| Score | Criteria |
|-------|----------|
| 100 | Optimal algorithms, O(n) or better where possible |
| 80 | Efficient with minor optimization opportunities |
| 60 | Acceptable but has O(n²) in non-critical paths |
| 40 | Performance concerns in critical paths |
| 0 | O(n²) or worse in hot paths, will not scale |

**Scalability Checklist:**
- No nested loops over large datasets
- Proper indexing for database queries
- Pagination for list operations
- Caching where appropriate
- Async for I/O-bound operations

### 9. Code Clarity (CC)
**Question:** Is the code literate and self-documenting? (Knuth-inspired)

| Score | Criteria |
|-------|----------|
| 100 | Crystal clear, reads like well-written prose |
| 80 | Clear with minor naming improvements possible |
| 60 | Understandable but requires effort |
| 40 | Confusing structure or naming |
| 0 | Unreadable, magic numbers, cryptic names |

**Clarity Checklist:**
- Meaningful variable/function names
- Consistent naming conventions
- Logical code organization
- Comments explain "why" not "what"
- No dead code or commented-out blocks

### 10. Completeness (CO)
**Question:** Is the work fully finished?

| Score | Criteria |
|-------|----------|
| 100 | Complete, no loose ends |
| 80 | Minor polish needed |
| 60 | Some TODOs remain but core is done |
| 40 | Significant unfinished sections |
| 0 | Stub implementations, placeholders throughout |

**Completeness Checklist:**
- No `TODO` or `FIXME` comments in new code
- No placeholder/stub implementations
- No `throw new NotImplementedException()`
- All edge cases handled
- Integration points connected

## Pass/Fail Criteria

```
PASS: Total ≥ 95 AND every metric ≥ 80
FAIL: Total < 95 OR any metric < 80
```

## Output Format

### On PASS
```
┌─────────────────────────────────────────┐
│ VALIDATION PASSED: 97/100               │
│                                         │
│ All 10 metrics meet threshold (≥80)     │
│ Ready for merge/completion              │
└─────────────────────────────────────────┘
```

### On FAIL (Concise - <20 lines)
```
┌─────────────────────────────────────────┐
│ VALIDATION FAILED: 87/100               │
│                                         │
│ Failing Metrics:                        │
│ • Test Existence: 60 → Add tests for:   │
│   - FooService.bar()                    │
│   - BazController.create()              │
│ • Completeness: 75 → Resolve:           │
│   - TODO on line 42 of Foo.java         │
│                                         │
│ Remediation (3 actions):                │
│ 1. Create FooServiceTest.java           │
│ 2. Implement TODO (add caching logic)   │
│ 3. Re-run /agent-validation             │
└─────────────────────────────────────────┘
```

## IMPORTANT: Concise Feedback Rule

When validation fails, the remediation report MUST:
- Be ≤20 lines total
- List only failing metrics with specific file:line references
- Provide numbered action items (max 5)
- Avoid verbose explanations

**Rationale:** The overseer's context window is precious. Dense, actionable feedback over verbose explanations.

## Validation Prompt Template

When invoking the Sonnet sub-agent, use this structure:

```
You are validating work completed by another agent.

TASK DEFINITION:
[Contents of task file]

FILES MODIFIED:
[git diff --name-only or file list from task]

SCORING INSTRUCTIONS:
Score each metric 0-100. Be rigorous but fair.
Pass threshold: 95 overall, 80 minimum per metric.

For failures, provide:
1. Specific file:line references
2. Concrete fix descriptions (not generic advice)
3. Maximum 5 remediation actions

OUTPUT FORMAT:
[Use the box format specified above]
```

## Integration with Wave Structure

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│ Opus Agent  │ ──► │ Compile     │ ──► │ /agent-validation│
│ (Work)      │     │ (Build)     │     │ (Sonnet Review)  │
└─────────────┘     └─────────────┘     └──────────────────┘
                                                 │
                           ┌─────────────────────┴─────────────────────┐
                           ▼                                           ▼
                    ┌─────────────┐                             ┌─────────────┐
                    │ PASS ≥95    │                             │ FAIL <95    │
                    │ Merge/Done  │                             │ → Rework    │
                    └─────────────┘                             └─────────────┘
```

## Logging Integration

On completion, log to `journal.md`:
```yaml
- type: validation
  task: <task-file-path>
  score: 97/100
  result: PASS
  timestamp: 2026-01-02T10:30:00Z
```

## Example Task File Format

```yaml
# spoq/epics/example-task.yml
name: Implement User Authentication
description: Add JWT-based authentication to the API

requirements:
  - Create AuthService with login/logout methods
  - Add JwtTokenProvider utility
  - Implement AuthController with /login endpoint
  - Add unit tests for AuthService

affected_files:
  - code/apps/orchestrator-java/src/main/java/com/wyrd/orchestrator/service/AuthService.java
  - code/apps/orchestrator-java/src/main/java/com/wyrd/orchestrator/controller/AuthController.java
  - code/apps/orchestrator-java/src/test/java/com/wyrd/orchestrator/service/AuthServiceTest.java

acceptance_criteria:
  - Login returns valid JWT token
  - Invalid credentials return 401
  - Token validation works correctly
  - 80%+ test coverage on new code
```

## Troubleshooting

**Skill not activating?**
- Ensure task file path is valid
- Check that code compiles first (prerequisite)

**Scores seem too harsh?**
- Review `references/metric-rubrics.md` for detailed criteria
- Ensure task file accurately describes requirements

**Output too verbose?**
- File an issue; concise output is a core requirement
