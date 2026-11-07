"""Tests for ``product_utils`` — the ``spoq/product.yml`` parser + validator.

Covers: parse into ProductRecord/VersionRecord, missing/empty/garbage tolerance,
the three-value status enum, per-product semver uniqueness (and cross-product
allowance), the released_date conditional, containment, feature pass-through, and
synthetic multi-product input validating clean.
"""

from __future__ import annotations

import os

import pytest

from spoq_server import product_utils as pu
from spoq_server.stores.records import ProductRecord, VersionRecord


# ---------------------------------------------------------------------------
# parse_product_yml
# ---------------------------------------------------------------------------

def _write(tmp_path, text: str) -> str:
    p = tmp_path / "product.yml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_returns_product_records_with_nested_versions(tmp_path):
    path = _write(
        tmp_path,
        """
products:
  - slug: example-product
    name: Example Product
    description: SDLC OS
    versions:
      - semver: 0.1.0
        status: planned
        features:
          - example-product-sdlc-uprev-2026-07
      - semver: 1.0.0
        status: released
        released_date: "2026-07-01"
""",
    )
    products = pu.parse_product_yml(path)
    assert len(products) == 1
    prod = products[0]
    assert isinstance(prod, ProductRecord)
    assert prod.slug == "example-product"
    assert prod.name == "Example Product"
    assert len(prod.versions) == 2
    assert all(isinstance(v, VersionRecord) for v in prod.versions)
    assert prod.versions[0].semver == "0.1.0"
    assert prod.versions[0].features == ["example-product-sdlc-uprev-2026-07"]
    assert prod.versions[1].released_date == "2026-07-01"


def test_parse_missing_file_returns_empty(tmp_path):
    assert pu.parse_product_yml(str(tmp_path / "nope.yml")) == []


def test_parse_empty_file_returns_empty(tmp_path):
    assert pu.parse_product_yml(_write(tmp_path, "")) == []


def test_parse_non_mapping_returns_empty(tmp_path):
    assert pu.parse_product_yml(_write(tmp_path, "- just\n- a\n- list\n")) == []


def test_parse_no_products_key_returns_empty(tmp_path):
    assert pu.parse_product_yml(_write(tmp_path, "other: value\n")) == []


def test_parse_malformed_yaml_tolerated(tmp_path):
    # Unbalanced brackets → YAMLError → [] (parity with load_roadmap).
    assert pu.parse_product_yml(_write(tmp_path, "products: [oops\n")) == []


def test_parse_accepts_directory_path(tmp_path):
    _write(tmp_path, "products:\n  - slug: p\n    name: P\n    versions: []\n")
    products = pu.parse_product_yml(str(tmp_path))
    assert len(products) == 1
    assert products[0].slug == "p"


# ---------------------------------------------------------------------------
# validate_product_registry — happy path
# ---------------------------------------------------------------------------

def _prod(slug, name, versions):
    return ProductRecord.from_dict(
        {"slug": slug, "name": name, "versions": versions}
    )


def test_valid_registry_has_no_errors():
    products = [
        _prod(
            "example-app",
            "Pinpoint",
            [{"semver": "1.0.0", "status": "in_progress"}],
        ),
        _prod(
            "example-product",
            "Example Product",
            [
                {"semver": "0.1.0", "status": "planned"},
                {"semver": "1.0.0", "status": "released",
                 "released_date": "2026-07-01"},
            ],
        ),
    ]
    assert pu.validate_product_registry(products) == []


def test_product_with_no_versions_is_valid():
    assert pu.validate_product_registry([_prod("p", "P", [])]) == []


def test_empty_registry_is_valid():
    assert pu.validate_product_registry([]) == []


# ---------------------------------------------------------------------------
# validate_product_registry — invalid cases
# ---------------------------------------------------------------------------

def test_bad_status_is_error():
    products = [_prod("p", "P", [{"semver": "0.1.0", "status": "shipped"}])]
    errors = pu.validate_product_registry(products)
    assert any("shipped" in e and "status" in e for e in errors)


def test_all_three_valid_statuses_accepted():
    products = [
        _prod(
            "p",
            "P",
            [
                {"semver": "0.1.0", "status": "planned"},
                {"semver": "0.2.0", "status": "in_progress"},
                {"semver": "0.3.0", "status": "released",
                 "released_date": "2026-01-01"},
            ],
        )
    ]
    assert pu.validate_product_registry(products) == []


def test_duplicate_semver_under_one_product_is_error():
    products = [
        _prod(
            "p",
            "P",
            [
                {"semver": "0.1.0", "status": "planned"},
                {"semver": "0.1.0", "status": "in_progress"},
            ],
        )
    ]
    errors = pu.validate_product_registry(products)
    assert any("duplicate" in e and "0.1.0" in e for e in errors)


def test_same_semver_across_two_products_is_ok():
    products = [
        _prod("a", "A", [{"semver": "1.0.0", "status": "in_progress"}]),
        _prod("b", "B", [{"semver": "1.0.0", "status": "planned"}]),
    ]
    assert pu.validate_product_registry(products) == []


def test_released_date_on_planned_version_is_error():
    products = [
        _prod(
            "p",
            "P",
            [{"semver": "0.1.0", "status": "planned",
              "released_date": "2026-01-01"}],
        )
    ]
    errors = pu.validate_product_registry(products)
    assert any("released_date" in e for e in errors)


def test_released_version_without_date_is_error():
    products = [
        _prod("p", "P", [{"semver": "2.0.0", "status": "released"}])
    ]
    errors = pu.validate_product_registry(products)
    assert any("released_date" in e for e in errors)


def test_missing_slug_is_error():
    products = [_prod("", "P", [])]
    errors = pu.validate_product_registry(products)
    assert any("slug" in e for e in errors)


def test_missing_name_is_error():
    products = [_prod("p", "", [])]
    errors = pu.validate_product_registry(products)
    assert any("name" in e for e in errors)


def test_feature_slugs_pass_through_without_disk_check():
    # A feature slug that does not exist on disk must NOT raise a validation
    # error — existence-checking is a validation-tool concern, not the parser's.
    products = [
        _prod(
            "p",
            "P",
            [{"semver": "0.1.0", "status": "planned",
              "features": ["does-not-exist-on-disk-xyz"]}],
        )
    ]
    assert pu.validate_product_registry(products) == []


# ---------------------------------------------------------------------------
# load_and_validate convenience
# ---------------------------------------------------------------------------

def test_load_and_validate_returns_pair(tmp_path):
    path = _write(
        tmp_path,
        "products:\n  - slug: p\n    name: P\n    versions:\n"
        "      - semver: 0.1.0\n        status: planned\n",
    )
    products, errors = pu.load_and_validate(path)
    assert len(products) == 1
    assert errors == []


# ---------------------------------------------------------------------------
# Synthetic multi-product compatibility input
# ---------------------------------------------------------------------------

def test_multiple_products_validate_clean(tmp_path):
    path = _write(tmp_path, "products:\n  - slug: example-app\n    name: Example App\n    versions: []\n  - slug: example-product\n    name: Example Product\n    versions: []\n")
    products, errors = pu.load_and_validate(path)
    assert errors == []
    assert {p.slug for p in products} == {"example-app", "example-product"}
