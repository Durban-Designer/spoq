import type { Snapshot } from "./types";
export function runUrl(run: string, resource?: string, id?: string) {
  return (
    "/api/runs/" +
    encodeURIComponent(run) +
    (resource ? "/" + resource : "") +
    (id ? "/" + encodeURIComponent(id) : "")
  );
}
export async function getJson<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) {
    let reason = "";
    try {
      reason = (await response.json()).error ?? "";
    } catch {}
    throw new Error(reason || `Read request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export function parseSnapshot(value: Snapshot): Snapshot {
  if (
    value?.format !== "spoq-workflow-view-1" ||
    !Number.isSafeInteger(value.cursor) ||
    value.cursor < 0 ||
    typeof value.run?.run_id !== "string" ||
    ![
      value.phases,
      value.attempts,
      value.artifacts,
      value.decisions,
      value.participants,
      value.blockers,
    ].every(Array.isArray) ||
    !Array.isArray(value.work?.nodes) ||
    !Array.isArray(value.work?.edges)
  )
    throw new Error("Unsupported viewer response. Update SPOQ and reload.");
  return value;
}
