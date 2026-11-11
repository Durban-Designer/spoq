import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { vi } from "vitest";
import { PhaseDetails } from "./PhaseDetails";
import { ArtifactPanel, DecisionCard } from "./ArtifactPanel";
import { WorkGraph, workLayout } from "./WorkGraph";
import { snapshotFixture } from "./fixtures.test-support";
import type { Artifact } from "./types";
vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right" },
  MarkerType: { ArrowClosed: "closed" },
  Background: () => null,
  Controls: () => null,
  ReactFlow: () => <div data-testid="work-graph" />,
}));
afterEach(() => vi.restoreAllMocks());
function api() {
  const s = snapshotFixture();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const id = decodeURIComponent(url.split("/").at(-1)!.split("?")[0]);
    const data = url.includes("/attempts/")
      ? {
          ...s.attempts.find((a) => a.id === id),
          evidence: {
            reviewer: { agent: "fixture-reviewer", review_type: "self_review" },
            provenance: "scripted adapter",
            checks_passed: true,
            average: 96,
            minimum: 93,
            observed_checks: [
              {
                command: "pytest recorded-check",
                exit_code: 0,
                observed: true,
                source: "shell",
                required: true,
              },
              {
                check_type: "review",
                name: "Architecture decision reviewed",
                passed: true,
                observed: true,
                source: "user",
                required: true,
              },
              {
                check_type: "tool",
                name: "Solver report retained",
                passed: false,
                observed: true,
                source: "fixture-solver",
                required: false,
              },
              {
                check_type: "artifact",
                name: "Narrative revision attached",
                passed: true,
                observed: true,
                source: "artifact-registry",
                required: true,
              },
            ],
          },
        }
      : url.includes("/nodes/")
        ? {
            ...s.work.nodes.find((n) => n.id === id),
            data: { acceptance_criteria: ["Actual contract passes"] },
          }
        : {
            ...s.artifacts.find((a) => a.id === id),
            content:
              "<script>window.UNSAFE=true</script>\n## Scope\nLiteral review text",
            render_as: "text",
          };
    return new Response(JSON.stringify(data), { status: 200 });
  });
  return s;
}

test("selected phase exposes declared IO, current actor, exact attempt and observed evidence", async () => {
  const s = api();
  render(<PhaseDetails snapshot={s} selected="review" />);
  expect(
    screen.getByRole("heading", { name: "Human review" }),
  ).toBeInTheDocument();
  expect(screen.getByText("narrative_plan")).toBeInTheDocument();
  expect(await screen.findByText("fixture-reviewer")).toBeInTheDocument();
  expect(screen.getByText("self_review")).toBeInTheDocument();
  expect(screen.getByText("pytest recorded-check")).toBeInTheDocument();
  expect(screen.getByText(/Average \/ floor/)).toBeInTheDocument();
  expect(screen.getByText("96 / 93")).toBeInTheDocument();
  expect(
    screen.getByText("Architecture decision reviewed"),
  ).toBeInTheDocument();
  expect(screen.getByText("Solver report retained")).toBeInTheDocument();
  expect(screen.getByText("Narrative revision attached")).toBeInTheDocument();
  expect(screen.getByText(/tool · Failed/)).toBeInTheDocument();
  expect(
    screen.getByText(/Source: fixture-solver · Observed · Optional/),
  ).toBeInTheDocument();
});

test("artifact detail renders active markup as literal text and never executes it", async () => {
  const s = api();
  render(<PhaseDetails snapshot={s} selected="narrative" />);
  fireEvent.click(screen.getByRole("button", { name: "View narrative plan" }));
  const text = await screen.findByLabelText("Escaped artifact text");
  expect(text.textContent).toContain("<script>");
  expect(document.querySelector(".artifact-text script")).toBeNull();
  expect((window as unknown as { UNSAFE?: boolean }).UNSAFE).toBeUndefined();
});

test("formal reports stay labeled caller supplied rather than proof executed by SPOQ", () => {
  const s = api();
  s.artifacts = [
    {
      ...s.artifacts[0],
      kind: "formal",
      metadata: {
        formal_status: "proven",
        validation: { provenance: "caller_supplied_not_reexecuted" },
      },
    },
  ];
  render(<ArtifactPanel snapshot={s} />);
  expect(screen.getByText("Reported proven")).toBeInTheDocument();
  expect(
    screen.getByText(/SPOQ did not re-execute the proof/),
  ).toBeInTheDocument();
});

test("superseded approval is visibly historical when attempt or specification differs", () => {
  const s = api();
  render(
    <DecisionCard
      snapshot={s}
      decision={{
        id: "old",
        attempt_id: "old-review",
        artifact_id: "old-plan",
        artifact_hash: "d".repeat(64),
        source: "user",
        author: "User",
        decision: "approve",
        specification_hash: "old",
      }}
    />,
  );
  expect(screen.getByText("Historical / superseded")).toBeInTheDocument();
});

