import { act, renderHook, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import * as api from "./api";
import { useHistoryPage } from "./useHistoryPage";
import type { HistoryPage, Pagination } from "./types";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getJson: vi.fn(),
}));
const request = vi.mocked(api.getJson);
interface Row {
  id: string;
  status: string;
  cursor: number;
}
function rows(from: number, to: number, status = "passed"): Row[] {
  return Array.from({ length: to - from + 1 }, (_, i) => ({
    id: `record-${from + i}`,
    cursor: from + i,
    status,
  }));
}
function page(
  items: Row[],
  cursor: number | null,
  more = cursor !== null,
): HistoryPage<Row> {
  return {
    resource: "attempts",
    items,
    pagination: { has_more: more, cursor },
  };
}
function props(initial = rows(901, 1000)) {
  return {
    run: "run",
    resource: "attempts",
    initial,
    first: { has_more: true, cursor: 901 } as Pagination,
    cursor: 1000,
  };
}
function useTest(p: ReturnType<typeof props>) {
  return useHistoryPage(p.run, p.resource, p.initial, p.first, p.cursor);
}
beforeEach(() => request.mockReset());

it("adopts the older cursor when an initially empty run receives more than one page", async () => {
  const empty: ReturnType<typeof props> = {
    ...props([]),
    cursor: 0,
    first: { has_more: false, cursor: null },
  };
  const { result, rerender } = renderHook(useTest, { initialProps: empty });
  rerender({
    ...props(rows(101, 200)),
    cursor: 200,
    first: { has_more: true, cursor: 101 },
  });
  await waitFor(() => expect(result.current.pagination.has_more).toBe(true));
  expect(result.current.pagination.cursor).toBe(101);
  request.mockResolvedValueOnce(page(rows(1, 100), null));
  await act(async () => result.current.loadMore());
  expect(result.current.items).toEqual(rows(1, 200));
});

it("retains the oldest latest-page row when live history rolls forward", async () => {
  request.mockResolvedValueOnce(page(rows(801, 900), 801));
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  await act(async () => result.current.loadMore());
  expect(result.current.items).toHaveLength(200);
  rerender({
    ...props(rows(902, 1001)),
    cursor: 1001,
    first: { has_more: true, cursor: 902 },
  });
  await waitFor(() => expect(result.current.items).toHaveLength(201));
  expect(result.current.items.map((r) => r.cursor)).toEqual(
    rows(801, 1001).map((r) => r.cursor),
  );
  expect(new Set(result.current.items.map((r) => r.id)).size).toBe(201);
  expect(result.current.pagination.cursor).toBe(801);
  expect(result.current.notice).toBe("");
});

it("updates overlapping records while preserving immutable older loaded pages", async () => {
  request.mockResolvedValueOnce(page(rows(801, 900), 801));
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  await act(async () => result.current.loadMore());
  const latest = rows(901, 1000);
  latest.at(-1)!.status = "failed";
  rerender({ ...props(latest), cursor: 1001 });
  await waitFor(() =>
    expect(result.current.items.at(-1)!.status).toBe("failed"),
  );
  expect(result.current.items).toHaveLength(200);
  expect(result.current.pagination.cursor).toBe(801);
});

it("rebases a disjoint refreshed page with an explicit notice and a usable older cursor", async () => {
  request.mockResolvedValueOnce(page(rows(801, 900), 801));
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  await act(async () => result.current.loadMore());
  rerender({
    ...props(rows(1201, 1300)),
    cursor: 1300,
    first: { has_more: true, cursor: 1201 },
  });
  await waitFor(() => expect(result.current.reset).toBe(true));
  expect(result.current.items.map((r) => r.cursor)).toEqual(
    rows(1201, 1300).map((r) => r.cursor),
  );
  expect(result.current.notice).toMatch(/Reload older/);
  request.mockResolvedValueOnce(page(rows(1101, 1200), 1101));
  await act(async () => result.current.loadMore());
  expect(String(request.mock.calls.at(-1)![0])).toContain("before=1201");
  expect(result.current.items.map((r) => r.cursor)).toEqual(
    rows(1101, 1300).map((r) => r.cursor),
  );
  expect(result.current.notice).toBe("");
});

