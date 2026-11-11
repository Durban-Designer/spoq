import { phaseLabel, Status } from "./Status";
import type { Snapshot } from "./types";
export function AccessibleRunList({
  snapshot,
  selected,
  onSelect,
}: {
  snapshot: Snapshot;
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="phase-sidebar" aria-label="Phase list">
      <h2>Phases</h2>
      {snapshot.phases.length ? (
        <>
          <ol>
            {snapshot.phases.map((phase) => (
              <li key={phase.id}>
                <button
                  aria-controls="selected-phase-details"
                  onClick={() => onSelect(phase.id)}
                  aria-pressed={selected === phase.id}
                >
                  <span>{phaseLabel(phase.id)}</span>{" "}
                  <Status status={phase.status} />
                  {phase.reason && (
                    <>
                      {" "}
                      <small className="phase-reason">{phase.reason}</small>
                    </>
                  )}
                </button>
              </li>
            ))}
          </ol>
          <a className="detail-jump" href="#selected-phase-details">
            Jump to phase details
          </a>
        </>
      ) : (
        <p className="muted">No strategy phases were recorded.</p>
      )}
    </aside>
  );
}
