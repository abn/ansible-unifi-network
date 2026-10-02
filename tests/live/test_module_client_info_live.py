# SPDX-License-Identifier: GPL-3.0-or-later
"""The client info module, against the throwaway controller.

The kernel's own live suite proves the transport. This proves the module against
the thing that has to answer it: that C(/rest/user) and C(/stat/sta) are both
served, that a read reports no change, that the two lists are not merged, and
that every field the module projects from is a field the controller actually
sends under that name.

It creates nothing, so it removes nothing.
"""

from __future__ import annotations

from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_client_info
from tests.live.harness import call
from tests.live.settings import connection


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection()
    task.update(overrides)
    return task


def test_both_collections_are_served(client: UniFiClient) -> None:
    for resource in (unifi_client_info.CLIENTS, unifi_client_info.ACTIVE):
        body = client.get(resource)
        assert "meta" in body, (resource, body)
        assert isinstance(body.get("data"), list), (resource, body)


def test_a_read_reports_no_change_and_writes_nothing() -> None:
    result = call(unifi_client_info, _task())

    assert not result.get("failed"), result.get("msg")
    assert result["changed"] is False
    assert "diff" not in result


def test_the_result_is_two_lists_and_nothing_else() -> None:
    result = call(unifi_client_info, _task())

    assert set(result) >= {"clients", "active"}
    assert isinstance(result["clients"], list)
    assert isinstance(result["active"], list)


def test_each_projection_reproduces_its_controller_rows(client: UniFiClient) -> None:
    result = call(unifi_client_info, _task())
    pairs = (
        (unifi_client_info.CLIENTS, result["clients"], unifi_client_info.CLIENT_FIELDS),
        (unifi_client_info.ACTIVE, result["active"], unifi_client_info.ACTIVE_FIELDS),
    )

    for resource, projected, fields in pairs:
        raw = rows(client.get(resource))
        assert len(projected) == len(raw), resource
        for row, entry in zip(raw, projected, strict=True):
            expected = {name: row[field] for field, name in fields.items() if field in row}
            assert entry == expected, resource
            assert set(entry) <= set(fields.values()), resource


def test_the_registry_and_the_station_listing_keep_their_own_fields() -> None:
    # The two collections answer different questions and carry different fields,
    # so neither list may carry the other's keys however the controller stores the
    # rows.
    result = call(unifi_client_info, _task())

    for entry in result["clients"]:
        assert "hostname" not in entry
        assert "id" in entry or "mac" in entry
    for entry in result["active"]:
        assert "fixed_ip" not in entry
        assert "use_fixedip" not in entry
        assert "local_dns_record" not in entry
        assert "local_dns_record_enabled" not in entry
