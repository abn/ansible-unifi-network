# SPDX-License-Identifier: GPL-3.0-or-later
"""The device info module, without a controller.

Every case here replaces the transport, so the run reaches no socket and the
constraint from the project rules is held by construction rather than by
inspection. What is asserted is the projection and the path: a device is read
from the listing at C(/stat/device), which is not where it is written, and a
field the controller stores beyond the declared set never reaches a play.

What only the controller can answer, and what the live suite therefore asks
instead, is whether that listing is served and whether the runtime fields this
module returns are carried by the rows the controller sends.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import RawResponse
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device_info as under

PARAMS: dict[str, Any] = {
    "controller": "unifi.example.invalid",
    "api_mount": "appliance",
    "api_family": "legacy",
    "site": "default",
    "api_key": "unit-test-key",
    "validate_certs": False,
    "base_url": "https://unifi.example.invalid/api/s/default",
    "api_root": "https://unifi.example.invalid",
    "control_root": "https://unifi.example.invalid",
}


class _Transport:
    """A transport answering each collection from a map, and refusing the rest."""

    def __init__(self, bodies: dict[str, Any]) -> None:
        self._bodies = bodies
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> RawResponse:
        self.requests.append(request)
        path = urlsplit(request.url).path
        for resource, data in self._bodies.items():
            if path.endswith(resource):
                body = {"meta": {"rc": "ok"}, "data": data}
                return RawResponse(200, json.dumps(body), {})
        raise AssertionError(f"unexpected request to {request.url}")


def _client(bodies: dict[str, Any]) -> tuple[UniFiClient, _Transport]:
    transport = _Transport(bodies)
    return UniFiClient(dict(PARAMS), transport), transport


def test_the_projection_keeps_only_the_declared_fields() -> None:
    row = {
        "_id": "abc",
        "mac": "de:ad:be:ef:00:01",
        "name": "Reception AP",
        "model": "U6Lite",
        "type": "uap",
        "ip": "10.0.20.5",
        "version": "6.6.55.15138",
        "state": 1,
        "adopted": True,
        # Declared nowhere, so none of these may survive.
        "site_id": "def",
        "port_overrides": [],
        "bytes": 1234,
    }
    client, _transport = _client({under.EXPORT: [row]})

    assert under.collect(client) == [
        {
            "id": "abc",
            "mac": "de:ad:be:ef:00:01",
            "name": "Reception AP",
            "model": "U6Lite",
            "type": "uap",
            "ip": "10.0.20.5",
            "version": "6.6.55.15138",
            "state": 1,
            "adopted": True,
        }
    ]


def test_a_field_the_controller_omits_is_not_invented() -> None:
    client, _transport = _client({under.EXPORT: [{"_id": "abc", "mac": "de:ad:be:ef:00:01"}]})

    assert under.collect(client) == [{"id": "abc", "mac": "de:ad:be:ef:00:01"}]


def test_a_site_holding_no_devices_reports_an_empty_list() -> None:
    client, _transport = _client({under.EXPORT: []})

    assert under.collect(client) == []


def test_the_read_addresses_the_device_listing_rather_than_the_write_path() -> None:
    # A device is listed at /stat/device and written at /rest/device. Reading the
    # write path answers 404 on a deployment that serves only the listing, which
    # reads like the site holding no devices.
    client, transport = _client({under.EXPORT: []})

    under.collect(client)

    assert urlsplit(transport.requests[0].url).path.endswith("/stat/device")
