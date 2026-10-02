# SPDX-License-Identifier: GPL-3.0-or-later
"""The wireless network module, against the throwaway controller.

The same questions the network module's suite asks, asked of a resource the
controller holds flat rather than nested, and of a resource that carries a secret.
The module runs through a stand-in for ``AnsibleModule``, so the argument spec, the
check mode handling and the reporting are under test rather than assumed.

The network the wireless networks ride on is created through the module that owns
a network, which is also what the collection would do in a play, and it is removed
again on the way out.

It writes, and it removes what it creates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network
from ansible_collections.abn.unifi_network.plugins.modules import unifi_wlan
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection
from tests.live.settings import wlan_network

NAME = "verify-module-wlan"
COLLECTION = "/rest/wlanconf"
NETWORK_COLLECTION = "/rest/networkconf"

#: Names created here, so a run that fails part-way leaves a wireless network this
#: suite recognises and removes rather than one that accumulates.
OWNED = "verify-"

#: The network the wireless networks below ride on. Matched by name rather than
#: by an identifier recorded at creation, so a leftover from an earlier run is
#: found and removed.
NETWORK_NAME = "verify-wlan-network"

#: Long enough for the controller's own bound, and not a secret.
PASSPHRASE = "a-passphrase-for-verification"


def _wlan_task(network_id: str, ap_group_id: str, **overrides: Any) -> dict[str, Any]:
    task = connection(
        name=NAME,
        network_id=network_id,
        ap_group_ids=[ap_group_id],
        enabled=True,
        band="both",
        security="wpapsk",
        wpa_mode="wpa2",
        wpa_enc="ccmp",
        passphrase=PASSPHRASE,
        hide_ssid=True,
    )
    task.update(overrides)
    return task


def _by_name_task(network: str, ap_group: str, **overrides: Any) -> dict[str, Any]:
    """The same task, naming its references rather than pasting identifiers."""
    task = _wlan_task("", "", **overrides)
    task.pop("network_id")
    task.pop("ap_group_ids")
    task["network"] = network
    task["ap_groups"] = [ap_group]
    return task


@pytest.fixture(scope="session")
def engine(client: Any) -> Any:
    """The shared session, addressed at the policy engine."""
    return client.rebased()


@pytest.fixture(scope="session")
def ap_group(engine: Any) -> dict[str, Any]:
    """An AP group the site already holds.

    A wireless network must name the group it is broadcast from. Read from the
    controller rather than invented: an invented name is one the controller
    refuses, and the refusal is the answer this suite is looking for.
    """
    groups = rows(engine.get("/apgroups"))
    assert groups, "the site holds no AP group, so no wireless network can be created"
    return dict(groups[0])


@pytest.fixture(scope="session")
def ap_group_id(ap_group: dict[str, Any]) -> str:
    return str(ap_group["_id"])


@pytest.fixture(scope="session")
def ap_group_name(ap_group: dict[str, Any]) -> str:
    return str(ap_group["name"])


@pytest.fixture(autouse=True)
def _remove_everything(controller: Any) -> Any:
    remove_by_prefix(controller, COLLECTION, prefix=OWNED)
    yield
    remove_by_prefix(controller, COLLECTION, prefix=OWNED)


@pytest.fixture(scope="module")
def network_id(controller: Any) -> Any:
    """The network every case here attaches its wireless network to.

    Created through the module that owns a network, because that is what a play
    would do and a network written by hand here would prove nothing about the
    collection. Scoped to this module so the object is gone before another suite's
    cleanup matches a name it does not own.
    """
    created = call(unifi_network, {**connection(), **wlan_network()})
    assert not created.get("failed"), created.get("msg")
    yield str(find_named(controller, NETWORK_COLLECTION, name=NETWORK_NAME)["_id"])
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=NETWORK_NAME)


def test_a_task_creates_the_wireless_network_and_a_second_run_does_not(
    network_id: str,
    ap_group_id: str,
) -> None:
    first = call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_security_options_reach_the_controller_under_their_own_field_names(
    network_id: str,
    ap_group_id: str,
) -> None:
    call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    result = call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    obj = result["obj"]

    # The task names passphrase, band and wpa_enc; the controller holds
    # x_passphrase, wlan_band and wpa_enc. A table that got the first two wrong
    # would still have created a wireless network, so the field names are asserted
    # rather than the object's existence.
    assert "x_passphrase" not in obj
    assert obj["wlan_band"] == "both"
    assert obj["wpa_enc"] == "ccmp"
    # A second run does not restate the passphrase, so the controller's stored copy
    # is what the diff would have carried without the redaction.
    assert "x_passphrase" not in result["diff"]["before"]
    assert "x_passphrase" not in result["diff"]["after"]


def test_the_wireless_network_rides_on_the_network_the_task_named(
    network_id: str, ap_group_id: str
) -> None:
    call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    obj = call(unifi_wlan, _wlan_task(network_id, ap_group_id))["obj"]

    # network_id is what a task can know: another task's result, or a lookup by
    # name. It is networkconf_id on the object.
    assert obj["networkconf_id"] == network_id


def test_check_mode_reports_the_change_without_creating(network_id: str, ap_group_id: str) -> None:
    reported = call(unifi_wlan, _wlan_task(network_id, ap_group_id, _ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME
    # In check mode obj is the document the run would write, so it matches the
    # diff rather than reporting the document the controller still holds.
    assert reported["obj"] == reported["diff"]["after"]

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    assert afterwards["changed"] is True, "check mode appears to have created the network"


def test_absent_removes_and_a_second_run_reports_no_change(
    network_id: str, ap_group_id: str
) -> None:
    call(unifi_wlan, _wlan_task(network_id, ap_group_id))
    removed = call(unifi_wlan, _wlan_task(network_id, ap_group_id, state="absent"))
    assert removed["changed"] is True
    # A removal has nothing left to describe, so it reports no obj.
    assert "obj" not in removed

    again = call(unifi_wlan, _wlan_task(network_id, ap_group_id, state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_a_security_mode_that_needs_a_passphrase_is_refused_without_one(
    network_id: str,
    ap_group_id: str,
) -> None:
    result = call(unifi_wlan, _wlan_task(network_id, ap_group_id, passphrase=None))

    assert result.get("failed") is True
    assert "passphrase" in str(result.get("msg", ""))


def test_an_empty_passphrase_is_refused(network_id: str, ap_group_id: str) -> None:
    result = call(unifi_wlan, _wlan_task(network_id, ap_group_id, passphrase=" "))

    assert result.get("failed") is True
    assert "passphrase" in str(result.get("msg", ""))


def test_a_credential_is_never_echoed_in_a_failure(network_id: str, ap_group_id: str) -> None:
    # The key is the credential the run authenticates with, so it is the one the
    # result may not carry. A password beside a key is refused by the spec before
    # the module runs.
    result = call(
        unifi_wlan,
        _wlan_task(
            network_id,
            ap_group_id,
            controller="127.0.0.1:1",
            api_key="a-secret-not-to-appear",
            passphrase="a-passphrase-not-to-appear",
        ),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert "a-passphrase-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True


def test_a_network_named_in_the_task_reaches_the_network_it_means(
    network_id: str, ap_group_name: str
) -> None:
    # The point of the name reference: a play that knows the network's name and
    # not its ObjectId still attaches to the right one, and the controller is the
    # thing that supplies the identifier.
    first = call(unifi_wlan, _by_name_task(NETWORK_NAME, ap_group_name))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_wlan, _by_name_task(NETWORK_NAME, ap_group_name))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")
    assert second["obj"]["networkconf_id"] == network_id


def test_an_ap_group_named_in_the_task_reaches_the_group_it_means(
    network_id: str, ap_group_id: str, ap_group_name: str
) -> None:
    call(unifi_wlan, _by_name_task(NETWORK_NAME, ap_group_name))
    obj = call(unifi_wlan, _by_name_task(NETWORK_NAME, ap_group_name))["obj"]

    assert obj["ap_group_ids"] == [ap_group_id]


def test_a_network_named_both_ways_is_refused(network_id: str, ap_group_id: str) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    with pytest.raises(ValueError, match="network"):
        call(unifi_wlan, _wlan_task(network_id, ap_group_id, network=NETWORK_NAME))


def test_an_ap_group_named_both_ways_is_refused(
    network_id: str, ap_group_id: str, ap_group_name: str
) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    with pytest.raises(ValueError, match="ap_groups"):
        call(
            unifi_wlan,
            _wlan_task(network_id, ap_group_id, ap_groups=[ap_group_name]),
        )


def test_a_network_name_the_controller_does_not_hold_is_refused(
    ap_group_id: str,
) -> None:
    # The reference is the name alone. The framework reads a key present with an
    # empty value as naming the option, so the empty identifier is dropped rather
    # than left beside the name.
    task = _wlan_task("", ap_group_id, network="verify-no-such-network")
    task.pop("network_id")
    result = call(unifi_wlan, task)

    assert result.get("failed") is True
    assert "verify-no-such-network" in str(result.get("msg", ""))
