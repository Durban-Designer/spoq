# SPOQ 1.1 strategy execution semantics

SPOQ keeps Project Plans → Features → Tasks and their dependency DAGs. A strategy
adds a separate control graph for deciding which skills run and which evidence
must exist. A strategy phase is neither a Feature nor a new work hierarchy.
Classic SPOQ and PIQARD share this execution contract.

Definitions use schema version 1, a stable strategy ID and semantic version.
The canonical SHA-256 of the complete definition identifies its content. A run
pins that content and the routing inputs; replacing an installed template never
rewrites an active run. The runner uses JSON data and declared skills. It does
not evaluate Python, shell commands or arbitrary expressions from definitions.

## Control flow and finite loops

Pass and always edges form the forward DAG. A fail edge may return to a forward
ancestor, including the failing phase itself for a bounded retry. Other cyclic
topologies are rejected by the compiler. This restriction keeps selected-branch
joins and invalidation precise while supporting planning and QA rework loops.
Every phase declares a finite `max_attempts`; every definition also declares
`max_transitions`. Both are positive integers, persisted across resume. Exhaustion
blocks progression and retains the attempts; it never silently grants a retry.

One attempt is one invocation of a phase. A transition atomically records its
result, selected edges, updated run state and event under revision/fencing checks.
The invocation identity, lease token and operation key distinguish legitimate
work from delayed or repeated submissions. The same key and payload return the
original receipt. Reusing a key for different content fails. Waiting, polling,
duplicate submissions and human wait time do not start another attempt or consume
an implementation retry. Recovering an abandoned attempt retains its identity and
uses a new lease fence; a former worker cannot advance it afterward.

The following definition is an executable contract example. `review` may send work
back to `draft`, but no path has an unlimited transition or phase budget.

```python
from spoq_server.v1.workflows.types import StrategyDefinition

loop_example = StrategyDefinition.from_dict({
    "schema_version": 1, "id": "bounded-review", "version": "1.0.0",
    "title": "Revision-bound review", "entry": "draft", "max_transitions": 9,
    "phases": [
        {"id": "draft", "kind": "skill", "skill": "spoq-discover",
         "inputs": ["goal"], "outputs": ["narrative"], "max_attempts": 3},
        {"id": "review", "kind": "human", "skill": None,
         "inputs": ["narrative"], "outputs": ["decision"], "max_attempts": 3},
        {"id": "plan", "kind": "skill", "skill": "spoq-plan",
         "inputs": ["narrative", "decision"], "outputs": ["plan"], "max_attempts": 3}
    ],
    "edges": [
        {"source": "draft", "target": "review"},
        {"source": "review", "target": "plan"},
        {"source": "review", "target": "draft", "on": "fail"}
    ]
})
assert loop_example.max_transitions == 9
assert all(phase.max_attempts == 3 for phase in loop_example.phases)
```

## Branches, parallel phases and joins

Edge predicates read the pinned routing input snapshot only. Supported operations
are `eq`, `ne`, `in` and `truthy`; dotted keys select JSON object fields. Missing
keys never select a branch. All matching forward edges may be selected, permitting
parallel independent design phases. A false predicate resolves its edge as
unselected. No random sampling or model call occurs during edge evaluation.

A join uses `config: {"join": "selected"}`. It waits until every incoming forward
edge is resolved, then requires all selected predecessors to have passed. It does
not wait for unselected branches to produce outputs. If none is selected, the join
is skipped. Skipping propagates resolved unselected edges through the forward DAG.
Required outputs from a selected phase cannot be replaced by a skipped result.
An unfinished selected input blocks a join; it cannot advance early.

```python
from spoq_server.v1.workflows.types import Predicate

pinned = {"design": {"erd": True, "formal": False}}
assert Predicate("design.erd", "truthy").evaluate(pinned)
assert not Predicate("design.formal", "truthy").evaluate(pinned)
assert not Predicate("design.missing", "truthy").evaluate(pinned)
```

On rework the runner resets the target and its forward descendants. Prior
attempts, evidence, artifacts and decisions remain historical records. They are
not current outputs merely because they once passed. Selected-branch decisions
are recomputed from the same pinned route inputs. Changing routing inputs starts
a new run rather than modifying branch decisions in place.

## Evidence, revisions and quality gates

Each result binds the run, phase and attempt identities, definition hash, current
scope specification hash and exact artifact content hashes. The specification
hash excludes operational status, claim and retry bookkeeping; it includes goals,
acceptance criteria, ownership and dependencies. An edited specification or
artifact invalidates affected current evidence and approvals. Invalidation never
deletes historical evidence. An unchanged output may be reused only after checking
these identities and its original actual checks.

```python
from spoq_server.v1.workflows.types import evidence_matches

reviewed = {"definition_hash": "a" * 64, "specification_hash": "b" * 64,
            "artifact_hashes": {"narrative": "c" * 64}}
assert evidence_matches(reviewed, definition_hash="a" * 64,
                        specification_hash="b" * 64,
                        artifact_hashes={"narrative": "c" * 64})
assert not evidence_matches(reviewed, definition_hash="a" * 64,
                            specification_hash="b" * 64,
                            artifact_hashes={"narrative": "d" * 64})
```

Identity matching alone does not prove correctness. Planning gates require all
ten metrics, average ≥95, floor ≥90 and passing hard checks. Implementation gates
require average ≥95, floor ≥80 and passing required checks. The runner records
reviewer type, command/exit provenance, artifact hashes and the computed gate
report. A report cannot pass when a required check fails or a required output is
missing. Existing 1.0 task APIs retain their compatibility contract; this stricter
evidence contract applies to new strategy phases.

## Human checkpoints and PIQARD

PIQARD performs discovery and any selected design work, writes a narrative plan,
and waits for a human decision before decomposition. A pending response is
`waiting_human`, distinct from `failed`. Rejection follows the bounded revision
edge; approval is bound to the artifact revision actually presented. A changed
narrative requires another response. An old receipt cannot approve the new text.

Only a user-originated response can satisfy a human phase. The local client must
explicitly attest that it is relaying the user's action; this is a provenance
boundary, not operating-system authentication of a human. Agent messages, inferred
agreement, elapsed time, notifications and board discussions never create that
attestation. Human consent to the plan does not grant Git publication, deployment
or any additional authorization outside the user's requested scope.

Markdown is the default narrative format. Confluence references may retain URL,
version and an attached reviewed export. A URL alone is not reviewed content.
Diagram/ERD source, algorithm inputs/outputs/invariants/complexity and formal
evidence are registered artifacts. Formal states distinguish specified, tested,
proven, disproven and unverified. Missing required tools block work; SPOQ never
calls an unexecuted specification a proof.

## Persistence, interruption and presentation

Transactions commit state and events together. Atomic snapshots bind state to a
committed cursor. Replay is ordered and idempotent; lost cursors require a new
snapshot. Pause stops new dispatch, preserves existing attempts and cannot grant
success. Restart reuses committed attempts/receipts, recovers leases deliberately
and rejects stale evidence. Legacy runs are `legacy_unclassified`, with no
invented phase history or retrospective quality passes.

The local viewer is read-only. Its definition graph shows reusable phases; its
timeline shows individual attempts, loops, waits and decisions. A keyboard list
exposes the same states and blockers. Scope links drill into the existing work
DAGs. Missing telemetry never becomes an estimated duration, cost or fabricated
completion percentage. See `SPOQ_1_1_UI_CONTRACT.md` for the read-model contract.
