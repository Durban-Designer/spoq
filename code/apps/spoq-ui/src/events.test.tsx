import {
  act,
  renderHook,
  waitFor,
  render,
  screen,
  fireEvent,
} from "@testing-library/react";
import { vi } from "vitest";
import {
  acceptEventBatch,
  acceptSnapshot,
  useWorkflowSnapshot,
} from "./events";
import { snapshotFixture } from "./fixtures.test-support";
import { WorkGraph } from "./WorkGraph";
import type { EventBatch } from "./events";
vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right" },
  MarkerType: { ArrowClosed: "closed" },
  Background: () => null,
  Controls: () => null,
  ReactFlow: () => <div />,
}));
const event = (sequence: number) => ({
  sequence,
  kind: "workflow.completed",
  payload: { outcome: "pass" },
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
test("replay applies identities idempotently and accepts gaps from unrelated global events", () => {
  const batch: EventBatch = {
    events: [event(45), event(45), event(51)],
    cursor: 55,
    has_more: false,
    reset: false,
  };
  expect(acceptEventBatch(42, batch).events.map((e) => e.sequence)).toEqual([
    45, 51,
  ]);
  expect(acceptEventBatch(55, batch).events).toEqual([]);
  expect(acceptEventBatch(60, batch)).toMatchObject({
    cursor: 60,
    stale: true,
  });
});
test("only authoritative reset permits an older snapshot to replace newer state", () => {
  const previous = snapshotFixture();
  const next = structuredClone(previous);
  next.cursor = 30;
  expect(acceptSnapshot(previous, next)).toBe(previous);
  expect(acceptSnapshot(previous, next, 0, true)).toBe(next);
  expect(
    acceptEventBatch(42, {
      events: [],
      cursor: 30,
      has_more: false,
      reset: true,
    }).reset,
  ).toBe(true);
});
test("out-of-order or impossible event identities cannot advance the projection", () => {
  expect(() =>
    acceptEventBatch(1, {
      events: [event(4), event(3)],
      cursor: 4,
      has_more: false,
      reset: false,
    }),
  ).toThrow("ordered");
  expect(() =>
    acceptEventBatch(1, {
      events: [event(9)],
      cursor: 4,
      has_more: false,
      reset: false,
    }),
  ).toThrow("identity");
});
test("a snapshot predating an event batch is discarded rather than manufacturing pass state", () => {
  const previous = snapshotFixture();
  const next = structuredClone(previous);
  next.cursor = 43;
  next.run.status = "passed";
  expect(acceptSnapshot(previous, next, 44)).toBe(previous);
});

test("hook refreshes from snapshots, preserves explicit human wait, and recovers after disconnect/reset", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const initial = snapshotFixture();
  let mode = "initial";
  let snapshots = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    if (String(url).includes("/events?")) {
      if (mode === "offline") throw new Error("server disconnected");
      return new Response(
        JSON.stringify(
          mode === "reset"
            ? { events: [], cursor: 10, has_more: false, reset: true }
            : {
                events: [event(45)],
                cursor: 45,
                has_more: false,
                reset: false,
              },
        ),
        { status: 200 },
      );
    }
    snapshots++;
    const next = structuredClone(initial);
    if (mode === "reset") next.cursor = 10;
    else if (mode === "online") {
      next.cursor = 46;
      next.phases.find((p) => p.id === "review")!.status = "passed";
      next.run.status = "running";
    }
    return new Response(JSON.stringify(next), { status: 200 });
  });
  const hook = renderHook(() => useWorkflowSnapshot(initial.run.run_id));
  await waitFor(() => expect(hook.result.current.snapshot?.cursor).toBe(42));
  mode = "offline";
  await act(async () => vi.advanceTimersByTimeAsync(1100));
  expect(hook.result.current.connection).toContain("Disconnected");
  expect(hook.result.current.snapshot?.run.status).toBe("waiting_human");
  mode = "online";
  await act(async () => vi.advanceTimersByTimeAsync(1100));
  expect(hook.result.current.snapshot?.cursor).toBe(46);
  expect(
    hook.result.current.snapshot?.phases.find((p) => p.id === "review")?.status,
  ).toBe("passed");
  mode = "reset";
  await act(async () => vi.advanceTimersByTimeAsync(1100));
  expect(hook.result.current.snapshot?.cursor).toBe(10);
  expect(hook.result.current.notice).toContain("cursor reset");
  expect(hook.result.current.epoch).toBe(1);
  expect(snapshots).toBeGreaterThanOrEqual(3);
  hook.unmount();
});

