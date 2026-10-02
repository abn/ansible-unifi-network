# SPDX-License-Identifier: GPL-3.0-or-later
"""The network info module, against the throwaway controller.

The kernel's own live suite proves the transport. This proves the module against
the thing that has to answer it: that C(/rest/networkconf) is served, that a read
reports no change, and that every field the module projects from is a field the
controller actually sends under that name.

It creates nothing, so it removes nothing.
"""

from __future__ import annotations

from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network_info
from tests.live.harness import call
from tests.live.settings import connection


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection()
    task.update(overrides)
    return task


def _raw(client: UniFiClient) -> list[dict[str, Any]]:
    return rows(client.get(unifi_network_info.EXPORT))


def test_the_network_collection_is_served(client: UniFiClient) -> None:
    body = client.get(unifi_network_info.EXPORT)

    assert "meta" in body, body
    assert isinstance(body.get("data"), list), body


def test_a_read_reports_no_change_and_writes_nothing() -> None:
    result = call(unifi_network_info, _task())

    assert not result.get("failed"), result.get("msg")
    assert result["changed"] is False
    assert "diff" not in result


def test_the_projection_reproduces_the_controller_rows(client: UniFiClient) -> None:
    # The controller's own field names are the ones the module projects from, so
    # a name the collection got wrong fails here rather than silently returning
    # nothing for that key.
    result = call(unifi_network_info, _task())
    raw = _raw(client)
    projected = result["resources"]

    assert len(projected) == len(raw)
    for row, entry in zip(raw, projected, strict=True):
        expected = {
            name: row[field] for field, name in unifi_network_info.FIELDS.items() if field in row
        }
        assert entry == expected
        assert set(entry) <= set(unifi_network_info.FIELDS.values())


def test_the_sites_own_default_network_is_reported(client: UniFiClient) -> None:
    result = call(unifi_network_info, _task())

    assert "Default" in [entry.get("name") for entry in result["resources"]]


def test_a_controller_field_outside_the_whitelist_is_not_reported() -> None:
    # attr_hidden and site_id are the controller's bookkeeping, declared nowhere,
    # and a projection that handed the row back whole would carry them.
    result = call(unifi_network_info, _task())

    for entry in result["resources"]:
        assert "attr_hidden" not in entry
        assert "site_id" not in entry
        assert "ip_subnet" not in entry
