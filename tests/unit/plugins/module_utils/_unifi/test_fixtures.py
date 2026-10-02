# SPDX-License-Identifier: GPL-3.0-or-later
"""The vendored API descriptions, checked for integrity.

Two descriptions are vendored: the legacy family's, generated from the
controller's own field-validation metadata, and the official family's, published
by the vendor. Both are the authority for field names elsewhere in the unit
suite, so a broken or truncated fixture would make those checks pass by saying
nothing rather than by agreeing.

This file asserts the fixtures are whole. It needs no controller and no network,
which is what lets it run on every change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
LEGACY = FIXTURES / "unifi-local-api.yaml"
OFFICIAL = FIXTURES / "unifi-integration-api.json"

#: Paths this collection addresses, so a fixture that stopped declaring one is
#: caught here rather than by a module failing at run time.
OFFICIAL_PATHS = (
    "/v1/sites",
    "/v1/sites/{siteId}/networks",
    "/v1/sites/{siteId}/wifi/broadcasts",
    "/v1/sites/{siteId}/firewall/zones",
    "/v1/sites/{siteId}/devices",
    "/v1/sites/{siteId}/clients",
)


@pytest.fixture(scope="module")
def legacy() -> dict[str, Any]:
    return yaml.safe_load(LEGACY.read_text())


@pytest.fixture(scope="module")
def official() -> dict[str, Any]:
    return json.loads(OFFICIAL.read_text())


def _refs(node: Any) -> list[str]:
    """Every ``$ref`` in a document, at any depth."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_refs(item))
    return found


def _unresolved(document: dict[str, Any]) -> list[str]:
    """References a document makes that it does not itself define."""
    schemas = document.get("components", {}).get("schemas", {})
    broken = []
    for ref in _refs(document):
        name = ref.rsplit("/", 1)[-1]
        if "#/components/schemas/" in ref and name not in schemas:
            broken.append(ref)
    return sorted(set(broken))


def test_the_legacy_description_is_whole(legacy: dict[str, Any]) -> None:
    assert legacy["info"]["version"]
    assert legacy["paths"]
    assert _unresolved(legacy) == []


def test_the_official_description_is_whole(official: dict[str, Any]) -> None:
    assert official["info"]["version"]
    assert official["paths"]
    assert _unresolved(official) == []


def test_the_official_description_declares_every_path_the_collection_uses(
    official: dict[str, Any],
) -> None:
    # A description that stopped declaring one of these would leave the module
    # addressing a path the vendor no longer documents.
    missing = [path for path in OFFICIAL_PATHS if path not in official["paths"]]
    assert missing == []


def test_the_official_description_is_versioned_as_the_documentation_says(
    official: dict[str, Any],
) -> None:
    # Not a gate on the deployment, which is allowed to differ and degrades at
    # the response.
    version = official["info"]["version"]
    assert version.count(".") == 2, version
