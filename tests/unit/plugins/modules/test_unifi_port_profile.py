# SPDX-License-Identifier: GPL-3.0-or-later
"""The port profile module's computed exclusions, without a controller.

The console holds a profile's networks as the native one and the list it excludes,
so the tagged set a task names is the complement of the two. The computation is
what this suite pins: the exclusions have to be every other network on the site,
the native network has to be named by the task, and the exclusions have to be
compared in a canonical order so a second run reports no change.

The controller's own answers, which are the ones that matter most here, are asked
in the live suite.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_PROFILE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_profile as under

#: The site's networks, as the controller would list them. The controller marks no
#: network as the site's default in a field the module reads, so none is special
#: and a task has to name the native one.
SITE: dict[str, Any] = {
    "data": [
        {"_id": "net-default", "name": "Default"},
        {"_id": "net-iot", "name": "IoT"},
        {"_id": "net-guest", "name": "Guest"},
    ]
}


class _Stub:
    """A client answering the one collection the module reads."""

    def __init__(self, body: Any) -> None:
        self._body = body

    def get(self, resource: str) -> Any:
        return self._body


def _wanted(**task: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"name": "IoT access", **task}
    return under._wanted(_Stub(SITE), params)


def _excluded(wanted: dict[str, Any]) -> list[str]:
    return wanted["excluded_networkconf_ids"]


def test_the_exclusions_are_every_network_apart_from_native_and_tagged() -> None:
    wanted = _wanted(native_network="IoT", tagged_networks=["Guest"])

    assert _excluded(wanted) == ["net-default"]


def test_a_profile_that_tags_nothing_excludes_every_other_network() -> None:
    # The console stores membership by exclusion, so no tagged network means the
    # native one plus every other network on the site is excluded.
    wanted = _wanted(native_network="IoT")

    assert _excluded(wanted) == ["net-default", "net-guest"]


def test_the_exclusions_do_not_name_the_native_network() -> None:
    # An exclusion list naming the native network is a contradiction: the native
    # network is what the complement is computed against.
    wanted = _wanted(native_network="IoT", tagged_networks=["Guest"])

    assert "net-iot" not in _excluded(wanted)


def test_the_exclusions_are_sorted_so_a_second_run_is_stable() -> None:
    first = _excluded(_wanted(native_network="IoT"))
    second = _excluded(_wanted(native_network="IoT"))

    assert first == second == sorted(first)


def test_native_named_by_a_name_is_resolved_to_its_identifier() -> None:
    wanted = _wanted(native_network="IoT")

    assert wanted["native_networkconf_id"] == "net-iot"


def test_native_named_by_an_identifier_is_not_looked_up() -> None:
    # A task that already spells out the identifier does not resolve a name, so a
    # network the site does not hold under that name is not consulted.
    wanted = _wanted(native_network_id="a-pasted-identifier")

    assert wanted["native_networkconf_id"] == "a-pasted-identifier"


def _connection() -> dict[str, Any]:
    return {
        "controller": "unifi.example.invalid",
        "api_mount": "appliance",
        "api_family": "legacy",
    }


def _validated(task: dict[str, Any]) -> dict[str, Any]:
    """The parameters the framework validates a task into, with the module's spec."""
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    return basic.AnsibleModule(
        argument_spec=under.ARGUMENT_SPEC,
        required_if=[("state", "present", under.NATIVE_ONE_OF, True)],
    ).params


def test_naming_neither_native_form_is_refused_at_argument_validation() -> None:
    # The exclusion list is computed against the native network, and the controller
    # marks no network as the site's default in a field this module reads, so there
    # is nothing to fall back to and a task has to name one.
    task = {**_connection(), "name": "IoT access"}

    with pytest.raises(SystemExit):
        _validated(task)


def test_removing_naming_neither_native_form_is_accepted() -> None:
    # A removal selects the profile by name and reads no network, so the native
    # requirement applies only while the profile is managed.
    task = {**_connection(), "name": "IoT access", "state": "absent"}

    assert _validated(task)["state"] == "absent"


