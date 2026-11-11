import { useEffect, useRef, useState } from "react";
import { getJson, runUrl } from "./api";
import type { HistoryPage, Pagination } from "./types";

export function mergeById<T extends { id: string }>(...groups: T[][]): T[] {
  return [...new Map(groups.flat().map((item) => [item.id, item])).values()];
}

type RecordWithId = { id: string; status?: string };
interface HistoryState<T> {
  identity: string;
  items: T[];
  head: T[];
  headBefore: Pagination["cursor"];
  headHasMore: boolean;
  pagination: Pagination;
  snapshotCursor?: number;
  generation: number;
  loading: boolean;
  error: string;
  notice: string;
}

function mutableOutsideHead<T extends RecordWithId>(
  resource: string,
  records: T[],
  headIds: Set<string>,
): boolean {
  if (resource !== "attempts" && resource !== "participants") return false;
  return records.some(
    (record) =>
      !headIds.has(record.id) &&
      (resource === "participants" ||
        !["passed", "failed", "blocked", "skipped"].includes(
          record.status ?? "",
        )),
  );
}

/** Retain contiguous loaded history; explicitly rebase when its continuity is unknown. */
export function useHistoryPage<T extends RecordWithId>(
  runId: string,
  resource: string,
  initial: T[],
  first: Pagination = { has_more: false, cursor: null },
  snapshotCursor?: number,
) {
  const identity = JSON.stringify([runId, resource]);
  const fresh = (generation = 0): HistoryState<T> => ({
    identity,
    items: initial,
    head: initial,
    headBefore: first.cursor,
    headHasMore: first.has_more,
    pagination: first,
    snapshotCursor,
    generation,
    loading: false,
    error: "",
    notice: "",
  });
  const [state, setState] = useState<HistoryState<T>>(fresh);
  const request = useRef<{
    identity: string;
    generation: number;
    abort: AbortController;
  } | null>(null);
  const activeIdentity = useRef(identity);
  activeIdentity.current = identity;

  useEffect(() => () => request.current?.abort.abort(), []);
  useEffect(() => {
    setState((old) => {
      if (old.identity !== identity) return fresh(old.generation + 1);
      if (
        old.head === initial &&
        old.snapshotCursor === snapshotCursor &&
        old.headBefore === first.cursor &&
        old.headHasMore === first.has_more
      )
        return old;
      if (!old.items.length) return fresh(old.generation);
      const ids = new Set(initial.map((item) => item.id));
      const moved =
        old.head !== initial || old.snapshotCursor !== snapshotCursor;
      const reset =
        old.snapshotCursor !== undefined &&
        snapshotCursor !== undefined &&
        snapshotCursor < old.snapshotCursor;
      const disjoint =
        old.items.length > 0 &&
        initial.length > 0 &&
        !old.items.some((item) => ids.has(item.id));
      const changedMutable =
        moved && mutableOutsideHead(resource, old.items, ids);
      const removed =
        !first.has_more && old.items.some((item) => !ids.has(item.id));
      if (reset || disjoint || changedMutable || removed) {
        return {
          ...fresh(old.generation + 1),
          notice: changedMutable
            ? "Earlier loaded records may have changed. Reload older history for current state."
            : "History was refreshed beyond the loaded window. Reload older records to continue.",
        };
      }
      // A rolling latest page drops its oldest row. Preserve that row and all
      // previously loaded pages, keeping the cursor at the oldest loaded boundary.
      return {
        ...old,
        items: mergeById(old.items, initial),
        head: initial,
        headBefore: first.cursor,
        headHasMore: first.has_more,
        snapshotCursor,
        pagination: first.has_more ? old.pagination : first,
      };
    });
  }, [identity, initial, first.cursor, first.has_more, snapshotCursor]);

  // Never render a previous run's records while its effect is being reconciled.
  const current =
    state.identity === identity ? state : fresh(state.generation + 1);
  async function loadMore() {
    if (!current.pagination.has_more || current.pagination.cursor === null)
      return;
    if (
      request.current?.identity === identity &&
      request.current.generation === current.generation
    )
      return;
    request.current?.abort.abort();
    const abort = new AbortController();
    const pending = { identity, generation: current.generation, abort };
    request.current = pending;
    setState((old) => ({ ...old, loading: true, error: "" }));
    const applicable = (old: HistoryState<T>) =>
      old.identity === identity && old.generation === pending.generation;
    try {
      const page = await getJson<HistoryPage<T>>(
        runUrl(runId, resource) +
          "?limit=100&before=" +
          encodeURIComponent(current.pagination.cursor),
        abort.signal,
      );
      if (abort.signal.aborted || activeIdentity.current !== identity) return;
      setState((old) =>
        applicable(old)
          ? {
              ...old,
              items: mergeById(page.items, old.items),
              pagination: page.pagination,
              notice: "",
              error: "",
            }
          : old,
      );
    } catch (error) {
      if (!abort.signal.aborted) {
        setState((old) =>
          applicable(old) ? { ...old, error: (error as Error).message } : old,
        );
      }
    } finally {
      setState((old) => (applicable(old) ? { ...old, loading: false } : old));
      if (request.current === pending) request.current = null;
    }
  }
  return {
    items: current.items,
    pagination: current.pagination,
    loading: current.loading,
    error: current.error,
    notice: current.notice,
    reset: !!current.notice,
    loadMore,
  };
}
