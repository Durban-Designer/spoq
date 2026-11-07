"""Storage abstraction contract for the SPOQ MCP server.

Three ABCs — :class:`EpicStore`, :class:`MapStore`, :class:`RoadmapStore` —
define every persistence operation the existing tool/util modules perform. The
method set is driven by an audit of all ``yaml.safe_load``/``yaml.dump``,
``Path.read_text``/``write_text``, ``glob``, and ``shutil.move`` calls across
``epic_utils.py``, ``epic_tools.py``, ``task_tools.py``, ``map_utils.py``,
``map_tools.py``, ``roadmap_utils.py``, and ``roadmap_tools.py`` — not from an
idealized model. No method here is speculative; each maps to at least one
observed I/O site, and its docstring names the tool(s) that consume it.

Concrete backends (``stores/fs.py``, ``stores/api.py``) land in later tasks of
this epic; this module only fixes the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .records import Epic, MapDoc, RoadmapEntry, Task


class EpicStore(ABC):
    """Persistence operations for epics and their tasks.

    Covers the filesystem I/O currently smeared across ``epic_utils.py``
    (EPIC.md + task YAML reads), ``epic_tools.py`` (tier scans + ``shutil.move``
    transitions), and ``task_tools.py`` (task read/write).
    """

    # --- epic reads --------------------------------------------------------

    @abstractmethod
    def load_epic(self, path: str) -> Epic:
        """Load and parse a single epic (EPIC.md frontmatter + body + tasks).

        Backs ``epic_utils.parse_epic_md`` / ``parse_epic`` /
        ``read_epic_frontmatter`` (each ``EPIC.md.read_text``).
        Consumed by: spoq_parse_epic, spoq_validate_epic, spoq_compute_waves,
        spoq_get_wave_tasks, spoq_generate_execution_plan, spoq_analyze_dag"""

    @abstractmethod
    def list_epics(self, tier: str) -> list[Epic]:
        """List all epics in a tier (backlog/active/complete).

        Backs the ``epics/<tier>`` ``iterdir`` + per-task ``glob`` scan in
        ``epic_tools.spoq_list_epics``.
        Consumed by: spoq_list_epics"""

    # --- task reads/writes -------------------------------------------------

    @abstractmethod
    def load_tasks(self, epic_id: str) -> list[Task]:
        """Load every task in an epic (``tasks/*.yml`` glob + parse).

        Backs ``epic_utils.load_tasks`` (``tasks_dir.glob('*.yml')`` +
        ``parse_task_yaml``).
        Consumed by: spoq_list_task_statuses, spoq_update_task_status (the
        epic-complete rollup), spoq_complete_epic, spoq_get_map_status"""

    @abstractmethod
    def get_task(self, epic_id: str, task_id: str) -> Task | None:
        """Resolve and parse a single task by id (returns None if absent).

        Backs ``task_tools._find_task_file`` (``glob`` + id match) +
        ``parse_task_yaml``.
        Consumed by: spoq_get_task, spoq_update_task_status"""

    @abstractmethod
    def update_task(self, epic_id: str, task_id: str, fields: dict[str, Any]) -> Task:
        """Apply *fields* to a task and persist it, returning the updated task.

        Backs the read-modify-``yaml.dump``-``write_text`` cycle in
        ``task_tools.spoq_update_task_status`` (status, last_update,
        progress_notes).
        Consumed by: spoq_update_task_status"""

    # --- creation ----------------------------------------------------------

    @abstractmethod
    def create_epic(self, skeleton: dict[str, Any]) -> Epic:
        """Create a new epic directory + EPIC.md from a skeleton spec.

        The epic-scaffolding counterpart to the map skeleton writer; persists a
        new epic so downstream backends (fs/api) own creation rather than tool
        modules.
        Consumed by: spoq_generate_skeleton"""

    @abstractmethod
    def create_task(self, epic_id: str, skeleton: dict[str, Any]) -> Task:
        """Create a new task YAML inside an epic from a skeleton spec.

        Writes a ``tasks/*.yml`` for a newly scaffolded task.
        Consumed by: spoq_generate_skeleton"""

    # --- tier transitions --------------------------------------------------

    @abstractmethod
    def promote_epic(self, epic_id: str) -> Epic:
        """Move an epic forward one tier (backlog→active→complete).

        Backs the ``shutil.move`` + ROADMAP tier update in
        ``epic_tools.spoq_promote`` (resource_type='epic').
        Consumed by: spoq_promote"""

    @abstractmethod
    def demote_epic(self, epic_id: str) -> Epic:
        """Move an epic back one tier (complete→active→backlog).

        Backs the ``shutil.move`` + ROADMAP tier update in
        ``epic_tools.spoq_demote`` (resource_type='epic').
        Consumed by: spoq_demote"""

    @abstractmethod
    def complete_epic(self, epic_id: str) -> Epic:
        """Move a fully-completed epic from active/ to complete/.

        Backs the completion-verifying ``shutil.move`` + map/ROADMAP update in
        ``epic_tools.spoq_complete_epic``.
        Consumed by: spoq_complete_epic"""

    @abstractmethod
    def archive_epic(self, epic_id: str) -> Epic:
        """Move an epic into the archive tier (out of the lifecycle).

        The archive-tier transition counterpart to promote/demote; the archive
        tier is the location that keeps epics out of ROADMAP.yml.
        Consumed by: spoq_demote (archive-tier handling)"""


class MapStore(ABC):
    """Persistence operations for feature maps (MAP.md documents).

    MAP.md *parsing* stays a parsing concern; what this contract owns is the
    document read, the maps-tier scan, and the status-line rewrite.
    """

    @abstractmethod
    def parse_map(self, path: str) -> MapDoc:
        """Read and parse a MAP.md (directory or standalone ``.md``).

        Backs ``map_utils.parse_map_md`` / ``parse_map`` (``map_md.read_text``).
        Consumed by: spoq_parse_map, spoq_validate_map, spoq_compute_epic_waves,
        spoq_analyze_map_dag, spoq_get_map_status"""

    @abstractmethod
    def list_maps(self) -> list[MapDoc]:
        """List all maps across backlog/active/complete tiers.

        Backs the ``maps/<tier>`` ``iterdir`` scan in
        ``map_tools.spoq_list_maps``.
        Consumed by: spoq_list_maps"""

    @abstractmethod
    def update_map(self, map_id: str, fields: dict[str, Any]) -> MapDoc:
        """Rewrite fields in a MAP.md (e.g. an epic's ``**Status:**`` line).

        Backs the read-rewrite-``write_text`` in
        ``map_utils.update_epic_status_in_map`` (invoked by spoq_complete_epic
        when a map_path is supplied).
        Consumed by: spoq_complete_epic"""

    # --- filesystem-shaped map I/O (task 03-fs-store-maps-roadmap) ---------
    #
    # The methods above are the typed-record contract task 01 froze; the three
    # below are the path/dict-shaped surface the map tools actually call after
    # the task-03 extraction. They are declared (not abstract) so other backends
    # can override them without being forced to, and so MAP.md
    # *parsing* can stay in ``map_utils`` while *I/O* lives in the store.

    def resolve_map_file(self, map_id: str):  # pragma: no cover - overridden
        """Resolve the MAP.md file for *map_id* (path or slug).

        Returns the resolved markdown :class:`~pathlib.Path` (or ``None`` when
        no file is found). Backs ``map_utils.resolve_map_file``; consumed by
        every map tool that needs the on-disk document location."""
        raise NotImplementedError

    def read_map_status(self, map_id: str) -> dict[str, Any]:
        """Read raw MAP.md bytes and return parsed metadata for *map_id*.

        I/O lives here; the markdown parsing is delegated to the shared
        ``map_utils`` helpers. Consumed by: spoq_parse_map, spoq_validate_map,
        spoq_list_maps, spoq_get_map_status."""
        raise NotImplementedError

    def write_map_status(self, map_id: str, status_updates: dict[str, Any]) -> dict[str, Any]:
        """Rewrite an epic's ``**Status:**`` line inside a MAP.md.

        *status_updates* carries ``epic_slug`` + ``new_status``. Backs the inline
        ``map_utils.update_epic_status_in_map`` write; consumed by
        spoq_complete_epic."""
        raise NotImplementedError


class RoadmapStore(ABC):
    """Persistence operations for ROADMAP.yml.

    Owns the ROADMAP.yml read/write, the disk-reconciliation sync, and the
    rendered-roadmap projection.
    """

    @abstractmethod
    def load_roadmap(self) -> list[RoadmapEntry]:
        """Load ROADMAP.yml entries (empty scaffold on miss).

        Backs ``roadmap_utils.load_roadmap`` (``ROADMAP.yml.read_text`` +
        ``yaml.safe_load``).
        Consumed by: spoq_roadmap_show, spoq_roadmap_sync, spoq_complete_epic,
        spoq_promote, spoq_demote"""

    @abstractmethod
    def save_roadmap(self, data: list[RoadmapEntry]) -> None:
        """Persist roadmap entries to ROADMAP.yml (stamps updated_at).

        Backs ``roadmap_utils.save_roadmap`` (``yaml.dump`` + ``write_text``).
        Consumed by: spoq_roadmap_sync, spoq_complete_epic, spoq_promote,
        spoq_demote"""

    @abstractmethod
    def sync_roadmap(self) -> list[RoadmapEntry]:
        """Reconcile ROADMAP.yml against on-disk epic directories.

        Backs ``roadmap_utils.sync_from_disk`` (tier ``iterdir`` +
        ``read_epic_frontmatter``), returning the reconciled entries.
        Consumed by: spoq_roadmap_sync"""

    @abstractmethod
    def show_roadmap(self, tier: str = "") -> list[RoadmapEntry]:
        """Return roadmap entries for rendering, optionally filtered by tier.

        Backs the load + tier-filter projection in
        ``roadmap_tools.spoq_roadmap_show`` (rendered by
        ``roadmap_utils.render_table``).
        Consumed by: spoq_roadmap_show"""

    # --- filesystem-shaped roadmap I/O (task 03-fs-store-maps-roadmap) -----
    #
    # The abstract methods above are the typed-record contract task 01 froze.
    # The dict-shaped trio below is the surface the roadmap tools actually call
    # after the task-03 extraction (``roadmap_utils`` keeps the pure data
    # transforms; the disk reads/writes route through the store). Declared
    # non-abstract for compatibility with the shared store interface.

    def load_roadmap_dict(self, spoq_dir: str | None = None) -> dict[str, Any]:
        """Load ROADMAP.yml as a raw dict (empty scaffold on miss).

        Backs ``roadmap_utils.load_roadmap``; consumed by spoq_roadmap_show,
        spoq_roadmap_sync, spoq_complete_epic, spoq_promote, spoq_demote."""
        raise NotImplementedError

    def save_roadmap_dict(self, data: dict[str, Any], spoq_dir: str | None = None) -> None:
        """Persist a raw ROADMAP.yml dict (stamps ``updated_at``).

        Backs ``roadmap_utils.save_roadmap``; consumed by spoq_roadmap_sync,
        spoq_complete_epic, spoq_promote, spoq_demote."""
        raise NotImplementedError

    def sync_roadmap_from_disk(
        self, spoq_dir: str | None = None, warnings: list[str] | None = None
    ) -> dict[str, Any]:
        """Reconcile ROADMAP.yml against on-disk epic directories.

        Backs ``roadmap_utils.sync_from_disk``; consumed by spoq_roadmap_sync.
        Other backends may provide an equivalent reconciliation operation."""
        raise NotImplementedError
