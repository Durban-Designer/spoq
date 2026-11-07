"""Parse and validate ``spoq/product.yml`` — the product/version registry.

``product.yml`` holds the two planning layers above Feature (Product and
Version). Unlike ``MAP.md``/``EPIC.md`` frontmatter (a leading ``---`` fence),
``product.yml`` is a **plain YAML document parsed whole** with
``yaml.safe_load``.

Format authority: ``spoq/FEATURE_FRONTMATTER_SCHEMA.md`` (product.yml section).
This module is the parser + validator library only — it wires **no** MCP tool
(that surface belongs to tasks 05/09) and does **no** disk I/O beyond reading the
single ``product.yml`` file (feature-slug existence-on-disk is a validation-tool
concern, not the parser's).

Validation enforced by :func:`validate_product_registry`:

- version ``status`` ∈ ``{planned, in_progress, released}`` (distinct from the
  epic status enum);
- ``semver`` unique **per product** (the same semver under two products is fine);
- ``released_date`` present **iff** ``status == released``;
- structural containment: versions nest under products (a product with no
  ``versions`` is a valid empty stream); feature slugs pass through unchecked.
"""

from __future__ import annotations

import os
from typing import Any

import yaml

from .stores.records import ProductRecord

PRODUCT_YML_FILENAME = "product.yml"

#: Exactly the three version-status values (schema doc wins). This is DISTINCT
#: from the epic status enum (``pending|in_progress|completed|blocked``).
VALID_VERSION_STATUS = {"planned", "in_progress", "released"}


def _resolve_path(path: str) -> str:
    """Return the ``product.yml`` file path.

    Accepts either the file itself or a directory containing it (so callers may
    pass a ``spoq/`` dir, mirroring ``roadmap_utils.load_roadmap``).
    """
    if path and os.path.isdir(path):
        return os.path.join(path, PRODUCT_YML_FILENAME)
    return path


def parse_product_yml(path: str) -> list[ProductRecord]:
    """Parse ``product.yml`` at *path* into a list of :class:`ProductRecord`.

    *path* may be the ``product.yml`` file or a directory holding it. A missing,
    empty, or non-mapping file returns ``[]`` (the layer is optional
    everywhere). ``OSError`` / ``yaml.YAMLError`` are tolerated and yield ``[]``,
    matching ``roadmap_utils.load_roadmap``.
    """
    target = _resolve_path(path)
    try:
        if not target or not os.path.isfile(target):
            return []
        with open(target, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return []

    if not isinstance(data, dict):
        return []

    products = data.get("products") or []
    if not isinstance(products, list):
        return []

    result: list[ProductRecord] = []
    for entry in products:
        if isinstance(entry, dict):
            result.append(ProductRecord.from_dict(entry))
    return result


def validate_product_registry(products: list[ProductRecord]) -> list[str]:
    """Validate a parsed product registry; return a list of error strings.

    An empty list means the registry is valid. Rules mirror
    ``FEATURE_FRONTMATTER_SCHEMA.md``:

    - each product carries a non-empty ``slug`` and ``name``;
    - ``semver`` is unique per product;
    - version ``status`` is one of :data:`VALID_VERSION_STATUS`;
    - ``released_date`` is present **iff** ``status == released``.

    Feature-slug entries are passed through unchecked (on-disk existence is out
    of scope for the parser).
    """
    errors: list[str] = []

    for product in products:
        slug = product.slug
        if not slug or not str(slug).strip():
            errors.append("Product is missing a non-empty 'slug'")
        if not product.name or not str(product.name).strip():
            errors.append(
                f"Product '{slug or '<unknown>'}' is missing a non-empty 'name'"
            )

        seen_semvers: set[str] = set()
        for version in product.versions:
            semver = version.semver
            if not semver or not str(semver).strip():
                errors.append(
                    f"Product '{slug}' has a version with a missing 'semver'"
                )
            else:
                if semver in seen_semvers:
                    errors.append(
                        f"Product '{slug}' has duplicate semver '{semver}'"
                    )
                seen_semvers.add(semver)

            status = version.status
            if status not in VALID_VERSION_STATUS:
                errors.append(
                    f"Product '{slug}' version '{semver}' has invalid status "
                    f"'{status}' (must be one of "
                    f"{sorted(VALID_VERSION_STATUS)})"
                )

            has_date = bool(version.released_date)
            if status == "released" and not has_date:
                errors.append(
                    f"Product '{slug}' version '{semver}' is released but has "
                    f"no 'released_date'"
                )
            if status != "released" and has_date:
                errors.append(
                    f"Product '{slug}' version '{semver}' has a "
                    f"'released_date' but status is '{status}' (not released)"
                )

    return errors


def load_and_validate(path: str) -> tuple[list[ProductRecord], list[str]]:
    """Convenience: parse *path* then validate, returning ``(products, errors)``."""
    products = parse_product_yml(path)
    return products, validate_product_registry(products)
