import { useEffect, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { Snapshot } from "./types";
import { phaseLabel, Status, statusLabel } from "./Status";

function ReworkEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  style,
  label,
}: EdgeProps) {
  const offset = 190;
  const path = `M ${sourceX} ${sourceY} C ${sourceX - offset} ${sourceY + 35}, ${targetX - offset} ${targetY - 35}, ${targetX} ${targetY}`;
  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <span
          className="rework-label nodrag nopan"
          style={{
            transform: `translate(-50%,-50%) translate(${(sourceX + targetX) / 2 - offset * 0.75}px,${(sourceY + targetY) / 2}px)`,
          }}
        >
          {label}
        </span>
      </EdgeLabelRenderer>
    </>
  );
}
const edgeTypes = { rework: ReworkEdge };
export function strategyLayout(snapshot: Snapshot) {
  const definitions = snapshot.definition.phases ?? [];
  const links = snapshot.definition.edges ?? [];
  const levels = new Map<string, number>();
  let pending = definitions.map((p) => p.id);
  while (pending.length) {
    const ready = pending.filter((id) =>
      links
        .filter((e) => e.target === id && e.on !== "fail")
        .every((e) => levels.has(e.source)),
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
          ...links
            .filter((e) => e.target === id && e.on !== "fail")
            .map((e) => (levels.get(e.source) ?? 0) + 1),
        ),
      );
    pending = pending.filter((id) => !ready.includes(id));
  }
  const groups = new Map<number, string[]>();
  for (const p of definitions) {
    const level = levels.get(p.id) ?? 0;
    groups.set(level, [...(groups.get(level) ?? []), p.id]);
  }
  return definitions.map((p) => {
    const level = levels.get(p.id) ?? 0;
    const row = groups.get(level) ?? [p.id];
    return {
      id: p.id,
      x: (row.indexOf(p.id) - (row.length - 1) / 2) * 250,
      y: level * 142,
    };
  });
}
export function StrategyGraph({
  snapshot,
  selected,
  onSelect,
}: {
  snapshot: Snapshot;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  const layoutKey = JSON.stringify({
    phases: snapshot.definition.phases?.map((p) => p.id),
    edges: snapshot.definition.edges,
  });
  // Snapshot objects change during polling; unchanged topology must not reset pan/zoom.
  const layout = useMemo(() => strategyLayout(snapshot), [layoutKey]);
  const nodes: Node[] = layout.map((p) => {
    const phase = snapshot.phases.find((s) => s.id === p.id);
    const def = snapshot.definition.phases?.find((d) => d.id === p.id);
    return {
      id: p.id,
      position: { x: p.x, y: p.y },
      selected: selected === p.id,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      ariaLabel: `${phaseLabel(p.id)}, ${statusLabel(phase?.status)}`,
      data: {
        label: (
          <>
            <span className="graph-kind">{def?.kind ?? "phase"}</span>
            <strong>{phaseLabel(p.id)}</strong>
            <Status status={phase?.status} />
          </>
        ),
      },
      style: { width: 220 },
      className: "phase-node phase-" + (phase?.status ?? "unknown"),
    };
  });
  const edges: Edge[] = (snapshot.definition.edges ?? []).map((e, i) => ({
    id: `edge-${i}`,
    source: e.source,
    target: e.target,
    type: e.on === "fail" ? "rework" : "smoothstep",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: e.on === "fail" ? "#e6a56d" : "#78889e",
    },
    label:
      e.on === "fail"
        ? "Reject / rework"
        : e.when
          ? `${e.when.key} selected`
          : "",
    style: {
      stroke: e.on === "fail" ? "#e6a56d" : "#78889e",
      strokeDasharray: e.on === "fail" ? "7 5" : e.when ? "3 4" : undefined,
    },
    labelStyle: { fill: "#dce2ea", fontSize: 11 },
    labelBgStyle: { fill: "#171c25" },
    labelBgPadding: [5, 4],
  }));
  useEffect(() => {
    const p = layout.find((n) => n.id === selected);
    if (instance && p)
      void instance.setCenter(p.x + 110, p.y + 48, { zoom: 0.85, duration: 0 });
  }, [instance, layout, selected]);
  if (!nodes.length)
    return (
      <div className="empty-panel">
        <h2>Strategy not recorded</h2>
        <p>
          This run predates strategy tracking. Its work DAG remains available;
          past phase passes are not inferred.
        </p>
      </div>
    );
  return (
    <div
      className="graph-region"
      role="region"
      aria-label="Read-only strategy graph"
    >
      <ReactFlow
        edgeTypes={edgeTypes}
        nodes={nodes}
        edges={edges}
        onInit={setInstance}
        onNodeClick={(_, node) => onSelect(node.id)}
        onNodesChange={(changes) => {
          const selection = changes.find(
            (change) => change.type === "select" && change.selected,
          );
          if (selection?.type === "select" && selection.id !== selected)
            onSelect(selection.id);
        }}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        nodesFocusable
        edgesFocusable={false}
        colorMode="dark"
        minZoom={0.15}
        maxZoom={1.5}
        ariaLabelConfig={{
          "controls.zoomIn.ariaLabel": "Zoom in strategy graph",
          "controls.zoomOut.ariaLabel": "Zoom out strategy graph",
          "controls.fitView.ariaLabel": "Fit strategy graph",
        }}
      >
        <Background color="#303949" gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <p className="graph-caption">
        Inspect only · Pan and zoom to explore · Dashed arrows return for
        revision
      </p>
    </div>
  );
}
