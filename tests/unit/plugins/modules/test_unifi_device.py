# SPDX-License-Identifier: GPL-3.0-or-later
"""The device module's port_overrides list, hermetic.

The list is merged by port index on the device document, so what this suite pins
is that a task naming one port leaves the others as the controller holds them,
that a port named twice or a profile beside a field is refused, and that the
field names an element uses are the same ones the single-port module offers.
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
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device as under

MAC = "de:ad:be:ef:00:02"

DEVICE_INVENTORY = "/stat/device"
NETWORKS = "/rest/networkconf"
PROFILES = "/rest/portconf"

SITE = {"data": [{"_id": "net-iot", "name": "IoT"}]}
PORT_PROFILES = {"data": [{"_id": "prof-trunk", "name": "Trunk"}]}


class _Client:
    """A controller holding one device, answering the reference collections."""

    def __init__(self, port_overrides: list[dict[str, Any]] | None = None) -> None:
        device: dict[str, Any] = {"_id": "d1", "mac": MAC, "name": "Switch"}
        if port_overrides is not None:
            device["port_overrides"] = [dict(entry) for entry in port_overrides]
        self.devices = [device]
        self.sets: list[dict[str, Any]] = []
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
        raise AssertionError("a device module never creates a device")


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


def _run(
    monkeypatch: pytest.MonkeyPatch,
    client: _Client,
    *,
    port_overrides: list[dict[str, Any]] | None = None,
    **task: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"mac": MAC, "port_overrides": port_overrides or [], **task}
    module = _Module(params)
    monkeypatch.setattr(under, "build_client", lambda params: client)
    under.run(cast(Any, module))
    assert module.result is not None, "the module reported nothing"
    return module.result


def _stored(client: _Client) -> list[dict[str, Any]]:
    return list(client.devices[0].get("port_overrides") or [])


def test_an_element_adds_a_port_and_a_second_run_reports_no_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    first = _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "name": "Uplink"}])
    assert first["changed"] is True, first

    second = _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "name": "Uplink"}])
    assert second["changed"] is False, second.get("changed_fields")

    assert _stored(client) == [{"port_idx": 2, "name": "Uplink"}]


def test_a_write_reads_the_inventory_once_before_and_once_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The device is refused from a read the reconciler then reuses as current, so
    # a write costs one read before and one re-read after rather than three.
    client = _Client()

    _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "name": "Uplink"}])

    assert client.reads.count(DEVICE_INVENTORY) == 2


def test_a_task_naming_one_port_leaves_the_others_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(
        [
            {"port_idx": 1, "name": "Uplink"},
            {"port_idx": 2, "name": "Desk"},
            {"port_idx": 3, "name": "Lab"},
        ]
    )

    result = _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "name": "Changed"}])
    assert result["changed"] is True, result

    assert _stored(client) == [
        {"port_idx": 1, "name": "Uplink"},
        {"port_idx": 2, "name": "Changed"},
        {"port_idx": 3, "name": "Lab"},
    ]


def test_an_empty_list_is_not_a_request_to_clear_the_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Removal is the single-port module's job, so an empty list has nothing to
    # merge and must not replace the list the controller holds.
    client = _Client([{"port_idx": 1, "name": "Uplink"}])

    result = _run(monkeypatch, client, port_overrides=[])

    assert result["changed"] is False, result
    assert _stored(client) == [{"port_idx": 1, "name": "Uplink"}]
    assert client.sets == []


def test_a_duplicate_port_idx_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="port_idx 2"):
        _run(
            monkeypatch,
            client,
            port_overrides=[
                {"port_idx": 2, "name": "One"},
                {"port_idx": 2, "name": "Two"},
            ],
        )

    assert client.sets == []


def test_a_profile_and_a_field_in_one_element_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="poe_mode"):
        _run(
            monkeypatch,
            client,
            port_overrides=[{"port_idx": 2, "port_profile": "Trunk", "poe_mode": "auto"}],
        )

    assert client.sets == []


def test_a_profile_name_resolves_to_its_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "port_profile": "Trunk"}])

    assert _stored(client) == [{"port_idx": 2, "portconf_id": "prof-trunk"}]


def test_a_tagged_name_resolves_to_its_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()

    _run(monkeypatch, client, port_overrides=[{"port_idx": 2, "tagged_networks": ["IoT"]}])

    assert _stored(client) == [{"port_idx": 2, "tagged_networkconf_ids": ["net-iot"]}]


def test_a_network_name_the_site_does_not_hold_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    with pytest.raises(UniFiError, match="verify-no-such-network"):
        _run(
            monkeypatch,
            client,
            port_overrides=[{"port_idx": 2, "tagged_networks": ["verify-no-such-network"]}],
        )


def test_the_option_is_named_enabled_and_the_controller_holds_disabled() -> None:
    # Every other module spells the flag enabled, and the controller's field is
    # that reading rather than a second vocabulary for the same question.
    assert "enabled" in under.ARGUMENT_SPEC
    assert "disabled" not in under.ARGUMENT_SPEC


def test_the_enabled_option_has_no_default() -> None:
    # A default turns "not mentioned" into "set", which would overwrite the
    # controller's own value on a task that never named the option.
    assert "default" not in under.ARGUMENT_SPEC["enabled"]
    assert under.ARGUMENT_SPEC["enabled"]["type"] == "bool"


def test_enabled_false_sets_the_controllers_disabled_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    result = _run(monkeypatch, client, enabled=False)

    assert result["changed"] is True, result
    assert client.devices[0]["disabled"] is True


def test_enabled_true_clears_the_controllers_disabled_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    client.devices[0]["disabled"] = True

    result = _run(monkeypatch, client, enabled=True)

    assert result["changed"] is True, result
    assert client.devices[0]["disabled"] is False


def test_a_task_that_omits_enabled_leaves_the_flag_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The controller's own value survives a run that never names the option, so
    # an omitted flag is not read as enabled=false.
    client = _Client()
    client.devices[0]["disabled"] = True

    result = _run(monkeypatch, client)

    assert result["changed"] is False, result.get("changed_fields")
    assert client.devices[0]["disabled"] is True


def test_the_documented_options_are_the_specified_ones() -> None:
    documented = yaml.safe_load(under.DOCUMENTATION)["options"]
    own = set(documented) - set(CONNECTION_ARGUMENTS)

    assert own == set(under.ARGUMENT_SPEC) - set(CONNECTION_ARGUMENTS)


def test_the_documented_suboptions_are_the_specified_ones() -> None:
    documented = yaml.safe_load(under.DOCUMENTATION)["options"]["port_overrides"]["suboptions"]

    assert set(documented) == set(under.ARGUMENT_SPEC["port_overrides"]["options"])


def test_the_list_offers_no_removal() -> None:
    # Removing one port's entry is the single-port module's job, and a state
    # suboption here would leave two surfaces claiming it.
    options = under.ARGUMENT_SPEC["port_overrides"]["options"]

    assert "state" not in options


def test_no_two_suboptions_map_to_the_same_field() -> None:
    # An element is projected through the override table, and two options writing
    # one field is a coin toss at apply time.
    from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import (
        PORT_OVERRIDE,
    )

    mapped = [
        PORT_OVERRIDE[name]
        for name in under.ARGUMENT_SPEC["port_overrides"]["options"]
        if name in PORT_OVERRIDE
    ]

    assert len(mapped) == len(set(mapped))
