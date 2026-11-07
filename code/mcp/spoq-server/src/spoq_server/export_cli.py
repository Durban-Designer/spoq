"""``spoq export`` — snapshot the live SPOQ store back into an on-disk YAML tree.

This legacy command creates a reviewable filesystem snapshot through the
store abstraction. The SQLite CLI uses its separate JSON snapshot commands.
The filesystem snapshot layout is:

    <out>/epics/<tier>/<slug>/EPIC.md          (frontmatter + body)
    <out>/epics/<tier>/<slug>/tasks/<id>.yml   (one file per task)
    <out>/maps/<tier>/<slug>/MAP.md            (frontmatter + body)
    <out>/ROADMAP.yml

so ``spoq_validate_epic`` in fs mode accepts the output directory and the
round-trip property (import(export(store)) is a no-op) is auditable.

**Freeze guard (non-negotiable):** the exporter refuses to write into the
frozen workspace ``spoq/`` tree. ``freeze_guard`` is called before any write;
it raises :class:`SystemExit` when ``--out`` resolves at or inside
:data:`WORKSPACE_SPOQ`. It must never be softened to make a test pass — fix the
test instead.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from spoq_server.server import project_root

# Protect the active project tree in both installed and source layouts.
WORKSPACE_SPOQ = project_root() / "spoq"

# --- freeze guard ------------------------------------------------------------


def freeze_guard(out_dir: Path) -> None:
    """Refuse to export into the frozen workspace ``spoq/`` tree.

    Raises :class:`SystemExit` (non-zero) with a clear message when *out_dir*
    resolves *at* the frozen tree or *inside* it. A sibling path that merely
    shares a name prefix (e.g. ``.../spoq-export``) is allowed — the check is on
    resolved path identity / parent containment, not string prefixes.
    """
    resolved = Path(out_dir).resolve()
    spoq_resolved = WORKSPACE_SPOQ.resolve()
    if resolved == spoq_resolved or spoq_resolved in resolved.parents:
        raise SystemExit(
            f"EXPORT REFUSED: --out {out_dir} resolves inside the frozen "
            f"spoq/ tree ({spoq_resolved}). Choose a path outside the workspace."
        )
    # Also refuse the inverse nesting: writing a parent that *contains* the
    # frozen tree would let a later step clobber it. e.g. --out=<workspace root>.
    if resolved in spoq_resolved.parents:
        raise SystemExit(
            f"EXPORT REFUSED: --out {out_dir} ({resolved}) contains the frozen "
            f"spoq/ tree ({spoq_resolved}). Choose a path outside the workspace."
        )


# --- record/dict normalization ----------------------------------------------


def _as_dict(obj: Any) -> dict[str, Any]:
    """Return a plain dict view of a store record or an already-plain dict."""
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"cannot normalize {type(obj)!r} to a dict")


def _epic_body(epic: dict[str, Any]) -> str:
    """Resolve the EPIC.md markdown body from whatever the backend supplied.

    The fs store carries the parsed sections under ``metadata``; other store implementations
    stashes the raw markdown under ``metadata['bodyMd']``. A caller may also
    pass an explicit ``body``/``bodyMd`` key. Prefer the most faithful source.
    """
    for key in ("body", "bodyMd"):
        if epic.get(key):
            return str(epic[key])
    meta = epic.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("bodyMd", "body"):
            if meta.get(key):
                return str(meta[key])
    return ""


def build_frontmatter(epic: dict[str, Any]) -> dict[str, Any]:
    """Build EPIC.md frontmatter conforming to EPIC_FRONTMATTER_SCHEMA.md.

    Closed field set: ``slug``, ``title``, ``tier``, ``status`` (required);
    ``repos`` and ``map`` (additive); ``completed_date`` (only when
    ``status == completed``). ``complete`` is coerced to ``completed`` on emit
    (the schema's legacy-drift rule). ``id`` is accepted as a slug alias for
    store records whose primary key is ``id``.
    """
    slug = epic.get("slug") or epic.get("id") or ""
    status = epic.get("status") or "pending"
    if status == "complete":
        status = "completed"

    fm: dict[str, Any] = {
        "slug": slug,
        "title": epic.get("title", ""),
        "tier": epic.get("tier"),
        "status": status,
    }

    repos = epic.get("repos")
    if isinstance(repos, list):
        fm["repos"] = list(repos)

    map_slug = epic.get("map") or epic.get("mapSlug")
    if map_slug:
        fm["map"] = map_slug

    # feature is the forward alias of map (FEATURE_FRONTMATTER_SCHEMA.md); emit it
    # when present so the alias survives the round-trip. projects[] is additive.
    feature = epic.get("feature")
    if feature:
        fm["feature"] = feature
    projects = epic.get("projects")
    if isinstance(projects, list) and projects:
        fm["projects"] = list(projects)

    # completed_date appears ONLY alongside status == completed (schema rule).
    completed_date = epic.get("completed_date")
    if status == "completed" and completed_date:
        fm["completed_date"] = completed_date

    return fm


def _dump_frontmatter(fm: dict[str, Any]) -> str:
    """Serialize frontmatter as a leading ``---`` fenced YAML block."""
    body = yaml.dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def _task_to_yaml_dict(task: Any) -> dict[str, Any]:
    """Normalize a task record/dict to its on-disk YAML mapping.

    Drops store-internal provenance (``_source_file`` / ``source_file``) so the
    exported file matches the task YAML schema verbatim and the round-trip is
    clean.
    """
    if is_dataclass(task) and hasattr(task, "to_dict"):
        d = task.to_dict()  # type: ignore[attr-defined]
    else:
        d = _as_dict(task)
    d.pop("_source_file", None)
    d.pop("source_file", None)
    return d


# --- writers -----------------------------------------------------------------


def write_epic(epic: Any, out_dir: Path) -> Path:
    """Write one epic (EPIC.md + tasks/*.yml) under *out_dir*.

    Layout: ``<out_dir>/epics/<tier>/<slug>/EPIC.md`` plus one
    ``tasks/<id>.yml`` per task. Returns the epic directory path.
    """
    epic_d = _as_dict(epic)
    tier = epic_d.get("tier") or "active"
    slug = epic_d.get("slug") or epic_d.get("id") or ""
    epic_dir = Path(out_dir) / "epics" / tier / slug
    epic_dir.mkdir(parents=True, exist_ok=True)

    fm = build_frontmatter(epic_d)
    body = _epic_body(epic_d)
    text = _dump_frontmatter(fm)
    if body:
        text += "\n" + body
        if not body.endswith("\n"):
            text += "\n"
    (epic_dir / "EPIC.md").write_text(text, encoding="utf-8")

    tasks = epic_d.get("tasks") or []
    if tasks:
        tasks_dir = epic_dir / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        for task in tasks:
            task_d = _task_to_yaml_dict(task)
            task_id = task_d.get("id") or "task"
            (tasks_dir / f"{task_id}.yml").write_text(
                yaml.dump(
                    task_d,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
    return epic_dir


def write_map(map_doc: Any, out_dir: Path, tier: str = "active") -> Path:
    """Write one MAP.md under ``<out_dir>/maps/<tier>/<slug>/MAP.md``.

    Maps carry no closed frontmatter schema; a minimal ``slug``/``title``
    frontmatter is emitted for round-trip fidelity, followed by whatever body
    the store supplied (``body``/``raw``), else a reconstructed stub from the
    parsed sections so the file remains a parseable MAP.md.
    """
    map_d = _as_dict(map_doc)
    slug = map_d.get("id") or map_d.get("slug") or ""
    map_dir = Path(out_dir) / "maps" / tier / slug
    map_dir.mkdir(parents=True, exist_ok=True)

    fm: dict[str, Any] = {"slug": slug, "title": map_d.get("title", "")}
    # A Feature descriptor (MAP.md leading fence) carries version/projects[]
    # (FEATURE_FRONTMATTER_SCHEMA.md); emit them when present for round-trip fidelity.
    version = map_d.get("version")
    if version:
        fm["version"] = version
    projects = map_d.get("projects")
    if isinstance(projects, list) and projects:
        fm["projects"] = list(projects)
    text = _dump_frontmatter(fm)

    body = map_d.get("body") or map_d.get("raw")
    if not body:
        # Reconstruct a minimal-but-valid MAP.md from parsed sections.
        title = map_d.get("title") or slug
        parts = [f"\n# {title}\n"]
        if map_d.get("vision"):
            parts.append(f"\n## Vision\n\n{map_d['vision']}\n")
        if map_d.get("dispatch_strategy"):
            parts.append(f"\n## Dispatch Strategy\n\n{map_d['dispatch_strategy']}\n")
        if map_d.get("success_criteria"):
            parts.append(f"\n## Success Criteria\n\n{map_d['success_criteria']}\n")
        body = "".join(parts)
    text += "\n" + str(body)
    if not text.endswith("\n"):
        text += "\n"
    (map_dir / "MAP.md").write_text(text, encoding="utf-8")
    return map_dir


def write_roadmap(entries: list[Any], out_dir: Path) -> Path:
    """Write ``<out_dir>/ROADMAP.yml`` from roadmap entries (records or dicts).

    The ``archive`` tier is excluded from ROADMAP.yml (matching SPOQ's existing
    behavior where archived epics live by location, not in the roadmap index).
    """
    epics: list[dict[str, Any]] = []
    for entry in entries:
        if is_dataclass(entry) and hasattr(entry, "to_dict"):
            d = entry.to_dict()  # type: ignore[attr-defined]
        else:
            d = _as_dict(entry)
        if d.get("tier") == "archive":
            continue
        epics.append(d)
    data = {"epics": epics}
    path = Path(out_dir) / "ROADMAP.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return path


# --- store-driven collection -------------------------------------------------

_ALL_TIERS = ("backlog", "active", "complete", "archive")


def _collect_epics(store: Any, epic_slug: str | None) -> list[Any]:
    """Pull epic records (with tasks) from *store*.

    When *epic_slug* is given, load that single epic; otherwise enumerate every
    tier and load each epic fully (so its tasks are populated). Returns store
    records (the writers normalize them).
    """
    if epic_slug:
        return [store.load_epic(epic_slug)]

    out: list[Any] = []
    for tier in _ALL_TIERS:
        try:
            listed = store.list_epics(tier)
        except Exception:
            continue
        for item in listed or []:
            item_d = _as_dict(item) if not isinstance(item, str) else {"id": item}
            slug = item_d.get("slug") or item_d.get("id")
            if isinstance(item, str):
                slug = item
            if not slug:
                continue
            try:
                # Load the full epic (frontmatter + body + tasks). Pass a
                # tier-qualified path so fs-mode resolution finds the dir.
                full = store.load_epic(f"spoq/epics/{tier}/{slug}")
            except Exception:
                # Fall back to the listed record if a full load is unavailable.
                full = item
            full_d = _as_dict(full) if not isinstance(full, str) else {"id": slug}
            full_d.setdefault("tier", tier)
            full_d.setdefault("slug", slug)
            out.append(full_d)
    return out


def export_store(
    store: Any,
    out_dir: Path,
    *,
    epic_slug: str | None = None,
    export_all: bool = False,
) -> dict[str, int]:
    """Export from *store* into *out_dir*. Returns a count summary.

    Calls :func:`freeze_guard` before any write. Exactly one of *epic_slug* or
    *export_all* selects the scope.
    """
    out_dir = Path(out_dir)
    freeze_guard(out_dir)

    if not export_all and not epic_slug:
        raise SystemExit("export requires either --epic <slug> or --all")

    out_dir.mkdir(parents=True, exist_ok=True)

    epics = _collect_epics(store, epic_slug if not export_all else None)
    for epic in epics:
        write_epic(epic, out_dir)

    map_count = 0
    if export_all:
        try:
            maps = store.list_maps()
        except Exception:
            maps = []
        for map_doc in maps or []:
            write_map(map_doc, out_dir)
            map_count += 1

        try:
            roadmap = store.load_roadmap()
        except Exception:
            roadmap = []
        write_roadmap(roadmap, out_dir)

    return {"epics": len(epics), "maps": map_count}


# --- CLI entry ---------------------------------------------------------------


def run_export(epic: str | None, export_all: bool, out: str, store: Any = None) -> int:
    """CLI body for ``spoq export``. Returns a process exit code.

    *store* is injectable for tests; in production it is built from the active
    server configuration (respecting ``SPOQ_STORE``).
    """
    out_dir = Path(out)
    # Guard FIRST, before constructing a store or touching the network.
    freeze_guard(out_dir)

    if not export_all and not epic:
        print("Error: specify --epic <slug> or --all", flush=True)
        return 2

    if store is None:
        from spoq_server import config

        cfg = config.load_config()
        store = config.build_store(cfg)

    summary = export_store(
        store, out_dir, epic_slug=epic, export_all=export_all
    )
    print(
        f"Exported {summary['epics']} epic(s) and {summary['maps']} map(s) "
        f"to {out_dir}",
        flush=True,
    )
    return 0
