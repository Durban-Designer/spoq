# Agent Validation Metric Rubrics

Detailed scoring criteria for each of the 10 validation metrics. Use these rubrics to ensure consistent, fair evaluation.

## 1. Syntactic Correctness (SC)

**Core Question:** Does the code compile/parse without errors?

### Scoring Matrix

| Score | Java | TypeScript | Python |
|-------|------|------------|--------|
| 100 | `mvn compile` clean, 0 warnings | `tsc` clean | `python -m py_compile` clean, mypy passes |
| 80 | Compiles, <5 deprecation warnings | Compiles, minor type warnings | Compiles, minor mypy warnings |
| 60 | Compiles, significant warnings | Compiles, type:any usage | Compiles, type hints missing |
| 40 | Compiles with `-Werror` disabled | Compiles with `skipLibCheck` | Compiles but crashes at runtime |
| 0 | Does not compile | Does not compile | Syntax errors |

### Common Issues → Fixes

| Issue | Score Impact | Fix |
|-------|--------------|-----|
| Missing semicolons | -10 | Add semicolons |
| Unclosed brackets | -100 | Fix bracket matching |
| Type mismatch | -20 | Cast or fix types |
| Missing imports | -100 | Add import statements |

---

## 2. Test Existence (TE)

**Core Question:** Does new code have corresponding unit tests?

### Scoring Formula

```
Score = (tested_methods / new_public_methods) × 100
```

### What Counts as "Tested"

- Direct unit test for the method
- Integration test exercising the method
- Edge cases covered (null, empty, boundary)

### Scoring Examples

| Scenario | Score |
|----------|-------|
| 10 new methods, 10 test classes | 100 |
| 10 new methods, 8 test classes | 80 |
| 10 new methods, 5 test classes | 50 |
| 10 new methods, 0 test classes | 0 |

### Exception: Test Not Required

- Private helper methods (covered via public method tests)
- Simple getters/setters (unless complex logic)
- Configuration classes (no business logic)

---

## 3. Test Pass Rate (TP)

**Core Question:** Do all tests pass?

### Scoring Formula

```
Score = (passing_tests / total_tests) × 100
```

### Critical Test Multiplier

If any test marked `@Critical` or in `critical/` package fails:
```
Score = min(Score, 40)
```

### Scoring Examples

| Scenario | Score |
|----------|-------|
| 100/100 tests pass | 100 |
| 98/100 tests pass | 98 |
| 80/100 tests pass | 80 |
| 50/100 tests pass | 50 |
| Critical test fails | max 40 |

---

## 4. Requirements Fidelity (RF)

**Core Question:** Does implementation match task specification?

### Evaluation Method

1. Extract requirements from task file
2. Check each requirement against implementation
3. Score based on coverage

### Scoring Matrix

| Coverage | Score |
|----------|-------|
| All requirements fully implemented | 100 |
| All core requirements, minor gaps | 80 |
| Core requirements, some missing | 60 |
| Partial implementation | 40 |
| Major requirements missing | 20 |
| Does not address task | 0 |

### Requirement Classification

- **Core:** Must-have functionality
- **Secondary:** Should-have enhancements
- **Nice-to-have:** Could-have polish

Core requirements have 2× weight in scoring.

---

## 5. SOLID Adherence (SA)

**Core Question:** Does code follow SOLID principles?

### Per-Principle Scoring (20 points each)

**Single Responsibility (S):**
| Scenario | Points |
|----------|--------|
| Each class has one clear purpose | 20 |
| Minor violations (2-3 responsibilities) | 15 |
| Moderate violations | 10 |
| God class present | 0 |

**Open/Closed (O):**
| Scenario | Points |
|----------|--------|
| Uses interfaces/abstractions for extension | 20 |
| Mostly extensible, some hardcoding | 15 |
| Requires modification for changes | 10 |
| No extension points | 0 |

**Liskov Substitution (L):**
| Scenario | Points |
|----------|--------|
| Subtypes fully substitutable | 20 |
| Minor behavioral differences | 15 |
| Overrides break contracts | 5 |
| Inheritance misused | 0 |

**Interface Segregation (I):**
| Scenario | Points |
|----------|--------|
| Focused, cohesive interfaces | 20 |
| Slightly broad interfaces | 15 |
| Fat interfaces forcing implementation | 10 |
| One mega-interface | 0 |

**Dependency Inversion (D):**
| Scenario | Points |
|----------|--------|
| Depends on abstractions | 20 |
| Mixed concrete/abstract deps | 15 |
| Mostly concrete dependencies | 10 |
| Hardcoded `new` everywhere | 0 |

---

## 6. Security (SE)

**Core Question:** Are there security vulnerabilities?

### OWASP Top 10 Checklist

