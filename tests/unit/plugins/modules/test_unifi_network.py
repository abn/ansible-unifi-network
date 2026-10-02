# SPDX-License-Identifier: GPL-3.0-or-later
"""The network module's resolver list and its expansion into the controller slots.

The list is a module option with no field of its own: it is a spelling of the
four scalar slots the controller holds, and it has to expand to all four on every
run. A run that wrote only the slots the task named would leave a resolver it
dropped behind, because the controller keeps a slot it was given and only ever
clears one it is sent an empty string for.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import differences
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import NETWORK
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network

#: The four controller slots the list expands into, and the option each comes
#: from. Stated rather than read from the module, so a spec that renamed one
#: fails here rather than agreeing with itself.
SLOTS = ("dhcp_dns_1", "dhcp_dns_2", "dhcp_dns_3", "dhcp_dns_4")


def _connection() -> dict[str, Any]:
    return {
        "controller": "unifi.example.invalid",
        "api_mount": "appliance",
        "api_family": "legacy",
        "name": "IoT",
    }


def _expanded(**task: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "IoT", **task}
    unifi_network._expand_dhcp_dns(params)
    return params


def test_the_resolver_list_is_a_list_of_strings() -> None:
    spec = unifi_network.ARGUMENT_SPEC["dhcp_dns"]

    assert spec["type"] == "list"
    assert spec["elements"] == "str"


def test_the_list_expands_to_all_four_controller_slots() -> None:
    wanted = project(_expanded(dhcp_dns=["10.0.20.1", "1.1.1.1"]), NETWORK)

    assert wanted == {
        "name": "IoT",
        "dhcpd_dns_enabled": True,
        "dhcpd_dns_1": "10.0.20.1",
        "dhcpd_dns_2": "1.1.1.1",
        "dhcpd_dns_3": "",
        "dhcpd_dns_4": "",
    }


def test_the_list_turns_resolver_serving_on() -> None:
    params = _expanded(dhcp_dns=["10.0.20.1"])

    assert params["dhcp_dns_enabled"] is True


def test_the_list_and_the_flag_being_off_are_refused() -> None:
    # The list asks the controller to serve resolvers and the flag asks it not to.
    # Resolving that by precedence would serve resolvers the task asked it not to.
    with pytest.raises(UniFiError, match="dhcp_dns_enabled"):
        _expanded(dhcp_dns=["10.0.20.1"], dhcp_dns_enabled=False)


def test_a_shorter_list_clears_the_slots_it_dropped() -> None:
    # A controller holding two resolvers that is then given one has to lose the
    # second, and the empty string is what the controller stores for a cleared
    # slot. A run that skipped the slot would leave the old resolver in place.
    two = project(_expanded(dhcp_dns=["10.0.20.1", "1.1.1.1"]), NETWORK)
    one = project(_expanded(dhcp_dns=["10.0.20.1"]), NETWORK)

    assert differences(one, two) == {"dhcpd_dns_2": ""}


def test_rerunning_the_same_shorter_list_reports_no_change() -> None:
    one = project(_expanded(dhcp_dns=["10.0.20.1"]), NETWORK)

    assert differences(one, one) == {}


def test_a_five_element_list_is_refused() -> None:
    with pytest.raises(UniFiError, match="dhcp_dns"):
        _expanded(dhcp_dns=["10.0.20.1", "1.1.1.1", "8.8.8.8", "9.9.9.9", "8.8.4.4"])


def test_an_empty_list_is_refused() -> None:
    # Serving no resolvers is expressed by turning the flag off, not by an empty
    # list, and an empty list that expanded would clear all four silently.
    with pytest.raises(UniFiError, match="dhcp_dns_enabled"):
        _expanded(dhcp_dns=[])


def test_the_list_is_mutually_exclusive_with_every_scalar_slot() -> None:
    pairs = unifi_network.DNS_MUTUALLY_EXCLUSIVE

    assert pairs == [("dhcp_dns", slot) for slot in SLOTS]


def test_naming_the_list_and_a_scalar_slot_is_refused() -> None:
    task = {
        **_connection(),
        "dhcp_dns": ["1.1.1.1"],
        "dhcp_dns_1": "9.9.9.9",
    }
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))

    with pytest.raises(SystemExit):
        basic.AnsibleModule(
            argument_spec=unifi_network.ARGUMENT_SPEC,
            mutually_exclusive=unifi_network.DNS_MUTUALLY_EXCLUSIVE,
        )


def test_the_list_is_not_a_controller_field_of_its_own() -> None:
    # The list is a spelling of the four slots, so a table entry for it would
    # send a field the controller does not declare.
    assert "dhcp_dns" not in NETWORK
