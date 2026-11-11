import classic from "../../../mcp/spoq-server/src/spoq_server/data/strategies/classic.json" with { type: "json" };
import piqard from "../../../mcp/spoq-server/src/spoq_server/data/strategies/piqard.json" with { type: "json" };
import type { Snapshot } from "./types";
export function snapshotFixture(
  strategy: "classic" | "piqard" = "piqard",
): Snapshot {
  const definition = JSON.parse(
    JSON.stringify(strategy === "classic" ? classic : piqard),
  );
  const active = strategy === "classic" ? "execute" : "review";
  const activeIndex = definition.phases.findIndex(
    (p: { id: string }) => p.id === active,
  );
  const phases = definition.phases.map((p: { id: string }, i: number) => ({
    id: p.id,
    status:
      i < activeIndex
        ? "passed"
        : i === activeIndex
          ? strategy === "piqard"
            ? "waiting_human"
            : "running"
          : "queued",
    attempt_id: i <= activeIndex ? "attempt-" + p.id : null,
    number: i <= activeIndex ? 1 : undefined,
    owner: i <= activeIndex ? "fixture-worker" : undefined,
    reason:
      p.id === active && strategy === "piqard"
        ? "Awaiting user response for narrative revision"
        : "",
  }));
  if (strategy === "piqard") {
    for (const phase of phases) {
      if (["diagram", "algorithm", "formal"].includes(phase.id)) {
        phase.status = "skipped";
        phase.attempt_id = null;
        phase.number = undefined;
        phase.owner = undefined;
        phase.reason = "Not selected by pinned routing inputs.";
      }
    }
  }
  return {
    format: "spoq-workflow-view-1",
    cursor: 42,
    run: {
      run_id: "demo-" + strategy,
      scope_id: "checkout",
      status: strategy === "piqard" ? "waiting_human" : "running",
      revision: 4,
      provenance: "strategy",
      definition_hash: "a".repeat(64),
      specification_hash: "b".repeat(64),
      current_specification_hash: "b".repeat(64),
      transitions: 4,
      pagination: {
        artifacts: { has_more: false, cursor: null },
        decisions: { has_more: false, cursor: null },
        participants: { has_more: false, cursor: null },
      },
    },
    definition: { ...definition, content_hash: "a".repeat(64) },
    routing: {
      strategy,
      profile: "standard",
      policy_version: "spoq-route-1",
      inputs: { uncertainty: strategy === "piqard" ? "high" : "low" },
      reasons: [
        strategy === "piqard"
          ? "Requirements need human decisions before decomposition."
          : "Known scope can use Classic SPOQ with both validation gates.",
      ],
      addons: { erd: strategy === "piqard" },
    },
    phases,
    attempts: phases
      .filter((p: { attempt_id: string | null }) => p.attempt_id)
      .map((p: { id: string; attempt_id: string; status: string }) => ({
        id: p.attempt_id,
        phase_id: p.id,
        number: 1,
        status: p.status,
        owner: "fixture-worker",
        created_at: "2026-11-08T12:00:00Z",
        updated_at: "2026-11-08T12:00:00Z",
        evidence: {
          reviewer: {
            agent: "fixture-adapter",
            review_type: "scripted_adapter",
          },
          provenance: "scripted UI fixture",
          checks_passed: p.status === "passed",
        },
      })),
    artifacts: [
      {
        id: "narrative-artifact",
        attempt_id: "attempt-narrative",
        kind: "narrative_plan",
        sha256: "c".repeat(64),
        source: "scripted_adapter",
        author: "fixture-worker",
        metadata: { validation: { source_only: true } },
      },
    ],
    decisions: [],
    participants: [{ id: "fixture-worker", role: "worker", runtime: "manual" }],
    work: {
      scope_id: "checkout",
      nodes: [
        {
          id: "checkout",
          kind: "project_plan",
          title: "Checkout",
          status: "pending",
        },
        {
          id: "checkout/api",
          kind: "feature",
          parent_id: "checkout",
          title: "API",
          status: "in_progress",
        },
        {
          id: "checkout/ui",
          kind: "feature",
          parent_id: "checkout",
          title: "UI",
          status: "pending",
        },
        {
          id: "checkout/api/contract",
          kind: "task",
          parent_id: "checkout/api",
          title: "API contract",
          status: "completed",
        },
        {
          id: "checkout/api/tests",
          kind: "task",
          parent_id: "checkout/api",
          title: "API tests",
          status: "pending",
        },
      ],
      edges: [
        {
          scope_id: "checkout",
          node_id: "checkout/ui",
          dependency_id: "checkout/api",
        },
        {
          scope_id: "checkout/api",
          node_id: "checkout/api/tests",
          dependency_id: "checkout/api/contract",
        },
      ],
      pagination: { has_more: false, cursor: null },
    },
    blockers:
      strategy === "piqard"
        ? [
            "Awaiting a user response for the exact narrative artifact revision.",
          ]
        : [],
    has_more_attempts: false,
    attempt_cursor: null,
  };
}
