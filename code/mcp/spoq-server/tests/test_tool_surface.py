"""Tool-surface snapshot guard (mcp-06).

The load-bearing guarantee of the whole storage-abstraction epic is that the MCP
*tool surface* — every tool name plus its input-schema fingerprint — does not
drift while the backend is re-pointed from filesystem to API. Downstream skills
(/agent-execution, /workflow-execute, /epic-planning, /jira-sync) hard-code tool
names and argument shapes; any rename, removal, addition, or schema change would
silently break them.

The reference baseline ``tests/fixtures/tool_surface_v0.5.1.json`` was captured
from the pristine v0.5.1 server HEAD (task mcp-01) *before* the refactor began.
This test re-derives the live surface and asserts it is byte-for-byte identical
to that baseline. The baseline is intentionally version-pinned at 0.5.1 and must
stay unchanged through the 0.6.0 version bump (task mcp-07): the version string
lives in package metadata, not in a tool name or schema, so a bump does not — and
must not — perturb the surface this test compares.

A mismatch is a hard failure: if the drift is intentional the operator must
regenerate the snapshot AND justify the surface change; it is never an automatic
pass.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from spoq_server.server import mcp

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "tool_surface_v0.5.1.json"

# Feature-aliased tools ADDED in the 0.7.0 SDLC-hierarchy uprev (design §4.2).
# They are thin wrappers over the ``spoq_*_map`` verbs — a deliberate, purely
# additive surface change over the v0.5.1 baseline. The baseline fixture stays
# pinned at 27 map-era tools; these four are the ONLY sanctioned additions.
FEATURE_ALIAS_TOOLS = {
    "spoq_list_features",
    "spoq_parse_feature",
    "spoq_validate_feature",
    "spoq_get_feature_status",
}


def _fingerprint(name: str, input_schema: Any) -> dict[str, Any]:
    """Stable per-tool representation: its name + input schema, JSON-roundtripped.

    The JSON round-trip normalizes key ordering and tuple/list/Pydantic quirks so
    the comparison is on structure, not on Python object identity or dict order.
    """
    return json.loads(json.dumps({"name": name, "inputSchema": input_schema}, sort_keys=True))


def _live_surface() -> list[dict[str, Any]]:
    """Derive the live tool surface from the running FastMCP instance.

    ``mcp.list_tools`` is async (it is the MCP server's tool-discovery entry
    point — exactly what a client sees), so it is driven on a private event loop
    here. Returns the fingerprints sorted by name for a deterministic compare.
    """
    tools = asyncio.run(mcp.list_tools())
    surface = [_fingerprint(t.name, t.inputSchema) for t in tools]
    return sorted(surface, key=lambda x: x["name"])


def _committed_surface() -> list[dict[str, Any]]:
    """Load the committed baseline and reduce it to the same fingerprint shape."""
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    tools = snapshot["tools"]
    surface = [_fingerprint(t["name"], t["inputSchema"]) for t in tools]
    return sorted(surface, key=lambda x: x["name"])


def test_snapshot_baseline_present_and_pinned_to_v051():
    """The committed baseline exists, is well-formed, and is the v0.5.1 capture."""
    assert SNAPSHOT_PATH.exists(), f"missing baseline: {SNAPSHOT_PATH}"
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot["version"] == "0.5.1", "baseline must remain the v0.5.1 capture"
    assert snapshot["tool_count"] == len(snapshot["tools"]) == 27


def test_tool_count_matches_baseline_plus_feature_aliases():
    """Live surface = baseline + exactly the four sanctioned feature aliases.

    The only surface growth permitted over the v0.5.1 baseline is the four
    feature-aliased tools added in 0.7.0. Any other count delta is drift.
    """
    live = _live_surface()
    committed = _committed_surface()
    assert len(live) == len(committed) + len(FEATURE_ALIAS_TOOLS), (
        f"tool count drifted: live={len(live)} "
        f"baseline={len(committed)} + feature_aliases={len(FEATURE_ALIAS_TOOLS)}"
    )


def test_tool_names_only_grow_by_feature_aliases():
    """Every baseline tool is still present; the ONLY additions are the aliases."""
    live_names = {t["name"] for t in _live_surface()}
    committed_names = {t["name"] for t in _committed_surface()}
    added = live_names - committed_names
    removed = committed_names - live_names
    assert added == FEATURE_ALIAS_TOOLS, (
        f"unexpected tool additions vs v0.5.1 baseline: "
        f"{sorted(added - FEATURE_ALIAS_TOOLS)}"
    )
    assert not removed, f"tools REMOVED since v0.5.1 baseline: {sorted(removed)}"


def test_feature_alias_tools_registered_alongside_map_tools():
    """The four feature aliases AND their map counterparts are all registered.

    Asserts the alias tools joined the surface without displacing any
    ``spoq_*_map`` verb (design §4.2: alias only, no rename/removal).
    """
    live_names = {t["name"] for t in _live_surface()}
    map_counterparts = {
        "spoq_list_maps",
        "spoq_parse_map",
        "spoq_validate_map",
        "spoq_get_map_status",
    }
    missing_features = FEATURE_ALIAS_TOOLS - live_names
    assert not missing_features, f"feature alias tools not registered: {sorted(missing_features)}"
    missing_maps = map_counterparts - live_names
    assert not missing_maps, f"map tools missing (must not be renamed/removed): {sorted(missing_maps)}"


def test_baseline_tool_schemas_unchanged():
    """Every BASELINE tool's name+schema is byte-for-byte identical to v0.5.1.

    This is the hard gate against silent schema drift: the four feature aliases
    are permitted additions (asserted separately), but no existing v0.5.1 tool
    may change its input schema. If a baseline drift is intentional, regenerate
    the snapshot and justify the surface change in review.
    """
    committed = _committed_surface()
    committed_names = {t["name"] for t in committed}
    # Restrict the live surface to the baseline tools; the additive feature
    # aliases are validated by the dedicated registration/count tests.
    live_baseline = [t for t in _live_surface() if t["name"] in committed_names]
    if live_baseline != committed:
        live_by = {t["name"]: t["inputSchema"] for t in live_baseline}
        committed_by = {t["name"]: t["inputSchema"] for t in committed}
        drifted = [
            name
            for name in sorted(set(live_by) & set(committed_by))
            if live_by[name] != committed_by[name]
        ]
        raise AssertionError(
            "MCP tool surface drifted from the v0.5.1 baseline. "
            f"schema-changed tools: {drifted}. "
            "If intentional, regenerate tests/fixtures/tool_surface_v0.5.1.json "
            "and justify the change in review."
        )
