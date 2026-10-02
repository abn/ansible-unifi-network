# SPDX-License-Identifier: GPL-3.0-or-later
"""The network info module, without a controller.

Every case here replaces the transport, so the run reaches no socket and the
constraint from the project rules is held by construction rather than by
inspection. What is asserted is the projection: the module reports a whitelist of
the controller's fields, and a field the controller stores beyond that set never
reaches a play.

What only the controller can answer, and what the live suite therefore asks
instead, is whether C(/rest/networkconf) is served and whether the controller's
own field names are the ones this module projects from.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import RawResponse
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network_info as under

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
    """A transport answering each collection from a map, and refusing the rest.

    The refusal is the point: a resource this file did not plan for is a bug in
    the module rather than a request that quietly succeeds.
    """

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
        "name": "IoT",
        "purpose": "corporate",
        "vlan": 20,
        "ip_subnet": "10.0.20.1/24",
        "dhcpd_enabled": True,
        # Declared nowhere, so none of these may survive.
        "site_id": "def",
        "attr_hidden": False,
        "dhcpd_boot_enabled": True,
    }
    client, _transport = _client({under.EXPORT: [row]})

    assert under.collect(client) == [
        {
            "id": "abc",
            "name": "IoT",
            "purpose": "corporate",
            "vlan": 20,
            "subnet": "10.0.20.1/24",
            "dhcp_enabled": True,
        }
    ]


def test_a_controller_field_is_reported_under_its_documented_name() -> None:
    client, _transport = _client({under.EXPORT: [{"_id": "abc", "ip_subnet": "10.0.20.1/24"}]})

    entry = under.collect(client)[0]

    assert entry["subnet"] == "10.0.20.1/24"
    assert "ip_subnet" not in entry


def test_a_field_the_controller_omits_is_not_invented() -> None:
    # A projection that filled every declared key with null would make "the
    # controller said nothing" indistinguishable from "the controller said null".
    client, _transport = _client({under.EXPORT: [{"_id": "abc", "name": "IoT"}]})

    assert under.collect(client) == [{"id": "abc", "name": "IoT"}]


def test_all_four_resolver_slots_are_projected() -> None:
    # The controller holds four DNS resolver slots; a projection that stopped at
    # two silently withheld the third and fourth.
    row = {
        "_id": "abc",
        "dhcpd_dns_1": "10.0.20.1",
        "dhcpd_dns_2": "10.0.20.2",
        "dhcpd_dns_3": "10.0.20.3",
        "dhcpd_dns_4": "10.0.20.4",
    }
    client, _transport = _client({under.EXPORT: [row]})

    entry = under.collect(client)[0]

    assert entry["dhcp_dns_1"] == "10.0.20.1"
    assert entry["dhcp_dns_2"] == "10.0.20.2"
    assert entry["dhcp_dns_3"] == "10.0.20.3"
    assert entry["dhcp_dns_4"] == "10.0.20.4"


def test_a_site_holding_no_networks_reports_an_empty_list() -> None:
    client, _transport = _client({under.EXPORT: []})

    assert under.collect(client) == []


def test_a_response_that_is_not_a_list_reports_nothing() -> None:
    assert under.export({"meta": {"rc": "ok"}}) == []


def test_the_read_addresses_the_network_collection() -> None:
    client, transport = _client({under.EXPORT: []})

    under.collect(client)

    assert urlsplit(transport.requests[0].url).path.endswith(under.EXPORT)
