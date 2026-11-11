import { useEffect, useState } from "react";
import { getJson } from "./api";
import { useWorkflowSnapshot } from "./events";
import { RunHistory } from "./RunHistory";
import { StrategyGraph } from "./StrategyGraph";
import { AccessibleRunList } from "./AccessibleRunList";
import { PhaseDetails } from "./PhaseDetails";
import { WorkGraph } from "./WorkGraph";
import { ArtifactPanel } from "./ArtifactPanel";
import { Status } from "./Status";
import type { Run, RunPage } from "./types";
export function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runPage, setRunPage] = useState<RunPage | null>(null);
  const [runId, setRunId] = useState(
    () => new URLSearchParams(window.location.search).get("run") ?? "",
  );
  const live = useWorkflowSnapshot(runId);
  const snapshot = live.snapshot?.run.run_id === runId ? live.snapshot : null;
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("strategy");
  const [error, setError] = useState("");
  const [listing, setListing] = useState(true);
  const loading = listing || live.loading;
  const [workspace, setWorkspace] = useState("Local workspace");
  async function loadRuns(after = "") {
    const page = await getJson<RunPage>(
      "/api/runs?limit=100" +
        (after ? "&after=" + encodeURIComponent(after) : ""),
    );
    setRuns((old) => (after ? [...old, ...page.runs] : page.runs));
    setRunPage(page);
    setListing(false);
    if (!runId && page.runs[0])
      setRunId(
        (
          page.runs.find((r) =>
            ["running", "waiting_human", "blocked", "paused"].includes(
              r.status,
            ),
          ) ?? page.runs[0]
        ).run_id,
      );
  }
  useEffect(() => {
    void loadRuns().catch((e) => {
      setError(e.message);
      setListing(false);
    });
    void getJson<{ project_root: string }>("/api/health")
      .then((h) => setWorkspace(h.project_root))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (
      snapshot &&
      (!selected || !snapshot.phases.some((p) => p.id === selected))
    ) {
      setSelected(
        snapshot.phases.find((p) =>
          ["running", "waiting_human", "blocked"].includes(p.status),
        )?.id ??
          snapshot.phases[0]?.id ??
          "",
      );
    }
  }, [snapshot, selected]);
  useEffect(() => {
    setSelected("");
    setTab("strategy");
  }, [runId]);
  async function refresh() {
    await live.refresh();
    try {
      await loadRuns();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const readError = live.error || error;
  const runKey = runId + ":" + live.epoch;
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to workflow
      </a>
      <header className="app-header">
        <div className="brand">
          <img src="./spoq.svg" alt="" width="36" height="36" />
          <div>
            <strong>SPOQ</strong>
            <span>Workflow viewer</span>
          </div>
        </div>
        <div className="workspace" title={workspace}>
          <span className="eyebrow">Local workspace</span>
          <span>{workspace}</span>
        </div>
        <span className="readonly-label">Read-only</span>
        <button onClick={() => void refresh()}>Refresh</button>
      </header>
      <main id="main">
        <div className="run-toolbar">
          <label>
            Execution run
            <select
              value={runId}
              onChange={(e) => {
                setRunId(e.target.value);
                window.history.replaceState(
                  null,
                  "",
                  "?run=" + encodeURIComponent(e.target.value),
                );
              }}
            >
              <option value="">Choose a run</option>
              {runId && !runs.some((r) => r.run_id === runId) && (
                <option value={runId}>{runId}</option>
              )}
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} · {r.status.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          {runPage?.pagination.has_more && (
            <button
              onClick={() =>
                void loadRuns(String(runPage.pagination.cursor)).catch((e) =>
                  setError(e.message),
                )
              }
            >
              Load more runs
            </button>
          )}
          <div
            className="connection"
            role="status"
            aria-label="Viewer connection"
          >
            {loading ? "Connecting to local viewer" : live.connection}
          </div>
        </div>
        {readError && (
          <div className="notice danger" role="alert">
            {readError}
          </div>
        )}
        {live.notice && (
          <p className="notice provenance" role="status">
            {live.notice}
          </p>
        )}
        {loading && (
          <p className="loading">Loading committed workflow state…</p>
        )}
        {!loading && !snapshot && !readError && (
          <div className="empty-panel">
            <h1>No execution runs yet</h1>
            <p>
              Start <code>/spoq &lt;goal&gt;</code> in your coding client, then
              refresh this viewer.
            </p>
          </div>
        )}
        {snapshot && (
          <>
            <section className="run-heading">
              <div>
                <span className="eyebrow">
                  {snapshot.routing.strategy === "legacy_unclassified"
                    ? "Legacy run"
                    : `${snapshot.routing.profile ?? "standard"} strategy`}
                </span>
                <h1>
                  {snapshot.definition.title ??
                    snapshot.routing.strategy ??
                    "Strategy not recorded"}
                </h1>
                <p className="muted">
                  Scope <code>{snapshot.run.scope_id ?? "not recorded"}</code> ·
                  Snapshot cursor{" "}
                  <span data-testid="snapshot-cursor">{snapshot.cursor}</span>
                </p>
              </div>
              <Status status={snapshot.run.status} />
            </section>
            <section className="route-reasons" aria-label="Why this strategy">
              <span className="eyebrow">Why this route</span>
              {snapshot.routing.reasons?.length ? (
                <ul>
                  {snapshot.routing.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p>No routing rationale was recorded for this run.</p>
              )}
            </section>
            {snapshot.blockers.length > 0 && (
              <section
                className="notice warning"
                aria-label="Workflow blockers"
              >
                <strong>Attention needed</strong>
                <ul>
                  {snapshot.blockers.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </section>
            )}
            <div
              className="view-tabs"
              role="tablist"
              aria-label="Workflow views"
            >
              {[
                ["strategy", "Strategy"],
                ["work", "Work DAGs"],
                ["artifacts", "Artifacts & decisions"],
                ["history", "History"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  id={"tab-" + id}
                  role="tab"
                  aria-selected={tab === id}
                  aria-controls={"view-" + id}
                  tabIndex={tab === id ? 0 : -1}
                  onClick={() => setTab(id)}
                  onKeyDown={(e) => {
                    const tabs = ["strategy", "work", "artifacts", "history"];
                    if (
                      ["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)
                    ) {
                      e.preventDefault();
                      const index =
                        e.key === "Home"
                          ? 0
                          : e.key === "End"
                            ? tabs.length - 1
                            : (tabs.indexOf(id) +
                                (e.key === "ArrowRight"
                                  ? 1
                                  : tabs.length - 1)) %
                              tabs.length;
                      setTab(tabs[index]);
                      document.getElementById("tab-" + tabs[index])?.focus();
                    }
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === "strategy" && (
              <div
                id="view-strategy"
                role="tabpanel"
                aria-labelledby="tab-strategy"
                hidden={tab !== "strategy"}
              >
                <div className="viewer-layout">
                  <AccessibleRunList
                    snapshot={snapshot}
                    selected={selected}
                    onSelect={setSelected}
                  />
                  <section className="graph-panel">
                    <div className="panel-heading">
                      <h2>Strategy graph</h2>
                      <span>
                        {snapshot.definition.version
                          ? `Definition ${snapshot.definition.version}`
                          : "Provenance unavailable"}
                      </span>
                    </div>
                    <StrategyGraph
                      snapshot={snapshot}
                      selected={selected}
                      onSelect={setSelected}
                    />
                  </section>
                  <PhaseDetails
                    key={runKey}
                    snapshot={snapshot}
                    selected={selected}
                  />
                </div>
              </div>
            )}
            {tab === "work" && (
              <div id="view-work" role="tabpanel" aria-labelledby="tab-work">
                <WorkGraph key={runKey} snapshot={snapshot} />
              </div>
            )}
            {tab === "artifacts" && (
              <div
                id="view-artifacts"
                role="tabpanel"
                aria-labelledby="tab-artifacts"
              >
                <ArtifactPanel key={runKey} snapshot={snapshot} />
              </div>
            )}
            {tab === "history" && (
              <div
                id="view-history"
                role="tabpanel"
                aria-labelledby="tab-history"
              >
                <RunHistory key={runKey} snapshot={snapshot} />
              </div>
            )}
            <footer className="viewer-footer">
              <span>Committed local state · No execution controls</span>
              <span>Duration and cost telemetry are not recorded.</span>
            </footer>
          </>
        )}
      </main>
    </>
  );
}
