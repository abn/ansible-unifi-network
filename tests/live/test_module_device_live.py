# SPDX-License-Identifier: GPL-3.0-or-later
"""The device module, against a controller that has adopted nothing.

Adoption needs hardware on the network, so the throwaway stack holds no device
and nothing in this file can prove that a write reaches one. What it can answer
is the other side of that boundary, and it is the side that matters most: the
module refuses a device the controller does not hold instead of inventing one,
the refusal names the option that missed and says why, the inventory path the
module reads is served, and a credential survives neither refusal.

The module is invoked through a stand-in for ``AnsibleModule`` with a synthesised
argument payload, so the argument spec, the check mode handling and the reporting
are all exercised, and the run stays in one process. The integration target is
where a real playbook is driven.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import DEVICE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import (
    CONNECTION_ARGUMENTS,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_device
from tests.live.cleanup import find_named
from tests.live.harness import call
from tests.live.settings import EMULATED_MAC
from tests.live.settings import EMULATED_NAME
from tests.live.settings import UNADOPTED_MAC
from tests.live.settings import connection

#: A password no credential on the stack uses, so finding it in a result would
#: mean the module had put a secret where a task output would print it.
SECRET = "a-secret-not-to-appear"

#: The shared options whose values the rule about option names puts behind
#: ``no_log``. Stated here rather than read from the table, so the assertion says
#: which credentials the collection holds rather than agreeing with whatever the
#: table currently says.
_CREDENTIAL_OPTIONS = {"api_key", "password"}


def _device_task(**overrides: Any) -> dict[str, Any]:
    task = connection(mac=UNADOPTED_MAC, led="off")
    task.update(overrides)
    return task


def _documented() -> dict[str, Any]:
    """The options the module's own DOCUMENTATION block declares."""
    return yaml.safe_load(unifi_device.DOCUMENTATION)["options"]


def _held_macs(controller: UniFiClient) -> list[str]:
    return [str(row.get("mac", "")) for row in rows(controller.get(unifi_device.INVENTORY))]


def test_the_address_under_test_is_not_one_the_controller_holds(controller: UniFiClient) -> None:
    # The rest of this file asks for a device that is not there. If the stack ever
    # held this address the suite would be asserting against a device it created.
    assert UNADOPTED_MAC not in _held_macs(controller)


def test_the_inventory_path_is_served(controller: UniFiClient) -> None:
    # The module reads the site at this path rather than the one it writes to, and
    # only the controller can say whether it answers there.
    body = controller.get(unifi_device.INVENTORY)

    assert "meta" in body, body
    assert isinstance(body.get("data"), list), body


def test_a_device_the_controller_does_not_hold_is_refused() -> None:
    result = call(unifi_device, _device_task())

    assert result.get("failed") is True


def test_the_refusal_names_the_option_that_missed() -> None:
    message = str(call(unifi_device, _device_task()).get("msg", ""))

    assert "mac" in message, message


def test_the_refusal_names_the_address_it_looked_for() -> None:
    message = str(call(unifi_device, _device_task()).get("msg", ""))

    assert UNADOPTED_MAC in message, message


def test_the_refusal_says_the_module_cannot_create_or_adopt() -> None:
    # A device is adopted hardware. A refusal that only said "not found" would read
    # as a selector to correct rather than as a limit of what this API offers.
    message = str(call(unifi_device, _device_task()).get("msg", "")).lower()

    assert "cannot create or adopt" in message, message


def test_a_refused_task_reports_no_change() -> None:
    result = call(unifi_device, _device_task())

    assert result.get("changed") is not True, result


def test_a_refused_task_leaves_the_controller_holding_no_device(controller: UniFiClient) -> None:
    before = _held_macs(controller)

    call(unifi_device, _device_task())

    assert _held_macs(controller) == before


def test_check_mode_refuses_the_same_device() -> None:
    # A check-mode run is the one most likely to be pointed at a device that is not
    # there, and it is the one that must not be the run that brings it into being.
    result = call(unifi_device, _device_task(_ansible_check_mode=True))

    assert result.get("failed") is True, result


def test_a_credential_is_never_echoed_when_the_controller_refuses_it() -> None:
    # The key is the credential the run authenticates with, and the controller
    # refuses a value it does not hold. A password beside a key is refused by the
    # spec before the module runs.
    result = call(unifi_device, _device_task(api_key=SECRET))

    assert SECRET not in json.dumps(result)
    assert result.get("failed") is True


def test_a_credential_is_never_echoed_when_the_controller_is_not_reached() -> None:
    # Port 1 on loopback has nothing listening, so the request is refused before a
    # byte of the credential leaves the host.
    result = call(unifi_device, _device_task(controller="127.0.0.1:1", api_key=SECRET))

    assert SECRET not in json.dumps(result)
    assert result.get("failed") is True


def test_the_documented_options_are_the_specified_ones() -> None:
    own = set(_documented()) - set(CONNECTION_ARGUMENTS)

    assert own == set(unifi_device.ARGUMENT_SPEC) - set(CONNECTION_ARGUMENTS)