def test_naming_one_native_form_is_accepted() -> None:
    task = {**_connection(), "name": "IoT access", "native_network": "IoT"}

    assert _validated(task)["native_network"] == "IoT"


def test_naming_native_both_ways_is_refused() -> None:
    # A task stating both has two answers to one question, and neither resolves it.
    with pytest.raises(UniFiError, match="both"):
        _wanted(native_network="IoT", native_network_id="net-iot")


def test_a_native_name_the_site_does_not_hold_is_refused() -> None:
    with pytest.raises(UniFiError, match="verify-no-such-network"):
        _wanted(native_network="verify-no-such-network")


def test_a_tagged_name_resolves_to_its_identifier() -> None:
    wanted = _wanted(native_network="IoT", tagged_networks=["Guest"])

    assert "net-guest" not in _excluded(wanted)


def test_a_tagged_name_the_site_does_not_hold_is_refused() -> None:
    with pytest.raises(UniFiError, match="verify-no-such-network"):
        _wanted(native_network="IoT", tagged_networks=["verify-no-such-network"])


def test_the_projection_names_the_controllers_own_fields() -> None:
    wanted = project(
        {
            "name": "IoT access",
            "native_network_id": "net-iot",
            "forward": "customize",
            "poe_mode": "auto",
            "speed": 1000,
        },
        PORT_PROFILE,
    )

    assert wanted == {
        "name": "IoT access",
        "native_networkconf_id": "net-iot",
        "forward": "customize",
        "poe_mode": "auto",
        "speed": 1000,
    }


def test_the_wanted_document_carries_the_computed_fields_the_table_names() -> None:
    wanted = _wanted(native_network="IoT", tagged_networks=["Guest"])

    assert set(wanted) == {
        "name",
        "native_networkconf_id",
        "excluded_networkconf_ids",
    }


def test_every_settable_option_is_one_the_table_sends() -> None:
    # An option absent from the table is not sent, so one a task can name and the
    # table does not carry is a field the collection silently drops. forward is in
    # the table but not settable: the controller derives it from membership and
    # overwrites any other value.
    derived = {"state", "native_network", "tagged_networks"}
    settable = {
        name for name in under.ARGUMENT_SPEC if name not in _CONNECTION and name not in derived
    }

    assert settable == set(PORT_PROFILE) - {"excluded_network_ids", "forward"}


def test_forward_is_not_a_task_option() -> None:
    # The controller reads forward back from membership and never stores a task's
    # value unless it matches, so exposing it would report a change forever.
    assert "forward" not in under.ARGUMENT_SPEC


def test_the_module_offers_no_raw_exclusion_list() -> None:
    # The ergonomic surface is the names of the networks, and a raw exclusion list
    # beside it would leave the controller two answers to what the profile carries.
    assert "excluded_network_ids" not in under.ARGUMENT_SPEC


def test_the_enumerated_options_carry_the_controllers_own_choices() -> None:
    assert under.ARGUMENT_SPEC["poe_mode"]["choices"] == ["auto", "off"]
    assert under.ARGUMENT_SPEC["fec_mode"]["choices"] == ["rs-fec", "fc-fec", "default", "disabled"]
    assert under.ARGUMENT_SPEC["tagged_vlan_mgmt"]["choices"] == ["auto", "block_all", "custom"]


#: The options the connection doc fragment contributes, which are not this
#: module's and so are not in its field table. Stated rather than imported, so the
#: assertion says which options the table is responsible for rather than agreeing
#: with whatever the fragment currently declares.
_CONNECTION = frozenset(
    {
        "api_family",
        "api_key",
        "api_mount",
        "ca_path",
        "controller",
        "login_path",
        "password",
        "site",
        "timeout",
        "username",
        "validate_certs",
    }
)
