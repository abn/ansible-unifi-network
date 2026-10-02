# SPDX-License-Identifier: GPL-3.0-or-later
"""The port profile module, against the throwaway controller.

A profile's networks are stored as the native one and the list the profile
excludes, and the module computes that list from every network the site holds. The
site is shared, and other suites create and remove networks, so this suite creates
its own baseline networks around each profile and removes them again. It asserts
what only the controller can answer: that the computed list is stored verbatim,
that a second run reports no change, that changing the tagged set is a change, and
that a removal stays removed.

The module runs through a stand-in for ``AnsibleModule``, so the argument spec, the
check mode handling and the reporting are under test rather than assumed.

It writes, and it removes what it creates.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_profile
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

#: Every object this suite creates carries it, so a run that failed part-way
#: leaves networks and a profile the next run recognises and removes.
OWNED = "verify-port-profile"

#: The profile under test, and the networks it names. Distinct names and VLANs, so
#: nothing another suite owns collides with them.
PROFILE = f"{OWNED}-access"
NATIVE = f"{OWNED}-native"
TAGGED = f"{OWNED}-tagged"
SECOND = f"{OWNED}-second"

PROFILE_COLLECTION = "/rest/portconf"
NETWORK_COLLECTION = "/rest/networkconf"

#: The three baseline networks and their VLANs, which no other suite uses.
BASELINE = ((NATIVE, 171), (TAGGED, 172), (SECOND, 173))


def _network(name: str, vlan: int) -> dict[str, Any]:
    return connection(
        name=name,
        purpose="corporate",
        vlan=vlan,
        vlan_enabled=True,
        subnet=f"10.30.{vlan}.1/24",
        dhcp_enabled=True,
        dhcp_start=f"10.30.{vlan}.100",
        dhcp_stop=f"10.30.{vlan}.200",
        dhcp_lease_time=86400,
    )


def _profile_task(**overrides: Any) -> dict[str, Any]:
    task = connection(
        name=PROFILE,
        native_network=NATIVE,
        tagged_networks=[TAGGED],
    )
    task.update(overrides)
    return task


def _id(controller: Any, name: str) -> str:
    return str(find_named(controller, NETWORK_COLLECTION, name=name)["_id"])


def _network_ids(controller: Any) -> set[str]:
    return {str(row["_id"]) for row in rows(controller.get(NETWORK_COLLECTION)) if row.get("_id")}


@pytest.fixture(scope="module")
def baseline(controller: Any) -> Any:
    """The networks the computed exclusion list is measured against.

    Created before and removed after, because the exclusion list is computed from
    the whole site and another suite's leftover network would move it. Removal
    matches the prefix, so a run that failed part-way is repeatable.
    """
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=OWNED)
    for name, vlan in BASELINE:
        created = call(unifi_network, _network(name, vlan))
        assert not created.get("failed"), created.get("msg")
    yield
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=OWNED)


@pytest.fixture(autouse=True)
def _remove_profiles(controller: Any) -> Any:
    remove_by_prefix(controller, PROFILE_COLLECTION, prefix=OWNED)
    yield
    remove_by_prefix(controller, PROFILE_COLLECTION, prefix=OWNED)


def test_a_task_creates_the_profile_and_a_second_run_does_not(baseline: Any) -> None:
    first = call(unifi_port_profile, _profile_task())
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_port_profile, _profile_task())
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_computed_exclusions_are_the_networks_the_profile_does_not_name(
    baseline: Any, controller: Any
) -> None:
    call(unifi_port_profile, _profile_task())
    obj = call(unifi_port_profile, _profile_task())["obj"]

    # The task names NATIVE and TAGGED; the console holds the complement of those
    # in excluded_networkconf_ids, and it stores the list verbatim.
    native = _id(controller, NATIVE)
    tagged = _id(controller, TAGGED)
    assert obj["native_networkconf_id"] == native
    assert set(obj["excluded_networkconf_ids"]) == _network_ids(controller) - {native, tagged}


def test_changing_the_tagged_set_is_a_change_and_converges(baseline: Any, controller: Any) -> None:
    call(unifi_port_profile, _profile_task())

    moved = call(unifi_port_profile, _profile_task(tagged_networks=[SECOND]))
    assert not moved.get("failed"), moved.get("msg")
    assert moved["changed"] is True, moved.get("changed_fields")
    assert _id(controller, TAGGED) in moved["obj"]["excluded_networkconf_ids"]
    assert _id(controller, SECOND) not in moved["obj"]["excluded_networkconf_ids"]

    again = call(unifi_port_profile, _profile_task(tagged_networks=[SECOND]))
    assert again["changed"] is False, again.get("changed_fields")


def test_a_fixed_speed_reaches_the_controller_and_converges(baseline: Any, controller: Any) -> None:
    # The controller negotiates speed and duplex on its hardware port table, but a
    # profile carries them as configuration. Only a live run proves the kernel
    # sends them rather than dropping them as server generated.
    created = call(unifi_port_profile, _profile_task(speed=100, full_duplex=False))
    assert not created.get("failed"), created.get("msg")
    assert created["changed"] is True, created

    stored = find_named(controller, PROFILE_COLLECTION, name=PROFILE)
    assert stored["speed"] == 100
    assert stored["full_duplex"] is False

    moved = call(unifi_port_profile, _profile_task(speed=10, full_duplex=False))
    assert not moved.get("failed"), moved.get("msg")
    assert moved["changed"] is True, moved.get("changed_fields")
    assert find_named(controller, PROFILE_COLLECTION, name=PROFILE)["speed"] == 10

    again = call(unifi_port_profile, _profile_task(speed=10, full_duplex=False))
    assert again["changed"] is False, again.get("changed_fields")


def test_absent_removes_and_a_second_run_reports_no_change(baseline: Any) -> None:
    call(unifi_port_profile, _profile_task())
    removed = call(unifi_port_profile, _profile_task(state="absent"))
    assert removed["changed"] is True

    again = call(unifi_port_profile, _profile_task(state="absent"))
    assert again["changed"] is False, "removing twice reported a change"
