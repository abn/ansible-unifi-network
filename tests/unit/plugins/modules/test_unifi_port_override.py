# SPDX-License-Identifier: GPL-3.0-or-later
"""The port override module's entry, its refusals and its removal, hermetic.

The override is one element of an array on a device, so what this suite pins is
the entry a task builds, the references it resolves, and the operations the
reconciler cannot express a merge for: refusing a contradiction before anything
is written, and dropping one port's entry.

The controller's own answers, which are the ones that matter most here, are
asked in the live suite.
"""

from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import yaml
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import (
    CONNECTION_ARGUMENTS,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.ports import (
    build_override_entry,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.ports import override_options
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import Outcome
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_override as under

MAC = "de:ad:be:ef:00:02"

DEVICE_INVENTORY = "/stat/device"
NETWORKS = "/rest/networkconf"
PROFILES = "/rest/portconf"

SITE = {
    "data": [
        {"_id": "net-default", "name": "Default"},
        {"_id": "net-iot", "name": "IoT"},
    ]
}

PORT_PROFILES = {"data": [{"_id": "prof-trunk", "name": "Trunk"}]}


class _Client:
    """A controller holding one device, answering the reference collections."""

    def __init__(
        self,
        port_overrides: list[dict[str, Any]] | None = None,
        *,
        present: bool = True,
    ) -> None:
        device: dict[str, Any] = {"_id": "d1", "mac": MAC, "name": "Switch"}
        if port_overrides is not None:
            device["port_overrides"] = [dict(entry) for entry in port_overrides]
        self.devices = [device] if present else []
        self.sets: list[dict[str, Any]] = []
        self.posts = 0
        self.reads: list[str] = []

    def get(self, resource: str) -> Any:
        self.reads.append(resource)
        if resource == DEVICE_INVENTORY:
            return {"data": [dict(device) for device in self.devices]}
        if resource == NETWORKS:
            return SITE
        if resource == PROFILES:
            return PORT_PROFILES
        raise AssertionError(f"unexpected read: {resource}")

    def set(self, resource: str, body: Any) -> None:
        self.sets.append(dict(body))
        self.devices = [dict(body)]

    def post(self, resource: str, body: Any) -> None:
        self.posts += 1
        raise AssertionError("a port override never creates a device")


class _Module:
    """A stand-in for ``AnsibleModule``, since ``run`` reads params and reports."""

    def __init__(self, params: dict[str, Any], *, check_mode: bool = False) -> None:
        self.params = params
        self.check_mode = check_mode
        self.result: dict[str, Any] | None = None

    def exit_json(self, **kwargs: Any) -> None:
        self.result = kwargs

    def fail_json(self, **kwargs: Any) -> None:
        self.result = {**kwargs, "failed": True}


def _run(monkeypatch: pytest.MonkeyPatch, client: _Client, **task: Any) -> dict[str, Any]:
    task = {"mac": MAC, "port_idx": 2, "state": "present", **task}
    module = _Module(task)
    monkeypatch.setattr(under, "build_client", lambda params: client)
    under.run(cast(Any, module))
    assert module.result is not None, "the module reported nothing"
    return module.result


def _stored(client: _Client) -> list[dict[str, Any]]:
    return list(client.devices[0].get("port_overrides") or [])


def test_a_task_adds_an_entry_and_a_second_run_reports_no_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    first = _run(monkeypatch, client, name="Uplink")
    assert first["changed"] is True, first

    second = _run(monkeypatch, client, name="Uplink")
    assert second["changed"] is False, second.get("changed_fields")

    assert _stored(client) == [{"port_idx": 2, "name": "Uplink"}]


def test_a_write_reads_the_inventory_once_before_and_once_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The device is refused from a read the reconciler then reuses as current, so
    # a write costs one read before and one re-read after rather than three.
    client = _Client()

    _run(monkeypatch, client, name="Uplink")

    assert client.reads.count(DEVICE_INVENTORY) == 2


def test_changing_one_port_leaves_another_entry_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The task owns one port, and the reconciler merges rather than replaces, so
    # the entry it did not name has to survive the write.
    client = _Client(
        [
            {"port_idx": 1, "name": "Uplink"},
            {"port_idx": 2, "name": "Desk"},
        ]
    )

    result = _run(monkeypatch, client, name="Lab")
    assert result["changed"] is True, result

    assert _stored(client) == [
        {"port_idx": 1, "name": "Uplink"},
        {"port_idx": 2, "name": "Lab"},
    ]


def test_check_mode_reports_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client([{"port_idx": 2, "name": "Desk"}])
    task = {"mac": MAC, "port_idx": 2, "state": "present", "name": "Lab"}
    module = _Module(task, check_mode=True)
    monkeypatch.setattr(under, "build_client", lambda params: client)

    under.run(cast(Any, module))

    assert module.result is not None
    assert module.result["changed"] is True
    assert client.sets == []


# Removal, which the merge cannot express.


def test_absent_drops_the_entry_and_a_second_absent_reports_no_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(
        [
            {"port_idx": 1, "name": "Uplink"},
            {"port_idx": 2, "name": "Desk"},
        ]
    )

    removed = _run(monkeypatch, client, state="absent")
    assert removed["changed"] is True, removed
    assert _stored(client) == [{"port_idx": 1, "name": "Uplink"}]

    again = _run(monkeypatch, client, state="absent")
    assert again["changed"] is False, again.get("changed_fields")


def test_absent_for_a_port_with_no_entry_is_not_a_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client([{"port_idx": 1, "name": "Uplink"}])

    result = _run(monkeypatch, client, state="absent")

    assert result["changed"] is False, result
    assert client.sets == []


def test_a_profile_and_a_field_together_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="poe_mode"):
        _run(monkeypatch, client, port_profile="Trunk", poe_mode="auto")

    assert client.sets == []


def test_the_refusal_names_the_profile_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="port_profile"):
        _run(monkeypatch, client, port_profile="Trunk", native_network="IoT")


