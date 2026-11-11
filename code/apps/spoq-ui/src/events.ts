import { useEffect, useRef, useState } from "react";
import { getJson, parseSnapshot, runUrl } from "./api";
import type { JsonObject, Snapshot } from "./types";
export interface WorkflowEvent {
  sequence: number;
  kind: string;
  actor?: string;
  created_at?: string;
  payload: JsonObject;
}
export interface EventBatch {
  events: WorkflowEvent[];
  cursor: number;
  has_more: boolean;
  reset: boolean;
}
export function acceptEventBatch(previous: number, batch: EventBatch) {
  if (
    !Number.isSafeInteger(previous) ||
    previous < 0 ||
    !batch ||
    !Array.isArray(batch.events) ||
    !Number.isSafeInteger(batch.cursor) ||
    batch.cursor < 0 ||
    typeof batch.reset !== "boolean" ||
    typeof batch.has_more !== "boolean"
  )
    throw new Error("Invalid event replay contract");
  if (batch.reset)
    return {
      cursor: batch.cursor,
      events: [] as WorkflowEvent[],
      reset: true,
      stale: false,
    };
  if (batch.cursor < previous)
    return {
      cursor: previous,
      events: [] as WorkflowEvent[],
      reset: false,
      stale: true,
    };
  const events: WorkflowEvent[] = [];
  const seen = new Set<number>();
  let last = previous;
  for (const event of batch.events) {
    if (
      !event ||
      !Number.isSafeInteger(event.sequence) ||
      event.sequence < 1 ||
      event.sequence > batch.cursor
    )
      throw new Error("Invalid event identity");
    if (event.sequence <= previous || seen.has(event.sequence)) continue;
    if (event.sequence < last) throw new Error("Events are not ordered");
    events.push(event);
    seen.add(event.sequence);
    last = event.sequence;
  }
  // Global identities can have gaps from other runs. Only the server declares reset.
  return { cursor: batch.cursor, events, reset: false, stale: false };
}
export function acceptSnapshot(
  current: Snapshot | null,
  next: Snapshot,
  minimum = 0,
  reset = false,
) {
  const parsed = parseSnapshot(next);
  if (
    !reset &&
    (parsed.cursor < minimum || (current && parsed.cursor < current.cursor))
  )
    return current;
  return parsed;
}
export function useWorkflowSnapshot(runId: string) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [connection, setConnection] = useState("Connecting to local viewer");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [epoch, setEpoch] = useState(0);
  const action = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let current: Snapshot | null = null;
    let cursor = 0;
    let active = true;
    let busy = false;
    setSnapshot(null);
    setNotice("");
    setError("");
    setLoading(!!runId);
    setConnection(runId ? "Connecting to local viewer" : "No run selected");
    if (!runId) {
      action.current = async () => {};
      return () => abort.abort();
    }
    async function reload(reset = false, minimum = 0) {
      const raw = await getJson<Snapshot>(runUrl(runId), abort.signal);
      if (!active || abort.signal.aborted) return false;
      if (raw.run.run_id !== runId)
        throw new Error("Snapshot belongs to a different run");
      const next = acceptSnapshot(current, raw, minimum, reset);
      if (next === current) return false;
      current = next;
      cursor = next!.cursor;
      setSnapshot(next);
      if (reset) {
        setEpoch((old) => old + 1);
        setNotice(
          "Event cursor reset. History and details were reloaded from committed state.",
        );
      }
      setLoading(false);
      return true;
    }
    async function pulse(force = false) {
      if (busy || !active) return;
      busy = true;
      let drainMore = false;
      try {
        if (!current || force) await reload(false);
        else {
          // Each response is bounded; drain at most ten pages before yielding
          // to the browser, then continue promptly instead of lagging a second/page.
          for (let page = 0; page < 10; page++) {
            const before = cursor;
            const batch = await getJson<EventBatch>(
              runUrl(runId, "events") + "?limit=100&after=" + cursor,
              abort.signal,
            );
            if (!active) return;
            const replay = acceptEventBatch(cursor, batch);
            if (replay.reset) {
              await reload(true);
              drainMore = false;
              break;
            }
            if (replay.events.length) {
              await reload(false, replay.cursor);
              drainMore = false;
              break;
            }
            cursor = replay.cursor;
            drainMore = batch.has_more;
            if (!drainMore || replay.stale) break;
            if (cursor <= before)
              throw new Error(
                "Event replay backlog did not advance its cursor",
              );
          }
        }
        if (active) {
          setConnection("Connected to local viewer");
          setError("");
        }
      } catch (e) {
        drainMore = false;
        if (active && !abort.signal.aborted) {
          setConnection("Disconnected · reconnecting");
          setError((e as Error).message);
          setLoading(false);
        }
      } finally {
        busy = false;
        if (active) {
          if (timer) clearTimeout(timer);
          timer = setTimeout(() => void pulse(), drainMore ? 0 : 1000);
        }
      }
    }
    action.current = () => pulse(true);
    void pulse();
    return () => {
      active = false;
      abort.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId]);
  return {
    snapshot,
    loading,
    connection,
    error,
    notice,
    epoch,
    refresh: () => action.current(),
  };
}
