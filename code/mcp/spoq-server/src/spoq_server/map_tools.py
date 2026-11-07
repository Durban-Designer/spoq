"""Map management MCP tools for SPOQ.

Maps coordinate multiple epics through wave-based parallel execution.
These tools mirror the epic tools pattern, operating at the inter-epic level.
"""

import json
from pathlib import Path

from spoq_server.server import mcp
from spoq_server import map_utils


def _store():
    """Return the single shared store instance selected at server init.

    The instance is injected by the server — this module never constructs its
    own store. Resolved at call time so a server reload under a patched
    ``SPOQ_STORE`` is observed.
    """
    from spoq_server.server import get_store

    return get_store()


def _resolve_map_path(map_path: str):
    """Resolve map path relative to project root (via the store)."""
    return _store()._resolve(map_path)


def _default_epics_base():
    """Return default epics base directory (via the store)."""
    return _store()._resolve("spoq/epics/active")


@mcp.tool()
def spoq_parse_map(map_path: str, epics_base: str = "") -> str:
    """Parse a map and return metadata, epics (with resolution status), and stats.

    Accepts either a directory containing MAP.md or a standalone .md file.

    Args:
        map_path: Path to map directory or .md file
                  (absolute or relative to project root).
                  Examples: "spoq/maps/active/example-project",
                            "spoq/maps/active/example-project.md"
        epics_base: Base directory where epic directories live.
                    Defaults to "spoq/epics/active/".
    """
    try:
        mu = map_utils
        resolved = _resolve_map_path(map_path)

        if not resolved.exists():
            return json.dumps({"error": f"Map not found: {resolved}"})

        if epics_base:
            eb = _store()._resolve(epics_base)
        else:
            eb = _default_epics_base()

        result = mu.parse_map(resolved, eb)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_validate_map(map_path: str, strict: bool = False) -> str:
    """Validate a map's structure, epic entries, and dependency graph.

    Accepts either a directory containing MAP.md or a standalone .md file.

    Args:
        map_path: Path to map directory or .md file.
        strict: If true, warnings become errors.

    Returns JSON with errors[], warnings[], and summary.
    """
    try:
        mu = map_utils
        resolved = _resolve_map_path(map_path)

        if not resolved.exists():
            return json.dumps({"error": f"Map not found: {resolved}"})

        errors = []
        warnings = []

        # Validate MAP.md structure
        md_errors = mu.validate_map_md_structure(resolved)
        for err in md_errors:
            if "recommend" in err.lower() and not strict:
                warnings.append(err)
            else:
                errors.append(err)

        # Parse epic entries for dependency validation
        metadata = mu.parse_map_md(resolved)
        if "error" in metadata:
            errors.append(metadata["error"])
        else:
            epics = metadata["epics"]

            # Validate dependencies reference existing slugs
            dep_errors = mu.validate_map_dependencies(epics)
            errors.extend(dep_errors)

            # Detect cycles
            cycle_errors = mu.detect_epic_cycles(epics)
            errors.extend(cycle_errors)

        summary = {
            "valid": len(errors) == 0,
            "total_epics": len(metadata.get("epics", [])),
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

        return json.dumps({
            "errors": errors,
            "warnings": warnings,
            "summary": summary,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_compute_epic_waves(
    map_path: str, critical_path: bool = False
) -> str:
    """Compute execution waves from the inter-epic dependency graph.

    Accepts either a directory containing MAP.md or a standalone .md file.

    Args:
        map_path: Path to map directory or .md file.
        critical_path: Include critical path analysis in output.

    Returns JSON with waves[], each containing epic details.
    """
    try:
        mu = map_utils
        resolved = _resolve_map_path(map_path)

        metadata = mu.parse_map_md(resolved)
        if "error" in metadata:
            return json.dumps(metadata)

        epics = metadata["epics"]
        if not epics:
            return json.dumps({"error": "No epics found in map"})

        waves_map = mu.compute_epic_waves(epics)
        wave_groups = mu.group_epic_waves(waves_map)
        epic_map = {e["slug"]: e for e in epics}

        waves = []
        for wave_num in sorted(wave_groups.keys()):
            slugs = wave_groups[wave_num]
            wave_epics = []
            for slug in sorted(slugs):
                epic = epic_map.get(slug, {})
                wave_epics.append({
                    "slug": slug,
                    "status": epic.get("status", "pending"),
                    "dependencies": epic.get("dependencies", []),
                })
            waves.append({
                "wave": wave_num,
                "epic_count": len(wave_epics),
                "epics": wave_epics,
            })

        output = {
            "map_name": metadata["title"],
            "total_waves": len(waves),
            "total_epics": len(epics),
            "waves": waves,
        }

        if critical_path:
            cp_slugs, _ = mu.compute_epic_critical_path(
                epics, waves_map
            )
            output["critical_path"] = {
                "epics": cp_slugs,
                "length": len(cp_slugs),
            }

        return json.dumps(output, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_analyze_map_dag(map_path: str) -> str:
    """Analyze the inter-epic DAG for critical path and parallelism metrics.

    Accepts either a directory containing MAP.md or a standalone .md file.

    Args:
        map_path: Path to map directory or .md file.

    Returns JSON with critical_path and parallelism analysis.
    """
    try:
        mu = map_utils
        resolved = _resolve_map_path(map_path)

        metadata = mu.parse_map_md(resolved)
        if "error" in metadata:
            return json.dumps(metadata)

        epics = metadata["epics"]
        if not epics:
            return json.dumps({"error": "No epics found in map"})

        waves = mu.compute_epic_waves(epics)
        metrics = mu.compute_map_metrics(epics, waves)
        cp_slugs, cp_length = mu.compute_epic_critical_path(epics, waves)

        return json.dumps({
            "map_name": metadata["title"],
            "total_epics": len(epics),
            "critical_path": {
                "epics": cp_slugs,
                "length": cp_length,
            },
            "parallelism": {
                "wave_count": metrics["wave_count"],
                "max_parallelism": metrics["max_parallelism"],
                "wave0_count": metrics["wave0_count"],
                "wave0_ratio": metrics["wave0_ratio"],
                "waves": {
                    str(k): v for k, v in metrics["waves"].items()
                },
            },
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_get_map_status(map_path: str, epics_base: str = "") -> str:
    """Get per-epic status rollup and overall map progress.

    For resolved epics (those with directories on disk), reads task YAML
    files to determine completion. For unresolved epics, reports the
    status from the map file.

    Accepts either a directory containing MAP.md or a standalone .md file.

    Args:
        map_path: Path to map directory or .md file.
        epics_base: Base directory where epic directories live.
                    Defaults to "spoq/epics/active/".
    """
    try:
        mu = map_utils
        resolved = _resolve_map_path(map_path)

        if not resolved.exists():
            return json.dumps({"error": f"Map not found: {resolved}"})

        if epics_base:
            eb = _store()._resolve(epics_base)
        else:
            eb = _default_epics_base()

        result = mu.get_map_status(resolved, eb)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_list_maps(base_path: str = "") -> str:
    """List all maps in backlog, active, and complete directories.

    Args:
        base_path: Base path to spoq/maps/. Defaults to project root's
                   spoq/maps/ directory.

    Returns JSON with backlog[], active[], and complete[] map lists.
    """
    try:
        mu = map_utils

        if base_path:
            bp = _store()._resolve(base_path)
        else:
            bp = _store()._resolve("spoq/maps")

        active_dir = bp / "active"
        complete_dir = bp / "complete"
        backlog_dir = bp / "backlog"

        def scan_maps(directory: Path) -> list[dict]:
            maps = []
            if not directory.exists():
                return maps
            for entry in sorted(directory.iterdir()):
                # Directory format: entry/MAP.md
                if entry.is_dir() and (entry / "MAP.md").exists():
                    metadata = mu.parse_map_md(entry)
                    if "error" not in metadata:
                        maps.append({
                            "slug": entry.name,
                            "title": metadata["title"],
                            "epic_count": len(metadata.get("epics", [])),
                            "path": str(entry),
                        })
                # Single-file format: entry.md (skip dotfiles, .gitkeep, etc.)
                elif (
                    entry.is_file()
                    and entry.suffix.lower() == ".md"
                    and not entry.name.startswith(".")
                ):
                    metadata = mu.parse_map_md(entry)
                    if "error" not in metadata:
                        maps.append({
                            "slug": entry.stem,
                            "title": metadata["title"],
                            "epic_count": len(metadata.get("epics", [])),
                            "path": str(entry),
                        })
            return maps

        backlog = scan_maps(backlog_dir)
        active = scan_maps(active_dir)
        complete = scan_maps(complete_dir)

        return json.dumps({
            "backlog": backlog,
            "active": active,
            "complete": complete,
            "total_backlog": len(backlog),
            "total_active": len(active),
            "total_complete": len(complete),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def spoq_generate_map_skeleton(
    name: str, epic_count: int, path: str = ""
) -> str:
    """Generate a map skeleton directory with a templated MAP.md.

    Creates a MAP.md pre-populated with epic entries distributed across
    waves (~30% Wave 0, ~40% Wave 1, ~30% later). Each later-wave epic
    auto-depends on an earlier-wave epic for a realistic DAG.

    Args:
        name: Map name (converted to slug).
        epic_count: Number of epic entries to generate (minimum 2).
        path: Base path for the map. Defaults to spoq/maps/active/.

    Returns JSON with map_path, epic_count, and paths_created.
    """
    try:
        if epic_count < 2:
            return json.dumps({
                "error": "Minimum 2 epics required for a valid map"
            })

        map_slug = name.lower().replace(" ", "-").replace("_", "-")

        if path:
            base = _store()._resolve(path)
        else:
            base = _store()._resolve("spoq/maps/active")

        map_path = base / map_slug

        if map_path.exists():
            return json.dumps({
                "error": f"Map already exists: {map_path}"
            })

        _store().create_map_dir(map_path)

        # Distribute epics across waves: ~30% Wave 0, ~40% Wave 1, rest later
        wave0_count = max(1, int(epic_count * 0.3))
        wave1_count = max(1, int(epic_count * 0.4))
        later_count = epic_count - wave0_count - wave1_count

        epic_entries = []
        wave0_slugs = []
        wave1_slugs = []
        idx = 1

        for i in range(wave0_count):
            slug = f"epic-{idx:02d}-component"
            wave0_slugs.append(slug)
            epic_entries.append({
                "slug": slug,
                "wave": 0,
                "deps": "none",
            })
            idx += 1

        for i in range(wave1_count):
            slug = f"epic-{idx:02d}-component"
            wave1_slugs.append(slug)
            dep = wave0_slugs[i % len(wave0_slugs)]
            epic_entries.append({
                "slug": slug,
                "wave": 1,
                "deps": f"[{dep}]",
            })
            idx += 1

        for i in range(later_count):
            slug = f"epic-{idx:02d}-component"
            dep = wave1_slugs[i % max(1, len(wave1_slugs))]
            epic_entries.append({
                "slug": slug,
                "wave": 2 + (i // max(1, later_count)),
                "deps": f"[{dep}]",
            })
            idx += 1

        # Build MAP.md content
        epics_section = ""
        for e in epic_entries:
            epics_section += f"""
### {e['slug']}
- **Status:** pending
- **Dependencies:** {e['deps']}
- **Summary:** [TODO: Describe scope and deliverables for this epic]
"""

        # Build dispatch strategy
        wave_groups: dict[int, list[str]] = {}
        for e in epic_entries:
            wave_groups.setdefault(e["wave"], []).append(e["slug"])

        dispatch_lines = ""
        for wn in sorted(wave_groups.keys()):
            slugs = ", ".join(wave_groups[wn])
            dispatch_lines += (
                f"**Wave {wn}:** {slugs}\n"
                f"- [TODO: Describe this wave's focus]\n\n"
            )

        # Build DAG ascii
        dag_lines = ""
        for wn in sorted(wave_groups.keys()):
            slugs_str = ", ".join(wave_groups[wn])
            dag_lines += f"Wave {wn}:\n    {slugs_str}\n"

        content = f"""# Map: {name.title()}

## Vision

[TODO: 2-5 sentences describing the program-level objective. What outcome does completing all epics achieve?]

## Program Structure

```
[TODO: ASCII diagram showing epic relationships and data flow]
```

## Epics
{epics_section}
## Epic Dependencies

```
{dag_lines}```

## Dispatch Strategy

{dispatch_lines}
## Success Criteria

- [ ] [Program-level criterion spanning multiple epics]
- [ ] [End-to-end workflow verification across epic boundaries]
- [ ] [Performance or quality target for the assembled system]
- [ ] [Integration test covering cross-epic interfaces]
- [ ] [Deployment or operational readiness check]

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [Cross-epic interface mismatch] | Medium | High | [Define interfaces in Wave 0] |
| [Scope creep across epics] | Medium | Medium | [Freeze scope per-epic before Wave 1] |
| [Integration complexity] | Low | High | [Incremental integration tests per wave] |
"""

        map_file = map_path / "MAP.md"
        _store().write_map_file(map_file, content)

        return json.dumps({
            "map_path": str(map_path),
            "map_name": map_slug,
            "epic_count": epic_count,
            "wave_distribution": {
                "wave_0": wave0_count,
                "wave_1": wave1_count,
                "later": later_count,
            },
            "paths_created": [str(map_path), str(map_file)],
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Feature-aliased tools (SDLC-hierarchy uprev, design §4.2)
#
# In the SDLC language canon a "Feature" IS a map on disk — same directory
# (``spoq/maps/``), same ``MAP.md`` file, same ``MapDoc`` internals. These
# tools are THIN aliases that delegate 1:1 to their ``spoq_*_map`` counterpart
# so the customer-facing "feature" verb returns byte-identical payloads without
# forking any logic. The ``spoq_*_map`` tools stay registered and unchanged.
# ---------------------------------------------------------------------------


@mcp.tool()
def spoq_list_features(base_path: str = "") -> str:
    """List all features (alias of spoq_list_maps; features are maps on disk).

    Args:
        base_path: Base path to spoq/maps/. Defaults to project root's
                   spoq/maps/ directory.

    Returns the same JSON as spoq_list_maps.
    """
    return spoq_list_maps(base_path)


@mcp.tool()
def spoq_parse_feature(map_path: str, epics_base: str = "") -> str:
    """Parse a feature MAP.md incl. leading frontmatter (alias of spoq_parse_map).

    Surfaces the MAP.md frontmatter (slug/title/tier/version/projects) alongside
    the parsed epics and stats.

    Args:
        map_path: Path to feature/map directory or .md file.
        epics_base: Base directory where epic directories live.
                    Defaults to "spoq/epics/active/".

    Returns the same JSON as spoq_parse_map.
    """
    return spoq_parse_map(map_path, epics_base)


@mcp.tool()
def spoq_validate_feature(map_path: str, strict: bool = False) -> str:
    """Validate a feature MAP.md (alias of spoq_validate_map).

    Args:
        map_path: Path to feature/map directory or .md file.
        strict: If true, warnings become errors.

    Returns the same JSON as spoq_validate_map.
    """
    return spoq_validate_map(map_path, strict)


@mcp.tool()
def spoq_get_feature_status(map_path: str, epics_base: str = "") -> str:
    """Feature status rollup (alias of spoq_get_map_status).

    Args:
        map_path: Path to feature/map directory or .md file.
        epics_base: Base directory where epic directories live.
                    Defaults to "spoq/epics/active/".

    Returns the same JSON as spoq_get_map_status.
    """
    return spoq_get_map_status(map_path, epics_base)
