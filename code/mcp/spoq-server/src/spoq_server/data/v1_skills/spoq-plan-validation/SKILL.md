---
name: spoq-plan-validation
description: Review saved SPOQ Project Plans and Feature/task DAGs before execution using the ten-metric planning gate. Use for /spoq-plan-validation and planning readiness checks.
---

# SPOQ planning validation

Replace epic-validation with a planning gate over SQLite Project Plans, Features,
and Tasks. Review the plan, not implementation quality. This stage never starts
implementation or marks Tasks complete.

Use `../spoq/references/runtime.md` to connect and record stage handoffs. Accept
a saved Project Plan or Feature ID; if omitted, infer it from the active request
and existing state. Read the user's goal, node metadata, prerequisites, relevant
repository code/tests, and migration diagnostics. Include every affected Feature
and its task DAG; check the containing Project Plan's Feature DAG as well.

## Review readiness

Compute both DAG levels. Cycles, unknown dependencies, unresolved migration
errors, missing acceptance criteria/verification, or uncovered requested outcomes
are hard failures regardless of average. Unfinished upstream work is a scheduling
constraint, not itself a malformed plan.

Score each metric 0–100 with evidence and specific findings:

| Metric | Review |
|---|---|
| Vision Clarity | Goal, scope boundaries, user outcome, assumptions |
| Architecture Quality | Approach fits the repository and intended interfaces |
| Task Decomposition | Bounded outcomes, executable context, clear file ownership |
| Dependency Graph | Valid references, acyclic task and Feature prerequisites |
| Coverage Completeness | Every requested outcome is assigned and verified |
| Phase Ordering | Prerequisites precede consumers; shared writes have an owner |
| Scope Coherence | Tasks contribute to the stated goal without unrelated work |
| Success Criteria Quality | Observable criteria and real verification commands |
| Risk Identification | Material risks have proportionate mitigations |
| Integration Strategy | Components fit together and integrated behavior is tested |

Use evidence-based scores: 100 fully supported, 95 sound with minor polish,
90 bounded weakness, 80 meaningful gap, 60 substantial gap, 0 absent/invalid.
A tiny change can meet architecture/risk criteria with a short explanation;
do not require diagrams, arbitrary task counts, or extra layers.

Run `../spoq/scripts/score_gate.py --stage plan --input <report.json>` with
all ten scores and `checks_passed` reflecting the hard checks above.
**PASS requires average ≥95, every metric ≥90, and all hard checks passing.**
Record scores, rationale, reviewed scope/specification, DAG results, and verdict
in a linked journal. Reuse only a current PASS covering the same specification.

## Return to the caller

Return the gate report and journal ID. On failure, provide at most five concrete
fixes with node IDs or file locations; leave work unexecuted. The planner or root
SPOQ may repair the plan and rerun this gate. A direct validation request reports
findings without silently expanding into planning or execution. Use an independent
reviewer when repository policy requires it and delegation is available; identify
self-review explicitly if it is the permitted fallback.
