"""Typed record dataclasses for the SPOQ storage layer.

These mirror the dict shapes the existing tool/util modules already produce and
consume — no fields are added or removed relative to current usage. Each field
below is traceable to an observed key in the pre-refactor code:

- ``Task``        → ``epic_utils.parse_task_yaml`` (required id/title/description
                     plus the eight ``setdefault`` keys, the ``last_update`` /
                     ``progress_notes`` / ``retry_count`` keys touched by
                     ``task_tools``, and the internal ``_source_file`` marker).
- ``Epic``        → ``epic_utils.parse_epic`` result (epic_path, epic_name,
                     metadata, tasks, stats, errors) merged with the EPIC.md
                     frontmatter fields (slug/title/tier/status/repos/map/
                     completed_date) read by ``read_epic_frontmatter``.
- ``MapDoc``      → ``map_utils.parse_map_md`` result (title, vision, epics,
                     dispatch_strategy, success_criteria, raw_length).
- ``RoadmapEntry``→ a single ``epics[]`` entry in ROADMAP.yml as written by
                     ``roadmap_utils`` (slug/title/tier/status required; priority/
                     tasks/repos/map/completed_date optional).

Records are intentionally permissive: ``from_dict`` keeps only the known keys so
a record can be built straight from the dicts the parsers already return, and
``to_dict`` drops ``None`` optionals so round-tripping does not invent keys that
were absent in the source YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


def _filter_known(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Return only the items of *data* whose keys are fields of *cls*."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


@dataclass
class Task:
    """A single task parsed from a ``tasks/*.yml`` file.

    Mirrors ``epic_utils.parse_task_yaml`` exactly: the three required keys, the
    eight ``setdefault`` keys, the mutable status bookkeeping written by
    ``spoq_update_task_status`` (``last_update``, ``progress_notes``), the
    ``retry_count`` read by ``spoq_generate_execution_plan``, and the internal
    ``_source_file`` provenance marker (stripped before tool output).
    """

    id: str
    title: str
    description: str
    status: str = "pending"
    priority: str = "medium"
    phase: int = 1
    dependencies: list[Any] = field(default_factory=list)
    files_to_touch: list[Any] = field(default_factory=list)
    acceptance_criteria: list[Any] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)
    skills_required: list[Any] = field(default_factory=list)
    last_update: str | None = None
    progress_notes: str | None = None
    retry_count: int = 0
    source_file: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        d = dict(data)
        # The parser stamps the on-disk path under the private ``_source_file``
        # key; map it onto the public field name.
        if "_source_file" in d:
            d.setdefault("source_file", d.pop("_source_file"))
        return cls(**_filter_known(cls, d))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "phase": self.phase,
            "dependencies": list(self.dependencies),
            "files_to_touch": list(self.files_to_touch),
            "acceptance_criteria": list(self.acceptance_criteria),
            "outputs": list(self.outputs),
            "skills_required": list(self.skills_required),
            "retry_count": self.retry_count,
        }
        if self.last_update is not None:
            out["last_update"] = self.last_update
        if self.progress_notes is not None:
            out["progress_notes"] = self.progress_notes
        if self.source_file is not None:
            out["_source_file"] = self.source_file
        return out


@dataclass
class Epic:
    """An epic directory: EPIC.md frontmatter/metadata plus its tasks.

    Frontmatter fields (``slug``/``tier``/``status``/``repos``/``map``/
    ``completed_date``) come from ``read_epic_frontmatter``; ``epic_path`` /
    ``epic_name`` / ``metadata`` / ``stats`` / ``errors`` mirror the
    ``parse_epic`` aggregate result.
    """

    id: str
    title: str
    phase: str = ""
    tier: str | None = None
    status: str | None = None
    epic_path: str | None = None
    epic_name: str | None = None
    tasks: list[Task] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    repos: list[Any] = field(default_factory=list)
    map: str | None = None
    feature: str | None = None
    projects: list[Any] = field(default_factory=list)
    completed_date: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class MapDoc:
    """A parsed MAP.md document.

    Field-for-field mirror of ``map_utils.parse_map_md``'s return dict. ``id`` is
    the map slug/name (``map_path.name``). ``slug``/``title``/``tier``/``version``/
    ``projects`` mirror the MAP.md leading-fence frontmatter (a **Feature**
    descriptor per ``FEATURE_FRONTMATTER_SCHEMA.md``); the remaining fields are the
    parsed body sections. ``id`` stays the map dir/name; ``slug`` mirrors it from
    frontmatter when present.
    """

    id: str
    slug: str = ""
    title: str = ""
    tier: str = ""
    version: str | None = None
    projects: list[Any] = field(default_factory=list)
    vision: str = ""
    epics: list[dict[str, Any]] = field(default_factory=list)
    dispatch_strategy: str = ""
    success_criteria: str = ""
    raw_length: int = 0

    @classmethod
    def from_dict(cls, map_id: str, data: dict[str, Any]) -> "MapDoc":
        return cls(id=map_id, **_filter_known(cls, data))


@dataclass
class RoadmapEntry:
    """A single entry in ROADMAP.yml's ``epics[]`` list.

    ``slug``/``title``/``tier``/``status`` are the required fields validated by
    ``roadmap_utils.validate_roadmap``; ``priority``/``tasks``/``repos``/``map``/
    ``completed_date`` are the optional passthrough fields written by
    ``sync_from_disk`` and the markdown migration.
    """

    slug: str
    title: str
    tier: str
    status: str
    priority: Any | None = None
    tasks: int | None = None
    repos: list[Any] | None = None
    map: str | None = None
    feature: str | None = None
    projects: list[Any] | None = None
    completed_date: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoadmapEntry":
        return cls(**_filter_known(cls, data))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "slug": self.slug,
            "title": self.title,
            "tier": self.tier,
            "status": self.status,
        }
        for opt in ("priority", "tasks", "repos", "map", "completed_date", "feature", "projects"):
            val = getattr(self, opt)
            if val is not None:
                out[opt] = val
        return out


@dataclass
class VersionRecord:
    """A single version under a product in ``spoq/product.yml``.

    Mirrors the ``versions[]`` shape in ``FEATURE_FRONTMATTER_SCHEMA.md``: a semver
    (unique per product), a three-value status (``planned|in_progress|released``),
    an optional ``released_date`` (present only when released), freeform
    ``notes_md``, and the ``features[]`` membership list. Parsing/validation live in
    ``product_utils`` (task 03); this record is the typed target.
    """

    semver: str
    status: str
    released_date: str | None = None
    notes_md: str | None = None
    features: list[Any] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionRecord":
        return cls(**_filter_known(cls, data))


@dataclass
class ProductRecord:
    """A single product in ``spoq/product.yml`` with its version stream.

    Mirrors the ``products[]`` shape in ``FEATURE_FRONTMATTER_SCHEMA.md``.
    ``versions`` nests :class:`VersionRecord` instances built from the parsed dict.
    """

    slug: str
    name: str
    description: str | None = None
    versions: list[VersionRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProductRecord":
        d = dict(data)
        d["versions"] = [
            VersionRecord.from_dict(v) for v in (d.get("versions") or [])
        ]
        return cls(**_filter_known(cls, d))
