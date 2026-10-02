# SPDX-License-Identifier: GPL-3.0-or-later
"""The static reservation module, without a controller.

The address handling, the document a task asks for, and the release. None of these
need the controller to be right, and each of them is a place where being wrong
produces a plausible result rather than an obvious one: an address normalised wrongly
creates a second record, a release that reported a change it did not make leaves a
play permanently changed, and a document missing the flag creates a client rather
than a reservation.

The controller's own answers, which are the ones that matter most here, are asked in
the live suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from ansible.module_utils.common.arg_spec import ArgumentSpecValidator
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.modules import unifi_dhcp_reservation as under

SPEC = Path(__file__).resolve().parents[3] / "fixtures" / "unifi-local-api.yaml"

PARAMS: dict[str, Any] = {"mac": "aa:bb:cc:dd:ee:01", "fixed_ip": "10.0.20.50", "name": "printer"}


class _Stub:
    """A client answering one collection, applying a write to the record it names.

    The write is applied rather than recorded only, because the reconciler reads the
    collection back after writing and a stub that answered with what it held before
    the write would report every release as one the controller ignored.
    """

    def __init__(self, body: Any) -> None:
        self._body = body
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def get(self, resource: str) -> Any:
        return self._body

    def set(self, resource: str, payload: dict[str, Any]) -> Any:
        self.writes.append((resource, dict(payload)))
        identifier = resource.rpartition("/")[2]
        for record in (self._body or {}).get("data", []):
            if str(record.get("_id")) == identifier:
                record.update(payload)
        return {"data": []}


def _network_client() -> _Stub:
    return _Stub({"data": [{"_id": "6a3c2d8f", "name": "Office"}]})


def test_a_hardware_address_is_stored_as_the_controller_stores_it() -> None:
    # The controller records a hardware address in lower case and the reconciler
    # matches a record on it exactly, so an upper-case address reaching it unchanged
    # would post a second record rather than find the one the task means.
    assert under._mac("AA:BB:CC:DD:EE:01") == "aa:bb:cc:dd:ee:01"


def test_surrounding_whitespace_is_trimmed_before_the_address_is_matched() -> None:
    assert under._mac("  aa:bb:cc:dd:ee:01\n") == "aa:bb:cc:dd:ee:01"


@pytest.mark.parametrize(
    "value",
    [
        "not-a-mac",
        "aa:bb:cc:dd:ee",
        "aa:bb:cc:dd:ee:01:02",
        "aa-bb-cc-dd-ee-01",
        "zz:bb:cc:dd:ee:01",
        "",
    ],
)
def test_something_that_is_not_a_hardware_address_is_refused(value: str) -> None:
    # A malformed address would create a record nothing can select rather than a
    # reservation, and the refusal names the address the task wrote.
    with pytest.raises(UniFiError, match="not a hardware address"):
        under._mac(value)


def test_a_reservation_carries_the_flag_the_address_alone_does_not() -> None:
    # fixed_ip without use_fixedip is a client the controller has seen, which is
    # not what this module creates, so the flag is set rather than left to a task
    # to name.
    wanted = under._wanted(
        _network_client(), dict(PARAMS, network="Office"), "aa:bb:cc:dd:ee:01", None
    )

    assert wanted["use_fixedip"] is True
    assert wanted["fixed_ip"] == "10.0.20.50"
    assert wanted["mac"] == "aa:bb:cc:dd:ee:01"


def test_a_network_named_in_the_task_is_resolved_to_the_controller_identifier() -> None:
    wanted = under._wanted(
        _network_client(), dict(PARAMS, network="Office"), "aa:bb:cc:dd:ee:01", None
    )

    assert wanted["network_id"] == "6a3c2d8f"
    # The name is the task's own spelling of the reference and is not a field the
    # controller holds, so sending it would be a field the controller does not know.
    assert "network" not in wanted


def test_a_network_named_by_identifier_is_not_looked_up() -> None:
    # A controller that cannot be reached must not be consulted for a reference the
    # task already spelled out.
    wanted = under._wanted(
        _Stub(None), dict(PARAMS, network_id="6a3c2d8f"), "aa:bb:cc:dd:ee:01", None
    )

    assert wanted["network_id"] == "6a3c2d8f"


def test_a_reservation_with_no_address_is_refused() -> None:
    params = {name: value for name, value in PARAMS.items() if name != "fixed_ip"}

    with pytest.raises(UniFiError, match="fixed_ip"):
        under._require_address(params, "aa:bb:cc:dd:ee:01", None)


def test_an_existing_record_can_be_relabelled_without_an_address() -> None:
    # The controller keeps fixed_ip, use_fixedip and network_id on a write that
    # names none of them, so a task changing only the label does not restate the
    # reservation it is not changing.
    current = {
        "_id": "abc",
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "before",
        "fixed_ip": "10.0.20.50",
        "use_fixedip": True,
        "network_id": "6a3c2d8f",
    }
    params = {"mac": "aa:bb:cc:dd:ee:01", "name": "after"}

    under._require_address(params, "aa:bb:cc:dd:ee:01", current)
    wanted = under._wanted(_Stub(None), params, "aa:bb:cc:dd:ee:01", current)

    assert wanted["name"] == "after"
    # A rename-only run asserts nothing about the reservation, so it does not send
    # the flag or the address it is not changing.
    assert "use_fixedip" not in wanted
    assert "fixed_ip" not in wanted
    assert wanted["network_id"] == "6a3c2d8f"


def test_omitting_the_network_keeps_the_one_the_record_already_holds() -> None:
    current = {"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "network_id": "6a3c2d8f"}
    params = {"mac": "aa:bb:cc:dd:ee:01", "fixed_ip": "10.0.20.50"}

    wanted = under._wanted(_Stub(None), params, "aa:bb:cc:dd:ee:01", current)

    assert wanted["network_id"] == "6a3c2d8f"


def test_reserving_an_address_with_no_network_anywhere_is_refused() -> None:
    # A write that needs a network the record does not carry and the task did not
    # name cannot be aimed, so it is refused with both options named rather than
    # with the kernel's reference error for an empty name.
    params = {"mac": "aa:bb:cc:dd:ee:01", "fixed_ip": "10.0.20.50"}

    with pytest.raises(UniFiError, match="network"):
        under._wanted(_Stub(None), params, "aa:bb:cc:dd:ee:01", None)


def test_a_local_dns_record_derives_the_flag_the_controller_requires() -> None:
    params = dict(PARAMS, network="Office", local_dns_record="printer.example.invalid")

    wanted = under._wanted(_network_client(), params, "aa:bb:cc:dd:ee:01", None)

    assert wanted["local_dns_record"] == "printer.example.invalid"
    assert wanted["local_dns_record_enabled"] is True


def test_a_local_dns_record_with_no_address_is_refused() -> None:
    # The controller answers api.err.LocalDnsRecordRequiresFixedIp, and the refusal
    # is stated here in terms of the option rather than forwarded from the
    # controller.
    params = {"mac": "aa:bb:cc:dd:ee:01", "local_dns_record": "printer.example.invalid"}

    with pytest.raises(UniFiError, match="fixed_ip"):
        under._require_dns_address(params, "aa:bb:cc:dd:ee:01", None)


def test_a_local_dns_record_is_allowed_on_a_record_that_already_reserves_an_address() -> None:
    # The address may come from the record: a task adding a name to a reservation
    # that already holds one need not restate the address to add the name to it.
    params = {"mac": "aa:bb:cc:dd:ee:01", "local_dns_record": "printer.example.invalid"}
    current = {"mac": "aa:bb:cc:dd:ee:01", "use_fixedip": True, "fixed_ip": "10.0.20.50"}

    under._require_dns_address(params, "aa:bb:cc:dd:ee:01", current)


def test_a_local_dns_record_is_refused_on_a_record_that_reserves_nothing() -> None:
    # An address the controller will not serve is no address for the name to
    # resolve against, so a released record does not satisfy the requirement.
    params = {"mac": "aa:bb:cc:dd:ee:01", "local_dns_record": "printer.example.invalid"}
    current = {"mac": "aa:bb:cc:dd:ee:01", "use_fixedip": False, "fixed_ip": "10.0.20.50"}

    with pytest.raises(UniFiError, match="fixed_ip"):
        under._require_dns_address(params, "aa:bb:cc:dd:ee:01", current)


def test_the_address_aliases_resolve_to_the_option_the_module_reads() -> None:
    validated = ArgumentSpecValidator(under.ARGUMENT_SPEC).validate(
        {"mac": "aa:bb:cc:dd:ee:01", "ip": "10.0.20.50"}
    )

    assert validated.validated_parameters["fixed_ip"] == "10.0.20.50"


def test_the_address_aliases_are_the_ones_the_request_asked_for() -> None:
    assert under.ARGUMENT_SPEC["fixed_ip"]["aliases"] == ["ip", "address"]


def test_every_field_the_module_writes_is_declared_by_the_controller() -> None:
    # A name the controller does not declare is a rejected request on an operator's
    # network, with nothing earlier saying so. The table covers the options a task
    # names, and the rest are the fields the module derives.
    schema = yaml.safe_load(SPEC.read_text())["components"]["schemas"]["Client"]
    declared = set(schema["properties"])
    derived = {under.SELECTOR, under.USE_FIXED_IP, under.LOCAL_DNS_ENABLED, "network_id"}

    for field in set(under.CLIENT.values()) | derived:
        assert field in declared, f"{field!r} is not declared by the Client schema"


def test_the_flags_are_ones_the_controller_declares_as_required() -> None:
    # The controller marks three fields required on a client, and both flags are
    # among them. A module that omitted one would be relying on a default nobody
    # measured.
    schema = yaml.safe_load(SPEC.read_text())["components"]["schemas"]["Client"]

    assert under.USE_FIXED_IP in schema["required"]
    assert under.LOCAL_DNS_ENABLED in schema["required"]


def _client_registry(*records: dict[str, Any]) -> _Stub:
    return _Stub({"data": list(records)})


def test_a_release_clears_the_flag_and_leaves_the_record() -> None:
    client = _client_registry({"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": True})

    result = under._release(client, "aa:bb:cc:dd:ee:01", check_mode=False)

    assert result["changed"] is True
    assert result["changed_fields"] == ["use_fixedip"]
    # The write names the per-object path, because a write to the collection with
    # no identifier is answered with api.err.IdRequired.
    resource, payload = client.writes[0]
    assert resource == "/rest/user/abc"
    assert payload["use_fixedip"] is False


def test_a_release_clears_a_local_dns_name_with_the_flag() -> None:
    # A local DNS name cannot outlive the reserved address: the controller refuses
    # the release itself while the name is set, so the write has to clear the flag
    # beside it or the record is left holding a reservation nothing can release.
    client = _client_registry(
        {
            "_id": "abc",
            "mac": "aa:bb:cc:dd:ee:01",
            "use_fixedip": True,
            "local_dns_record": "printer.example.invalid",
            "local_dns_record_enabled": True,
        }
    )

    result = under._release(client, "aa:bb:cc:dd:ee:01", check_mode=False)

    assert result["changed"] is True
    assert result["changed_fields"] == ["use_fixedip", "local_dns_record_enabled"]
    _resource, payload = client.writes[0]
    assert payload["use_fixedip"] is False
    assert payload["local_dns_record_enabled"] is False


def test_a_release_reaches_the_record_behind_an_address_written_in_upper_case() -> None:
    # A task writing the address in upper case is one of the ordinary ways a play
    # asks, and the reduction that makes it find the record is the one the module
    # applies to the task's spelling before anything is selected on it.
    client = _client_registry({"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": True})

    result = under._release(client, under._mac("AA:BB:CC:DD:EE:01"), check_mode=False)

    assert result["changed"] is True
    assert client.writes


def test_an_already_released_record_is_not_written_again() -> None:
    # A play running this every night has to be quiet, and a write that changes
    # nothing is the failure this avoids.
    client = _client_registry({"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": False})

    result = under._release(client, "aa:bb:cc:dd:ee:01", check_mode=False)

    assert result["changed"] is False
    assert not client.writes


def test_a_record_carrying_no_flag_at_all_counts_as_released() -> None:
    # The controller answers null for a record that never reserved anything, and
    # null is not false: it says the task has never reserved here, which is the
    # state a release leaves behind.
    client = _client_registry({"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": None})

    result = under._release(client, "aa:bb:cc:dd:ee:01", check_mode=False)

    assert result["changed"] is False
    assert not client.writes


def test_a_release_in_check_mode_writes_nothing() -> None:
    client = _client_registry({"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": True})

    result = under._release(client, "aa:bb:cc:dd:ee:01", check_mode=True)

    assert result["changed"] is True
    assert result["diff"]["after"]["use_fixedip"] is False
    assert not client.writes


def test_a_release_of_a_record_that_is_not_there_reports_no_change() -> None:
    result = under._release(_client_registry(), "aa:bb:cc:dd:ee:01", check_mode=False)

    assert result["changed"] is False
    assert result["obj"] == {}


def test_a_release_that_the_controller_did_not_apply_is_an_error() -> None:
    # The reconciler exists so that what is reported is what the controller holds.
    # A write the controller accepted and ignored is a reservation the play
    # believes it gave back and the client still holds.
    class _Ignoring(_Stub):
        def get(self, resource: str) -> Any:
            return {"data": [{"_id": "abc", "mac": "aa:bb:cc:dd:ee:01", "use_fixedip": True}]}

    with pytest.raises(UniFiError, match="still holds"):
        under._release(_Ignoring(None), "aa:bb:cc:dd:ee:01", check_mode=False)


def test_the_argument_spec_offers_no_option_the_table_does_not_send() -> None:
    # Options the collection cannot send are options a task may name and see
    # nothing happen, which is the failure a second run reporting no change
    # disguises.
    connection = {
        "controller",
        "api_mount",
        "api_family",
        "site",
        "login_path",
        "api_key",
        "username",
        "password",
        "ca_path",
        "validate_certs",
        "timeout",
    }
    derived = {"mac", "network", "network_id", "state"}

    for name in under.ARGUMENT_SPEC:
        assert name in connection or name in under.CLIENT or name in derived, name
