export type JsonObject = Record<string, unknown>;
export interface PhaseDefinition {
  id: string;
  kind: string;
  skill?: string | null;
  inputs?: string[];
  outputs?: string[];
  max_attempts?: number;
  config?: JsonObject;
}
export interface PhaseState {
  id: string;
  status: string;
  attempt_id?: string | null;
  number?: number;
  owner?: string;
  ready?: boolean;
  reason?: string;
  last_outcome?: string;
}
export interface StrategyEdge {
  source: string;
  target: string;
  on?: string;
  when?: { key: string; op: string; value?: unknown } | null;
}
export interface Attempt {
  id: string;
  phase_id: string;
  number: number;
  status: string;
  owner?: string;
  created_at?: string;
  updated_at?: string;
  evidence?: JsonObject;
  details_url?: string;
  cursor?: number;
}
export interface Artifact {
  id: string;
  attempt_id: string;
  kind: string;
  sha256: string;
  source: string;
  author?: string;
  metadata?: JsonObject;
  content?: string;
  render_as?: string;
  created_at?: string;
  details_url?: string;
}
export interface Decision {
  id: string;
  attempt_id: string;
  artifact_id: string;
  artifact_hash: string;
  specification_hash?: string;
  definition_hash?: string;
  source: string;
  author: string;
  decision: string;
  reason?: string;
  created_at?: string;
}
export interface Participant {
  id: string;
  role: string;
  runtime?: string;
  heartbeat?: string;
}
export interface WorkNode {
  id: string;
  kind: string;
  parent_id?: string | null;
  title: string;
  status: string;
  data?: JsonObject;
}
export interface WorkEdge {
  scope_id?: string;
  node_id: string;
  dependency_id: string;
}
export interface Pagination {
  has_more: boolean;
  cursor: string | number | null;
}
export interface Work {
  scope_id: string | null;
  nodes: WorkNode[];
  edges: WorkEdge[];
  pagination: Pagination;
}
export interface Run {
  run_id: string;
  scope_id: string | null;
  status: string;
  strategy?: string;
  revision?: number;
  provenance?: string;
  definition_hash?: string;
  specification_hash?: string;
  current_specification_hash?: string;
  stale_specification?: boolean;
  transitions?: number | null;
  epoch?: number | null;
  pagination?: Record<string, Pagination>;
}
export interface Snapshot {
  format: "spoq-workflow-view-1";
  cursor: number;
  run: Run;
  definition: {
    id?: string;
    version?: string;
    title?: string;
    content_hash?: string;
    phases?: PhaseDefinition[];
    edges?: StrategyEdge[];
    max_transitions?: number;
  };
  routing: {
    strategy?: string;
    profile?: string;
    policy_version?: string;
    reasons?: string[];
    inputs?: JsonObject;
    addons?: Record<string, boolean>;
  };
  phases: PhaseState[];
  attempts: Attempt[];
  artifacts: Artifact[];
  decisions: Decision[];
  participants: Participant[];
  work: Work;
  blockers: string[];
  has_more_attempts: boolean;
  attempt_cursor: number | null;
}
export interface RunPage {
  runs: Run[];
  pagination: Pagination;
  cursor: number;
}
export interface HistoryPage<T> {
  resource: string;
  items: T[];
  pagination: Pagination;
}
