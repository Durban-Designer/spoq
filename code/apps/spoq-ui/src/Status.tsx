export function statusLabel(status?: string) {
  if (status === "waiting_human") return "Waiting for human";
  return (status || "unknown")
    .replaceAll("_", " ")
    .replace(/^./, (c) => c.toUpperCase());
}
export function Status({ status }: { status?: string }) {
  const safe = /^[a-z_]+$/.test(status ?? "") ? status : "unknown";
  return (
    <span className={"status status-" + safe}>
      <span aria-hidden="true" className="status-dot" />
      {statusLabel(status)}
    </span>
  );
}
export function phaseLabel(id: string) {
  return (
    (
      {
        "plan-validation": "Planning gate",
        "implementation-validation": "Implementation gate",
        "design-join": "Design join",
        review: "Human review",
        discover: "Discovery",
        narrative: "Narrative plan",
        execute: "Execute tasks",
        erd: "ERD",
        formal: "Formal methods",
      } as Record<string, string>
    )[id] ?? id.replaceAll(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}
