# SPDX-License-Identifier: GPL-3.0-or-later
"""Port overrides, against the throwaway controller's emulated switch.

The override is one element of an array on a device, so what only the controller
can answer is how it merges: a write to one port has to leave the others as they
were, a second run has to report no change, and dropping an entry has to stay
dropped. The switch reports eight ports, so the suite uses three it owns and
cleans them before and after.

Both surfaces are exercised here: C(unifi_port_override) for one port, including
its removal, and C(unifi_device)'s C(port_overrides) list, which merges.

It writes, and it removes what it creates.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_override
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_profile
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import EMULATED_SWITCH_MAC
from tests.live.settings import connection

#: Every entry this suite writes carries it, so a run that failed part-way is
#: recognisable to the next run. The switch is shared, so the ports are too.
OWNED = "verify-port-override"
PORTS = (6, 7, 8)

PROFILE = f"{OWNED}-profile"
NETWORK = f"{OWNED}-network"

DEVICE_INVENTORY = "/stat/device"
PROFILE_COLLECTION = "/rest/portconf"
NETWORK_COLLECTION = "/rest/networkconf"


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection(mac=EMULATED_SWITCH_MAC, port_idx=PORTS[0], state="present", name=OWNED)
    task.update(overrides)
    return task


def _device(**overrides: Any) -> dict[str, Any]:
    task = connection(mac=EMULATED_SWITCH_MAC)
    task.update(overrides)
    return task


def _switch(controller: Any) -> dict[str, Any]:
    for row in rows(controller.get(DEVICE_INVENTORY)):
        if str(row.get("mac", "")) == EMULATED_SWITCH_MAC:
            return dict(row)
    raise AssertionError(f"the controller does not hold {EMULATED_SWITCH_MAC}")


def _entry(controller: Any, port_idx: int) -> dict[str, Any]:
    for entry in _switch(controller).get("port_overrides") or []:
        if str(entry.get("port_idx", "")) == str(port_idx):
            return dict(entry)
    return {}


def _clear(controller: Any) -> None:
    """Drop every override this suite owns, whichever surface wrote it.

    Absence is not a change, so removing a port that holds no entry is a no-op.
    """
    for port_idx in PORTS:
        call(
            unifi_port_override,
            connection(mac=EMULATED_SWITCH_MAC, port_idx=port_idx, state="absent"),
        )


@pytest.fixture(autouse=True)
def _remove_overrides(controller: Any) -> Any:
    _clear(controller)
    yield
    _clear(controller)


@pytest.fixture
def profile_baseline(controller: Any) -> Any:
    """A network and a port profile for the profile reference to resolve against.

    Removed in the reverse order they were created, and after the overrides that
    point at the profile, so nothing is deleted while it is in use.
    """
    remove_by_prefix(controller, PROFILE_COLLECTION, prefix=OWNED)
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=OWNED)
    created_network = call(
        unifi_network,
        connection(
            name=NETWORK,
            purpose="corporate",
            vlan=181,
            vlan_enabled=True,
            subnet="10.30.181.1/24",
            dhcp_enabled=True,
            dhcp_start="10.30.181.100",
            dhcp_stop="10.30.181.200",
            dhcp_lease_time=86400,
        ),
    )
    assert not created_network.get("failed"), created_network.get("msg")
    created_profile = call(unifi_port_profile, connection(name=PROFILE, native_network=NETWORK))
    assert not created_profile.get("failed"), created_profile.get("msg")
    yield str(find_named(controller, PROFILE_COLLECTION, name=PROFILE)["_id"])
    _clear(controller)
    remove_by_prefix(controller, PROFILE_COLLECTION, prefix=OWNED)
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=OWNED)


def test_a_task_sets_an_override_and_a_second_run_reports_no_change(
    controller: Any,
) -> None:
    first = call(unifi_port_override, _task(port_idx=6, name=OWNED))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_port_override, _task(port_idx=6, name=OWNED))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")

    assert _entry(controller, 6)["name"] == OWNED


def test_the_controllers_own_field_names_reach_the_device(controller: Any) -> None:
    # The task names `poe_mode`; a write that dropped it would leave the entry
    # without it and still report a change. The controller fills in a native
    # network when it accepts an entry, which is the shape that proves the write
    # landed rather than being merged into nothing.
    result = call(unifi_port_override, _task(port_idx=6, name=OWNED, poe_mode="off"))
    assert not result.get("failed"), result.get("msg")

    entry = _entry(controller, 6)
    assert entry["name"] == OWNED
    assert entry["poe_mode"] == "off"


def test_changing_one_port_leaves_another_alone(controller: Any) -> None:
    call(unifi_port_override, _task(port_idx=6, name=f"{OWNED}-one"))
    call(unifi_port_override, _task(port_idx=7, name=f"{OWNED}-two"))

    moved = call(unifi_port_override, _task(port_idx=6, name=f"{OWNED}-changed"))
    assert not moved.get("failed"), moved.get("msg")
    assert moved["changed"] is True, moved.get("changed_fields")

    assert _entry(controller, 6)["name"] == f"{OWNED}-changed"
    assert _entry(controller, 7)["name"] == f"{OWNED}-two"


def test_a_port_profile_reference_reaches_the_controller(
    controller: Any,
    profile_baseline: str,
) -> None:
    # The task names the profile and the controller holds the identifier it
    # resolves to, which is what a write aimed at the wrong profile would miss.
    result = call(unifi_port_override, _task(port_idx=8, port_profile=PROFILE))
    assert not result.get("failed"), result.get("msg")
    assert result["changed"] is True, result

    assert _entry(controller, 8)["portconf_id"] == profile_baseline


def test_the_controller_derives_forward_from_the_ports_membership(
    controller: Any,
    profile_baseline: str,
) -> None:
    # The module does not expose forward. A value written straight onto the device
    # is not stored: the controller reads it back from membership, so a task could
    # only ever converge on the value the controller was going to derive anyway.
    network = find_named(controller, NETWORK_COLLECTION, name=NETWORK)
    device = _switch(controller)
    device["port_overrides"] = [
        entry for entry in device.get("port_overrides") or [] if str(entry.get("port_idx")) != "8"
    ]
    device["port_overrides"].append(
        {
            "port_idx": 8,
            "name": OWNED,
            "forward": "native",
            "native_networkconf_id": network["_id"],
        }
    )

    controller.set(f"/rest/device/{device['_id']}", device)

    assert _entry(controller, 8)["forward"] == "customize"


def test_absent_removes_the_entry_and_stays_removed(controller: Any) -> None:
    call(unifi_port_override, _task(port_idx=6, name=OWNED))

    removed = call(unifi_port_override, _task(port_idx=6, state="absent"))
    assert not removed.get("failed"), removed.get("msg")
    assert removed["changed"] is True, removed
    assert _entry(controller, 6) == {}

    again = call(unifi_port_override, _task(port_idx=6, state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_the_device_module_merges_a_port_override(controller: Any) -> None:
    # The list surface writes through the same embedded merge, so the entry it
    # names lands and a port it does not name keeps its own.
    call(unifi_port_override, _task(port_idx=6, name=f"{OWNED}-kept"))

    first = call(
        unifi_device,
        _device(port_overrides=[{"port_idx": 7, "name": f"{OWNED}-list"}]),
    )
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first
    assert _entry(controller, 7)["name"] == f"{OWNED}-list"

    second = call(
        unifi_device,
        _device(port_overrides=[{"port_idx": 7, "name": f"{OWNED}-list"}]),
    )
    assert second["changed"] is False, second.get("changed_fields")
    assert _entry(controller, 6)["name"] == f"{OWNED}-kept"