test("paged work outside initial snapshot is invalidated and reloaded after committed updates", async () => {
  const initial = snapshotFixture();
  initial.work.pagination = { has_more: true, cursor: "next-page" };
  let completed = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () =>
      new Response(
        JSON.stringify({
          scope_id: "checkout",
          nodes: [
            {
              id: "checkout/api/late",
              kind: "task",
              parent_id: "checkout/api",
              title: "Late task",
              status: completed ? "completed" : "pending",
            },
          ],
          edges: [],
          pagination: { has_more: false, cursor: null },
        }),
        { status: 200 },
      ),
  );
  const { rerender } = render(<WorkGraph snapshot={initial} />);
  fireEvent.click(screen.getByRole("button", { name: "Open API Task DAG" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Load more work nodes and edges" }),
  );
  await waitFor(() =>
    expect(screen.getByText("Late task").closest("li")).toHaveTextContent(
      "Pending",
    ),
  );
  const next = structuredClone(initial);
  next.cursor = 43;
  completed = true;
  rerender(<WorkGraph snapshot={next} />);
  expect(screen.queryByText("Late task")).not.toBeInTheDocument();
  expect(
    await screen.findByText(/Additional work pages were cleared/),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Load more work nodes and edges" }),
  );
  await waitFor(() =>
    expect(screen.getByText("Late task").closest("li")).toHaveTextContent(
      "Completed",
    ),
  );
});

test("bounded replay drains unrelated backlog promptly before rendering a relevant update", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const initial = snapshotFixture();
  let snapshotReads = 0;
  const cursors: number[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/events?")) {
      const after = Number(
        new URL(url, "http://local").searchParams.get("after"),
      );
      cursors.push(after);
      return new Response(
        JSON.stringify(
          after < 342
            ? { events: [], cursor: after + 100, has_more: true, reset: false }
            : {
                events: [event(350)],
                cursor: 350,
                has_more: false,
                reset: false,
              },
        ),
        { status: 200 },
      );
    }
    const next = structuredClone(initial);
    if (snapshotReads++) {
      next.cursor = 351;
      next.run.status = "running";
    }
    return new Response(JSON.stringify(next), { status: 200 });
  });
  const hook = renderHook(() => useWorkflowSnapshot(initial.run.run_id));
  await waitFor(() => expect(hook.result.current.snapshot?.cursor).toBe(42));
  await act(async () => vi.advanceTimersByTimeAsync(1100));
  expect(cursors).toEqual([42, 142, 242, 342]);
  expect(hook.result.current.snapshot?.cursor).toBe(351);
  expect(snapshotReads).toBe(2);
  hook.unmount();
});

test("late previous-run snapshot cannot replace the selected run", async () => {
  const initial = snapshotFixture();
  let resolveOld!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input).includes("/old-run"))
      return new Promise<Response>((resolve) => {
        resolveOld = resolve;
      });
    const current = structuredClone(initial);
    current.run.run_id = "new-run";
    current.cursor = 20;
    return new Response(JSON.stringify(current), { status: 200 });
  });
  const hook = renderHook(({ run }) => useWorkflowSnapshot(run), {
    initialProps: { run: "old-run" },
  });
  hook.rerender({ run: "new-run" });
  await waitFor(() =>
    expect(hook.result.current.snapshot?.run.run_id).toBe("new-run"),
  );
  const old = structuredClone(initial);
  old.run.run_id = "old-run";
  old.cursor = 999;
  await act(async () => {
    resolveOld(new Response(JSON.stringify(old), { status: 200 }));
  });
  expect(hook.result.current.snapshot?.run.run_id).toBe("new-run");
  expect(hook.result.current.snapshot?.cursor).toBe(20);
  hook.unmount();
});

test("without a selected run the hook does not invent a successful connection", () => {
  const request = vi.spyOn(globalThis, "fetch");
  const hook = renderHook(() => useWorkflowSnapshot(""));
  expect(hook.result.current.connection).toBe("No run selected");
  expect(request).not.toHaveBeenCalled();
  hook.unmount();
});
