"""Utility functions for ROADMAP.yml operations.

Bundled copy for standalone PyPI distribution.
Handles the 3-tier epic lifecycle: backlog -> active -> complete.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

import yaml

from spoq_server import epic_utils

ROADMAP_FILENAME = "ROADMAP.yml"
ROADMAP_VERSION = 1
VALID_TIERS = {"backlog", "active", "complete"}
# Re-export the canonical status vocabulary from the schema home.
VALID_STATUS = epic_utils.VALID_STATUS


# =============================================================================
# Load / Save
# =============================================================================

def load_roadmap(spoq_dir: str) -> dict:
    """Load ROADMAP.yml from *spoq_dir*, returning an empty scaffold on miss."""
    path = Path(spoq_dir) / ROADMAP_FILENAME
    try:
        if not path.exists():
            return _empty_scaffold()
        raw = path.read_text(encoding='utf-8')
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            return _empty_scaffold()
        return data
    except (OSError, yaml.YAMLError):
        return _empty_scaffold()


def save_roadmap(spoq_dir: str, data: dict) -> None:
    """Persist *data* as ROADMAP.yml with an auto-updated timestamp."""
    path = Path(spoq_dir) / ROADMAP_FILENAME
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True), encoding='utf-8')


def _empty_scaffold() -> dict:
    return {"version": 1, "updated_at": "", "epics": []}


# =============================================================================
# Validation
# =============================================================================

def validate_roadmap(data: dict) -> list[str]:
    """Return a list of error strings; empty means valid."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Data must be a dict"]

    if data.get("version") != ROADMAP_VERSION:
        errors.append(f"Expected version {ROADMAP_VERSION}, got {data.get('version')}")

    epics = data.get("epics")
    if not isinstance(epics, list):
        errors.append("'epics' must be a list")
        return errors

    required = {"slug", "title", "tier", "status"}
    for i, entry in enumerate(epics):
        if not isinstance(entry, dict):
            errors.append(f"Entry {i} is not a dict")
            continue
        missing = required - set(entry.keys())
        if missing:
            errors.append(f"Entry {i} ('{entry.get('slug', '?')}') missing fields: {sorted(missing)}")
        tier = entry.get("tier")
        if tier and tier not in VALID_TIERS:
            errors.append(f"Entry {i} ('{entry.get('slug', '?')}') has invalid tier '{tier}'")

    return errors


# =============================================================================
# Entry Lookup & Mutation
# =============================================================================

def find_entry(data: dict, slug: str) -> dict | None:
    """Linear search through epics by slug."""
    for entry in data.get("epics", []):
        if entry.get("slug") == slug:
            return entry
    return None


def update_entry_tier(data: dict, slug: str, new_tier: str) -> bool:
    """Move an entry to *new_tier*. Returns False if not found."""
    entry = find_entry(data, slug)
    if entry is None:
        return False
    entry["tier"] = new_tier
    if new_tier == "complete":
        entry["completed_date"] = date.today().isoformat()
    else:
        entry["completed_date"] = None
    return True


