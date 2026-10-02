# SPDX-License-Identifier: GPL-3.0-or-later
"""The static reservation module, against the throwaway controller.

The questions here are ones a mock cannot answer: whether a record can be created
for a hardware address that has never connected, which fields the controller keeps
the fixed address and its flag in, whether a second run is quiet, and what a
release leaves behind. The module runs through a stand-in for ``AnsibleModule``, so
the argument spec, the check mode handling and the reporting are under test rather
than assumed.

The network the reservations live on is created through the module that owns a
network, which is also what a play would do, and it is removed again on the way
out.

It writes, and it releases what it creates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.modules import unifi_dhcp_reservation
from ansible_collections.abn.unifi_network.plugins.modules import unifi_network
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection
from tests.live.settings import dhcp_network

COLLECTION = "/rest/user"
NETWORK_COLLECTION = "/rest/networkconf"

#: The prefix every hardware address below carries, so a record left by a run that
#: failed part-way is recognised and released rather than accumulating.
OWNED = "aa:bb:cc:dd:16:"

#: The network the reservations below are held on. Matched by name rather than by
#: an identifier recorded at creation, so a leftover is found and removed.
NETWORK_NAME = "verify-dhcp-network"

#: A hardware address no adopted device on the throwaway stack carries, so every
#: record below is one the controller has never seen. Locally administered and
#: unicast, in the range this suite owns.
MAC = {
    "created": "aa:bb:cc:dd:16:01",
    "relabelled": "aa:bb:cc:dd:16:02",
    "moved": "aa:bb:cc:dd:16:03",
    "upper": "aa:bb:cc:dd:16:04",
    "released": "aa:bb:cc:dd:16:05",
    "check_mode": "aa:bb:cc:dd:16:06",
    "first_claimant": "aa:bb:cc:dd:16:07",
    "second_claimant": "aa:bb:cc:dd:16:08",
    "refused": "aa:bb:cc:dd:16:09",
    "unknown": "aa:bb:cc:dd:16:0a",
    "rename_only": "aa:bb:cc:dd:16:0b",
    "keep_network": "aa:bb:cc:dd:16:0c",
    "dns": "aa:bb:cc:dd:16:0d",
    "no_network": "aa:bb:cc:dd:16:0e",
    "no_address": "aa:bb:cc:dd:16:0f",
}

#: The address each case reserves, within the network's own range. Distinct per
#: case, because a second record claiming an address already reserved is refused
#: and would make one case depend on the case that ran before it.
ADDRESS = {
    "created": "10.30.161.11",
    "relabelled": "10.30.161.12",
    "moved": "10.30.161.13",
    "upper": "10.30.161.14",
    "released": "10.30.161.15",
    "check_mode": "10.30.161.16",
    "first_claimant": "10.30.161.17",
    "second_claimant": "10.30.161.17",
    # Never reserved by a passing case, so a run that leaves a record behind does
    # not make the next one believe the address is already held.
    "refused": "10.30.161.18",
    "unknown": "10.30.161.19",
    "rename_only": "10.30.161.21",
    "keep_network": "10.30.161.22",
    "dns": "10.30.161.23",
    "no_network": "10.30.161.24",
    "no_address": "10.30.161.25",
}


def _task(case: str, **overrides: Any) -> dict[str, Any]:
    task = connection(
        mac=MAC[case],
        network=NETWORK_NAME,
        fixed_ip=ADDRESS[case],
    )
    task.update(overrides)
    return task


def _reserved(controller: Any, mac: str) -> dict[str, Any] | None:
    """The record holding a reservation for this address, or ``None``.

    What the module manages is the reservation, not the record. A record cannot be
    removed on this controller version, so a record carrying no reservation is
    indistinguishable from one that was never created, and both mean the same
    thing to a task: no address is held.
    """
    record = _held(controller, mac)
    return record if record and record.get("use_fixedip") else None


def _held(controller: Any, mac: str) -> dict[str, Any] | None:
    """The record the controller holds for this hardware address, or ``None``.

    Matched without regard to case, because the addresses are spelled in upper case
    in one of the cases below and the controller answers in lower.
    """
    for row in controller.get(COLLECTION)["data"]:
        if str(row.get("mac", "")).lower() == mac.lower():
            return dict(row)
    return None


@pytest.fixture(scope="module")
def network_id(controller: Any) -> Any:
    """The network every case here reserves an address on.

    Created through the module that owns a network, because that is what a play
    would do and a network written by hand here would prove nothing about the
    collection. Scoped to this module so the object is gone before another suite's
    cleanup matches a name it does not own.
    """
    created = call(unifi_network, {**connection(), **dhcp_network()})
    assert not created.get("failed"), created.get("msg")
    yield str(find_named(controller, NETWORK_COLLECTION, name=NETWORK_NAME)["_id"])
    remove_by_prefix(controller, NETWORK_COLLECTION, prefix=NETWORK_NAME)


@pytest.fixture(autouse=True)
def _release_everything(controller: Any) -> Any:
    _release(controller)
    yield
    _release(controller)


def _release(controller: Any) -> None:
    """Clear the reservation flag on every record this suite owns.

    The record is left, and there is no removal to perform: on this controller
    version ``DELETE rest/user/{id}`` answers ``api.err.NotFound`` for a record
    that is there. What the suite can clean is the reservation, and a record
    carrying no flag is one the next run re-reserves rather than a second record
    beside it.
    """
    for row in controller.get(COLLECTION)["data"]:
        if str(row.get("mac", "")).startswith(OWNED):
            # The DNS flag goes false with the reservation: the controller refuses a
            # release while a local DNS name is still set.
            controller.set(
                f"{COLLECTION}/{row['_id']}",
                {**row, "use_fixedip": False, "local_dns_record_enabled": False},
            )


def test_a_task_reserves_an_address_for_a_hardware_address_the_controller_never_saw(
    network_id: str,
) -> None:
    # The point of the module. Nothing is adopted, connected or named beforehand,
    # and the record the controller answers with is one it holds rather than one the
    # task sent.
    first = call(unifi_dhcp_reservation, _task("created", name="verify-dhcp-created"))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_dhcp_reservation, _task("created", name="verify-dhcp-created"))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_reservation_reaches_the_controller_under_its_own_field_names(network_id: str) -> None:
    call(unifi_dhcp_reservation, _task("created", name="verify-dhcp-created"))
    obj = call(unifi_dhcp_reservation, _task("created", name="verify-dhcp-created"))["obj"]

    # The task names fixed_ip, and the controller holds the address there with the
    # flag beside it. A table that sent either under another name would still have
    # created a record, so the fields are asserted rather than the record's
    # existence.
    assert obj["mac"] == MAC["created"]
    assert obj["fixed_ip"] == ADDRESS["created"]
    assert obj["use_fixedip"] is True


def test_the_reservation_rides_on_the_network_the_task_named(network_id: str) -> None:
    call(unifi_dhcp_reservation, _task("created"))
    obj = call(unifi_dhcp_reservation, _task("created"))["obj"]

    # A task names a network; the object carries network_id, which is what the
    # controller checks the address against.
    assert obj["network_id"] == network_id


def test_a_network_named_by_identifier_reaches_the_same_record(network_id: str) -> None:
    by_name = call(unifi_dhcp_reservation, _task("relabelled", name="verify-dhcp-relabelled"))
    assert not by_name.get("failed"), by_name.get("msg")
    assert by_name["obj"]["network_id"] == network_id

    # The reference is the identifier alone: the framework reads a key present
    # with a null value as naming the option, so the name is dropped rather than
    # set to None.
    by_identifier = _task("relabelled", network_id=network_id)
    by_identifier.pop("network")
    by_id = call(unifi_dhcp_reservation, by_identifier)
    assert not by_id.get("failed"), by_id.get("msg")
    assert by_id["obj"]["network_id"] == network_id


def test_a_network_named_both_ways_is_refused(network_id: str) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    with pytest.raises(ValueError, match="network"):
        call(unifi_dhcp_reservation, _task("relabelled", network_id=network_id))


def test_a_hardware_address_written_in_upper_case_finds_the_record_it_means(
    network_id: str,
) -> None:
    first = call(unifi_dhcp_reservation, _task("upper", name="verify-dhcp-upper"))
    assert not first.get("failed"), first.get("msg")

    # The controller stores a hardware address in lower case, so an upper-case one
    # in a task has to reach it lower-cased or the second run would post a second
    # record and report the change again.
    second = call(
        unifi_dhcp_reservation, _task("upper", mac=MAC["upper"].upper(), name="verify-dhcp-upper")
    )
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_a_task_that_moves_the_address_changes_only_that_field(network_id: str) -> None:
    call(unifi_dhcp_reservation, _task("moved", name="verify-dhcp-moved"))
    moved = call(
        unifi_dhcp_reservation, _task("moved", fixed_ip="10.30.161.19", name="verify-dhcp-moved")
    )

    assert moved["changed"] is True
    assert moved["changed_fields"] == ["fixed_ip"]
    assert moved["obj"]["fixed_ip"] == "10.30.161.19"


def test_a_relabelled_reservation_leaves_the_address_alone(network_id: str) -> None:
    call(unifi_dhcp_reservation, _task("relabelled", name="verify-dhcp-before"))
    relabelled = call(unifi_dhcp_reservation, _task("relabelled", name="verify-dhcp-after"))

    assert relabelled["changed"] is True
    assert relabelled["changed_fields"] == ["name"]
    assert relabelled["obj"]["fixed_ip"] == ADDRESS["relabelled"]


def test_a_client_is_relabelled_without_restating_the_reservation(network_id: str) -> None:
    # The controller keeps fixed_ip, use_fixedip and network_id on a write that
    # names none of them, so a task changing only the label sends only the label.
    # The record is asserted rather than the change, because a module that sent the
    # address again would also report a change and would have hidden the fact.
    call(unifi_dhcp_reservation, _task("rename_only", name="verify-dhcp-before"))
    renamed = call(
        unifi_dhcp_reservation, connection(mac=MAC["rename_only"], name="verify-dhcp-after")
    )

    assert not renamed.get("failed"), renamed.get("msg")
    assert renamed["changed"] is True
    assert renamed["changed_fields"] == ["name"]
    assert renamed["obj"]["fixed_ip"] == ADDRESS["rename_only"]
    assert renamed["obj"]["use_fixedip"] is True
    assert renamed["obj"]["network_id"] == network_id


def test_omitting_the_network_keeps_the_one_the_record_already_holds(network_id: str) -> None:
    # A task that names an address but no network on a record that already carries
    # one keeps it, so a play does not have to restate the network it is not
    # changing.
    call(unifi_dhcp_reservation, _task("keep_network", name="verify-dhcp-keep"))
    relabelled = call(
        unifi_dhcp_reservation,
        _task("keep_network", name="verify-dhcp-kept", network=None),
    )

    assert not relabelled.get("failed"), relabelled.get("msg")
    assert relabelled["obj"]["network_id"] == network_id


def test_reserving_an_address_with_no_network_is_refused(controller: Any) -> None:
    # The kernel's reference error for an empty name is not a description a task
    # can act on, so a write that needs a network the record does not carry names
    # both options instead.
    result = call(
        unifi_dhcp_reservation,
        connection(mac=MAC["no_network"], fixed_ip=ADDRESS["no_network"]),
    )

    assert result.get("failed") is True
    assert "network" in str(result.get("msg", ""))
    assert not _reserved(controller, MAC["no_network"])


def test_a_local_dns_record_is_set_beside_the_flag_that_enables_it(network_id: str) -> None:
    named = "verify-dhcp-dns.example.invalid"
    first = call(
        unifi_dhcp_reservation,
        _task("dns", name="verify-dhcp-dns", local_dns_record=named),
    )

    assert not first.get("failed"), first.get("msg")
    assert first["obj"]["local_dns_record"] == named
    assert first["obj"]["local_dns_record_enabled"] is True

    second = call(
        unifi_dhcp_reservation,
        _task("dns", name="verify-dhcp-dns", local_dns_record=named),
    )
    assert second["changed"] is False, second.get("changed_fields")


def test_a_local_dns_record_without_an_address_is_refused(network_id: str) -> None:
    # The controller answers api.err.LocalDnsRecordRequiresFixedIp, and the refusal
    # names the option here rather than the controller's error for a document the
    # module could have described. The record does not exist and no address is
    # named, so there is nothing for the name to resolve against.
    result = call(
        unifi_dhcp_reservation,
        connection(mac=MAC["no_address"], local_dns_record="verify-dhcp-dns.example.invalid"),
    )

    assert result.get("failed") is True
    assert "fixed_ip" in str(result.get("msg", ""))


def test_a_local_dns_record_is_added_to_a_reservation_without_restating_the_address(
    network_id: str,
) -> None:
    # The name resolves against the address the reservation already holds, so a
    # task that adds the name need not restate fixed_ip or the network.
    reserved = call(unifi_dhcp_reservation, _task("dns", name="verify-dhcp-dns"))
    assert not reserved.get("failed"), reserved.get("msg")

    named = call(
        unifi_dhcp_reservation,
        connection(mac=MAC["dns"], local_dns_record="verify-dhcp-dns.example.invalid"),
    )

    assert not named.get("failed"), named.get("msg")
    assert named["obj"]["local_dns_record_enabled"] is True
    assert named["obj"]["fixed_ip"] == ADDRESS["dns"]


def test_check_mode_reports_the_change_without_reserving(network_id: str) -> None:
    reported = call(unifi_dhcp_reservation, _task("check_mode", _ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["fixed_ip"] == ADDRESS["check_mode"]

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_dhcp_reservation, _task("check_mode"))
    assert afterwards["changed"] is True, "check mode appears to have reserved the address"


def test_absent_releases_the_reservation_and_leaves_the_record(controller: Any) -> None:
    call(unifi_dhcp_reservation, _task("released", name="verify-dhcp-released"))
    released = call(unifi_dhcp_reservation, _task("released", state="absent"))

    assert released["changed"] is True
    assert released["changed_fields"] == ["use_fixedip"]

    # The record stays. A client is the controller's registry of devices, and
    # forgetting one is not what a released reservation asks for.
    still_held = _held(controller, MAC["released"])
    assert still_held is not None
    assert still_held["use_fixedip"] is False


def test_absent_on_an_already_released_reservation_reports_no_change(network_id: str) -> None:
    call(unifi_dhcp_reservation, _task("released", state="absent"))
    again = call(unifi_dhcp_reservation, _task("released", state="absent"))

    assert again["changed"] is False, "releasing twice reported a change"


def test_absent_for_a_hardware_address_the_controller_never_saw_reports_no_change(
    controller: Any, network_id: str
) -> None:
    # The address has no record, so there is no reservation and nothing to do. The
    # assertion is on the reservation rather than on the record's absence, because
    # a record a previous run created cannot be removed on this controller version
    # and a case asserting its absence would only pass on a site that had never
    # been run against.
    result = call(unifi_dhcp_reservation, _task("unknown", state="absent"))

    # A successful result carries no `failed` key at all, so this is a falsiness
    # check and not an identity one.
    assert not result.get("failed"), result.get("msg")
    assert result["changed"] is False
    assert not _reserved(controller, MAC["unknown"])


def test_an_address_outside_the_network_is_refused_by_the_controller(
    controller: Any, network_id: str
) -> None:
    # No arithmetic on the range is done here, so this refusal is the controller's
    # and arrives in its own words.
    task = _task("refused", fixed_ip="192.168.77.50", network_id=network_id)
    task.pop("network")
    result = call(unifi_dhcp_reservation, task)

    assert result.get("failed") is True
    assert not _reserved(controller, MAC["refused"])


def test_a_second_record_claiming_a_reserved_address_is_refused(network_id: str) -> None:
    first = call(unifi_dhcp_reservation, _task("first_claimant"))
    assert not first.get("failed"), first.get("msg")

    second = call(unifi_dhcp_reservation, _task("second_claimant"))
    assert second.get("failed") is True


def test_a_reservation_with_no_address_is_refused(network_id: str) -> None:
    # The refusal is about creating: a record the controller does not hold and
    # that names no address is a client, not a reservation. A record it already
    # holds can be relabelled without restating its address, which the relabel
    # case covers. This address has never been seen.
    result = call(unifi_dhcp_reservation, _task("no_address", fixed_ip=None))

    assert result.get("failed") is True
    assert "fixed_ip" in str(result.get("msg", ""))


def test_a_hardware_address_that_is_not_one_is_refused(network_id: str) -> None:
    task = _task("created", mac="not-a-mac", network_id=network_id)
    task.pop("network")
    result = call(unifi_dhcp_reservation, task)

    assert result.get("failed") is True
    assert "mac" in str(result.get("msg", "")).lower()


def test_a_credential_is_never_echoed_in_a_failure() -> None:
    # The key is the credential the run authenticates with, so it is the one the
    # result may not carry. A password beside a key is refused by the spec before
    # the module runs.
    result = call(
        unifi_dhcp_reservation,
        _task(
            "created",
            controller="127.0.0.1:1",
            api_key="a-secret-not-to-appear",
        ),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True
