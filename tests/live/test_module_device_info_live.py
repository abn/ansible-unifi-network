# SPDX-License-Identifier: GPL-3.0-or-later
"""The device info module, against the throwaway controller.

The kernel's own live suite proves the transport. This proves the module against
the thing that has to answer it: that C(/stat/device) is served rather than the
write path, that a read reports no change, and that every field the module
projects from is a field the controller actually sends under that name.

The throwaway stack adopts the emulated fleet, so these cases read the rows the
controller holds: an access point and a switch, whose populated port table is
what a port-configuration write targets. It creates nothing, so it removes
nothing.
"""

from __future__ import annotations

from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device_info
from tests.live.harness import call
from tests.live.settings import EMULATED_SWITCH_MAC
from tests.live.settings import connection


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection()
    task.update(overrides)
    return task


def _raw(client: UniFiClient) -> list[dict[str, Any]]:
    return rows(client.get(unifi_device_info.EXPORT))


def test_the_device_listing_is_served(client: UniFiClient) -> None:
    body = client.get(unifi_device_info.EXPORT)

    assert "meta" in body, body
    assert isinstance(body.get("data"), list), body


def test_a_read_reports_no_change_and_writes_nothing() -> None:
    result = call(unifi_device_info, _task())

    assert not result.get("failed"), result.get("msg")
    assert result["changed"] is False
    assert "diff" not in result


def test_the_projection_reproduces_the_controller_rows(client: UniFiClient) -> None:
    result = call(unifi_device_info, _task())
    raw = _raw(client)
    projected = result["resources"]

    assert len(projected) == len(raw)
    for row, entry in zip(raw, projected, strict=True):
        expected = {
            name: row[field] for field, name in unifi_device_info.FIELDS.items() if field in row
        }
        assert entry == expected
        assert set(entry) <= set(unifi_device_info.FIELDS.values())
    # A projection computed from the same table cannot catch a wrong source field
    # name on its own, because both sides would drop it together. A field the
    # controller always sends is asserted present when the site holds a device.
    if raw:
        assert "mac" in projected[0]


def test_the_listing_holds_the_emulated_switch_with_its_ports(client: UniFiClient) -> None:
    # The fleet is an access point and a switch, and only the switch reports a port
    # table. The projection drops port_table, so the assertion reads the
    # controller's own row rather than the module's result.
    switch = next(
        (row for row in _raw(client) if str(row.get("mac", "")) == EMULATED_SWITCH_MAC),
        None,
    )

    assert switch is not None, f"the controller does not hold {EMULATED_SWITCH_MAC}"
    assert len(switch.get("port_table", [])) > 1, switch.get("port_table")


def test_a_controller_field_outside_the_whitelist_is_not_reported() -> None:
    # The device document carries runtime and statistics the write schema does not
    # declare, and a projection that handed the row back whole would carry them.
    result = call(unifi_device_info, _task())

    for entry in result["resources"]:
        assert "port_overrides" not in entry
        assert "site_id" not in entry
        assert "_id" not in entry