it("does not keep an old mutable attempt whose current state is outside the latest page", async () => {
  const initial = rows(901, 1000);
  initial[0].status = "running";
  const { result, rerender } = renderHook(useTest, {
    initialProps: props(initial),
  });
  rerender({
    ...props(rows(902, 1001)),
    cursor: 1001,
    first: { has_more: true, cursor: 902 },
  });
  await waitFor(() =>
    expect(result.current.notice).toMatch(/may have changed/),
  );
  expect(result.current.items.some((r) => r.id === "record-901")).toBe(false);
  request.mockResolvedValueOnce(page(rows(802, 901), 802));
  await act(async () => result.current.loadMore());
  expect(result.current.items.find((r) => r.id === "record-901")?.status).toBe(
    "passed",
  );
});

it("rebases older participant pages because role and heartbeat records can change", async () => {
  request.mockResolvedValueOnce(page(rows(801, 900), 801));
  const initialProps = { ...props(), resource: "participants" };
  const { result, rerender } = renderHook(useTest, { initialProps });
  await act(async () => result.current.loadMore());
  rerender({ ...initialProps, initial: rows(901, 1000), cursor: 1001 });
  await waitFor(() =>
    expect(result.current.notice).toMatch(/may have changed/),
  );
  expect(result.current.items).toHaveLength(100);
});

it("ignores a late page from before a rebase even when the mocked transport ignores abort", async () => {
  let resolveOld!: (value: HistoryPage<Row>) => void;
  request.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  let oldRequest!: Promise<void>;
  act(() => {
    oldRequest = result.current.loadMore();
  });
  rerender({
    ...props(rows(2001, 2100)),
    cursor: 2100,
    first: { has_more: true, cursor: 2001 },
  });
  await waitFor(() => expect(result.current.reset).toBe(true));
  request.mockResolvedValueOnce(page(rows(1901, 2000), 1901));
  await act(async () => result.current.loadMore());
  await act(async () => {
    resolveOld(page(rows(801, 900), 801));
    await oldRequest;
  });
  expect(result.current.items.map((r) => r.cursor)).toEqual(
    rows(1901, 2100).map((r) => r.cursor),
  );
  expect(result.current.pagination.cursor).toBe(1901);
});

it("never leaks another run's records or a late in-flight response", async () => {
  let resolveOld!: (value: HistoryPage<Row>) => void;
  request.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  let oldRequest!: Promise<void>;
  act(() => {
    oldRequest = result.current.loadMore();
  });
  rerender({
    run: "second",
    resource: "artifacts",
    initial: rows(1, 3),
    cursor: 3,
    first: { has_more: false, cursor: null },
  });
  await waitFor(() => expect(result.current.items).toEqual(rows(1, 3)));
  await act(async () => {
    resolveOld(page(rows(801, 900), 801));
    await oldRequest;
  });
  expect(result.current.items).toEqual(rows(1, 3));
  expect(result.current.loading).toBe(false);
  expect(result.current.error).toBe("");
});

it("signals a cursor rollback rather than keeping rows from the replaced history", async () => {
  request.mockResolvedValueOnce(page(rows(801, 900), 801));
  const { result, rerender } = renderHook(useTest, { initialProps: props() });
  await act(async () => result.current.loadMore());
  rerender({ ...props(), cursor: 999 });
  await waitFor(() => expect(result.current.reset).toBe(true));
  expect(result.current.items).toHaveLength(100);
  expect(result.current.pagination.cursor).toBe(901);
});

it("keeps records on a read error, permits retry, and prevents duplicate concurrent fetches", async () => {
  request.mockRejectedValueOnce(new Error("Viewer offline"));
  const { result } = renderHook(useTest, { initialProps: props() });
  await act(async () => result.current.loadMore());
  expect(result.current.error).toBe("Viewer offline");
  expect(result.current.items).toHaveLength(100);
  request.mockResolvedValueOnce(page(rows(801, 900), null));
  await act(async () =>
    Promise.all([result.current.loadMore(), result.current.loadMore()]),
  );
  expect(request).toHaveBeenCalledTimes(2);
  expect(result.current.items).toHaveLength(200);
  expect(result.current.error).toBe("");
  expect(result.current.pagination.has_more).toBe(false);
});
