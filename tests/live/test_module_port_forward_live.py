# SPDX-License-Identifier: GPL-3.0-or-later
"""The port forward module, against the throwaway controller.

The same shape as the wireless network suite, over a resource the controller
requires three fields on and holds two ends of separately. What only the
controller can answer is whether those three are stored as sent rather than
normalised, whether the two ports and the two ends keep their own field names,
and whether a delete actually stops the controller listing the forward, which is
the first verified delete in this collection.

A port forward is a path into the site, so the suite removes what it creates
before each test and after it, and a run that dies part-way leaves nothing open.
The module runs through a stand-in for ``AnsibleModule``, so the argument spec,
the check mode handling and the reporting are under test rather than assumed.

It writes, and it removes what it creates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_forward
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

#: Names created here, so a run that fails part-way leaves a forward this suite
#: recognises and removes rather than one that accumulates.
OWNED = "verify-pf-"

#: The ports this suite uses. Another suite holds 16xxx identifiers for DHCP
#: reservations, so the two cannot be told apart by range alone: these sit above
#: 16900, and the forward names carry the prefix above, so a cleanup matching on
#: that prefix cannot remove another suite's objects even if a port were shared.
#:
#: The two ends differ on purpose. The port the outside world connects to and the
#: port on the internal host are separate fields, and a fixture giving them the
#: same value cannot tell a module that confused them from one that did not.
DESTINATION_PORT = "16901"
OTHER_DESTINATION_PORT = "16902"
FORWARD_PORT = "16911"
OTHER_FORWARD_PORT = "16912"

NAME = f"{OWNED}basic"
OTHER_NAME = f"{OWNED}other"

#: The internal address the traffic is delivered to. Nothing answers there, and
#: nothing needs to: the controller stores the address rather than reaching it,
#: and a suite that created a reachable host to answer would be testing the
#: stack's networking rather than this module.
FORWARD_ADDRESS = "192.168.1.50"

#: The zone the site holds, relative to the site's base. Written out rather than
#: imported from the module, so a module addressing a different path fails to
#: read back what it wrote instead of quietly agreeing with this file.
PORT_FORWARDS = "/rest/portforward"

#: The firewall groups a source limit can name. A group is a resource of its own,
#: so a test that needs one creates it and removes it.
FIREWALL_GROUPS = "/rest/firewallgroup"
GROUP_NAME = "verify-pf-group"


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection(
        name=NAME,
        forward_address=FORWARD_ADDRESS,
        forward_port=FORWARD_PORT,
        destination_port=DESTINATION_PORT,
        protocol="tcp",
        interface="wan",
        destination_ip="any",
        log_enabled=True,
    )
    task.update(overrides)
    return task


@pytest.fixture(autouse=True)
def _remove_everything(controller: Any) -> Any:
    remove_by_prefix(controller, PORT_FORWARDS, prefix=OWNED)
    yield
    remove_by_prefix(controller, PORT_FORWARDS, prefix=OWNED)


@pytest.fixture(scope="module")
def firewall_group(controller: Any) -> Any:
    """A firewall group for a source limit to name, created and removed here.

    The site holds none, and a group is a resource of its own, so the name
    reference can only be exercised against one this suite makes. The group is
    removed on the way out whatever the run did in between.
    """
    remove_by_prefix(controller, FIREWALL_GROUPS, prefix=GROUP_NAME)
    controller.post(
        FIREWALL_GROUPS,
        {"name": GROUP_NAME, "group_type": "address-group", "group_members": ["10.0.0.0/8"]},
    )
    yield find_named(controller, FIREWALL_GROUPS, name=GROUP_NAME)
    remove_by_prefix(controller, FIREWALL_GROUPS, prefix=GROUP_NAME)


def _held(controller: Any) -> list[dict[str, Any]]:
    return [row for row in rows(controller.get(PORT_FORWARDS)) if OWNED in str(row.get("name", ""))]


def test_the_site_serves_the_port_forward_collection(controller: Any) -> None:
    # The module reads and writes beneath the site's own base rather than the
    # policy engine's, and only the controller can say whether this path is served.
    body = controller.get(PORT_FORWARDS)

    assert "meta" in body, body
    assert isinstance(body.get("data"), list), body


def test_a_task_creates_the_forward_and_a_second_run_does_not() -> None:
    first = call(unifi_port_forward, _task())
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_port_forward, _task())
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_options_reach_the_controller_under_their_own_field_names() -> None:
    call(unifi_port_forward, _task())
    obj = call(unifi_port_forward, _task())["obj"]

    # The task names forward_address, forward_port, destination_port, protocol
    # and interface; the controller holds fwd, fwd_port, dst_port, proto and
    # pfwd_interface. A table that got any of them wrong would still have
    # created a forward, so the field names are asserted rather than the
    # object's existence.
    assert obj["fwd"] == FORWARD_ADDRESS
    assert obj["fwd_port"] == FORWARD_PORT
    assert obj["dst_port"] == DESTINATION_PORT
    assert obj["proto"] == "tcp"
    assert obj["pfwd_interface"] == "wan"


def test_the_two_ends_of_the_forward_are_held_separately() -> None:
    created = call(unifi_port_forward, _task())
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    # The port the outside world connects to and the port on the internal host
    # are distinct fields. The fixture gives them different values, so a module
    # that collapsed the two, sending one where the other belongs, is caught here
    # rather than looking like a forward that works.
    assert obj["dst_port"] == DESTINATION_PORT
    assert obj["fwd_port"] == FORWARD_PORT
    assert obj["dst_port"] != obj["fwd_port"]


def test_the_three_required_fields_are_stored_as_the_module_sends_them() -> None:
    created = call(unifi_port_forward, _task(log_enabled=False))
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    # The controller requires enabled, log and src_limiting_enabled on every
    # document, and the module always sends all three. If the controller stored
    # one as anything other than the value sent, a run that sends it and one that
    # did not would differ on every pass.
    assert obj["enabled"] is True
    assert obj["log"] is False
    assert obj["src_limiting_enabled"] is False


def test_a_task_naming_none_of_the_three_reports_no_change_on_the_second_run() -> None:
    first = call(
        unifi_port_forward, _task(enabled=None, log_enabled=None, source_limiting_enabled=None)
    )
    assert not first.get("failed"), first.get("msg")

    # The three carry defaults, so leaving them out asserts those defaults
    # rather than declining to manage them.
    again = call(
        unifi_port_forward, _task(enabled=None, log_enabled=None, source_limiting_enabled=None)
    )
    assert again["changed"] is False, again.get("changed_fields")


def test_the_defaults_are_reported_on_a_first_run() -> None:
    created = call(
        unifi_port_forward, _task(enabled=None, log_enabled=None, source_limiting_enabled=None)
    )
    assert not created.get("failed"), created.get("msg")

    # The diff names what the run sent, so a play that omitted the three still
    # shows it asserted them.
    assert set(created["changed_fields"]) >= {"enabled", "log", "src_limiting_enabled"}


def test_a_port_forward_stores_its_ports_as_strings() -> None:
    call(unifi_port_forward, _task())
    obj = call(unifi_port_forward, _task())["obj"]

    # The controller holds both ports as strings, and a module that sent an
    # integer would be refused or silently coerced into a different value.
    assert isinstance(obj["fwd_port"], str), obj["fwd_port"]
    assert isinstance(obj["dst_port"], str), obj["dst_port"]


def test_source_limiting_reaches_the_controller_under_its_own_field_names() -> None:
    call(
        unifi_port_forward,
        _task(
            source_limiting_enabled=True,
            source_limiting_type="ip",
            source="10.20.0.0/16",
        ),
    )
    second = call(unifi_port_forward, _task(source_limiting_enabled=True))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")
    obj = second["obj"]

    assert obj["src_limiting_enabled"] is True
    assert obj["src_limiting_type"] == "ip"
    assert obj["src"] == "10.20.0.0/16"


def test_a_protocol_outside_the_controllers_own_values_is_refused() -> None:
    # `choices` is the framework's constraint, so the real AnsibleModule refuses
    # this at argument validation and names the option. The live stand-in enforces
    # the constraint too, but by raising rather than by calling fail_json, so the
    # refusal arrives as an exception here. Both are refusals before any request,
    # which is the property under test; what differs is only how the stand-in
    # reports it.
    with pytest.raises(ValueError, match="protocol") as raised:
        call(unifi_port_forward, _task(protocol="sctp"))

    # The message names the option and the values the controller accepts, which is
    # what an operator needs to correct the task. It does not echo the rejected
    # value, so that is not asserted.
    assert "tcp_udp" in str(raised.value)


def test_aliases_reach_the_options_they_name() -> None:
    # The spec declares short spellings, and the framework resolves them before
    # the module sees the task. A task written with the aliases has to reach the
    # same object as one written with the canonical names.
    task = connection(
        name=OTHER_NAME,
        fwd=FORWARD_ADDRESS,
        fwd_port=OTHER_FORWARD_PORT,
        dst_port=OTHER_DESTINATION_PORT,
        proto="tcp",
        interface="wan",
        destination_ip="any",
    )
    created = call(unifi_port_forward, task)
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    assert obj["fwd"] == FORWARD_ADDRESS
    assert obj["fwd_port"] == OTHER_FORWARD_PORT
    assert obj["dst_port"] == OTHER_DESTINATION_PORT
    assert obj["proto"] == "tcp"


def test_check_mode_reports_the_change_without_creating() -> None:
    reported = call(unifi_port_forward, _task(_ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_port_forward, _task())
    assert afterwards["changed"] is True, "check mode appears to have created the forward"


def test_a_check_mode_run_leaves_the_site_holding_no_forward(controller: Any) -> None:
    call(unifi_port_forward, _task(_ansible_check_mode=True))

    assert _held(controller) == []


def test_absent_removes_and_a_second_run_reports_no_change() -> None:
    call(unifi_port_forward, _task())
    removed = call(unifi_port_forward, _task(state="absent"))
    assert removed["changed"] is True

    again = call(unifi_port_forward, _task(state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_absent_actually_stops_the_site_listing_the_forward(controller: Any) -> None:
    call(unifi_port_forward, _task())
    call(unifi_port_forward, _task(state="absent"))

    # A delete answered with a success status is not proof the controller
    # stopped listing the object, and a forward left listed is a path into the
    # site that nothing closed.
    assert _held(controller) == []


def test_a_second_forward_coexists_and_removes_independently(controller: Any) -> None:
    call(unifi_port_forward, _task())
    call(
        unifi_port_forward,
        _task(
            name=OTHER_NAME,
            destination_port=OTHER_DESTINATION_PORT,
            forward_port=OTHER_FORWARD_PORT,
        ),
    )

    assert len(_held(controller)) == 2

    call(unifi_port_forward, _task(state="absent"))
    remaining = [str(row["name"]) for row in _held(controller)]
    assert remaining == [OTHER_NAME], remaining


def test_a_credential_is_never_echoed_in_a_failure() -> None:
    # The key is the credential the run authenticates with, so it is the one the
    # result may not carry. A password beside a key is refused by the spec before
    # the module runs.
    result = call(
        unifi_port_forward,
        _task(
            controller="127.0.0.1:1",
            api_key="a-secret-not-to-appear",
        ),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True


def _group_task(**overrides: Any) -> dict[str, Any]:
    return _task(
        source_limiting_enabled=True,
        source_limiting_type="firewall_group",
        **overrides,
    )


def test_a_firewall_group_named_in_the_task_reaches_the_group_it_means(
    firewall_group: dict[str, Any],
) -> None:
    # The point of the name reference: a play that knows the group's name and not
    # its ObjectId still limits the forward to the right group, and the controller
    # is the thing that supplies the identifier.
    task = _group_task(source_firewall_group=GROUP_NAME)

    first = call(unifi_port_forward, task)
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_port_forward, task)
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")
    assert second["obj"]["src_firewall_group_id"] == firewall_group["_id"]


def test_a_firewall_group_named_both_ways_is_refused(firewall_group: dict[str, Any]) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    with pytest.raises(ValueError, match="source_firewall_group"):
        call(
            unifi_port_forward,
            _group_task(
                source_firewall_group=GROUP_NAME,
                source_firewall_group_id=firewall_group["_id"],
            ),
        )


def test_a_firewall_group_name_the_controller_does_not_hold_is_refused() -> None:
    result = call(
        unifi_port_forward,
        _group_task(source_firewall_group="verify-no-such-group"),
    )

    assert result.get("failed") is True
    assert "verify-no-such-group" in str(result.get("msg", ""))
