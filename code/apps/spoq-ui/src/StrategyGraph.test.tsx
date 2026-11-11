import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { vi } from "vitest";
import { snapshotFixture } from "./fixtures.test-support";
import { StrategyGraph, strategyLayout } from "./StrategyGraph";
import { App } from "./App";
const captured = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));
vi.mock("@xyflow/react", () => ({
  Position: { Top: "top", Bottom: "bottom" },
  MarkerType: { ArrowClosed: "closed" },
  Background: () => null,
  BaseEdge: () => null,
  EdgeLabelRenderer: () => null,
  Controls: () => null,
  ReactFlow: (props: Record<string, unknown>) => {
    captured.props = props;
    return (
      <div data-testid="flow">
        {(
          props.nodes as { id: string; data: { label: React.ReactNode } }[]
        ).map((node) => (
          <button
            key={node.id}
            onClick={() => (props.onNodeClick as Function)({}, node)}
          >
            {node.data.label}
          </button>
        ))}
      </div>
    );
  },
}));

test("new snapshots with unchanged topology preserve graph viewport", () => {
  const snapshot = snapshotFixture();
  const select = vi.fn();
  const instance = { setCenter: vi.fn() };
  const { rerender } = render(
    <StrategyGraph snapshot={snapshot} selected="review" onSelect={select} />,
  );
  act(() => {
    (captured.props.onInit as Function)(instance);
  });
  expect(instance.setCenter).toHaveBeenCalledTimes(1);
  const next = structuredClone(snapshot);
  next.cursor = 43;
  rerender(
    <StrategyGraph snapshot={next} selected="review" onSelect={select} />,
  );
  expect(instance.setCenter).toHaveBeenCalledTimes(1);
  rerender(
    <StrategyGraph snapshot={next} selected="narrative" onSelect={select} />,
  );
  expect(instance.setCenter).toHaveBeenCalledTimes(2);
});

afterEach(() => vi.restoreAllMocks());

test.each(["classic", "piqard"] as const)(
  "renders %s statuses and loop edges with editing disabled",
  (strategy) => {
    const s = snapshotFixture(strategy);
    const select = vi.fn();
    render(
      <StrategyGraph
        snapshot={s}
        selected={s.phases[0].id}
        onSelect={select}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Read-only strategy graph" }),
    ).toBeInTheDocument();
    expect(captured.props.nodesDraggable).toBe(false);
    expect(captured.props.nodesConnectable).toBe(false);
    expect(captured.props.edgesReconnectable).toBe(false);
    expect(captured.props.deleteKeyCode).toBeNull();
    const edges = captured.props.edges as {
      label: string;
      style: { strokeDasharray?: string };
    }[];
    expect(
      edges.some(
        (e) => e.label === "Reject / rework" && e.style.strokeDasharray,
      ),
    ).toBe(true);
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(select).toHaveBeenCalledWith(s.phases[0].id);
  },
);

test("parallel layout is deterministic and excludes rework edges from topological levels", () => {
  const s = snapshotFixture();
  const layout = strategyLayout(s);
  expect(layout).toEqual(strategyLayout(s));
  const at = (id: string) => layout.find((p) => p.id === id)!;
  expect(at("diagram").y).toBe(at("algorithm").y);
  expect(at("diagram").x).not.toBe(at("algorithm").x);
  expect(at("narrative").y).toBeLessThan(at("review").y);
});

test("legacy runs do not invent a strategy graph", () => {
  const s = snapshotFixture();
  s.definition = {};
  s.phases = [];
  render(<StrategyGraph snapshot={s} selected="" onSelect={() => {}} />);
  expect(screen.getByText("Strategy not recorded")).toBeInTheDocument();
  expect(screen.queryByTestId("flow")).not.toBeInTheDocument();
});

test("App reads committed route rationale and explicit status from actual API envelopes", async () => {
  const s = snapshotFixture();
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).startsWith("/api/health")
            ? { project_root: "/example/project" }
            : String(url).startsWith("/api/runs?")
              ? {
                  runs: [s.run],
                  cursor: s.cursor,
                  pagination: { has_more: false, cursor: null },
                }
              : s,
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
  );
  render(<App />);
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Strategy graph" }),
    ).toBeInTheDocument(),
  );
  expect(screen.getByText(s.routing.reasons![0])).toBeInTheDocument();
  expect(screen.getByText(/Snapshot cursor/)).toHaveTextContent("42");
  expect(
    screen.getByRole("status", { name: "Viewer connection" }),
  ).toHaveTextContent("Connected");
  expect(
    screen.getByText("Duration and cost telemetry are not recorded."),
  ).toBeInTheDocument();
});

test("read failure stays visible without manufacturing an empty successful run", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "Database schema unsupported" }), {
      status: 400,
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Database schema unsupported",
  );
  expect(
    screen.queryByRole("heading", { name: "Strategy graph" }),
  ).not.toBeInTheDocument();
});
