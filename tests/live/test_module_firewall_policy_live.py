# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall policy module, against the throwaway controller.

The policy chain is reached at a base path of its own and holds its source and
destination as nested documents. A field table that named ``source.zone_id`` where
the controller holds ``source`` would still create a policy, so the nested keys are
asserted rather than the object's existence.

Two measured rules shape this suite. A create must state ``create_allow_respond``
false or the controller refuses it, and the controller assigns the position, so a
create without an index is accepted and comes back with one.

The module is invoked through the shared live harness, so the argument spec, the
check mode handling and the reporting are all exercised.

It writes, and it removes everything it creates, before each test and after it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import POLICY_ENGINE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import build_client
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_policy
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

#: The names this suite owns, so a run that fails part-way leaves objects it can
#: recognise and remove rather than ones that accumulate.
OWNED = "verify-fwp-"
NAME = f"{OWNED}policy"
NESTED_NAME = f"{OWNED}nested"
ORDERED_NAME = f"{OWNED}ordered"
ZONE = f"{OWNED}zone"
NETWORK = f"{OWNED}net"

#: A VLAN no other live suite uses, on a second octet of its own.
VLAN = 160
SUBNET = f"10.20.{VLAN}.1/24"

#: A position no other object in the suite claims. The chain's own default
#: policies hold the low positions, and a task that collides with one of them
#: leaves the order between the two to the controller.
INDEX = 160

#: The policy engine's two collections, relative to its own base path. They are
#: not beneath the site's ``rest/`` base, so a client built for the site cannot
#: read them.
POLICIES = "/firewall-policies"
ZONES = "/firewall/zone"

#: The site's own base, for the network the policies name.
NETWORKS = "/rest/networkconf"


@pytest.fixture(scope="session")
def engine() -> Any:
    """A session against the policy engine rather than the site.

    The credential, the site and the login are the site's own; only the base path
    differs, so the same builder composes it from the standard connection options.
    """
    return build_client(connection(), base=POLICY_ENGINE)


@pytest.fixture(scope="session", autouse=True)
def _require_zbf(engine: Any) -> None:
    """Skip where the zone-based firewall is not configured.

    The endpoint serves a site only once ZBF is switched on; without it a create
    answers api.err.CouldNotFindHotspotFirewallZone, and a suite that ran and failed
    would read as a defect rather than a target that cannot host it.
    """
    try:
        zones = engine.get(ZONES)
    except UniFiError:
        pytest.skip("the zone-based firewall is not configured on this target")
    if not isinstance(zones, list) or not zones:
        pytest.skip("the zone-based firewall is not configured on this target")


@pytest.fixture(autouse=True)
def zone_id(controller: Any, engine: Any) -> Iterator[str]:
    """The zone and the network the policies name, absent before and after each test.

    Before as well as after, because a run that failed part-way leaves objects
    holding a VLAN, and the next run would fail on a collision that has nothing to
    do with the module.
    """
    _remove_all(controller, engine)
    _create_network(controller)
    _create_zone(engine)
    yield _one(engine, ZONES, "name", ZONE)["_id"]
    _remove_all(controller, engine)


def _create_network(controller: Any) -> None:
    controller.post(
        NETWORKS,
        {
            "name": NETWORK,
            "purpose": "corporate",
            "enabled": True,
            "vlan": VLAN,
            "vlan_enabled": True,
            "ip_subnet": SUBNET,
        },
    )


def _create_zone(engine: Any) -> None:
    # The controller derives default_zone and refuses a create that carries it, so
    # the zone is created without one and comes back marked false by the controller.
    engine.post(ZONES, {"name": ZONE})


def _one(client: Any, collection: str, key: str, wanted: str) -> dict[str, Any]:
    """The single row carrying ``wanted``, or a failure naming what is there."""
    for row in rows(client.get(collection)):
        if str(row.get(key, "")) == wanted:
            return row
    listed = sorted(str(row.get(key, "")) for row in rows(client.get(collection)))
    raise AssertionError(f"no {collection} row named {wanted!r}; the site holds {listed}")


