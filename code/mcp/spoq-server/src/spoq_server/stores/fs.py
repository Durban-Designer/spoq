"""Filesystem backend for the SPOQ storage layer (epic/task half).

``FsStore`` implements the epic and task operations of the :class:`EpicStore`
contract by lifting the filesystem I/O that previously lived inline in
``epic_utils.py``, ``epic_tools.py``, and ``task_tools.py``. Behavior is
preserved verbatim — this is a mechanical extraction, not a redesign — so the
existing test suite and the captured tool surface both keep holding.

Path arguments keep accepting the convenience strings the tools already pass
(e.g. ``"spoq/epics/active/my-epic"``); :meth:`FsStore._resolve` anchors any
relative path against the configured root so callers never have to.

Map/roadmap operations of the wider store contract are intentionally **not**
implemented here — task 03 extends this same module with that half.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from spoq_server import epic_utils
from .base import EpicStore, MapStore, RoadmapStore
from .records import Epic, MapDoc, RoadmapEntry, Task

# Lifecycle tiers, low → high. Mirrors epic_tools.TIER_ORDER.
TIER_ORDER = ["backlog", "active", "complete"]


class FsStore(EpicStore, MapStore, RoadmapStore):
    """Filesystem-backed store rooted at *root* (epics, tasks, maps, roadmap).

    *root* is the SPOQ project root (the directory that contains ``spoq/``).
    Relative path arguments are resolved against it; absolute paths pass
    through unchanged.

    The map/roadmap half (task 03) keeps a clean separation of concerns: MAP.md
    *parsing* and the pure ROADMAP.yml data transforms stay in the shared
    ``map_utils`` / ``roadmap_utils`` modules (so other backends can reuse
    them on API-returned bodies), while every filesystem read/write lives here.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # --- path resolution ---------------------------------------------------

    def _resolve(self, path_arg: str | Path) -> Path:
        """Anchor a relative path argument against the configured root.

        Absolute paths and convenience strings like
        ``"spoq/epics/active/my-epic"`` are both accepted.
        """
        p = Path(path_arg)
        return p if p.is_absolute() else self.root / p

    def _epics_base(self) -> Path:
        return self.root / "spoq" / "epics"

    # --- epic reads --------------------------------------------------------

    def load_epic(self, path: str) -> Epic:
        """Parse a single epic directory (metadata + tasks + stats).

        Lifted from ``epic_tools`` delegating to ``epic_utils.parse_epic``.
        """
        resolved = self._resolve(path)
        result = epic_utils.parse_epic(resolved)
        return result  # type: ignore[return-value]

    def list_epics(self, tier: str) -> list[Epic]:
        """List epic slugs in a single tier directory (no stats).

        Backs the per-tier ``iterdir`` scan in ``spoq_list_epics``; the tool
        layer owns stats aggregation and multi-tier fan-out.
        """
        slugs: list[str] = []
        tier_dir = self._epics_base() / tier
        if tier_dir.is_dir():
            for child in sorted(tier_dir.iterdir()):
                if child.is_dir():
                    slugs.append(child.name)
        return slugs  # type: ignore[return-value]

    # --- task reads/writes -------------------------------------------------

    def load_tasks(self, epic_id: str) -> list[Task]:
        """Load every task in an epic (``tasks/*.yml`` glob + parse).

        Lifted from ``epic_utils.load_tasks``.
        """
        resolved = self._resolve(epic_id)
        return epic_utils.load_tasks(resolved)  # type: ignore[return-value]

    def task_stats(self, epic_id: str) -> tuple[int, int]:
        """Return ``(tasks_total, tasks_completed)`` for an epic's ``tasks/`` dir.

        Verbatim port of the raw counting loop in the pre-refactor
        ``spoq_list_epics(include_stats=True)``: every parseable YAML *mapping*
        counts toward the total regardless of whether it carries the
        ``title``/``description`` fields the strict task parser requires, and an
        unparseable file still bumps the total. This deliberately does NOT route
        through :meth:`load_tasks` (whose strict parser would reject a stub task
        and so undercount completion).
        """
        epic_path = self._resolve(epic_id)
        tasks_dir = epic_path / "tasks"
        total = 0
        completed = 0
        if tasks_dir.is_dir():
            for yml in tasks_dir.glob("*.yml"):
                try:
                    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        total += 1
                        if data.get("status") == "completed":
                            completed += 1
                except Exception:
                    total += 1
        return total, completed

    def get_task(self, epic_id: str, task_id: str) -> Task | None:
        """Resolve and parse a single task by id (None if absent).

        Lifted from ``task_tools._find_task_file`` + ``parse_task_yaml``,
        preserving the exact prefix-match resolution order.
        """
        resolved = self._resolve(epic_id)
        task_file = self.find_task(resolved, task_id)
        if task_file is None:
            return None
        return epic_utils.parse_task_yaml(task_file)  # type: ignore[return-value]

    def find_task(self, epic_id: str | Path, task_id: str) -> Path | None:
        """Find a task YAML file by id, preserving prefix-match semantics.

        Exact ``<id>.yml`` and ``<id>*.yml`` glob matches are tried first
        (the convenience prefix match that lets callers pass ``"09-drop"``),
        then a full scan matching the parsed ``id`` field. Verbatim port of
        ``task_tools._find_task_file``.
        """
        epic_path = self._resolve(epic_id)
        tasks_dir = epic_path / "tasks"
        if not tasks_dir.exists():
            tasks_dir = epic_path

        for pattern in [f"{task_id}.yml", f"{task_id}*.yml"]:
            matches = list(tasks_dir.glob(pattern))
            if matches:
                return matches[0]

        for yml_file in sorted(tasks_dir.glob("*.yml")):
            try:
                data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id") == task_id:
                    return yml_file
            except Exception:
                continue

        return None

    def update_task(self, epic_id: str, task_id: str, fields: dict[str, Any]) -> Task:
        """Apply *fields* to a task YAML and persist it, returning the parsed task.

        Lifted from ``spoq_update_task_status``: read raw YAML, merge *fields*,
        write back with the same dump options (``default_flow_style=False,
        sort_keys=False, allow_unicode=True``) so on-disk format is unchanged.
        Raises ``FileNotFoundError`` if the task cannot be resolved.
        """
        resolved = self._resolve(epic_id)
        task_file = self.find_task(resolved, task_id)
        if task_file is None:
            raise FileNotFoundError(f"Task '{task_id}' not found in epic at {resolved}")

        content = task_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            data = {}

        data.update(fields)

        task_file.write_text(
            yaml.dump(
                data,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        return epic_utils.parse_task_yaml(task_file)  # type: ignore[return-value]

    def read_task_raw(self, epic_id: str, task_id: str) -> dict[str, Any] | None:
        """Return the raw parsed YAML mapping for a task (no setdefault coercion).

        Preserves the pre-refactor ``spoq_update_task_status`` semantics where
        the *old* status is read from the raw dict (defaulting to ``"unknown"``
        when the key is absent) rather than the ``parse_task_yaml`` view (which
        would default to ``"pending"``). Returns None if the task is absent.
        """
        resolved = self._resolve(epic_id)
        task_file = self.find_task(resolved, task_id)
        if task_file is None:
            return None
        data = yaml.safe_load(task_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    # --- creation ----------------------------------------------------------

    def create_epic(self, skeleton: dict[str, Any]) -> Epic:
        """Create an epic directory + EPIC.md from a skeleton spec.

        SCOPE BOUNDARY: this method is part of the EpicStore ABC defined in
        task 01-store-interface, but NO tool in this epic's scope
        (02-fs-store-epics-tasks) calls it — skeleton generation currently
        lives in ``util_tools``/``init_cmd`` and was never a disk-write site in
        epic_tools.py/task_tools.py. It is declared only to satisfy the ABC; a
        successor store task (next: 03-fs-store-maps-roadmap, which EXTENDS this
        same file) supplies the concrete behavior if/when a caller is wired up.
        """
        raise NotImplementedError(
            "create_epic: declared by 01-store-interface; no caller in "
            "02-fs-store-epics-tasks scope — implemented by a later store task"
        )

    def create_task(self, epic_id: str, skeleton: dict[str, Any]) -> Task:
        """Create a new task YAML inside an epic from a skeleton spec.

        SCOPE BOUNDARY: same as :meth:`create_epic` — ABC method from
        01-store-interface with no calling tool in 02-fs-store-epics-tasks;
        owned by a later store task (03-fs-store-maps-roadmap or later).
        """
        raise NotImplementedError(
            "create_task: declared by 01-store-interface; no caller in "
            "02-fs-store-epics-tasks scope — implemented by a later store task"
        )

    # --- tier transitions --------------------------------------------------

    def _move_tier(
        self, path: str, *, direction: int, resource_type: str = "epic"
    ) -> dict[str, Any]:
        """Shared promote/demote directory move + tier detection.

        Returns a dict describing the move (old/new path + tier) without
        touching ROADMAP.yml — that aggregate stays a RoadmapStore concern the
        tool layer wires in. Verbatim port of the ``spoq_promote`` /
        ``spoq_demote`` move logic. Raises on the same error conditions, with
        the message carried so the tool can surface it unchanged.
        """
        resolved = self._resolve(path)

        if not resolved.exists():
            raise FileNotFoundError(f"Path not found: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")

        current_tier = None
        for segment in resolved.parts:
            if segment in TIER_ORDER:
                current_tier = segment
                break
        if current_tier is None:
            raise ValueError(
                f"Cannot determine tier from path. "
                f"Expected one of {TIER_ORDER} in path segments."
            )

        current_index = TIER_ORDER.index(current_tier)
        target_index = current_index + direction
        if direction > 0 and current_index >= len(TIER_ORDER) - 1:
            raise ValueError(
                f"Already at highest tier '{current_tier}'. Cannot promote further."
            )
        if direction < 0 and current_index <= 0:
            raise ValueError(
                f"Already at lowest tier '{current_tier}'. Cannot demote further."
            )

        target_tier = TIER_ORDER[target_index]
        slug = resolved.name
        base = self.root / ("spoq/epics" if resource_type == "epic" else "spoq/maps")
        new_path = base / target_tier / slug

        if new_path.exists():
            raise FileExistsError(f"Destination already exists: {new_path}")

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(resolved), str(new_path))

        return {
            "old_path": str(resolved),
            "new_path": str(new_path),
            "old_tier": current_tier,
            "new_tier": target_tier,
            "slug": slug,
        }

    def promote_epic(self, epic_id: str) -> Epic:
        """Move a resource forward one tier (backlog→active→complete).

        Returns the move-description dict (see :meth:`_move_tier`); the tool
        layer renders it and applies the ROADMAP update.
        """
        return self._move_tier(epic_id, direction=+1)  # type: ignore[return-value]

    def demote_epic(self, epic_id: str) -> Epic:
        """Move a resource back one tier (complete→active→backlog)."""
        return self._move_tier(epic_id, direction=-1)  # type: ignore[return-value]

    def promote(self, path: str, resource_type: str = "epic") -> dict[str, Any]:
        """Tier-aware promote that also handles maps (resource_type='map')."""
        return self._move_tier(path, direction=+1, resource_type=resource_type)

    def demote(self, path: str, resource_type: str = "epic") -> dict[str, Any]:
        """Tier-aware demote that also handles maps (resource_type='map')."""
        return self._move_tier(path, direction=-1, resource_type=resource_type)

    def complete_epic(self, epic_id: str) -> Epic:
        """Move a completed epic from its current tier into the sibling complete/.

        Verbatim port of the ``spoq_complete_epic`` ``shutil.move``: the
        destination is ``<grandparent>/complete/<slug>`` (sibling of the epic's
        current tier directory), not the project-root epics tree, preserving the
        original relative-move behavior. Completion verification and the ROADMAP/
        map updates stay in the tool layer. Raises on the same conditions.
        """
        resolved = self._resolve(epic_id)
        if not resolved.exists():
            raise FileNotFoundError(f"Epic directory not found: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")

        parent = resolved.parent            # e.g. .../epics/active
        grandparent = parent.parent         # e.g. .../epics
        complete_dir = grandparent / "complete"
        destination = complete_dir / resolved.name

        if destination.exists():
            raise FileExistsError(f"Destination already exists: {destination}")

        complete_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(resolved), str(destination))

        return {  # type: ignore[return-value]
            "slug": resolved.name,
            "old_path": str(resolved),
            "new_path": str(destination),
        }

    def archive_epic(self, epic_id: str) -> Epic:
        """Move an epic into the archive tier.

        SCOPE BOUNDARY: ABC method from 01-store-interface. The current tool
        surface has no ``archive`` tool (tier moves are covered by promote/
        demote/complete_epic, which ARE implemented above), so there is no
        disk-write site in 02-fs-store-epics-tasks to port. Declared only to
        satisfy the contract; owned by a later store task.
        """
        raise NotImplementedError(
            "archive_epic: declared by 01-store-interface; no caller in "
            "02-fs-store-epics-tasks scope — implemented by a later store task"
        )

    # =====================================================================
    # Map storage (task 03-fs-store-maps-roadmap)
    #
    # All filesystem I/O for MAP.md lives here. The markdown *parsing* stays in
    # the shared ``map_utils`` module — FsStore reads the raw file location and
    # hands the parsing back to those helpers, never duplicating it.
    # =====================================================================

    def resolve_map_file(self, map_id: str | Path) -> Path | None:
        """Resolve the MAP.md file for *map_id* (path or convenience slug).

        Verbatim port of ``map_utils.resolve_map_file``: a standalone ``.md``
        file passes through; otherwise ``<dir>/MAP.md`` is returned when it
        exists, else ``None``. Relative arguments anchor against the root.
        """
        map_path = self._resolve(map_id)
        if map_path.is_file() and map_path.suffix.lower() == ".md":
            return map_path
        map_md = map_path / "MAP.md"
        if map_md.exists():
            return map_md
        return None

    def read_map_status(self, map_id: str | Path) -> dict[str, Any]:
        """Read MAP.md metadata for *map_id* (the parsed-document projection).

        FsStore owns the file resolution + ``read_text``; the markdown parsing
        is delegated to the shared :func:`map_utils.parse_map_md` so parsing
        never leaks into the store. Mirrors the pre-refactor behavior where
        ``parse_map_md`` resolved + read + parsed in one call.
        """
        from spoq_server import map_utils

        resolved = self._resolve(map_id)
        return map_utils.parse_map_md(resolved)

    def write_map_status(
        self, map_id: str | Path, status_updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Rewrite an epic's ``**Status:**`` line inside a MAP.md.

        Filesystem-bound port of ``map_utils.update_epic_status_in_map``:
        resolve the file, read its lines, locate the ``### <epic_slug>`` section,
        rewrite the first ``**Status**`` line within it (preserving bullet
        prefix and colon style), and write back. *status_updates* must carry
        ``epic_slug`` and ``new_status``.
        """
        epic_slug = status_updates["epic_slug"]
        new_status = status_updates["new_status"]

        map_md = self.resolve_map_file(map_id)
        if map_md is None:
            return {"error": f"Map file not found at {self._resolve(map_id)}"}

        lines = map_md.read_text(encoding="utf-8").splitlines(keepends=True)

        in_section = False
        status_idx: int | None = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("### "):
                in_section = stripped[4:].strip() == epic_slug
            elif stripped.startswith("## ") and not stripped.startswith("### "):
                in_section = False
            if in_section and re.match(r"[-\s]*\*\*Status", stripped, re.IGNORECASE):
                status_idx = i
                break

        if status_idx is None:
            return {"error": f"Epic '{epic_slug}' or its Status line not found in map"}

        old_line = lines[status_idx]
        prefix_match = re.match(r"^(\s*-\s*|\s*)", old_line)
        prefix = prefix_match.group(1) if prefix_match else ""

        if "**Status:**" in old_line:
            lines[status_idx] = f"{prefix}**Status:** {new_status}\n"
        else:
            lines[status_idx] = f"{prefix}**Status**: {new_status}\n"

        map_md.write_text("".join(lines), encoding="utf-8")

        return {
            "map_file": str(map_md),
            "epic_slug": epic_slug,
            "old_status": old_line.strip(),
            "new_status": new_status,
        }

    def create_map_dir(self, map_path: str | Path) -> Path:
        """Create a new map directory (skeleton generation I/O sink).

        Filesystem-bound port of the ``map_path.mkdir`` in
        ``spoq_generate_map_skeleton``; the MAP.md body is written by
        :meth:`write_map_file`.
        """
        resolved = self._resolve(map_path)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def write_map_file(self, map_file: str | Path, content: str) -> Path:
        """Write *content* to a MAP.md file (skeleton generation I/O sink).

        Port of the ``map_file.write_text`` in ``spoq_generate_map_skeleton``.
        """
        resolved = self._resolve(map_file)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return resolved

    # --- MapStore ABC (typed-record surface, task 01) ----------------------

    def parse_map(self, path: str) -> MapDoc:
        """Read + parse a MAP.md into a :class:`MapDoc` (ABC method).

        Reads through :meth:`read_map_status` (FsStore owns the I/O) and builds
        the typed record from the parsed dict.
        """
        resolved = self._resolve(path)
        data = self.read_map_status(path)
        return MapDoc.from_dict(resolved.name, data)  # type: ignore[return-value]

    def list_maps(self) -> list[MapDoc]:
        """List maps across backlog/active/complete tiers (ABC method).

        Scans ``spoq/maps/<tier>`` for directory- and single-file-format maps,
        parsing each via the shared helpers.
        """
        from spoq_server import map_utils

        base = self.root / "spoq" / "maps"
        docs: list[MapDoc] = []
        for tier in ("backlog", "active", "complete"):
            tier_dir = base / tier
            if not tier_dir.is_dir():
                continue
            for entry in sorted(tier_dir.iterdir()):
                map_md = None
                if entry.is_dir() and (entry / "MAP.md").exists():
                    map_md = entry
                elif (
                    entry.is_file()
                    and entry.suffix.lower() == ".md"
                    and not entry.name.startswith(".")
                ):
                    map_md = entry
                if map_md is None:
                    continue
                data = map_utils.parse_map_md(map_md)
                if "error" not in data:
                    slug = entry.name if entry.is_dir() else entry.stem
                    docs.append(MapDoc.from_dict(slug, data))
        return docs  # type: ignore[return-value]

    def update_map(self, map_id: str, fields: dict[str, Any]) -> MapDoc:
        """Apply a status rewrite to a MAP.md and return the reparsed doc (ABC).

        Thin record-returning wrapper over :meth:`write_map_status`.
        """
        self.write_map_status(map_id, fields)
        return self.parse_map(map_id)

    # =====================================================================
    # Roadmap storage (task 03-fs-store-maps-roadmap)
    #
    # ROADMAP.yml read/write/sync I/O lives here. The pure data transforms
    # (validate, find_entry, render_table, frontmatter coercion) stay in the
    # shared ``roadmap_utils`` module.
    # =====================================================================

    def _spoq_dir(self, spoq_dir: str | None = None) -> Path:
        """Resolve the spoq/ directory (default: ``<root>/spoq``)."""
        if spoq_dir is not None:
            return self._resolve(spoq_dir)
        return self.root / "spoq"

    def load_roadmap_dict(self, spoq_dir: str | None = None) -> dict[str, Any]:
        """Load ROADMAP.yml as a raw dict (empty scaffold on miss/parse error).

        Verbatim port of ``roadmap_utils.load_roadmap``.
        """
        from spoq_server import roadmap_utils

        path = self._spoq_dir(spoq_dir) / roadmap_utils.ROADMAP_FILENAME
        try:
            if not path.exists():
                return roadmap_utils._empty_scaffold()
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return roadmap_utils._empty_scaffold()
            return data
        except (OSError, yaml.YAMLError):
            return roadmap_utils._empty_scaffold()

    def save_roadmap_dict(
        self, data: dict[str, Any], spoq_dir: str | None = None
    ) -> None:
        """Persist *data* as ROADMAP.yml, stamping ``updated_at``.

        Verbatim port of ``roadmap_utils.save_roadmap``.
        """
        from spoq_server import roadmap_utils

        path = self._spoq_dir(spoq_dir) / roadmap_utils.ROADMAP_FILENAME
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(
                data, default_flow_style=False, sort_keys=False, allow_unicode=True
            ),
            encoding="utf-8",
        )

    def sync_roadmap_from_disk(
        self, spoq_dir: str | None = None, warnings: list[str] | None = None
    ) -> dict[str, Any]:
        """Reconcile ROADMAP.yml against on-disk epic directories.

        Delegates to the single shared implementation
        ``roadmap_utils.sync_from_disk`` (the reconciliation loop — tier scan,
        frontmatter merge, status coercion, stale-entry removal — has one home).
        FsStore resolves the ``spoq/`` path from its ``root`` and hands it to the
        shared data layer. Returns the reconciled dict; the caller persists via
        :meth:`save_roadmap_dict`.
        """
        from spoq_server import roadmap_utils

        return roadmap_utils.sync_from_disk(
            str(self._spoq_dir(spoq_dir)), warnings
        )

    # =====================================================================
    # Product registry storage (task 06-fsstore-honors-fields)
    #
    # ``spoq/product.yml`` read I/O lives here; the whole-file YAML parse and
    # the validation rules (status enum, semver uniqueness, released_date,
    # containment) stay in the shared ``product_utils`` module — the same
    # I/O-in-the-store / parsing-in-the-shared-module split used by
    # ``read_map_status`` and ``sync_roadmap_from_disk``.
    # =====================================================================

    def load_product_registry(self, spoq_dir: str | None = None) -> list[Any]:
        """Load ``spoq/product.yml`` into a list of ``ProductRecord`` (I/O only).

        FsStore resolves the ``spoq/`` directory and the ``product.yml`` path;
        the whole-file parse is delegated to
        :func:`product_utils.parse_product_yml`. A missing file yields ``[]``
        (the product/version layer is optional everywhere), mirroring
        :meth:`load_roadmap_dict`'s tolerance of an absent ROADMAP.yml.
        """
        from spoq_server import product_utils

        path = self._spoq_dir(spoq_dir) / product_utils.PRODUCT_YML_FILENAME
        return product_utils.parse_product_yml(str(path))

    def validate_product_registry(self, spoq_dir: str | None = None) -> list[str]:
        """Validate ``spoq/product.yml``; return a list of error strings (``[]`` = valid).

        Loads through :meth:`load_product_registry`, then hands the parsed
        records to :func:`product_utils.validate_product_registry` (status enum,
        per-product semver uniqueness, ``released_date`` iff ``released``). An
        absent file loads as ``[]`` and validates clean.
        """
        from spoq_server import product_utils

        return product_utils.validate_product_registry(
            self.load_product_registry(spoq_dir)
        )

    # --- RoadmapStore ABC (typed-record surface, task 01) ------------------

    @staticmethod
    def _roadmap_entry(e: dict[str, Any]) -> RoadmapEntry:
        """Build a RoadmapEntry tolerant of entries missing required fields.

        ROADMAP.yml is reconciled from disk and can momentarily hold entries
        without a ``status``/``title``/``tier`` (e.g. a freshly-added slug); fill
        the required fields with neutral defaults so the typed projection never
        raises while the dict-shaped tool path stays the source of truth.
        """
        return RoadmapEntry.from_dict(
            {
                "slug": e.get("slug", ""),
                "title": e.get("title", ""),
                "tier": e.get("tier", "backlog"),
                "status": e.get("status", "pending"),
                **{
                    k: v
                    for k, v in e.items()
                    if k in ("priority", "tasks", "repos", "map", "feature", "projects", "completed_date")
                },
            }
        )

    def load_roadmap(self) -> list[RoadmapEntry]:
        """Load ROADMAP.yml entries as typed records (ABC method)."""
        data = self.load_roadmap_dict()
        return [self._roadmap_entry(e) for e in data.get("epics", [])]  # type: ignore[return-value]

    def save_roadmap(self, data: list[RoadmapEntry]) -> None:
        """Persist typed roadmap records to ROADMAP.yml (ABC method)."""
        existing = self.load_roadmap_dict()
        existing["epics"] = [
            r.to_dict() if isinstance(r, RoadmapEntry) else r for r in data
        ]
        self.save_roadmap_dict(existing)

    def sync_roadmap(self) -> list[RoadmapEntry]:
        """Reconcile + return typed roadmap records (ABC method)."""
        data = self.sync_roadmap_from_disk()
        return [self._roadmap_entry(e) for e in data.get("epics", [])]  # type: ignore[return-value]

    def show_roadmap(self, tier: str = "") -> list[RoadmapEntry]:
        """Return roadmap records, optionally filtered by tier (ABC method)."""
        entries = self.load_roadmap()
        if tier:
            entries = [e for e in entries if getattr(e, "tier", None) == tier]
        return entries


# Module-level singleton cache keyed by resolved root, so repeated tool calls in
# the same process reuse one store instance. Keyed (not a bare global) because
# tests monkeypatch project_root to different tmpdirs within a single process.
_store_cache: dict[str, FsStore] = {}


def get_fs_store(root: Path) -> FsStore:
    """Return an :class:`FsStore` for *root*, cached per resolved root path.

    Task 05 replaces this ad-hoc accessor with proper backend selection /
    dependency injection; for now it gives the tool modules a single seam to
    obtain the store without re-implementing path resolution.
    """
    key = str(Path(root))
    store = _store_cache.get(key)
    if store is None:
        store = FsStore(Path(root))
        _store_cache[key] = store
    return store