@pytest.mark.parametrize("option", sorted(set(_documented()) - set(CONNECTION_ARGUMENTS)))
def test_a_documented_option_matches_its_specification(option: str) -> None:
    documented = _documented()[option]
    spec = unifi_device.ARGUMENT_SPEC[option]

    assert documented["type"] == spec["type"]
    assert bool(documented.get("required", False)) == bool(spec.get("required", False))
    assert ("choices" in documented) == ("choices" in spec)


@pytest.mark.parametrize("option", sorted(CONNECTION_ARGUMENTS))
def test_a_shared_option_is_specified_as_the_fragment_declares_it(option: str) -> None:
    # A spec assembled from the shared constant would leave the documentation
    # describing options the cross-check in validate-modules never sees.
    assert unifi_device.ARGUMENT_SPEC[option] == CONNECTION_ARGUMENTS[option]


def test_only_a_credential_is_marked_no_log() -> None:
    # A blanket no_log on a display setting hides the diff an operator needs, and
    # the rule is by name, so the module adds none of its own.
    hidden = {name for name, spec in unifi_device.ARGUMENT_SPEC.items() if spec.get("no_log")}

    assert hidden == _CREDENTIAL_OPTIONS


def test_the_selector_is_not_a_settable_field() -> None:
    # mac selects the device. Had the table carried it, project() would send it with
    # every write, and a task would be able to aim that write at a device other than
    # the one it named.
    assert "mac" not in DEVICE


def _device_record(controller: UniFiClient) -> dict[str, Any]:
    """The controller's own document for the emulated device."""
    for row in rows(controller.get(unifi_device.INVENTORY)):
        if str(row.get("mac", "")) == EMULATED_MAC:
            return dict(row)
    raise AssertionError(f"the controller does not hold {EMULATED_MAC}")


def test_a_task_writes_to_a_device_the_controller_already_holds() -> None:
    # The only case that exercises the write path. Everything else about this
    # module is refusal, which is worth having and is not the feature.
    #
    # The device is put into a state this task differs from first, because the
    # device outlives the test and a run that changed nothing would otherwise fail
    # this for the wrong reason on the second run.
    call(unifi_device, _device_task(mac=EMULATED_MAC, name=EMULATED_NAME, led="on"))

    first = call(unifi_device, _device_task(mac=EMULATED_MAC, name=EMULATED_NAME))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_device, _device_task(mac=EMULATED_MAC, name=EMULATED_NAME))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_options_reach_the_controller_under_their_own_field_names(
    controller: UniFiClient,
) -> None:
    call(
        unifi_device,
        _device_task(mac=EMULATED_MAC, name=EMULATED_NAME, led="off", outdoor_mode="off"),
    )
    record = _device_record(controller)

    # The task names `led` and `outdoor_mode`; the controller holds
    # `led_override` and `outdoor_mode_override`. A table that sent the option
    # name would leave the device unchanged and still report a change.
    assert record["led_override"] == "off"
    assert record["outdoor_mode_override"] == "off"
    assert "led" not in record
    assert "outdoor_mode" not in record


def test_enabled_is_stored_as_the_controllers_disabled_flag(controller: UniFiClient) -> None:
    # The controller holds the opposite flag, so a run that projected the option
    # name through would write `enabled` and leave `disabled` as it was. The
    # device is returned to enabled afterwards, because it is shared.
    disable = _device_task(mac=EMULATED_MAC, name=EMULATED_NAME, enabled=False)
    call(unifi_device, disable)
    disabled = call(unifi_device, disable)
    assert not disabled.get("failed"), disabled.get("msg")
    assert disabled["changed"] is False, disabled.get("changed_fields")
    assert _device_record(controller)["disabled"] is True

    enable = _device_task(mac=EMULATED_MAC, name=EMULATED_NAME, enabled=True)
    call(unifi_device, enable)
    enabled = call(unifi_device, enable)
    assert not enabled.get("failed"), enabled.get("msg")
    assert enabled["changed"] is False, enabled.get("changed_fields")
    assert _device_record(controller)["disabled"] is False


def test_a_management_network_named_in_the_task_reaches_the_network_it_means(
    controller: UniFiClient,
) -> None:
    # The device holds its management network by identifier, and the site's own
    # default network is the one there is to name. The controller resolves it, so
    # a play that knows the name and not the ObjectId still aims at the right one.
    default = find_named(controller, "/rest/networkconf", name="Default")
    task = _device_task(mac=EMULATED_MAC, name=EMULATED_NAME, management_network="Default")

    first = call(unifi_device, task)
    assert not first.get("failed"), first.get("msg")
    assert first["obj"]["mgmt_network_id"] == default["_id"]

    second = call(unifi_device, task)
    assert second["changed"] is False, second.get("changed_fields")


def test_a_management_network_named_both_ways_is_refused(controller: UniFiClient) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    default = find_named(controller, "/rest/networkconf", name="Default")

    with pytest.raises(ValueError, match="management_network"):
        call(
            unifi_device,
            _device_task(
                mac=EMULATED_MAC,
                management_network="Default",
                management_network_id=default["_id"],
            ),
        )


def test_a_management_network_name_the_controller_does_not_hold_is_refused() -> None:
    result = call(
        unifi_device,
        _device_task(mac=EMULATED_MAC, management_network="verify-no-such-network"),
    )

    assert result.get("failed") is True
    assert "verify-no-such-network" in str(result.get("msg", ""))
