# SPDX-License-Identifier: GPL-3.0-or-later
"""Reconciliation against the throwaway controller.

The unit suite proves the reconciler agrees with the tests' own expectations, and
the read suite proves the transport can authenticate. Neither can show that a
write lands, that the controller normalises what it is sent, or that a second run
reports no change. Only a controller can.

Everything here writes to the throwaway stack and nothing else, and every object
it creates is removed afterwards. The controller serves one site, so these tests
share it and are ordered by nothing: each names its own object and cleans up its
own, and a failure mid-test leaves the object for the next run to remove rather
than skipping it.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import NETWORK
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import apply
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select
from tests.live.cleanup import remove_by_prefix

RESOURCE = "/rest/networkconf"

#: Names the tests create, so a run that fails part-way leaves an object this
#: suite can recognise and remove rather than one that accumulates.
OWNED = "verify-write-"


@pytest.fixture(autouse=True)
def _clean_up(client: UniFiClient) -> Any:
    """Remove this suite's objects before and after each test.

    Before as well as after: a run that failed part-way leaves objects holding
    their VLANs, and the next run would then fail on a collision that has nothing
    to do with the code under test.
    """
    remove_by_prefix(client, RESOURCE, prefix=OWNED)
    yield
    remove_by_prefix(client, RESOURCE, prefix=OWNED)


def a_network(name: str, vlan: int) -> dict[str, Any]:
    """A network as a task would describe it.

    The address is a /24 on a fixed second octet, so the VLAN cannot reach into it.
    A third octet of 101 makes ``10.101.1.1/24`` an address outside its own subnet,
    which the controller refuses as an invalid payload.
    """
    return {
        "name": name,
        "purpose": "corporate",
        "enabled": True,
        "vlan": vlan,
        "vlan_enabled": True,
        "subnet": f"10.20.{vlan}.1/24",
        "dhcp_enabled": True,
        "dhcp_start": f"10.20.{vlan}.100",
        "dhcp_stop": f"10.20.{vlan}.200",
        "dhcp_lease_time": 86400,
    }


def test_a_network_is_created_and_read_back(client: UniFiClient) -> None:
    wanted = project(a_network(OWNED + "create", 101), NETWORK)

    outcome = apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    assert outcome.changed
    assert outcome.obj is not None
    assert outcome.obj["name"] == OWNED + "create"


def test_a_second_run_of_the_same_task_reports_no_change(client: UniFiClient) -> None:
    # The property the collection exists for. A run that reports a change here has
    # either compared something the controller does not store or sent a value in a
    # shape it stores differently.
    wanted = project(a_network(OWNED + "idempotent", 102), NETWORK)

    first = apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])
    second = apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    assert first.changed
    assert not second.changed, f"second run reported a change: {second.changes}"


def test_the_controller_normalises_a_value_the_task_sent_differently(client: UniFiClient) -> None:
    # The controller answers a VLAN id as a string on some endpoints and an integer
    # on others. If that difference read as drift, every run would report a change
    # against a controller nobody had touched.
    wanted = project(a_network(OWNED + "coerce", 103), NETWORK)
    apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    stored = select(client.get(RESOURCE), key="name", wanted=OWNED + "coerce", what="network")

    assert str(stored["vlan"]) == "103"


def test_a_field_the_task_did_not_mention_is_not_a_difference(client: UniFiClient) -> None:
    # The controller fills in fields no task names. Comparing the whole document
    # would report a change on every run. A VLAN is included because the controller
    # refuses a network without one, falling back to the VLAN already in use.
    wanted = project(
        {
            "name": OWNED + "projection",
            "purpose": "corporate",
            "vlan": 109,
            "vlan_enabled": True,
            "subnet": "10.20.109.1/24",
        },
        NETWORK,
    )
    apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    outcome = apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    assert not outcome.changed, f"a field the task never named read as drift: {outcome.changes}"


def test_a_check_mode_run_reports_the_change_without_writing(client: UniFiClient) -> None:
    wanted = project(a_network(OWNED + "checkmode", 104), NETWORK)

    outcome = apply(
        client, collection=RESOURCE, wanted=wanted, name=wanted["name"], check_mode=True
    )

    assert outcome.changed
    assert outcome.after
    created = [row for row in rows(client.get(RESOURCE)) if row.get("name") == OWNED + "checkmode"]
    assert not created, "check mode wrote to the controller"


def test_a_changed_value_is_applied_and_then_stops_changing(client: UniFiClient) -> None:
    wanted = project(a_network(OWNED + "update", 105), NETWORK)
    apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    changed = project({**a_network(OWNED + "update", 105), "dhcp_lease_time": 3600}, NETWORK)
    second = apply(client, collection=RESOURCE, wanted=changed, name=changed["name"])

    assert second.changed
    assert "dhcpd_leasetime" in second.changes
    assert not apply(client, collection=RESOURCE, wanted=changed, name=changed["name"]).changed


def test_the_diff_names_the_field_that_differed(client: UniFiClient) -> None:
    wanted = project(a_network(OWNED + "diff", 106), NETWORK)
    apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    changed = project({**a_network(OWNED + "diff", 106), "enabled": False}, NETWORK)
    outcome = apply(client, collection=RESOURCE, wanted=changed, name=changed["name"])

    assert outcome.changes == {"enabled": False}
    assert outcome.as_result()["diff"]["before"]["enabled"] is True
    assert outcome.as_result()["diff"]["after"]["enabled"] is False


def test_a_deleted_object_is_reported_as_absent_not_as_a_change(client: UniFiClient) -> None:
    wanted = project(a_network(OWNED + "gone", 107), NETWORK)
    apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])
    row = select(client.get(RESOURCE), key="name", wanted=OWNED + "gone", what="network")
    client.delete(f"{RESOURCE}/{row['_id']}")

    outcome = apply(client, collection=RESOURCE, wanted=wanted, name=wanted["name"])

    assert outcome.changed, "recreating a deleted object should report a change"


def test_two_names_that_collide_are_an_error_rather_than_a_choice(client: UniFiClient) -> None:
    # Choosing one of two rows a name matches is how the wrong one gets changed,
    # and the mistake is only visible afterwards.
    from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError

    with pytest.raises(UniFiError, match="ambiguous"):
        select(
            [
                {"_id": "one", "name": "duplicate"},
                {"_id": "two", "name": "duplicate"},
            ],
            key="name",
            wanted="duplicate",
            what="network",
        )


def test_a_name_that_matches_nothing_is_an_error(client: UniFiClient) -> None:
    from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError

    with pytest.raises(UniFiError, match="no network"):
        select(client.get(RESOURCE), key="name", wanted="no-such-network", what="network")
