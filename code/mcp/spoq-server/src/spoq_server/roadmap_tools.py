"""Roadmap management MCP tools for SPOQ.

Provides tools for viewing and syncing the ROADMAP.yml file that tracks
the 3-tier epic lifecycle: backlog -> active -> complete.
"""

import json

from spoq_server.server import mcp, project_root
from spoq_server import roadmap_utils


def _store():
    """Return the single shared store instance selected at server init.

    The instance is injected by the server — this module never constructs its
    own store. Resolved at call time so a server reload under a patched
    ``SPOQ_STORE`` is observed.

    The module-local :func:`project_root` reference is passed to ``get_store``
    as the fs-mode root resolver so a test patching
    ``roadmap_tools.project_root`` anchors the store at its tmpdir; api mode
    ignores the resolver.
    """
    from spoq_server.server import get_store

    return get_store(project_root)


@mcp.tool()
def spoq_roadmap_show(tier: str = "", format: str = "table") -> str:
    """Display the project roadmap, optionally filtered by lifecycle tier.

    Args:
        tier: Filter by lifecycle tier. Accepts "" (all), "backlog",
              "active", or "complete".
        format: Output style. "table" returns a markdown table,
                "json" returns raw structured data.

    Returns JSON with {rendered: str, epics: list, counts: dict}.
    """
    try:
        store = _store()
        spoq_dir = str(project_root() / "spoq")
        roadmap_path = store._resolve("spoq") / roadmap_utils.ROADMAP_FILENAME

        if not roadmap_path.exists():
            return json.dumps({
                "error": "ROADMAP.yml not found",
                "expected_path": str(roadmap_path),
            })

        data = store.load_roadmap_dict(spoq_dir)
        epics = data.get("epics", [])

        # Filter by tier if specified
        if tier:
            if tier not in roadmap_utils.VALID_TIERS:
                return json.dumps({
                    "error": f"Invalid tier '{tier}'. Must be one of: backlog, active, complete",
                })
            epics = [e for e in epics if e.get("tier") == tier]

        # Build counts
        counts = {"backlog": 0, "active": 0, "complete": 0, "total": len(epics)}
        for e in epics:
            t = e.get("tier", "backlog")
            if t in counts:
                counts[t] += 1

        # Render output
        if format == "json":
            rendered = json.dumps(epics, default=str)
        else:
            filtered_data = {"epics": epics}
            rendered = roadmap_utils.render_table(filtered_data)

        return json.dumps({
            "rendered": rendered,
            "epics": epics,
            "counts": counts,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_roadmap_sync() -> str:
    """Synchronize ROADMAP.yml with on-disk epic directories.

    Scans spoq/epics/{backlog,active,complete} directories to discover
    epic directories. Compares against current ROADMAP.yml entries and
    reconciles: adds missing entries, removes stale ones, and updates
    tier assignments based on directory location.

    If ROADMAP.yml does not exist yet, every discovered epic is treated
    as "added".

    Returns JSON with {added: list, removed: list, updated: list,
    warnings: list, roadmap: dict}.
    """
    try:
        store = _store()
        spoq_dir = str(project_root() / "spoq")
        roadmap_path = store._resolve("spoq") / roadmap_utils.ROADMAP_FILENAME

        # Capture state before sync
        is_new = not roadmap_path.exists()
        before = store.load_roadmap_dict(spoq_dir)
        before_slugs = {e["slug"] for e in before.get("epics", [])}
        before_tiers = {
            e["slug"]: e.get("tier") for e in before.get("epics", [])
        }

        # Perform sync
        warnings: list[str] = []
        after = store.sync_roadmap_from_disk(spoq_dir, warnings=warnings)
        after_slugs = {e["slug"] for e in after.get("epics", [])}
        after_tiers = {
            e["slug"]: e.get("tier") for e in after.get("epics", [])
        }

        # Compute diffs
        added = sorted(after_slugs - before_slugs)
        removed = sorted(before_slugs - after_slugs)
        updated = sorted(
            slug for slug in (before_slugs & after_slugs)
            if before_tiers.get(slug) != after_tiers.get(slug)
        )

        # Persist
        store.save_roadmap_dict(after, spoq_dir)

        return json.dumps({
            "added": added,
            "removed": removed,
            "updated": updated,
            "warnings": warnings,
            "new_file": is_new,
            "roadmap": after,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
