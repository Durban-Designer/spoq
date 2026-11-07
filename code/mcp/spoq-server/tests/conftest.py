"""Pytest configuration and shared fixtures for SPOQ MCP server tests."""

import shutil
from pathlib import Path

import pytest
import yaml


# --- Fixtures -----------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_epic_path() -> Path:
    """Return the path to the test-epic fixture directory."""
    path = FIXTURES_DIR / "test-epic"
    assert path.exists(), f"Fixture not found: {path}"
    return path


@pytest.fixture
def tmp_epic_copy(tmp_path: Path, fixture_epic_path: Path) -> Path:
    """
    Copy the test-epic fixture to a temporary directory.

    Use this for tests that mutate task files (e.g., status updates)
    to avoid corrupting shared fixtures.
    """
    dest = tmp_path / "test-epic"
    shutil.copytree(fixture_epic_path, dest)
    return dest


@pytest.fixture
def fixture_map_path() -> Path:
    """Return the path to the test-map fixture directory."""
    path = FIXTURES_DIR / "test-map"
    assert path.exists(), f"Fixture not found: {path}"
    return path


@pytest.fixture
def fixture_map_file_path() -> Path:
    """Return the path to the single-file map fixture (.md file, not directory)."""
    path = FIXTURES_DIR / "test-map-file.md"
    assert path.exists(), f"Fixture not found: {path}"
    return path


@pytest.fixture
def fixture_map_epics_path() -> Path:
    """Return the path to the test-map-epics fixture directory."""
    path = FIXTURES_DIR / "test-map-epics"
    assert path.exists(), f"Fixture not found: {path}"
    return path


@pytest.fixture
def tmp_map_copy(
    tmp_path: Path, fixture_map_path: Path, fixture_map_epics_path: Path
) -> tuple[Path, Path]:
    """
    Copy both the test-map and test-map-epics fixtures to a temporary directory.

    Returns (map_dest, epics_dest) paths.
    """
    map_dest = tmp_path / "test-map"
    epics_dest = tmp_path / "test-map-epics"
    shutil.copytree(fixture_map_path, map_dest)
    shutil.copytree(fixture_map_epics_path, epics_dest)
    return map_dest, epics_dest


@pytest.fixture
def tmp_spoq_dir(tmp_path: Path) -> Path:
    """Create a 3-tier spoq directory structure with a populated ROADMAP.yml.

    Structure::

        tmp_path/
        └── spoq/
            ├── ROADMAP.yml  (3 entries across tiers)
            └── epics/
                ├── backlog/
                │   └── plan-feature/
                ├── active/
                │   └── build-feature/
                └── complete/
                    └── ship-feature/

    Returns the ``tmp_path/spoq`` directory.
    """
    spoq = tmp_path / "spoq"
    spoq.mkdir()

    # Tier directories with placeholder epics
    for tier, slug in [("backlog", "plan-feature"), ("active", "build-feature"), ("complete", "ship-feature")]:
        epic_dir = spoq / "epics" / tier / slug
        epic_dir.mkdir(parents=True)

    # Matching ROADMAP.yml
    roadmap = {
        "version": 1,
        "updated_at": "",
        "epics": [
            {"slug": "plan-feature", "title": "Plan Feature", "tier": "backlog", "status": "pending"},
            {"slug": "build-feature", "title": "Build Feature", "tier": "active", "status": "in_progress"},
            {"slug": "ship-feature", "title": "Ship Feature", "tier": "complete", "status": "completed",
             "completed_date": "2026-03-01"},
        ],
    }
    (spoq / "ROADMAP.yml").write_text(
        yaml.dump(roadmap, default_flow_style=False, sort_keys=False)
    )

    return spoq


@pytest.fixture
def fixture_roadmap_path(tmp_spoq_dir: Path) -> Path:
    """Return the path to the ROADMAP.yml inside the tmp_spoq_dir fixture."""
    path = tmp_spoq_dir / "ROADMAP.yml"
    assert path.exists(), f"ROADMAP.yml not found at {path}"
    return path
