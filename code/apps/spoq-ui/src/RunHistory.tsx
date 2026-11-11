import { useState } from "react";
import { AttemptEvidence } from "./PhaseDetails";
import { phaseLabel, Status } from "./Status";
import { useHistoryPage } from "./useHistoryPage";
import type { Attempt, Participant, Snapshot } from "./types";
export function RunHistory({ snapshot }: { snapshot: Snapshot }) {
  const run = snapshot.run.run_id;
  const attempts = useHistoryPage<Attempt>(
    run,
    "attempts",
    snapshot.attempts,
    {
      has_more: snapshot.has_more_attempts,
      cursor: snapshot.attempt_cursor,
    },
    snapshot.cursor,
  );
  const participants = useHistoryPage<Participant>(
    run,
    "participants",
    snapshot.participants,
    snapshot.run.pagination?.participants,
    snapshot.cursor,
  );
  const [inspect, setInspect] = useState<string>("");
  const selected = attempts.items.find((a) => a.id === inspect);
  return (
    <section className="history-panel" aria-label="Execution attempt history">
      <div className="section-title">
        <div>
          <span className="eyebrow">Actual visits · immutable identities</span>
          <h2>Execution history</h2>
        </div>
        <span className="muted">
          Definition phases and attempts are separate records.
        </span>
      </div>
      {attempts.items.length ? (
        <ol className="timeline">
          {[...attempts.items].reverse().map((a) => (
            <li key={a.id} data-attempt-id={a.id}>
              <div className="timeline-state">
                <Status status={a.status} />
                <span>
                  {phaseLabel(a.phase_id)} · Attempt {a.number}
                </span>
              </div>
              <div className="muted">
                <code>{a.id}</code>
                <span>
                  {a.owner ?? "Owner not recorded"}
                  {a.created_at
                    ? " · " + new Date(a.created_at).toLocaleString()
                    : ""}
                </span>
              </div>
              <button onClick={() => setInspect(inspect === a.id ? "" : a.id)}>
                Inspect {phaseLabel(a.phase_id)} attempt {a.number}
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p>
          {snapshot.run.provenance === "legacy_unclassified"
            ? "This legacy run has no recorded strategy attempts."
            : "No phase has been invoked yet."}
        </p>
      )}
      {attempts.pagination.has_more && (
        <button
          disabled={attempts.loading}
          onClick={() => void attempts.loadMore()}
        >
          Load older attempts
        </button>
      )}
      {attempts.notice && (
        <p className="notice warning" role="status">
          {attempts.notice}
        </p>
      )}
      {attempts.error && <p role="alert">{attempts.error}</p>}
      {selected && (
        <div className="record-card">
          <AttemptEvidence
            key={selected.id + selected.status}
            runId={run}
            attempt={selected}
          />
        </div>
      )}
      <section className="participants">
        <h3>Recorded participants</h3>
        {participants.items.length ? (
          <ul>
            {participants.items.map((p) => (
              <li key={p.id}>
                <strong>{p.id}</strong> · {p.role} ·{" "}
                {p.runtime ?? "Runtime not recorded"}
              </li>
            ))}
          </ul>
        ) : (
          <p>No participant identity is recorded.</p>
        )}
        {participants.pagination.has_more && (
          <button
            disabled={participants.loading}
            onClick={() => void participants.loadMore()}
          >
            Load older participants
          </button>
        )}
        {participants.notice && (
          <p className="notice warning" role="status">
            {participants.notice}
          </p>
        )}
        {participants.error && <p role="alert">{participants.error}</p>}
      </section>
    </section>
  );
}