def test_a_profile_named_both_ways_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="both"):
        _run(monkeypatch, client, port_profile="Trunk", port_profile_id="prof-trunk")


def test_native_network_named_both_ways_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="both"):
        _run(monkeypatch, client, native_network="IoT", native_network_id="net-iot")


def test_a_profile_name_resolves_to_its_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    _run(monkeypatch, client, port_profile="Trunk")

    assert _stored(client) == [{"port_idx": 2, "portconf_id": "prof-trunk"}]


def test_a_native_name_resolves_to_its_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    _run(monkeypatch, client, native_network="IoT")

    assert _stored(client) == [{"port_idx": 2, "native_networkconf_id": "net-iot"}]


def test_tagged_names_resolve_to_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    _run(monkeypatch, client, tagged_networks=["IoT"])

    assert _stored(client) == [{"port_idx": 2, "tagged_networkconf_ids": ["net-iot"]}]


def test_a_supplied_network_listing_is_used_without_a_read() -> None:
    # A caller that already holds the site's networks hands them in, so the entry
    # builder does not read the collection a second time.
    client = _Client()

    entry = build_override_entry(
        cast(Any, client),
        {"port_idx": 2, "tagged_networks": ["IoT"]},
        collection=under.NETWORKS,
        profiles=under.PROFILES,
        networks=SITE,
    )

    assert entry["tagged_networkconf_ids"] == ["net-iot"]
    assert under.NETWORKS not in client.reads


def test_a_network_name_the_site_does_not_hold_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="verify-no-such-network"):
        _run(monkeypatch, client, tagged_networks=["verify-no-such-network"])


# A device the controller does not hold is refused, not created.


def test_a_device_the_controller_does_not_hold_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(present=False)

    with pytest.raises(UniFiError, match="cannot create or adopt"):
        _run(monkeypatch, client, name="Uplink")

    assert client.posts == 0


def test_the_entry_carries_the_controllers_field_names() -> None:
    client = _Client()

    entry = build_override_entry(
        cast(Any, client),
        {
            "port_idx": 2,
            "name": "Uplink",
            "poe_mode": "auto",
            "speed": 1000,
        },
        collection=under.NETWORKS,
        profiles=under.PROFILES,
    )

    assert entry == {
        "port_idx": 2,
        "name": "Uplink",
        "poe_mode": "auto",
        "speed": 1000,
    }


def test_the_enumerated_choices_are_the_controllers_own() -> None:
    assert under.ARGUMENT_SPEC["poe_mode"]["choices"] == ["auto", "pasv24", "passthrough", "off"]
    assert under.ARGUMENT_SPEC["op_mode"]["choices"] == ["switch", "mirror", "aggregate"]


def test_forward_is_not_a_task_option() -> None:
    # The controller derives forward from membership and overwrites any value that
    # does not match, so exposing it would report a change on every run.
    assert "forward" not in under.ARGUMENT_SPEC
    assert "forward" not in override_options()


def test_the_module_hands_the_entry_to_the_reconciler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The merge is the kernel's rather than a second implementation here, so the
    # module has to call apply with the entry under the embedded key.
    client = _Client()
    calls: list[dict[str, Any]] = []

    def _capture(*args: Any, **kwargs: Any) -> Outcome:
        calls.append(kwargs)
        return Outcome(changed=False, before={}, after={}, obj={})

    monkeypatch.setattr(under, "apply", _capture)
    monkeypatch.setattr(under, "build_client", lambda params: client)
    module = _Module({"mac": MAC, "port_idx": 2, "state": "present", "name": "Uplink"})

    under.run(cast(Any, module))

    assert calls[0]["embed"] == {
        "port_overrides": ("port_idx", [{"port_idx": 2, "name": "Uplink"}])
    }


# Removal, which goes through the reconciler's drop rather than a list computed
# here, so a retry recomputes it from the fresh document.


def test_removal_hands_the_reconciler_a_drop_and_the_document_it_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client([{"port_idx": 1, "name": "Uplink"}, {"port_idx": 2, "name": "Desk"}])
    calls: list[dict[str, Any]] = []

    def _capture(*args: Any, **kwargs: Any) -> Outcome:
        calls.append(kwargs)
        return Outcome(changed=False, before={}, after={}, obj={})

    monkeypatch.setattr(under, "apply", _capture)
    monkeypatch.setattr(under, "build_client", lambda params: client)
    module = _Module({"mac": MAC, "port_idx": 2, "state": "absent"})

    under.run(cast(Any, module))

    assert calls[0]["drop"] == {"port_overrides": ("port_idx", [2])}
    assert calls[0]["current"] == client.devices[0]
    assert calls[0]["wanted"] == {}


# The two surfaces offer one field set, so a field dropped from either is a
# failure here rather than only in validate-modules.


def test_both_surfaces_offer_the_same_override_fields() -> None:
    single = set(under.ARGUMENT_SPEC) - set(CONNECTION_ARGUMENTS) - {"mac", "state"}
    listed = set(unifi_device.ARGUMENT_SPEC["port_overrides"]["options"])

    assert single == listed == set(override_options())


def test_the_documented_options_are_the_specified_ones() -> None:
    documented = yaml.safe_load(under.DOCUMENTATION)["options"]
    own = set(documented) - set(CONNECTION_ARGUMENTS)

    assert own == set(under.ARGUMENT_SPEC) - set(CONNECTION_ARGUMENTS)
