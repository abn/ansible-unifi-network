# SPDX-License-Identifier: GPL-3.0-or-later
"""The port forward module's option names, checked against the controller.

A name the controller does not declare is a write refused on an operator's
network at apply time, with nothing earlier saying so. The source of truth is
the vendored OpenAPI description, generated from the same field-validation
metadata that validates the request, so a field declared there exists.

What only a controller can answer, and what the live suite therefore asks
instead, is whether the endpoint is served, whether the required fields are
stored as sent, and whether a delete stops the controller listing the forward.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_FORWARD
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_port_forward

SPEC = Path(__file__).resolve().parents[3] / "fixtures" / "unifi-local-api.yaml"

#: The options carrying a default, which is exactly the set the controller
#: requires and therefore the set the module always sends.
DEFAULTED = ("enabled", "log_enabled", "source_limiting_enabled")

#: The option the module declares that is its own rather than the controller's.
#: The controller has no field for whether an object should exist, so it is the
#: one module option absent from the table.
LIFECYCLE = "state"

#: The options the module resolves rather than sends. A reference by name is
#: turned into the identifier the controller holds, so it has no field of its own.
REFERENCES = frozenset({"source_firewall_group"})


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())["components"]["schemas"]["PortForward"]


@pytest.fixture(scope="module")
def declared(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]


def test_every_field_the_table_names_is_one_the_controller_declares(
    declared: dict[str, Any],
) -> None:
    for option, field in PORT_FORWARD.items():
        assert field in declared, f"{option} maps to {field!r}, which PortForward does not declare"


def test_the_table_carries_every_option_the_module_lets_a_task_set() -> None:
    # An option absent from the table is not sent, so one a task can name and the
    # table does not carry is a field the collection silently drops. Read from the
    # module's own spec, so a new option nobody added to the table fails here.
    # name is both: it selects the forward and is written on it, so it is in the
    # table as well as being the selector. state is the exception, because the
    # controller has no field for whether an object should exist.
    settable = {
        name
        for name in unifi_port_forward.ARGUMENT_SPEC
        if name not in _CONNECTION and name != "state" and name not in REFERENCES
    }

    assert settable == set(PORT_FORWARD)


def test_no_two_options_map_to_the_same_field() -> None:
    # Two options writing one field is a coin toss at apply time, and the losing
    # option is whichever was not named in the play.
    fields = list(PORT_FORWARD.values())

    assert len(fields) == len(set(fields))


def test_the_ports_are_declared_as_strings_by_the_controller(declared: dict[str, Any]) -> None:
    # A module that sent an integer where the controller holds a string is either
    # refused or coerced into a value the task did not ask for, and the option
    # types follow from what the controller declares.
    for field in ("fwd_port", "dst_port"):
        assert declared[field]["type"] == "string", field

    assert unifi_port_forward.ARGUMENT_SPEC["forward_port"]["type"] == "str"
    assert unifi_port_forward.ARGUMENT_SPEC["destination_port"]["type"] == "str"


def test_the_fields_the_module_always_sends_are_the_ones_the_controller_requires(
    schema: dict[str, Any],
) -> None:
    # The controller refuses a document missing any of these, so the module sends
    # all three whatever a task names. Which three comes from the schema rather
    # than from this file, so a controller requiring a fourth fails here rather
    # than as a refused create on an operator's network.
    assert set(schema["required"]) == {"enabled", "log", "src_limiting_enabled"}
    assert set(schema["required"]) == {PORT_FORWARD[name] for name in DEFAULTED}


def test_only_the_required_fields_carry_a_default() -> None:
    # A default anywhere else turns "not mentioned" into "set to false", which on
    # an object where unmentioned means leave-as-is makes every undeclared option
    # a change. The three are the exception, and the reason is the requirement.
    # The connection fragment's own defaults are the fragment's business.
    defaulted = {
        name
        for name, spec in unifi_port_forward.ARGUMENT_SPEC.items()
        if "default" in spec and name not in _CONNECTION and name != "state"
    }

    assert defaulted == set(DEFAULTED)


def test_a_task_naming_some_options_sends_those_and_the_required_three() -> None:
    wanted = project(
        {
            "name": "Web",
            "forward_address": "192.168.1.50",
            "destination_port": "443",
            "enabled": True,
            "log_enabled": False,
            "source_limiting_enabled": False,
        },
        PORT_FORWARD,
    )

    assert wanted == {
        "name": "Web",
        "fwd": "192.168.1.50",
        "dst_port": "443",
        "enabled": True,
        "log": False,
        "src_limiting_enabled": False,
    }


def test_an_option_the_task_left_out_is_not_sent() -> None:
    # Unset is absent rather than None, because sending None would ask the
    # controller to clear a field the task never mentioned.
    assert project({"name": "Web", "forward_address": None}, PORT_FORWARD) == {"name": "Web"}


def test_the_lifecycle_option_is_the_only_one_the_table_does_not_carry() -> None:
    # A table carrying state would send a field the controller does not have. name
    # is in the table as well as being the selector, because the controller holds
    # the forward's name as a field it stores.
    assert LIFECYCLE not in PORT_FORWARD
    assert PORT_FORWARD["name"] == "name"


def test_the_controller_owned_fields_are_not_settable() -> None:
    # The identifiers, the site and the hidden and no-edit flags are the
    # controller's own. A task setting one is writing metadata rather than
    # configuration, and the console offers no way to do it.
    for field in ("_id", "site_id", "attr_hidden", "attr_hidden_id", "attr_no_edit"):
        assert field not in PORT_FORWARD.values(), field


def test_the_plural_destination_array_is_declared_and_not_managed(declared: dict[str, Any]) -> None:
    # The controller declares a second field for the same purpose, an array of
    # address and interface pairs. The module sends the singular one only,
    # because sending both leaves it two answers to which address answers.
    assert declared["destination_ips"]["type"] == "array"
    assert "destination_ips" not in PORT_FORWARD.values()
    assert PORT_FORWARD["destination_ip"] == "destination_ip"


def test_the_plural_destination_array_names_a_pair_the_singular_fields_express_separately(
    declared: dict[str, Any],
) -> None:
    # The reason it is not managed: each element is an address and an interface,
    # which the singular fields carry separately, so projecting one onto the other
    # would drop one half of every pair.
    item = declared["destination_ips"]["items"]["$ref"].rsplit("/", 1)[-1]
    assert item == "PortForwardDestinationIPs"


def test_the_interface_is_not_given_a_choice_list() -> None:
    # The controller describes the field as a pattern rather than as a set of
    # values, and the pattern admits names a list could not be checked against it.
    # Choices here would refuse values the controller accepts and would look
    # checked when they are not.
    assert "choices" not in unifi_port_forward.ARGUMENT_SPEC["interface"]


def test_the_interface_pattern_admits_more_than_it_names(declared: dict[str, Any]) -> None:
    # The reason a choice list is not offered: the description spells out wan,
    # both and all, and admits wan2 through wan9 without naming them, so a list
    # built from the named values is not the controller's set.
    assert declared["pfwd_interface"]["description"] == "wan[2-9]?|both|all"
    assert "wan2" not in declared["pfwd_interface"]["description"]


def test_the_source_is_narrower_than_the_option_admits(declared: dict[str, Any]) -> None:
    # The controller accepts an address, a range, a CIDR, any of those negated
    # with a leading !, and the word any. The option is therefore a string the
    # controller validates, rather than one this collection narrows to a shape it
    # would then have to reimplement.
    described = declared["src"]["description"]

    for shape in ("^any$", "/([0-9]|[1-2][0-9]|3[0-2])$", "^!"):
        assert shape in described, shape


def test_the_enumerated_options_carry_the_controllers_own_choices() -> None:
    # The spec's choices are the field table's enum, so a controller that renamed
    # a value cannot leave this module offering the old one.
    assert unifi_port_forward.ARGUMENT_SPEC["protocol"]["choices"] == ["tcp_udp", "tcp", "udp"]
    assert unifi_port_forward.ARGUMENT_SPEC["source_limiting_type"]["choices"] == [
        "ip",
        "firewall_group",
    ]


def test_the_source_options_say_they_need_the_limit_enabled() -> None:
    # A source or a group named without the limit enabled is stored and restricts
    # nothing, so the options have to say that the limit is what makes them act.
    documented = yaml.safe_load(unifi_port_forward.DOCUMENTATION)["options"]

    for option in ("source", "source_firewall_group", "source_firewall_group_id"):
        described = " ".join(documented[option]["description"])
        assert "source_limiting_enabled=true" in described, option


def test_the_collection_is_on_the_site_base_and_not_the_policy_engine() -> None:
    # The controller serves the policy engine from above the site, so a path built
    # against the wrong base is a 404 rather than an empty collection.
    assert unifi_port_forward.COLLECTION == "/rest/portforward"


def test_the_module_offers_a_removal() -> None:
    # A port forward is a path into the site, and disabling it is not the same as
    # closing it, so the module has to be able to remove one.
    assert "absent" in unifi_port_forward.ARGUMENT_SPEC["state"]["choices"]


#: The aliases each option accepts, exactly as the argument spec declares them.
#: Stated rather than derived, so a spec that dropped one fails here.
ALIASES: dict[str, tuple[str, ...]] = {
    "destination_port": ("dst_port", "from_port"),
    "forward_port": ("fwd_port", "to_port"),
    "forward_address": ("fwd", "fwd_ip", "to_address", "target_ip"),
    "protocol": ("proto",),
    "source": ("src", "src_ip"),
}

#: A value each aliased option accepts, so a resolved alias can be told apart
#: from the option it belongs to.
ALIAS_VALUES: dict[str, str] = {
    "destination_port": "443",
    "forward_port": "8443",
    "forward_address": "192.168.1.50",
    "protocol": "tcp",
    "source": "10.20.0.0/16",
}


def _resolved(**task: Any) -> dict[str, Any]:
    """The parameters the framework validates a task into."""
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    return basic.AnsibleModule(argument_spec=unifi_port_forward.ARGUMENT_SPEC).params


def _connection() -> dict[str, Any]:
    return {
        "controller": "unifi.example.invalid",
        "api_mount": "appliance",
        "api_family": "legacy",
        "name": "Web",
    }


@pytest.mark.parametrize(
    ("option", "alias"),
    [(option, alias) for option, names in ALIASES.items() for alias in names],
)
def test_each_alias_is_declared_on_the_option_it_renames(option: str, alias: str) -> None:
    assert alias in unifi_port_forward.ARGUMENT_SPEC[option].get("aliases", [])


@pytest.mark.parametrize(
    ("option", "alias"),
    [(option, alias) for option, names in ALIASES.items() for alias in names],
)
def test_each_alias_resolves_to_the_option_it_renames(option: str, alias: str) -> None:
    value = ALIAS_VALUES[option]

    params = _resolved(**_connection(), **{alias: value})

    assert params[option] == value, f"{alias!r} did not resolve to {option!r}"


def test_no_alias_collides_with_an_option_or_another_alias() -> None:
    # An alias sharing a name with an option, or with another alias, makes the
    # name resolve to two things and the framework refuses the spec at runtime.
    aliases = [
        alias
        for spec in unifi_port_forward.ARGUMENT_SPEC.values()
        for alias in spec.get("aliases", [])
    ]

    assert not set(aliases) & set(unifi_port_forward.ARGUMENT_SPEC)
    assert len(aliases) == len(set(aliases))


class _Stub:
    """A client answering one collection with the rows it was handed."""

    def __init__(self, body: Any) -> None:
        self._body = body
        self.reads: list[str] = []

    def get(self, resource: str) -> Any:
        self.reads.append(resource)
        return self._body


def _groups() -> _Stub:
    return _Stub({"data": [{"_id": "6a3c2d8f", "name": "Office"}]})


def test_a_firewall_group_named_in_the_task_is_resolved_to_its_identifier() -> None:
    wanted: dict[str, Any] = {}

    unifi_port_forward._attach_source_firewall_group(
        _groups(), {"source_firewall_group": "Office"}, wanted
    )

    assert wanted["src_firewall_group_id"] == "6a3c2d8f"
    # The name is the task's own spelling of the reference and is not a field the
    # controller holds, so sending it would be a field the controller does not know.
    assert "source_firewall_group" not in wanted


def test_a_firewall_group_named_by_identifier_is_not_looked_up() -> None:
    # A controller that cannot be reached must not be consulted for a reference the
    # task already spelled out.
    client = _Stub(None)
    wanted: dict[str, Any] = {}

    unifi_port_forward._attach_source_firewall_group(
        client, {"source_firewall_group_id": "6a3c2d8f"}, wanted
    )

    assert wanted["src_firewall_group_id"] == "6a3c2d8f"
    assert client.reads == []


def test_a_firewall_group_named_both_ways_is_refused() -> None:
    with pytest.raises(UniFiError, match="firewall group"):
        unifi_port_forward._attach_source_firewall_group(
            _groups(),
            {"source_firewall_group": "Office", "source_firewall_group_id": "6a3c2d8f"},
            {},
        )


def test_naming_no_firewall_group_leaves_the_field_absent() -> None:
    # The reference is optional, so a task that names neither must not have the
    # controller resolve an empty name.
    client = _Stub(None)
    wanted: dict[str, Any] = {}

    unifi_port_forward._attach_source_firewall_group(client, {}, wanted)

    assert wanted == {}
    assert client.reads == []


#: The options the connection doc fragment contributes, which are not this
#: module's and so are not in its field table. Stated rather than imported, so
#: the assertion says which options the table is responsible for rather than
#: agreeing with whatever the fragment currently declares.
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
