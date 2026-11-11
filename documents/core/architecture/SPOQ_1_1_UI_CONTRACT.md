# SPOQ 1.1 local viewer contract

The viewer inspects committed state. CLI and MCP clients own execution and human
responses; the browser has no mutation endpoints or model launcher. The Python
distribution contains its static assets and serves only a loopback address.

## Snapshot and replay

`GET /api/runs` lists runs. `GET /api/runs/<id>` returns
`spoq-workflow-view-1`. One SQLite read transaction obtains the run, pinned
definition, projections, and maximum global event sequence (`cursor`). Run IDs
are URL encoded. The same projection is available through CLI and MCP.

The snapshot includes `run`, `definition`, `routing`, `phases`, `attempts`,
`artifacts`, `decisions`, `participants`, `work`, and `blockers`. Routing records
policy version, inputs, selection reasons, profile, and optional design phases.
Phases describe the reusable definition; attempts identify actual visits. Do not
merge two revision attempts into one apparent execution. A run created before
strategy support has `legacy_unclassified` provenance and no invented definition,
attempts, scores, or independent review.

`GET /api/runs/<id>/events?after=<cursor>&limit=100` returns ordered global event
identities applicable to that run, `cursor`, `has_more`, and `reset`. Advancing
the cursor over unrelated events is permitted only after the server has scanned
them. Global sequences can have gaps; a client must not equate a numerical gap
with data loss. A cursor ahead of the database or older than retained events
returns `reset=true`, requiring a new snapshot. Replay pages are bounded (default
100, maximum 500). Clients may poll; streaming is a delivery optimization, not a
separate state source.

Apply each event identity at most once. On disconnect, reconnect from the last
accepted cursor. Refresh the authoritative snapshot after an event batch before
displaying new phase state. A response predating the currently applied cursor
cannot replace a newer snapshot. After a reset, discard the old projection and
reload; never infer that missing events passed a gate. Polling/replay tests must
include duplicate delivery, gaps from unrelated events, server restart, and
snapshot/event interleaving.

Attempts, artifacts, decisions, events, and work rows use explicit bounded pages;
pagination metadata reports further data. History queries include `limit` and an
opaque or integer cursor. A compact graph may show the latest attempt, but the
history remains accessible. A 1,000-attempt/10,000-event fixture checks bounded
responses; its measured timing is local evidence, not a production capacity claim.
The snapshot uses `run.pagination` for artifact/decision pages and `work.pagination`
for work rows; attempt pagination uses `has_more_attempts` and `attempt_cursor`.
Separate history endpoints return their own page metadata. This preserves the
fixed snapshot envelope while making truncated collections explicit.

## Presentation and navigation

The graph shows planned transitions, conditional paths, bounded revision edges,
selection reasons, and the current phase. Status text distinguishes queued,
running, waiting_human, blocked, failed, passed, skipped, and paused. Unselected
branches remain visible with their reason; they do not imply successful work.

Selecting a phase exposes attempts, owners, evidence provenance, required checks,
blocking findings, artifacts, and human decisions. A work tab drills into the
Project Plan Feature DAG and each Feature's Task DAG. Definition and execution
history views use different IDs and labels. Missing telemetry stays unknown:
there is no fabricated cost, remaining duration, or percentage of undefined work.

Every phase has a keyboard-reachable list alternative with the same state and
details. Focus is visible, detail headings are labeled, and status never relies
only on color. Narrow layouts retain navigation and findings. Automatic focus
movement must not steal focus during live updates. The UI announces connection
state separately from execution state.

## Local service boundary

Reject external bind addresses, foreign Host/Origin headers, writes, traversal,
and arbitrary filesystem reads. Serve only packaged static assets and registered
artifact records. Render artifact text as escaped text, with size limits; never
execute embedded HTML, scripts, Mermaid directives, or shell fragments. A link
to an external source is a reference, not proof that its content was fetched or
verified. Local process callers still control their workspace: user-origin
decision provenance is an attestation, not an authentication system.

The executable fixture is `tests/fixtures/spoq-1.1/viewer-contract.json`. Schema
shape checks belong to `test_viewer_contract.py`; actual consistency, transport,
keyboard, and reconnect behavior require integration and browser tests.
