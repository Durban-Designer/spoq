import { useEffect, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
  type Node,
  type Edge,
} from "@xyflow/react";
import { getJson, runUrl } from "./api";
import { Status } from "./Status";
import type { Snapshot, Work, WorkEdge, WorkNode } from "./types";
import { mergeById } from "./useHistoryPage";
function mergeEdges(...groups: WorkEdge[][]) {
  return [
    ...new Map(
      groups
        .flat()
        .map((e) => [`${e.scope_id}/${e.node_id}/${e.dependency_id}`, e]),
    ).values(),
  ];
}
export function workLayout(nodes: WorkNode[], edges: WorkEdge[]) {
  const levels = new Map<string, number>();
  const ids = new Set(nodes.map((n) => n.id));
  let pending = nodes.map((n) => n.id);
  while (pending.length) {
    const ready = pending.filter((id) =>
      edges
        .filter((e) => e.node_id === id && ids.has(e.dependency_id))
        .every((e) => levels.has(e.dependency_id)),
    );
    if (!ready.length) {
      pending.forEach((id) => levels.set(id, 0));
      break;
    }
    for (const id of ready)
      levels.set(
        id,
        Math.max(
          0,
          ...edges
            .filter((e) => e.node_id === id && ids.has(e.dependency_id))
            .map((e) => (levels.get(e.dependency_id) ?? 0) + 1),
        ),
      );
    pending = pending.filter((id) => !ready.includes(id));
  }
  return nodes.map((n, i) => ({
    id: n.id,
    x: (levels.get(n.id) ?? 0) * 290,
    y:
      nodes.slice(0, i).filter((p) => levels.get(p.id) === levels.get(n.id))
        .length * 135,
  }));
}
export function WorkGraph({ snapshot }: { snapshot: Snapshot }) {
  const [extra, setExtra] = useState<Work | null>(null);
  const [scope, setScope] = useState(snapshot.work.scope_id);
  const [detail, setDetail] = useState<WorkNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [cacheCursor, setCacheCursor] = useState(snapshot.cursor);
  const [cacheNotice, setCacheNotice] = useState(false);
  const snapshotCursor = useRef(snapshot.cursor);
  snapshotCursor.current = snapshot.cursor;
  const validExtra = cacheCursor === snapshot.cursor ? extra : null;
  useEffect(() => {
    if (extra && cacheCursor !== snapshot.cursor) {
      setExtra(null);
      setCacheNotice(true);
    }
    if (detail) setDetail(null);
  }, [snapshot.cursor]);
  const inspection = useRef(0);
  const inspectionAbort = useRef<AbortController | null>(null);
  useEffect(() => () => inspectionAbort.current?.abort(), []);
  useEffect(() => {
    inspection.current++;
    inspectionAbort.current?.abort();
    setDetail(null);
  }, [scope, snapshot.cursor]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  useEffect(() => {
    setExtra(null);
    setScope(snapshot.work.scope_id);
    setDetail(null);
    setError("");
  }, [snapshot.run.run_id]);
  const work: Work = {
    scope_id: snapshot.work.scope_id,
    nodes: mergeById(validExtra?.nodes ?? [], snapshot.work.nodes),
    edges: mergeEdges(validExtra?.edges ?? [], snapshot.work.edges),
    pagination: validExtra?.pagination ?? snapshot.work.pagination,
  };
  const root = work.nodes.find((n) => n.id === scope);
  const children = work.nodes.filter((n) => n.parent_id === scope);
  const links = work.edges.filter((e) => e.scope_id === scope);
  const layout = workLayout(children, links);
  const nodes: Node[] = children.map((n) => ({
    id: n.id,
    position: {
      x: layout.find((p) => p.id === n.id)!.x,
      y: layout.find((p) => p.id === n.id)!.y,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    data: {
      label: (
        <>
          <span className="graph-kind">{n.kind.replaceAll("_", " ")}</span>
          <strong>{n.title}</strong>
          <Status status={n.status} />
        </>
      ),
    },
    ariaLabel: `${n.kind} ${n.title}, ${n.status}`,
    className: "phase-node",
    style: { width: 235 },
  }));
  const edges: Edge[] = links
    .filter(
      (e) =>
        children.some((n) => n.id === e.node_id) &&
        children.some((n) => n.id === e.dependency_id),
    )
    .map((e, i) => ({
      id: "work-" + i,
      source: e.dependency_id,
      target: e.node_id,
      markerEnd: { type: MarkerType.ArrowClosed, color: "#8a9bb1" },
      style: { stroke: "#8a9bb1" },
    }));
  async function inspect(node: WorkNode) {
    const requestedScope = scope;
    const requestedCursor = snapshot.cursor;
    const request = ++inspection.current;
    inspectionAbort.current?.abort();
    const abort = new AbortController();
    inspectionAbort.current = abort;
    const current = () =>
      !abort.signal.aborted &&
      scopeRef.current === requestedScope &&
      snapshotCursor.current === requestedCursor &&
      inspection.current === request;
    setDetail(null);
    setError("");
    try {
      const result = await getJson<WorkNode>(
        runUrl(snapshot.run.run_id, "nodes", node.id),
        abort.signal,
      );
      if (current()) setDetail(result);
    } catch (e) {
      if (current()) setError((e as Error).message);
    }
  }
  async function more() {
    const requestedCursor = snapshot.cursor;
    if (!work.pagination.has_more || work.pagination.cursor === null) return;
    setLoading(true);
    setError("");
    try {
      const page = await getJson<Work>(
        runUrl(snapshot.run.run_id, "work") +
          "?limit=500&after=" +
          encodeURIComponent(work.pagination.cursor),
      );
      if (snapshotCursor.current !== requestedCursor) {
        setCacheNotice(true);
        return;
      }
      setCacheCursor(requestedCursor);
      setCacheNotice(false);
      setExtra({
        scope_id: page.scope_id,
        nodes: mergeById(work.nodes, page.nodes),
        edges: mergeEdges(work.edges, page.edges),
        pagination: page.pagination,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <section
      className="work-panel"
      aria-label="Feature and task dependency DAG"
    >
      <div className="section-title">
        <div>
          <span className="eyebrow">Work dependencies · DAG</span>
          <h2>{root?.title ?? scope ?? "Work scope not recorded"}</h2>
        </div>
        {scope !== snapshot.work.scope_id && (
          <button
            onClick={() => {
              setScope(root?.parent_id ?? snapshot.work.scope_id);
              setDetail(null);
            }}
          >
            Back to parent DAG
          </button>
        )}
      </div>
      <p className="muted">
        These are Feature or Task prerequisites. Strategy revision loops are
        shown separately in the Strategy tab.
      </p>
      {root && (
        <div className="work-root">
          <Status status={root.status} />
          <button onClick={() => void inspect(root)}>
            Inspect scope acceptance criteria
          </button>
        </div>
      )}
      {children.length > 0 ? (
        <>
          <div
            className="work-graph"
            role="region"
            aria-label="Read-only work DAG"
          >
            <ReactFlow
              key={scope}
              nodes={nodes}
              edges={edges}
              onNodeClick={(_, node) => {
                const item = children.find((n) => n.id === node.id)!;
                if (item.kind !== "task") {
                  setScope(item.id);
                  setDetail(null);
                } else void inspect(item);
              }}
              nodesDraggable={false}
              nodesConnectable={false}
              edgesReconnectable={false}
              nodesFocusable={false}
              edgesFocusable={false}
              deleteKeyCode={null}
              colorMode="dark"
              fitView
              fitViewOptions={{ maxZoom: 1, padding: 0.25 }}
            >
              <Background color="#303949" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <ul className="work-list">
            {children.map((n) => (
              <li key={n.id}>
                <div>
                  <strong>{n.title}</strong>
                  <span className="muted">
                    {n.kind} · <code>{n.id}</code>
                  </span>
                  <Status status={n.status} />
                  {links.some((e) => e.node_id === n.id) && (
                    <small>
                      Requires:{" "}
                      {links
                        .filter((e) => e.node_id === n.id)
                        .map((e) => e.dependency_id)
                        .join(", ")}
                    </small>
                  )}
                </div>
                <div>
                  {n.kind !== "task" && (
                    <button
                      onClick={() => {
                        setScope(n.id);
                        setDetail(null);
                      }}
                    >
                      Open {n.title} Task DAG
                    </button>
                  )}
                  <button onClick={() => void inspect(n)}>
                    Inspect {n.title}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>No child work nodes on the loaded pages.</p>
      )}
      {cacheNotice && (
        <p className="notice warning" role="status">
          Additional work pages were cleared after newer committed events. Load
          more work again to inspect current nodes and edges.
        </p>
      )}
      {work.pagination.has_more && (
        <div className="notice warning">
          <p>
            Work data is paged. Some nodes or dependency edges are not loaded
            yet.
          </p>
          <button disabled={loading} onClick={() => void more()}>
            Load more work nodes and edges
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="notice danger">
          {error}
        </p>
      )}
      {detail && (
        <section className="record-card" aria-label="Work acceptance details">
          <h3>{detail.title}</h3>
          <Status status={detail.status} />
          <p>
            <code>{detail.id}</code>
          </p>
          <pre tabIndex={0}>{JSON.stringify(detail.data ?? {}, null, 2)}</pre>
        </section>
      )}
    </section>
  );
}
