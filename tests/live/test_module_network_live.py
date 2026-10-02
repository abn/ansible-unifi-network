# SPDX-License-Identifier: GPL-3.0-or-later
"""The first module, against the throwaway controller.

The kernel's own live suite proves the transport and the reconciler. This proves
the module: that its argument spec accepts what a task passes, that its options
reach the controller under the field names it intends, and that a second run of
the same task reports no change.

The module is invoked through a stand-in for ``AnsibleModule`` with a synthesised
argument payload, so the argument spec, the check mode handling and the reporting
are all exercised, and the run stays in one process. The integration target is
where a real playbook is driven.

It writes, and it removes what it creates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

NAME = "verify-module-network"
VLAN = 140
SUBNET = f"10.30.{VLAN}.1/24"


def _network_task(**overrides: Any) -> dict[str, Any]:
    task = connection(
        name=NAME,
        purpose="corporate",
        vlan=VLAN,
        vlan_enabled=True,
        subnet=SUBNET,
        dhcp_enabled=True,
        dhcp_start=f"10.30.{VLAN}.100",
        dhcp_stop=f"10.30.{VLAN}.200",
        dhcp_lease_time=86400,
    )
    task.update(overrides)
    return task


@pytest.fixture(autouse=True)
def _remove_everything(controller: Any) -> Any:
    remove_by_prefix(controller, "/rest/networkconf", prefix="verify-")
    yield
    remove_by_prefix(controller, "/rest/networkconf", prefix="verify-")


def test_a_task_creates_the_network_and_a_second_run_does_not() -> None:
    first = call(unifi_network, _network_task())
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_network, _network_task())
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_options_reach_the_controller_under_their_own_field_names() -> None:
    call(unifi_network, _network_task())
    obj = call(unifi_network, _network_task())["obj"]

    # The task names subnet and dhcp_lease_time; the controller holds ip_subnet and
    # dhcpd_leasetime. A table that got either wrong would still have created a
    # network, so the field names are asserted rather than the object's existence.
    assert obj["ip_subnet"] == SUBNET
    assert obj["dhcpd_leasetime"] == 86400
    assert obj["vlan"] == VLAN


def test_a_resolver_list_creates_and_a_second_run_does_not() -> None:
    resolvers = ["10.30.140.1", "1.1.1.1"]

    first = call(unifi_network, _network_task(dhcp_dns=resolvers))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_network, _network_task(dhcp_dns=resolvers))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_resolver_list_reaches_the_controller_slots() -> None:
    call(unifi_network, _network_task(dhcp_dns=["10.30.140.1", "1.1.1.1"]))
    obj = call(unifi_network, _network_task(dhcp_dns=["10.30.140.1", "1.1.1.1"]))["obj"]

    # The list is a spelling of the four slots the controller holds, and every
    # slot is written. The unused ones carry the empty string the controller
    # stores for a cleared resolver rather than being left out.
    assert obj["dhcpd_dns_enabled"] is True
    assert obj["dhcpd_dns_1"] == "10.30.140.1"
    assert obj["dhcpd_dns_2"] == "1.1.1.1"
    assert obj["dhcpd_dns_3"] == ""
    assert obj["dhcpd_dns_4"] == ""


def test_a_shorter_resolver_list_clears_the_slot_it_dropped() -> None:
    call(unifi_network, _network_task(dhcp_dns=["10.30.140.1", "1.1.1.1"]))

    shrunk = call(unifi_network, _network_task(dhcp_dns=["10.30.140.1"]))
    assert not shrunk.get("failed"), shrunk.get("msg")
    assert shrunk["changed"] is True, shrunk.get("changed_fields")
    assert shrunk["obj"]["dhcpd_dns_2"] == ""

    again = call(unifi_network, _network_task(dhcp_dns=["10.30.140.1"]))
    assert again["changed"] is False, again.get("changed_fields")


def test_check_mode_reports_the_change_without_creating() -> None:
    reported = call(unifi_network, _network_task(_ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_network, _network_task())
    assert afterwards["changed"] is True, "check mode appears to have created the network"


def test_absent_removes_and_a_second_run_reports_no_change() -> None:
    call(unifi_network, _network_task())
    removed = call(unifi_network, _network_task(state="absent"))
    assert removed["changed"] is True

    again = call(unifi_network, _network_task(state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_a_credential_is_never_echoed_in_a_failure() -> None:
    # The key is the credential the run authenticates with, so it is the one the
    # result may not carry. A password beside a key is refused by the spec before
    # the module runs.
    result = call(
        unifi_network, _network_task(controller="127.0.0.1:1", api_key="a-secret-not-to-appear")
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True
