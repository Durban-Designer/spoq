import { useEffect, useState } from "react";
import { getJson, runUrl } from "./api";
import { ArtifactText, DecisionCard, FormalProvenance } from "./ArtifactPanel";
import { phaseLabel, Status } from "./Status";
import type { Artifact, Attempt, JsonObject, Snapshot } from "./types";

export function CheckObservation({ value }: { value: unknown }) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return <li>Malformed recorded check</li>;
  const check = value as JsonObject;
  const kind =
    typeof check.check_type === "string" ? check.check_type : "command";
  const command =
    typeof check.command === "string"
      ? check.command
      : JSON.stringify(check.command ?? "Command not recorded");
  const result =
    kind === "command"
      ? `Exit ${typeof check.exit_code === "number" ? check.exit_code : "not recorded"}`
      : check.passed === true
        ? "Passed"
        : check.passed === false
          ? "Failed"
          : "Result not recorded";
  return (
    <li>
      <code>
        {kind === "command"
          ? command
          : String(check.name ?? "Observation name not recorded")}
      </code>
      <span>
        {kind} · {result}
      </span>
      <small>
        Source: {String(check.source ?? "Not recorded")} ·{" "}
        {check.observed === true ? "Observed" : "Observation not recorded"} ·{" "}
        {check.required === false
          ? "Optional"
          : check.required === true
            ? "Required"
            : "Required (default)"}
      </small>
    </li>
  );
}

