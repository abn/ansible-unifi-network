# SPDX-License-Identifier: GPL-3.0-or-later
"""The client info module, without a controller.

Every case here replaces the transport, so the run reaches no socket and the
constraint from the project rules is held by construction rather than by
inspection. What is asserted is the shape: two lists read from two collections,
each a whitelist of that collection's fields, and neither merged into the other.

What only the controller can answer, and what the live suite therefore asks
instead, is whether C(/rest/user) and C(/stat/sta) are both served and whether the
field names this module projects from are the ones the controller sends.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import RawResponse
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.modules import unifi_client_info as under

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


def _both(**collections: Any) -> tuple[UniFiClient, _Transport]:
    bodies = {
        under.CLIENTS: collections.get("clients", []),
        under.ACTIVE: collections.get("active", []),
    }
    return _client(bodies)


def test_the_result_is_two_lists_and_nothing_else() -> None:
    client, _transport = _both()

    result = under.collect(client)

    assert set(result) == {"clients", "active"}
    assert isinstance(result["clients"], list)
    assert isinstance(result["active"], list)


def test_a_registry_record_is_projected_onto_the_declared_fields() -> None:
    row = {
        "_id": "abc",
        "mac": "de:ad:be:ef:00:01",
        "name": "printer",
        "fixed_ip": "10.0.20.50",
        "use_fixedip": True,
        "local_dns_record": "printer.example.invalid",
        "local_dns_record_enabled": True,
        "network_id": "6a3c2d8f",
        # Declared nowhere, so none of these may survive.
        "hostname": "printer",
        "usergroup_id": "def",
        "blocked": False,
    }
    client, _transport = _both(clients=[row])

    assert under.collect(client)["clients"] == [
        {
            "id": "abc",
            "mac": "de:ad:be:ef:00:01",
            "name": "printer",
            "fixed_ip": "10.0.20.50",
            "use_fixedip": True,
            "local_dns_record": "printer.example.invalid",
            "local_dns_record_enabled": True,
            "network_id": "6a3c2d8f",
        }
    ]


def test_a_station_is_projected_onto_the_declared_fields() -> None:
    row = {
        "mac": "de:ad:be:ef:00:02",
        "ip": "10.0.20.51",
        "hostname": "laptop",
        "network": "IoT",
        # Declared nowhere, so neither of these may survive.
        "essid": "IoT-wifi",
        "ap_mac": "de:ad:be:ef:00:03",
    }
    client, _transport = _both(active=[row])

    assert under.collect(client)["active"] == [
        {
            "mac": "de:ad:be:ef:00:02",
            "ip": "10.0.20.51",
            "hostname": "laptop",
            "network": "IoT",
        }
    ]


def test_a_client_in_both_collections_appears_once_in_each_list() -> None:
    # The registry and the station listing key a client differently and carry
    # different fields, so merging them would have to invent a key and would lose
    # whichever fields did not survive. They are reported separately.
    mac = "de:ad:be:ef:00:04"
    client, _transport = _both(
        clients=[{"_id": "abc", "mac": mac, "use_fixedip": True}],
        active=[{"mac": mac, "ip": "10.0.20.52", "network": "IoT"}],
    )

    result = under.collect(client)

    assert result["clients"] == [{"id": "abc", "mac": mac, "use_fixedip": True}]
    assert result["active"] == [{"mac": mac, "ip": "10.0.20.52", "network": "IoT"}]


def test_each_list_keeps_only_its_own_declared_fields() -> None:
    client, _transport = _both(clients=[{"_id": "abc", "mac": "de:ad:be:ef:00:05"}], active=[])

    result = under.collect(client)

    # fixed_ip is a registry field and not a station one, so a station cannot
    # carry it however the controller stores the row.
    assert "fixed_ip" not in result["clients"][0]
    assert result["active"] == []


def test_both_collections_are_read() -> None:
    client, transport = _both(clients=[], active=[])

    under.collect(client)

    paths = [urlsplit(request.url).path for request in transport.requests]
    assert paths[0].endswith(under.CLIENTS)
    assert paths[1].endswith(under.ACTIVE)
