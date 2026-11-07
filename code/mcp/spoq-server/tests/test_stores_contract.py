"""Contract tests for the storage abstraction layer (stores/).

These assert real behavior of the new ABCs and record types introduced by
task 01-store-interface, plus a pristine tool-surface snapshot guard so the
later refactor cannot silently change a tool name or input schema.
"""

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from spoq_server.stores import (
    Epic,
    EpicStore,
    MapDoc,
    MapStore,
    RoadmapEntry,
    RoadmapStore,
    Task,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SURFACE_FIXTURE = FIXTURES_DIR / "tool_surface_v0.5.1.json"

# Feature-aliased tools added in the 0.7.0 SDLC-hierarchy uprev (design §4.2):
# thin wrappers over the ``spoq_*_map`` verbs. They are a deliberate, purely
# additive surface change over the v0.5.1 baseline — the baseline fixture stays
# pinned at 27 map-era tools, and these four are the ONLY sanctioned additions.
FEATURE_ALIAS_TOOLS = {
    "spoq_list_features",
    "spoq_parse_feature",
    "spoq_validate_feature",
    "spoq_get_feature_status",
}


# --- ABCs are abstract --------------------------------------------------------

@pytest.mark.parametrize("abc_cls", [EpicStore, MapStore, RoadmapStore])
def test_store_abcs_cannot_be_instantiated(abc_cls):
    """Each store ABC must be abstract (has abstract methods)."""
    with pytest.raises(TypeError):
        abc_cls()
    assert abc_cls.__abstractmethods__, f"{abc_cls.__name__} declares no abstract methods"


# --- Method set matches the acceptance criteria exactly -----------------------

def _abstract_names(cls) -> set[str]:
    return set(cls.__abstractmethods__)


def test_epic_store_declares_required_methods():
    """EpicStore declares exactly the methods named in the task AC."""
    expected = {
        "load_epic", "list_epics", "load_tasks", "get_task", "update_task",
        "create_epic", "create_task", "promote_epic", "demote_epic",
        "complete_epic", "archive_epic",
    }
    assert _abstract_names(EpicStore) == expected


def test_map_store_declares_required_methods():
    assert _abstract_names(MapStore) == {"parse_map", "list_maps", "update_map"}


def test_roadmap_store_declares_required_methods():
    assert _abstract_names(RoadmapStore) == {
        "load_roadmap", "save_roadmap", "sync_roadmap", "show_roadmap",
    }


@pytest.mark.parametrize("abc_cls", [EpicStore, MapStore, RoadmapStore])
def test_every_abstract_method_has_a_consumer_docstring(abc_cls):
    """Each abstract method docstring names the tool(s) that consume it."""
    for name in abc_cls.__abstractmethods__:
        method = getattr(abc_cls, name)
        doc = inspect.getdoc(method) or ""
        assert "Consumed by:" in doc, f"{abc_cls.__name__}.{name} missing 'Consumed by:'"


def test_concrete_subclass_must_implement_all_methods():
    """A subclass missing an abstract method stays un-instantiable."""

    class Partial(EpicStore):
        def load_epic(self, path):  # only one of many
            return Epic(id="x", title="x")

    with pytest.raises(TypeError):
        Partial()


# --- Record shape fidelity ----------------------------------------------------

def test_task_from_dict_mirrors_parse_task_yaml():
    """Task.from_dict round-trips the dict shape parse_task_yaml produces."""
    from spoq_server import epic_utils

    fixture = next((FIXTURES_DIR / "test-epic" / "tasks").glob("*.yml"))
    parsed = epic_utils.parse_task_yaml(fixture)
    assert "error" not in parsed

    task = Task.from_dict(parsed)
    assert task.id == parsed["id"]
    assert task.title == parsed["title"]
    assert task.status == parsed["status"]
    # _source_file maps onto source_file and round-trips back.
    assert task.source_file == parsed["_source_file"]
    assert task.to_dict()["_source_file"] == parsed["_source_file"]


def test_task_to_dict_omits_unset_optionals():
    """Optional bookkeeping keys absent on input are absent on output."""
    task = Task(id="01-x", title="T", description="d")
    out = task.to_dict()
    assert "last_update" not in out
    assert "progress_notes" not in out
    assert "_source_file" not in out
    # Required + defaulted keys are always present.
    assert out["status"] == "pending"
    assert out["dependencies"] == []


def test_mapdoc_from_dict_mirrors_parse_map_md():
    from spoq_server import map_utils

    parsed = map_utils.parse_map_md(FIXTURES_DIR / "test-map")
    assert "error" not in parsed
    doc = MapDoc.from_dict("test-map", parsed)
    assert doc.id == "test-map"
    assert doc.title == parsed["title"]
    assert doc.epics == parsed["epics"]


def test_roadmap_entry_round_trips_required_and_optional():
    entry = RoadmapEntry.from_dict({
        "slug": "e", "title": "E", "tier": "active", "status": "pending",
        "completed_date": None, "extra_ignored": "drop me",
    })
    out = entry.to_dict()
    assert out == {"slug": "e", "title": "E", "tier": "active", "status": "pending"}
    # None optionals are dropped; unknown keys never enter the record.
    assert "completed_date" not in out
    assert "extra_ignored" not in out


# --- Pristine tool-surface snapshot guard -------------------------------------

def _current_surface() -> dict:
    from spoq_server import __version__
    from spoq_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {
        "package": "spoq",
        "version": __version__,
        "tool_count": len(tools),
        "tools": sorted(
            [{"name": t.name, "inputSchema": t.inputSchema} for t in tools],
            key=lambda d: d["name"],
        ),
    }


def test_tool_surface_snapshot_exists_and_is_well_formed():
    assert SURFACE_FIXTURE.exists(), "pristine tool-surface fixture missing"
    data = json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    assert data["version"] == "0.5.1"
    assert data["tool_count"] == len(data["tools"]) > 0
    names = [t["name"] for t in data["tools"]]
    assert names == sorted(names)


def test_tool_surface_matches_pristine_snapshot():
    """Every v0.5.1 baseline tool + schema is unchanged; the only surface growth
    is the four feature aliases added in 0.7.0 (design §4.2, alias-only).

    This is the contract mcp-06 asserts is unchanged through the refactor,
    extended for the sanctioned feature-alias additions: no baseline tool may be
    renamed, removed, or have its input schema drift.
    """
    snapshot = json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    current = _current_surface()

    baseline_names = {t["name"] for t in snapshot["tools"]}
    current_names = {t["name"] for t in current["tools"]}
    added = current_names - baseline_names
    removed = baseline_names - current_names
    assert added == FEATURE_ALIAS_TOOLS, (
        f"unexpected tool additions vs v0.5.1 baseline: {sorted(added - FEATURE_ALIAS_TOOLS)}"
    )
    assert not removed, f"tools removed since v0.5.1 baseline: {sorted(removed)}"

    # Baseline tools are byte-for-byte identical (both lists are name-sorted).
    current_baseline = [t for t in current["tools"] if t["name"] in baseline_names]
    assert current_baseline == snapshot["tools"]
    assert current["tool_count"] == snapshot["tool_count"] + len(FEATURE_ALIAS_TOOLS)
