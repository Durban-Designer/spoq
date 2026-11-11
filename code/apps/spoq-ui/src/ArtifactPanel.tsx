import { useEffect, useState } from "react";
import { getJson, runUrl } from "./api";
import { useHistoryPage } from "./useHistoryPage";
import type { Artifact, Decision, Snapshot } from "./types";
export function FormalProvenance({ artifact }: { artifact: Artifact }) {
  const status = artifact.metadata?.formal_status;
  return artifact.kind === "formal" ? (
    <p className="notice provenance">
      <strong>
        {typeof status === "string"
          ? `Reported ${status}`
          : "Formal result not recorded"}
      </strong>
      <br />
      Verifier reports are supplied by the caller. SPOQ did not re-execute the
      proof.
    </p>
  ) : null;
}
export function ArtifactText({
  runId,
  artifact,
  onClose,
}: {
  runId: string;
  artifact: Artifact;
  onClose?: () => void;
}) {
  const [detail, setDetail] = useState<Artifact | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setDetail(null);
    setError("");
    void getJson<Artifact>(
      runUrl(runId, "artifacts", artifact.id),
      abort.signal,
    )
      .then((a) => {
        if (abort.signal.aborted) return;
        if (a.render_as !== "text" || typeof a.content !== "string")
          throw new Error("Unsupported artifact rendering contract");
        setDetail(a);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [runId, artifact.id]);
  return (
    <section className="artifact-text" aria-label="Registered artifact content">
      <div className="section-title">
        <h3>{artifact.kind} · registered text</h3>
        {onClose && <button onClick={onClose}>Close artifact</button>}
      </div>
      <p>
        <code>{artifact.id}</code>
      </p>
      <FormalProvenance artifact={detail ?? artifact} />
      {error ? (
        <p role="alert" className="notice danger">
          {error}
        </p>
      ) : detail ? (
        <>
          <dl className="facts">
            <dt>Author / source</dt>
            <dd>
              {detail.author ?? "Not recorded"} · {detail.source}
            </dd>
            <dt>SHA-256</dt>
            <dd>
              <code>{detail.sha256}</code>
            </dd>
          </dl>
          <pre tabIndex={0} aria-label="Escaped artifact text">
            {detail.content}
          </pre>
          <details>
            <summary>Artifact metadata</summary>
            <pre tabIndex={0}>
              {JSON.stringify(detail.metadata ?? {}, null, 2)}
            </pre>
          </details>
        </>
      ) : (
        <p role="status">Loading registered artifact…</p>
      )}
    </section>
  );
}
export function DecisionCard({
  decision,
  snapshot,
}: {
  decision: Decision;
  snapshot: Snapshot;
}) {
  const phase = snapshot.phases.find(
    (p) => p.attempt_id === decision.attempt_id,
  );
  const current =
    !!phase &&
    ["waiting_human", "passed"].includes(phase.status) &&
    (!decision.specification_hash ||
      decision.specification_hash ===
        snapshot.run.current_specification_hash) &&
    (!decision.definition_hash ||
      decision.definition_hash === snapshot.run.definition_hash);
  return (
    <article className="record-card">
      <div className="section-title">
        <strong>
          {decision.decision === "approve" ? "Approval" : "Rejection"} ·{" "}
          {decision.author}
        </strong>
        <span className={current ? "record-label" : "record-label historical"}>
          {current ? "Recorded for current attempt" : "Historical / superseded"}
        </span>
      </div>
      <p>
        Source: {decision.source} · Artifact revision{" "}
        <code>{decision.artifact_hash}</code>
      </p>
      {decision.reason && <p>{decision.reason}</p>}
      <small>
        Attempt <code>{decision.attempt_id}</code>
      </small>
    </article>
  );
}
export function ArtifactPanel({ snapshot }: { snapshot: Snapshot }) {
  const run = snapshot.run.run_id;
  const artifacts = useHistoryPage<Artifact>(
    run,
    "artifacts",
    snapshot.artifacts,
    snapshot.run.pagination?.artifacts,
    snapshot.cursor,
  );
  const decisions = useHistoryPage<Decision>(
    run,
    "decisions",
    snapshot.decisions,
    snapshot.run.pagination?.decisions,
    snapshot.cursor,
  );
  const [selected, setSelected] = useState<Artifact | null>(null);
  useEffect(() => setSelected(null), [run]);
  return (
    <div className="records-panel">
      <section>
        <div className="section-title">
          <h2>Registered artifacts</h2>
          <span className="muted">Exact revisions, escaped text</span>
        </div>
        {artifacts.items.length ? (
          <div className="record-list">
            {artifacts.items.map((a) => (
              <article key={a.id} className="record-card">
                <div className="section-title">
                  <strong>{a.kind.replaceAll("_", " ")}</strong>
                  <button onClick={() => setSelected(a)}>
                    View {a.kind.replaceAll("_", " ")}
                  </button>
                </div>
                <p>
                  <code>{a.id}</code>
                </p>
                <p className="muted">
                  {a.author ?? "Author not recorded"} · {a.source}
                </p>
                <FormalProvenance artifact={a} />
                <small>
                  SHA-256 <code>{a.sha256}</code>
                </small>
              </article>
            ))}
          </div>
        ) : (
          <p>No artifacts have been recorded.</p>
        )}
        {artifacts.pagination.has_more && (
          <button
            disabled={artifacts.loading}
            onClick={() => void artifacts.loadMore()}
          >
            Load older artifacts
          </button>
        )}
        {artifacts.notice && (
          <p className="notice warning" role="status">
            {artifacts.notice}
          </p>
        )}
        {artifacts.error && <p role="alert">{artifacts.error}</p>}
      </section>
      {selected && (
        <ArtifactText
          runId={run}
          artifact={selected}
          onClose={() => setSelected(null)}
        />
      )}
      <section>
        <h2>Human decisions</h2>
        <p className="muted">
          Decisions apply to the reviewed artifact hash. Historical approvals do
          not authorize a revised plan.
        </p>
        {decisions.items.length ? (
          decisions.items.map((d) => (
            <DecisionCard key={d.id} decision={d} snapshot={snapshot} />
          ))
        ) : (
          <p>No human response is recorded.</p>
        )}
        {decisions.pagination.has_more && (
          <button
            disabled={decisions.loading}
            onClick={() => void decisions.loadMore()}
          >
            Load older decisions
          </button>
        )}
        {decisions.notice && (
          <p className="notice warning" role="status">
            {decisions.notice}
          </p>
        )}
        {decisions.error && <p role="alert">{decisions.error}</p>}
      </section>
    </div>
  );
}