| Vulnerability | Score Impact |
|---------------|--------------|
| SQL Injection | -100 |
| Command Injection | -100 |
| XSS (Cross-Site Scripting) | -60 |
| Broken Authentication | -80 |
| Sensitive Data Exposure | -60 |
| XXE (XML External Entities) | -40 |
| Broken Access Control | -80 |
| Security Misconfiguration | -30 |
| Insecure Deserialization | -50 |
| Using Components with Known Vulns | -40 |

### Automatic Failures (Score = 0)

- Hardcoded passwords/API keys in code
- SQL queries built with string concatenation
- `eval()` or equivalent with user input
- Disabled security checks (CSRF, etc.)

### Scoring Examples

| Scenario | Score |
|----------|-------|
| No vulnerabilities found | 100 |
| Missing input validation | 80 |
| XSS vulnerability | 40 |
| SQL injection present | 0 |

---

## 7. Error Handling (EH)

**Core Question:** Does code handle failures gracefully?

### Checklist

| Item | Points |
|------|--------|
| All I/O operations wrapped in try-catch | 20 |
| Meaningful error messages | 20 |
| Errors logged appropriately | 20 |
| Resources cleaned up (finally/try-with) | 20 |
| User-facing errors are safe (no stack traces) | 20 |

### Anti-Patterns (Score Deductions)

| Pattern | Deduction |
|---------|-----------|
| Empty catch blocks | -30 |
| Catch-all without handling | -20 |
| Swallowing exceptions silently | -25 |
| Exposing stack traces to users | -20 |
| No logging of errors | -15 |

---

## 8. Scalability (SC)

**Core Question:** Will this code scale?

### Algorithm Complexity Check

| Complexity | Score (for hot paths) |
|------------|----------------------|
| O(1) | 100 |
| O(log n) | 100 |
| O(n) | 100 |
| O(n log n) | 90 |
| O(n²) | 40 |
| O(n³) | 20 |
| O(2^n) | 0 |

### Database Query Check

| Pattern | Score Impact |
|---------|--------------|
| Uses indexes appropriately | +20 |
| N+1 query problem | -40 |
| Full table scan on large table | -30 |
| Missing pagination | -20 |

### Memory Check

| Pattern | Score Impact |
|---------|--------------|
| Streaming large files | +10 |
| Loading entire file into memory | -20 |
| Unbounded cache | -30 |
| Memory leaks | -50 |

---

## 9. Code Clarity (CC)

**Core Question:** Is the code literate and self-documenting?

### Naming Quality (40 points)

| Quality | Points |
|---------|--------|
| Names reveal intent (e.g., `calculateTotalPrice`) | 40 |
| Mostly clear (e.g., `calcTotal`) | 30 |
| Abbreviated but understandable | 20 |
| Cryptic (e.g., `ct`, `x1`) | 0 |

### Structure Quality (30 points)

| Quality | Points |
|---------|--------|
| Logical organization, easy to navigate | 30 |
| Mostly organized | 20 |
| Some structure issues | 10 |
| Chaotic, hard to follow | 0 |

### Documentation Quality (30 points)

| Quality | Points |
|---------|--------|
| Comments explain "why", code explains "what" | 30 |
| Some helpful comments | 20 |
| Over-commented or under-commented | 10 |
| No comments, unclear code | 0 |

### Knuth-Inspired Principles

- Code should read like well-written prose
- The program is a story told to humans
- Clarity over cleverness

---

## 10. Completeness (CO)

**Core Question:** Is the work fully finished?

### Checklist

| Item | Points |
|------|--------|
| No TODO comments in new code | 25 |
| No FIXME comments | 25 |
| No stub/placeholder implementations | 25 |
| All edge cases handled | 15 |
| Integration points connected | 10 |

### Automatic Deductions

| Pattern | Deduction |
|---------|-----------|
| `TODO:` in new code | -25 |
| `FIXME:` in new code | -25 |
| `throw new NotImplementedException()` | -30 |
| `// PLACEHOLDER` | -20 |
| `pass` with no implementation (Python) | -25 |
| Empty method bodies | -20 |

---

## Quick Reference: Pass Thresholds

```
Overall Pass: ≥ 95
Per-Metric Floor: ≥ 80

If any metric < 80, automatic FAIL regardless of total.
```

## Remediation Priority

When multiple metrics fail, prioritize fixes in this order:

1. **Syntactic Correctness** (must compile first)
2. **Security** (vulnerabilities are critical)
3. **Test Pass Rate** (broken tests block others)
4. **Requirements Fidelity** (core functionality)
5. **Test Existence** (quality gate)
6. **Completeness** (finish what you started)
7. **Error Handling** (production readiness)
8. **SOLID Adherence** (maintainability)
9. **Scalability** (future-proofing)
10. **Code Clarity** (polish)