def add_entry(data: dict, entry: dict) -> list[str]:
    """Append a new entry after minimal validation. Returns error list."""
    errors: list[str] = []
    required = {"slug", "title", "tier"}
    missing = required - set(entry.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
        return errors

    if find_entry(data, entry["slug"]) is not None:
        errors.append(f"Duplicate slug: '{entry['slug']}'")
        return errors

    data.setdefault("epics", []).append(entry)
    return []


def remove_entry(data: dict, slug: str) -> bool:
    """Remove the entry with *slug*. Returns True if removed."""
    epics = data.get("epics", [])
    before = len(epics)
    data["epics"] = [e for e in epics if e.get("slug") != slug]
    return len(data["epics"]) < before


# =============================================================================
# Disk Sync
# =============================================================================

def sync_from_disk(spoq_dir: str, warnings: list[str] | None = None) -> dict:
    """Reconcile ROADMAP.yml with the on-disk epic directories.

    Scans epics/backlog/, epics/active/, and epics/complete/ under *spoq_dir*
    (the ``archive`` tier is intentionally never scanned, so archived epics stay
    out of ROADMAP.yml). For each epic directory it reads the leading EPIC.md
    frontmatter and prefers ``title``/``status``/``repos`` (plus optional
    ``map``, ``feature``, ``projects`` and ``completed_date``) over
    directory-derived defaults, with
    per-field fallback when a field is absent. Disk location stays authoritative
    for ``tier``; a frontmatter ``tier`` (or ``slug``) that disagrees with the
    directory is reported via *warnings* rather than overriding it. All emitted
    statuses are coerced to the canonical vocabulary. Existing entry fields not
    sourced from frontmatter are preserved. Entries whose directory no longer
    exists are removed.

    Adds missing entries, removes stale ones. Returns the reconciled data dict
    (caller persists via save_roadmap). Pass a *warnings* list to collect
    non-fatal frontmatter mismatches.
    """
    if warnings is None:
        warnings = []

    data = load_roadmap(spoq_dir)
    base = Path(spoq_dir)
    entries_by_slug = {e["slug"]: e for e in data.get("epics", []) if "slug" in e}
    on_disk: set[str] = set()

    for tier in VALID_TIERS:
        tier_dir = base / "epics" / tier
        if not tier_dir.is_dir():
            continue
        try:
            children = list(tier_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue

            dir_slug = child.name
            fm = epic_utils.read_epic_frontmatter(child)

            # The directory name is authoritative for keying (sync keys on it);
            # a disagreeing frontmatter slug is surfaced but not honoured.
            fm_slug = fm.get("slug")
            if fm_slug and fm_slug != dir_slug:
                warnings.append(
                    f"Epic '{dir_slug}' frontmatter slug '{fm_slug}' does not "
                    f"match its directory name; using the directory name."
                )
            slug = dir_slug
            on_disk.add(slug)

            # Disk location is authoritative for tier; warn on disagreement.
            fm_tier = fm.get("tier")
            if fm_tier and fm_tier != tier:
                warnings.append(
                    f"Epic '{slug}' frontmatter tier '{fm_tier}' disagrees with "
                    f"its location '{tier}'; keeping '{tier}'."
                )

            entry = entries_by_slug.get(slug)
            if entry is None:
                entry = {"slug": slug}
                data.setdefault("epics", []).append(entry)
                entries_by_slug[slug] = entry

            # Tier always reflects the directory.
            entry["tier"] = tier

            # Title: frontmatter, else keep existing, else derive from the slug.
            if fm.get("title"):
                entry["title"] = fm["title"]
            elif "title" not in entry:
                entry["title"] = slug.replace("-", " ").title()

            # Status: frontmatter, else existing, else a tier default; always
            # coerced to the canonical vocabulary.
            if fm.get("status"):
                entry["status"] = epic_utils.coerce_status(fm["status"])
            elif "status" in entry:
                entry["status"] = epic_utils.coerce_status(entry["status"])
            else:
                entry["status"] = "completed" if tier == "complete" else "pending"

            # repos[] is additive surfacing; an explicit [] is meaningful.
            if isinstance(fm.get("repos"), list):
                entry["repos"] = fm["repos"]

            # Optional passthrough fields.
            if fm.get("map"):
                entry["map"] = fm["map"]
            # feature[] is the forward alias of map; projects[] mirrors repos[].
            if fm.get("feature"):
                entry["feature"] = fm["feature"]
            if isinstance(fm.get("projects"), list):
                entry["projects"] = fm["projects"]
            if fm.get("completed_date"):
                # YAML parses bare dates to date objects; store an ISO string so
                # ROADMAP.yml date types stay consistent with the rest of the file.
                cd = fm["completed_date"]
                entry["completed_date"] = cd.isoformat() if isinstance(cd, date) else str(cd)

    # Remove entries with no matching directory.
    data["epics"] = [e for e in data.get("epics", []) if e.get("slug") in on_disk]

    # Final safety: coerce every status so legacy 'complete' cannot survive.
    for e in data["epics"]:
        if "status" in e:
            e["status"] = epic_utils.coerce_status(e["status"])

    return data


# =============================================================================
# Rendering
# =============================================================================

def render_table(data: dict, max_complete: int = 10) -> str:
    """Build a markdown table grouped by tier (backlog, active, complete)."""
    epics = data.get("epics", [])
    by_tier: dict[str, list[dict]] = {"backlog": [], "active": [], "complete": []}
    for e in epics:
        tier = e.get("tier", "backlog")
        by_tier.setdefault(tier, []).append(e)

    lines = ["| Tier | Slug | Title | Status | Priority |"]
    lines.append("|------|------|-------|--------|----------|")

    for tier in ("backlog", "active", "complete"):
        group = by_tier.get(tier, [])
        if tier == "complete":
            group = group[:max_complete]
        for e in group:
            slug = e.get("slug", "")
            title = e.get("title", "")
            status = e.get("status", "")
            priority = e.get("priority", "")
            lines.append(f"| {tier} | {slug} | {title} | {status} | {priority} |")

    return "\n".join(lines)


# =============================================================================
# Migration from Markdown
# =============================================================================

def migrate_from_markdown(md_path: str, spoq_dir: str) -> dict:
    """Parse a pipe-delimited ROADMAP.md into a ROADMAP.yml data dict.

    Infers tier from section headers (e.g. "Active Epics", "Completed Epics").
    Returns a new data dict suitable for save_roadmap; does not write to disk.
    """
    try:
        content = Path(md_path).read_text(encoding='utf-8')
    except OSError:
        return _empty_scaffold()

    data = _empty_scaffold()
    current_tier = "active"

    for line in content.splitlines():
        stripped = line.strip()

        # Detect section headers to infer tier
        if stripped.startswith("#"):
            lower = stripped.lower()
            if "backlog" in lower:
                current_tier = "backlog"
            elif "complete" in lower:
                current_tier = "complete"
            elif "active" in lower:
                current_tier = "active"
            continue

        # Skip non-table or separator rows
        if not stripped.startswith("|"):
            continue
        # Separator rows: |---|---|, |-- , | ---
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # strip() leaves empty strings at the edges from leading/trailing |
        cells = [c for c in cells if c]

        if not cells:
            continue

        # Skip header rows (contain "Epic" or "Priority")
        if any(h.lower() in ("epic", "priority", "est. hours", "status") for h in cells):
            continue

        entry = _parse_md_table_row(cells, current_tier)
        if entry and entry.get("slug"):
            data["epics"].append(entry)

    return data


def _parse_md_table_row(cells: list[str], tier: str) -> dict:
    """Convert a list of table cell values into a roadmap entry."""
    entry: dict[str, Any] = {"tier": tier, "status": "pending"}

    # Active table: Priority | Epic | Status | Tasks | Est. Hours | Dependencies
    # Completed table: Epic | Completed | Tasks
    for cell in cells:
        # Strip markdown formatting: bold (**x**), strikethrough (~~x~~), italic (*x*)
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", cell)
        clean = re.sub(r"~~(.+?)~~", r"\1", clean)
        clean = clean.strip()

        # Extract slug from markdown link [name](path/)
        link = re.search(r"\[([^\]]+)\]\(([^)]*)\)", clean)
        if link:
            slug = link.group(1).strip()
            entry["slug"] = slug
            entry["title"] = slug.replace("-", " ").title()
            continue

        # Detect date-like values -> completed_date
        date_match = re.match(r"\d{4}-\d{2}-\d{2}$", clean)
        if date_match:
            entry["completed_date"] = clean
            continue

        # Skip legacy hour-estimate cells (~12, ~37h, 4.5h) — the estimate
        # concept was removed; these carry no roadmap data anymore.
        if re.match(r"~\d+(?:\.\d+)?h?$", clean) or re.match(r"\d+(?:\.\d+)?h$", clean):
            continue

        # Detect task count patterns: "0/6", "8/8", or pure integer
        task_match = re.match(r"(\d+)/(\d+)$", clean)
        if task_match:
            entry["tasks"] = int(task_match.group(2))
            continue
        if clean.isdigit():
            val = int(clean)
            if "priority" not in entry:
                entry["priority"] = val
            elif "tasks" not in entry:
                entry["tasks"] = val
            continue

        # Detect known statuses (including bold-wrapped)
        status_val = clean.lower()
        if status_val in ("pending", "in_progress", "in-progress", "completed",
                          "complete", "failed", "none", "proposed"):
            if status_val not in ("none",):
                entry["status"] = status_val.replace("-", "_")
            continue

        # If no slug yet and cell looks like a kebab-case slug, use it
        if "slug" not in entry and re.match(r"^[a-z][a-z0-9-]+$", clean):
            entry["slug"] = clean
            entry["title"] = clean.replace("-", " ").title()
            continue

    # Infer status for completed tier
    if tier == "complete":
        entry["status"] = "completed"

    return entry