export function AttemptEvidence({
  runId,
  attempt,
}: {
  runId: string;
  attempt: Attempt;
}) {
  const [detail, setDetail] = useState<Attempt | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setDetail(null);
    setError("");
    void getJson<Attempt>(runUrl(runId, "attempts", attempt.id), abort.signal)
      .then((value) => {
        if (abort.signal.aborted) return;
        if (
          value.id !== attempt.id ||
          !value.evidence ||
          typeof value.evidence !== "object"
        )
          throw new Error("Unsupported attempt evidence contract");
        setDetail(value);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [runId, attempt.id, attempt.status, attempt.updated_at]);
  const evidence = detail?.evidence;
  const reviewer = evidence?.reviewer as JsonObject | undefined;
  return (
    <section className="attempt-evidence" aria-label="Attempt evidence">
      <h3>Attempt {attempt.number} evidence</h3>
      {error ? (
        <p role="alert">{error}</p>
      ) : !detail ? (
        <p role="status">Loading recorded evidence…</p>
      ) : (
        <>
          <dl className="facts">
            <dt>Owner</dt>
            <dd>{detail.owner ?? "Not recorded"}</dd>
            <dt>Review type</dt>
            <dd>
              {String(
                reviewer?.review_type ??
                  evidence?.review_type ??
                  "Unverified / not recorded",
              )}
            </dd>
            <dt>Reviewer</dt>
            <dd>{String(reviewer?.agent ?? "Not recorded")}</dd>
            <dt>Provenance</dt>
            <dd>{String(evidence?.provenance ?? "Not recorded")}</dd>
            <dt>Checks</dt>
            <dd>
              {evidence?.checks_passed === true
                ? "Passing observations recorded"
                : evidence?.checks_passed === false
                  ? "Failing observations recorded"
                  : "Not recorded"}
            </dd>
            <dt>Average / floor</dt>
            <dd>
              {typeof evidence?.average === "number"
                ? evidence.average
                : "Not recorded"}{" "}
              /{" "}
              {typeof evidence?.minimum === "number"
                ? evidence.minimum
                : "Not recorded"}
            </dd>
          </dl>
          {Array.isArray(evidence?.observed_checks) &&
            evidence.observed_checks.length > 0 && (
              <>
                <h3>Observed checks</h3>
                <ul className="check-list">
                  {evidence.observed_checks.map((c, i) => (
                    <CheckObservation key={i} value={c} />
                  ))}
                </ul>
              </>
            )}
          <details>
            <summary>Full recorded evidence</summary>
            <pre tabIndex={0}>{JSON.stringify(evidence ?? {}, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
export function PhaseDetails({
  snapshot,
  selected,
}: {
  snapshot: Snapshot;
  selected: string;
}) {
  const phase = snapshot.phases.find((p) => p.id === selected);
  const definition = snapshot.definition.phases?.find((p) => p.id === selected);
  const attempts = snapshot.attempts.filter((a) => a.phase_id === selected);
  const [current, setCurrent] = useState<string>("");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  useEffect(() => {
    setCurrent("");
    setArtifact(null);
  }, [selected, snapshot.run.run_id]);
  const chosen =
    attempts.find((a) => a.id === current) ??
    attempts.find((a) => a.id === phase?.attempt_id) ??
    attempts.at(-1);
  const ids = new Set(attempts.map((a) => a.id));
  const artifacts = snapshot.artifacts.filter((a) => ids.has(a.attempt_id));
  const decisions = snapshot.decisions.filter((d) => ids.has(d.attempt_id));
  const loops =
    snapshot.definition.edges?.filter(
      (e) => e.source === selected && e.on === "fail",
    ) ?? [];
  return (
    <aside
      id="selected-phase-details"
      className="detail-panel"
      aria-label="Phase details"
      tabIndex={0}
    >
      <span className="eyebrow">Selected phase</span>
      <h2>{selected ? phaseLabel(selected) : "No phase selected"}</h2>
      {phase ? (
        <>
          <Status status={phase.status} />
          <p>
            <code>{selected}</code>
          </p>
          <dl className="facts">
            <dt>Skill</dt>
            <dd>{definition?.skill ?? "No skill invocation"}</dd>
            <dt>Owner</dt>
            <dd>{phase.owner ?? "Not recorded"}</dd>
            <dt>Current attempt</dt>
            <dd>
              {phase.number ?? "Not started"}
              {phase.number && definition?.max_attempts
                ? ` of ${definition.max_attempts}`
                : ""}
            </dd>
            <dt>Inputs</dt>
            <dd>{definition?.inputs?.join(", ") || "None declared"}</dd>
            <dt>Outputs</dt>
            <dd>{definition?.outputs?.join(", ") || "None declared"}</dd>
          </dl>
          {phase.reason && <p className="notice warning">{phase.reason}</p>}
          {loops.length > 0 && (
            <p className="muted">
              On rejection or failure:{" "}
              {loops.map((e) => phaseLabel(e.target)).join(", ")}. Declared
              retry limits still apply.
            </p>
          )}
          {attempts.length > 0 && (
            <label className="stacked-label">
              Inspect an attempt
              <select
                value={chosen?.id ?? ""}
                onChange={(e) => setCurrent(e.target.value)}
              >
                {attempts.map((a) => (
                  <option key={a.id} value={a.id}>
                    Attempt {a.number} · {a.status.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
          )}
          {chosen && (
            <>
              <p className="muted">
                {chosen.id === phase?.attempt_id
                  ? "Current recorded attempt"
                  : "Historical attempt; not a current phase result"}
              </p>
              <AttemptEvidence
                key={chosen.id + chosen.status}
                runId={snapshot.run.run_id}
                attempt={chosen}
              />
            </>
          )}
          <section>
            <h3>Phase artifacts</h3>
            {artifacts.length ? (
              artifacts.map((a) => (
                <div key={a.id} className="artifact-link">
                  <button onClick={() => setArtifact(a)}>
                    View {a.kind.replaceAll("_", " ")}
                  </button>
                  <small>
                    <code>{a.sha256}</code>
                  </small>
                  <FormalProvenance artifact={a} />
                </div>
              ))
            ) : (
              <p className="muted">No artifacts on the loaded history pages.</p>
            )}
            {artifact && (
              <ArtifactText
                runId={snapshot.run.run_id}
                artifact={artifact}
                onClose={() => setArtifact(null)}
              />
            )}
          </section>
          {decisions.length > 0 && (
            <section>
              <h3>Human decisions</h3>
              {decisions.map((d) => (
                <DecisionCard key={d.id} decision={d} snapshot={snapshot} />
              ))}
            </section>
          )}
          {snapshot.has_more_attempts && (
            <p className="muted">
              Older attempts are available in History. Artifact and decision
              pages are available under Artifacts.
            </p>
          )}
        </>
      ) : (
        <p className="muted">Select a recorded phase from the graph or list.</p>
      )}
    </aside>
  );
}
