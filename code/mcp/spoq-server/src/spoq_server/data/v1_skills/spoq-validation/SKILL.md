---
name: spoq-validation
description: Validate implemented SPOQ Tasks or integrated Features against acceptance criteria, actual checks, and the ten-metric code gate. Use for /spoq-validation and execution QA.
---

# SPOQ implementation validation

Replace agent-validation with evidence-based implementation QA. Accept a Task,
Feature, or Project Plan ID and the changed artifacts/check results. Review only
the requested scope and relevant integration; do not implement fixes while acting
as its independent reviewer or mark work complete yourself.

Use `../spoq/references/runtime.md` to connect and record stage handoffs. Read
the saved specification, acceptance criteria, actual diff, and tests. Use an
independent reviewer when required or permitted by the workflow; pass the raw
specification and artifacts rather than the implementer's desired verdict. Respect
delegation policy and available models. Label permitted self-review honestly.

## Verify before scoring

Run or inspect reproducible, current results for meaningful unit tests, relevant
build/type/lint checks, a real execution path, and acceptance/integration checks.
Verify that tests were discovered and exercise the changed behavior. Choose the
repository's actual checks; use `docker compose` for Compose commands. Record
commands, environment, exit codes, counts, and relevant output. A failing required
check, missing meaningful tests, unmet criterion, or blocking defect makes
`checks_passed=false`; a high score cannot override it. Unsupported checks are
limitations, never fabricated successes.

| Metric | Review |
|---|---|
| Syntactic Correctness | Code compiles and required static checks pass |
| Test Existence | Meaningful tests cover changed behavior and boundaries |
| Test Pass Rate | Required tests actually run and pass |
| Requirements Fidelity | Every scoped acceptance criterion is satisfied |
| SOLID Adherence | Design fits the codebase without needless abstraction |
| Security | Relevant trust boundaries, data handling, and authorization |
| Error Handling | Expected failures and edge cases behave deliberately |
| Scalability | Resource use is proportionate to the expected workload |
| Code Clarity | Names, structure, and rationale make maintenance practical |
| Completeness | Integration works; no hidden placeholders or missing behavior |

Score each 0–100 with rationale: 100 fully evidenced, 95 minor polish, 80 bounded
weakness, 60 substantial gap, 0 absent/broken. Judge relevance to this task; avoid
invented coverage percentages or unsupported claims about production scale.

Run `../spoq/scripts/score_gate.py --stage implementation --input <report.json>`
with all ten scores and the observed `checks_passed` boolean.
**PASS requires average ≥95, every metric ≥80, and passing required checks.**
Persist the full report, reviewer identity/type, specification, reviewed artifact
hashes or equivalent state, commands/results, limitations, and verdict in a linked
journal. Return its ID and report; execution owns rework and completion.

On FAIL, keep the remediation summary within 20 lines and five prioritized actions
with file:line or node references. Include an action for every blocker; group related
findings rather than hide them to meet the limit. Do not soften a failed build or
unmet requirement into a passing review. Rerun affected checks after changes;
unchanged evidence may be reused only when still applicable.
