"""SPOQ 1.0 MCP surface. Legacy filesystem tools remain in the legacy server."""
from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from spoq_server import __version__
from .board import Board
from .codex import dispatch_once
from .migration import get_store, migrate, status
from .workflows.mcp import register_workflow_tools, capabilities as workflow_capabilities


def create_server(root: Path):
    root = Path(root).resolve()
    mcp = FastMCP('spoq', instructions=(
        'SPOQ uses Project Plans → Features → Tasks in SQLite. Start with spoq_ping. '
        'If migration_required is true, call spoq_migrate with confirmed=false, show its preview '
        'and conversion prompt to the user, then convert only after confirmation. '
        'Use spoq_workflow_capabilities for Classic/PIQARD routing, bounded workflows, read-only graph/history and schema upgrade discovery. '
        'Coding clients execute phase skills; progress uses polling or native relay and never requires universal MCP push. '
        'Old maps become Project Plans and old epics become Features. '
        'Read collaboration inboxes at execution checkpoints; acknowledge receipt separately from resolution.'))

    def store():
        return get_store(root)

    def board():
        return Board(store())

    readonly=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)

    @mcp.tool(annotations=readonly)
    def spoq_ping() -> dict:
        """Health, hierarchy, and first-use migration prompt after upgrading to SPOQ 1.0."""
        return {'status': 'ok', 'version': __version__, 'active_backend': 'sqlite',
                'project_root': str(root), 'hierarchy': ['project_plan','feature','task'], **status(root),
                'workflow': workflow_capabilities(root)}

    @mcp.tool()
    def spoq_migrate(confirmed: bool = False) -> dict:
        """Preview conversion of journals/tasks/epics/maps. Ask the user before setting confirmed=true.

        Old maps become Project Plans and epics become Features.
        Original files and a byte-for-byte backup are preserved.
        """
        return migrate(root, confirmed=confirmed)

    @mcp.tool()
    def spoq_create_project_plan(plan_id: str, title: str, data: dict | None = None) -> dict:
        """Create a Project Plan: a DAG whose children are Features."""
        return store().create('project_plan', plan_id, title, data=data)

    @mcp.tool()
    def spoq_create_feature(feature_id: str, title: str, plan_id: str, data: dict | None = None) -> dict:
        """Create a Feature with one task DAG. No epic/story/map layer."""
        return store().create('feature', feature_id, title, plan_id, data)

    @mcp.tool()
    def spoq_create_task(task_id: str, title: str, feature_id: str, data: dict | None = None) -> dict:
        """Create a Task in a Feature. IDs are stable workspace-wide identifiers."""
        return store().create('task', task_id, title, feature_id, data)

    @mcp.tool(annotations=readonly)
    def spoq_list_nodes(kind: str = '', parent_id: str = '') -> list[dict]:
        """List Project Plans, Features, or Tasks; optionally filter by parent."""
        return store().list(kind, parent_id)

    @mcp.tool(annotations=readonly)
    def spoq_get_node(node_id: str) -> dict:
        """Get the authoritative node, status, metadata, and revision."""
        return store().get(node_id)

    @mcp.tool()
    def spoq_edit_node(node_id: str, data: dict, title: str | None = None, expected_revision: int | None = None) -> dict:
        """Edit acceptance criteria or metadata with revision checking; record resolution of migration errors here."""
        return store().edit(node_id, data, title, expected_revision)

    @mcp.tool()
    def spoq_add_dependency(node_id: str, dependency_id: str) -> dict:
        """Add a sibling dependency. Reject unknown nodes and cycles atomically."""
        store().depend(node_id, dependency_id)
        return {'node_id': node_id, 'dependency_id': dependency_id}

    @mcp.tool()
    def spoq_remove_dependency(node_id: str, dependency_id: str) -> dict:
        """Remove an incorrect dependency with audit history; reopen completed work first."""
        return store().remove_dependency(node_id,dependency_id)

    @mcp.tool(annotations=readonly)
    def spoq_compute_dag(scope_id: str) -> dict:
        """Compute deterministic waves and currently ready work for a Feature or Project Plan."""
        return store().dag(scope_id)

    @mcp.tool()
    def spoq_update_node(node_id: str, status: str, actor: str = 'user', expected_revision: int | None = None, evidence: dict | None = None, claim_token: str | None = None) -> dict:
        """Update status with revision checking and history. Task completion requires validation evidence."""
        return store().update(node_id, status, actor, expected_revision, evidence, claim_token)

    @mcp.tool()
    def spoq_claim_task(task_id: str, run_id: str, agent_id: str, ttl: int = 300) -> dict:
        """Atomically claim ready work for a registered agent; expired claims can be recovered."""
        return store().claim(task_id, run_id, agent_id, ttl)

    @mcp.tool()
    def spoq_renew_claim(task_id: str, token: str, ttl: int = 300) -> dict:
        """Renew a live claim while working; stale tokens cannot renew or update Tasks."""
        return store().renew_claim(task_id, token, ttl)

    @mcp.tool()
    def spoq_append_journal(body: str, agent: str = 'user', node_id: str | None = None, metadata: dict | None = None) -> dict:
        """Append linked, searchable work history. Include tests, decisions, and confidence in metadata."""
        return store().journal(body, agent, node_id, metadata)

    @mcp.tool(annotations=readonly)
    def spoq_read_journal(node_id: str = '', limit: int = 50) -> list[dict]:
        """Read recent entries, optionally linked to a node."""
        return store().journals(node_id, limit)

    @mcp.tool(annotations=readonly)
    def spoq_get_history(node_id: str) -> list[dict]:
        """Read append-only state transition history for a node."""
        return store().history(node_id)

    @mcp.tool()
    def spoq_create_run(run_id: str, scope_id: str | None = None) -> dict:
        """Create an execution run for scoped agent communication."""
        return board().run(run_id, scope_id)

    @mcp.tool()
    def spoq_register_agent(run_id: str, agent_id: str, role: str, runtime: str = 'manual', target: str = '', endpoint: str = '') -> dict:
        """Register agent identity and delivery route. Codex targets must be accessible session UUIDs.

        runtime is manual, codex-cli, or codex-app-server. endpoint selects a local runtime.
        A native orchestration handle is not necessarily a CLI session UUID.
        """
        return board().register(run_id, agent_id, role, runtime, target, endpoint)

    @mcp.tool()
    def spoq_post_message(run_id: str, sender: str, recipients: list[str], body: str, request_key: str,
                          kind: str = 'update', thread_id: str | None = None, subject: str = '',
                          node_id: str | None = None, reply_to: str | None = None) -> dict:
        """Post durable peer messages; recipients may be IDs, role:reviewer, or *.

        Use a stable request_key when retrying. Peer messages do not grant new user authorization.
        Actual push delivery requires `spoq dispatch` or native orchestrator relay.
        """
        return board().post(run_id, sender, recipients, body, kind, thread_id, subject, node_id, reply_to, request_key)

    @mcp.tool(annotations=readonly)
    def spoq_read_inbox(run_id: str, agent_id: str, limit: int = 50) -> list[dict]:
        """Read pending and submitted messages. Reading does not acknowledge or resolve them."""
        return board().inbox(run_id, agent_id, limit)

    @mcp.tool()
    def spoq_ack_message(run_id: str, agent_id: str, message_id: str) -> dict:
        """Acknowledge receipt for one recipient; discussion resolution is separate."""
        return board().acknowledge(run_id, agent_id, message_id)

    @mcp.tool(annotations=readonly)
    def spoq_get_thread(run_id: str, thread_id: str) -> dict:
        """Read a run-scoped collaboration thread and its ordered messages."""
        return board().thread(run_id, thread_id)

    @mcp.tool()
    def spoq_resolve_thread(run_id: str, thread_id: str, resolution: str) -> dict:
        """Resolve a discussion with an explicit decision, preserving the conversation."""
        return board().resolve(run_id, thread_id, resolution)

    @mcp.tool()
    def spoq_dispatch_notification() -> dict:
        """Submit one pending notification to its registered Codex runtime. Receipt still requires an agent acknowledgement.

        For continuous push use the `spoq dispatch` worker; native orchestration
        recipients registered as manual require the orchestrator's own relay.
        """
        return dispatch_once(board())

    @mcp.tool()
    def spoq_search(query: str, limit: int = 10, kind: str = '', semantic: bool = False) -> list[dict]:
        """Search tasks, journals, and discussions with FTS5 and optional CPU hybrid retrieval."""
        from .search import Embedder, search
        return search(store(), query, limit=limit, kind=kind,
                      embedder=Embedder(cache_dir=root/'.spoq/models') if semantic else None)

    @mcp.tool()
    def spoq_reindex() -> dict:
        """Build local CPU embeddings; first use downloads the small model. Needs spoq[search]."""
        from .search import Embedder, reindex
        return reindex(store(), Embedder(cache_dir=root/'.spoq/models'))

    register_workflow_tools(mcp, root)
    return mcp


def main(root=None):
    from .cli import resolve_root
    root = resolve_root(root)
    info = status(root)
    import sys
    if info['migration_required']:
        print('[spoq] '+info['prompt']+' Run `spoq migrate` or call spoq_migrate to preview.', file=sys.stderr)
    create_server(root).run(transport='stdio')