def _remove_all(controller: Any, engine: Any) -> None:
    remove_by_prefix(engine, POLICIES, prefix=OWNED)
    remove_by_prefix(engine, ZONES, prefix=OWNED)
    remove_by_prefix(controller, NETWORKS, prefix=OWNED)


def _policy_task(**overrides: Any) -> dict[str, Any]:
    task = connection(
        name=NAME,
        action="BLOCK",
        protocol="tcp",
        ip_version="BOTH",
        connection_state_type="ALL",
        enabled=True,
        logging=False,
    )
    task.update(overrides)
    return task


def test_a_task_creates_the_policy_and_a_second_run_does_not(zone_id: str) -> None:
    task = _policy_task(source_zone_id=zone_id)

    first = call(unifi_firewall_policy, task)
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_firewall_policy, task)
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_a_create_states_create_allow_respond_false(zone_id: str) -> None:
    # The controller refuses a create that omits it or sends it true, with
    # api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed, which is the one
    # correction the module has to make over the branch it was revived from.
    created = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id))
    assert not created.get("failed"), created.get("msg")

    assert created["obj"]["create_allow_respond"] is False


def test_the_controller_assigns_the_position(zone_id: str) -> None:
    # The controller assigns the position to a create, so a task that names none
    # must not be refused for the omission.
    created = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id))
    assert not created.get("failed"), created.get("msg")

    assert created["obj"]["index"] is not None


def test_the_options_reach_the_controller_under_their_own_field_names(zone_id: str) -> None:
    call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id))
    obj = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id))["obj"]

    # The task names source_zone_id; the controller holds a source document with a
    # zone_id inside it. A table that flattened the key would still have created a
    # policy, and the policy would govern everything rather than the zone.
    assert obj["source"]["zone_id"] == zone_id
    assert "source_zone_id" not in obj
    assert obj["action"] == "BLOCK"
    assert obj["protocol"] == "tcp"
    assert obj["ip_version"] == "BOTH"
    assert obj["connection_state_type"] == "ALL"
    assert obj["logging"] is False


def test_the_nested_source_and_destination_both_reach_the_controller(
    controller: Any, zone_id: str
) -> None:
    network_id = _one(controller, NETWORKS, "name", NETWORK)["_id"]
    task = _policy_task(
        name=NESTED_NAME,
        source_match="NETWORK",
        source_network_ids=[network_id],
        destination_match="ANY",
        destination_zone_id=zone_id,
        destination_port_list=443,
    )

    _call_ok(task)
    obj = _call_ok(task)["obj"]

    assert obj["source"]["matching_target"] == "NETWORK"
    assert obj["source"]["network_ids"] == [network_id]
    assert obj["destination"]["zone_id"] == zone_id
    assert obj["destination"]["matching_target"] == "ANY"
    assert obj["destination"]["port"] == 443


def test_a_position_is_compared_as_a_position(zone_id: str) -> None:
    task = _policy_task(name=ORDERED_NAME, index=INDEX, source_zone_id=zone_id)

    first = call(unifi_firewall_policy, task)
    assert first["changed"] is True, first

    second = call(unifi_firewall_policy, task)
    assert second["changed"] is False, second.get("changed_fields")


def test_check_mode_reports_the_change_without_creating(zone_id: str) -> None:
    reported = call(
        unifi_firewall_policy, _policy_task(source_zone_id=zone_id, _ansible_check_mode=True)
    )
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id))
    assert afterwards["changed"] is True, "check mode appears to have created the policy"


def test_absent_removes_and_a_second_run_reports_no_change(zone_id: str) -> None:
    _call_ok(_policy_task(source_zone_id=zone_id))

    removed = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id, state="absent"))
    assert removed["changed"] is True

    again = call(unifi_firewall_policy, _policy_task(source_zone_id=zone_id, state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_a_credential_is_never_echoed_in_a_failure(zone_id: str) -> None:
    result = call(
        unifi_firewall_policy,
        _policy_task(
            source_zone_id=zone_id,
            controller="127.0.0.1:1",
            api_key="a-secret-not-to-appear",
        ),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True


def _call_ok(task: dict[str, Any]) -> dict[str, Any]:
    """Run a task and fail the test if the module refused it."""
    result = call(unifi_firewall_policy, task)
    assert not result.get("failed"), result.get("msg")
    return result
