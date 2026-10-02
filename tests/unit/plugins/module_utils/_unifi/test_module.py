# SPDX-License-Identifier: GPL-3.0-or-later
"""Building a client, and the family a base path can be asked for.

A module names which set of collections it addresses. The site collections are
served by the legacy family on every deployment, and every module in this
collection addresses those paths, so a site client built for the official family
would compose an address the controller answers with a 404. The refusal belongs
where the base is chosen rather than at the first request.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import POLICY_ENGINE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import build_client

CONSOLE_PARAMS: dict[str, Any] = {
    "controller": "unifi.example.invalid",
    "api_mount": "console",
    "api_family": "legacy",
    "api_key": "a-key",
    "site": "default",
}


def test_the_legacy_family_builds_a_site_client() -> None:
    client = build_client(CONSOLE_PARAMS)

    assert client.options.base_url == "https://unifi.example.invalid/proxy/network/api/s/default"


def test_the_official_family_cannot_address_the_site_collections() -> None:
    # Every shipped module addresses the legacy collection paths, so an official
    # site client would compose /proxy/network/integration/rest/..., which the
    # controller answers with a 404 that reads like a missing resource.
    params = {**CONSOLE_PARAMS, "api_family": "official"}

    with pytest.raises(UniFiError, match="api_family"):
        build_client(params)


def test_the_refusal_names_the_family_the_shipped_modules_speak() -> None:
    params = {**CONSOLE_PARAMS, "api_family": "official"}

    with pytest.raises(UniFiError, match="legacy"):
        build_client(params)


def test_the_policy_engine_still_accepts_the_official_family() -> None:
    # The policy engine sits above the site and is served by the legacy family on
    # every deployment, so it does not carry the site collections' refusal.
    params = {**CONSOLE_PARAMS, "api_family": "official"}

    client = build_client(params, base=POLICY_ENGINE)

    assert (
        client.options.base_url == "https://unifi.example.invalid/proxy/network/v2/api/site/default"
    )