test("work drill-down keeps Feature and Task DAGs separate and loads actual acceptance metadata", async () => {
  const s = api();
  render(<WorkGraph snapshot={s} />);
  expect(
    screen.getByText(/Strategy revision loops are shown separately/),
  ).toBeInTheDocument();
  expect(screen.getByText("Requires: checkout/api")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open API Task DAG" }));
  expect(screen.getByRole("heading", { name: "API" })).toBeInTheDocument();
  expect(
    screen.getByText("Requires: checkout/api/contract"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Inspect API tests" }));
  expect(
    await screen.findByLabelText("Work acceptance details"),
  ).toHaveTextContent("Actual contract passes");
  fireEvent.click(screen.getByRole("button", { name: "Back to parent DAG" }));
  expect(
    screen.getByRole("button", { name: "Open API Task DAG" }),
  ).toBeInTheDocument();
});

test("work layout respects directed prerequisites regardless of input node order", () => {
  const s = snapshotFixture();
  const children = s.work.nodes.filter((n) => n.parent_id === "checkout");
  const positions = workLayout(children.reverse(), s.work.edges);
  expect(positions.find((n) => n.id === "checkout/ui")!.x).toBeGreaterThan(
    positions.find((n) => n.id === "checkout/api")!.x,
  );
});

test("older artifacts use bounded pagination and remain individually inspectable", async () => {
  const s = api();
  s.run.pagination!.artifacts = { has_more: true, cursor: 5 };
  const previous = globalThis.fetch;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).includes("before=5")
      ? new Response(
          JSON.stringify({
            resource: "artifacts",
            items: [{ ...s.artifacts[0], id: "older-artifact" } as Artifact],
            pagination: { has_more: false, cursor: null },
          }),
          { status: 200 },
        )
      : previous(input),
  );
  render(<ArtifactPanel snapshot={s} />);
  fireEvent.click(screen.getByRole("button", { name: "Load older artifacts" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "View narrative plan" }),
    ).toHaveLength(2),
  );
  expect(
    screen.queryByRole("button", { name: "Load older artifacts" }),
  ).not.toBeInTheDocument();
});

test("late work detail cannot restore old acceptance after snapshot cursor advances", async () => {
  const s = snapshotFixture();
  let resolve!: (response: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const { rerender } = render(<WorkGraph snapshot={s} />);
  fireEvent.click(screen.getByRole("button", { name: "Open API Task DAG" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect API tests" }));
  const next = structuredClone(s);
  next.cursor = 43;
  rerender(<WorkGraph snapshot={next} />);
  await act(async () => {
    resolve(
      new Response(
        JSON.stringify({
          id: "checkout/api/tests",
          title: "API tests",
          kind: "task",
          status: "pending",
          data: { acceptance_criteria: ["OLD_ACCEPTANCE"] },
        }),
        { status: 200 },
      ),
    );
  });
  expect(screen.queryByText(/OLD_ACCEPTANCE/)).not.toBeInTheDocument();
});

test("only latest work inspection can apply within the same scope and cursor", async () => {
  const s = snapshotFixture();
  const responses: Record<string, (response: Response) => void> = {};
  vi.spyOn(globalThis, "fetch").mockImplementation(
    (input) =>
      new Promise<Response>((done) => {
        responses[decodeURIComponent(String(input).split("/").at(-1)!)] = done;
      }),
  );
  render(<WorkGraph snapshot={s} />);
  fireEvent.click(screen.getByRole("button", { name: "Open API Task DAG" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect API contract" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect API tests" }));
  await act(async () => {
    responses["checkout/api/tests"](
      new Response(
        JSON.stringify({
          id: "checkout/api/tests",
          title: "API tests",
          kind: "task",
          status: "pending",
          data: { acceptance_criteria: ["LATEST_ACCEPTANCE"] },
        }),
        { status: 200 },
      ),
    );
  });
  expect(screen.getByLabelText("Work acceptance details")).toHaveTextContent(
    "LATEST_ACCEPTANCE",
  );
  await act(async () => {
    responses["checkout/api/contract"](
      new Response(
        JSON.stringify({
          id: "checkout/api/contract",
          title: "API contract",
          kind: "task",
          status: "completed",
          data: { acceptance_criteria: ["OLD_ACCEPTANCE"] },
        }),
        { status: 200 },
      ),
    );
  });
  expect(screen.getByLabelText("Work acceptance details")).toHaveTextContent(
    "LATEST_ACCEPTANCE",
  );
  expect(screen.queryByText(/OLD_ACCEPTANCE/)).not.toBeInTheDocument();
});
