# SPDX-License-Identifier: GPL-3.0-or-later
"""Every field name in this collection, checked against the controller's own schema.

The collection's field tables name controller properties. A name that is wrong
produces a rejected request on an operator's network, at apply time, with nothing
earlier saying so. This file is the thing that says so first.

The source is a vendored OpenAPI description generated from the controller's own
field-validation metadata, which is the same metadata that validates a request. A
field declared there exists; a field not declared there is either gone, renamed, or
never was.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import CLIENT
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import DEVICE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_POLICY
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_RULE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_ZONE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import NETWORK
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_FORWARD
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_OVERRIDE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_PROFILE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import WLAN
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project

SPEC = Path(__file__).resolve().parents[4] / "fixtures" / "unifi-local-api.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


def _schema(spec: dict[str, Any], name: str) -> dict[str, Any]:
    return spec["components"]["schemas"][name]


def _props(spec: dict[str, Any], name: str) -> dict[str, Any]:
    return _schema(spec, name).get("properties", {})


#: Table name -> the schema its fields must appear in.
TABLES = {
    "CLIENT": (CLIENT, "Client"),
    "PORT_FORWARD": (PORT_FORWARD, "PortForward"),
    "NETWORK": (NETWORK, "Network"),
    "WLAN": (WLAN, "WLAN"),
    "PORT_PROFILE": (PORT_PROFILE, "PortProfile"),
    "PORT_OVERRIDE": (PORT_OVERRIDE, "DevicePortOverrides"),
    "DEVICE": (DEVICE, "Device"),
    "FIREWALL_RULE": (FIREWALL_RULE, "FirewallRule"),
    "FIREWALL_ZONE": (FIREWALL_ZONE, "FirewallZone"),
    "FIREWALL_POLICY": (FIREWALL_POLICY, "FirewallPolicy"),
}


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_every_field_exists_in_the_controllers_own_schema(
    spec: dict[str, Any],
    table_name: str,
) -> None:
    table, schema_name = TABLES[table_name]
    declared = _props(spec, schema_name)

    for option, field in table.items():
        root = field.split(".")[0]
        assert root in declared, (
            f"{table_name}.{option} maps to {root!r}, which {schema_name} does not declare"
        )


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_no_two_options_map_to_the_same_field(
    spec: dict[str, Any],
    table_name: str,
) -> None:
    # Two options writing one field is a coin toss at apply time, and the losing
    # option is whichever was not named in the play.
    fields = list(TABLES[table_name][0].values())

    assert len(fields) == len(set(fields))


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_option_names_are_snake_case(table_name: str) -> None:
    table = TABLES[table_name][0]

    for option in table:
        assert option == option.lower(), f"{table_name}.{option}"


@pytest.mark.parametrize("key", sorted(ENUM_VALUES))
def test_every_enum_value_appears_in_the_controllers_validation(
    spec: dict[str, Any], key: str
) -> None:
    # A choice the controller does not accept fails on the operator's network at
    # apply time. This is the check that makes that impossible to ship by accident.
    schema_name, field = key.split(".")
    described = _props(spec, schema_name)[field].get("description", "")

    for value in ENUM_VALUES[key]:
        assert value in described, f"{key} choice {value!r} is not in {described!r}"


def test_the_override_surface_is_not_a_resource_with_its_own_endpoint(spec: dict[str, Any]) -> None:
    # It is an array on a device, and the reconciler depends on that. If a
    # controller version gave it an endpoint, this test is where that surfaces.
    assert _props(spec, "Device")["port_overrides"]["type"] == "array"
    assert "items" in _props(spec, "Device")["port_overrides"]


def test_the_override_carries_the_fields_that_shadow_its_profile(spec: dict[str, Any]) -> None:
    # These four are what make a profile plus a network on one port a
    # contradiction. The reconciler refuses that, and it can only do so because
    # they exist.
    declared = _props(spec, "DevicePortOverrides")

    for field in (
        "portconf_id",
        "native_networkconf_id",
        "tagged_networkconf_ids",
        "forward",
    ):
        assert field in declared


def test_the_wireless_passphrase_and_security_are_flat(spec: dict[str, Any]) -> None:
    # The controller validates these three separately on the WLAN object. A nested
    # security document would have every one of them silently dropped.
    declared = _props(spec, "WLAN")

    for field in ("x_passphrase", "security", "wpa_mode", "wpa_enc"):
        assert field in declared


def test_a_policy_position_is_a_number_and_not_a_list(spec: dict[str, Any]) -> None:
    # Nullable, so an absent position is one the controller fills in rather than a
    # value a task has to supply.
    assert _props(spec, "FirewallPolicy")["index"]["type"] == ["integer", "null"]


def test_a_zone_key_is_zone_key_and_not_zone_key_id(spec: dict[str, Any]) -> None:
    # The console's own name is the trap here: zone_key_id is the name a task
    # reaches for and the controller does not declare it.
    declared = _props(spec, "FirewallZone")

    assert "zone_key" in declared
    assert "zone_key_id" not in declared


def test_a_network_links_to_a_zone(spec: dict[str, Any]) -> None:
    # Without this the zone resource would have nothing to hold.
    assert "firewall_zone_id" in _props(spec, "Network")


def test_a_reservation_carries_a_local_dns_name(spec: dict[str, Any]) -> None:
    # The reservation resource is the client record, so a reservation task also
    # sets the name the site's local DNS server answers with.
    assert CLIENT["local_dns_record"] == "local_dns_record"
    assert "local_dns_record" in _props(spec, "Client")


def test_a_firewall_rule_matches_on_its_ruleset_and_name(spec: dict[str, Any]) -> None:
    # Two rules may share a name across rulesets, so both fields are what singles
    # a rule out, and both have to exist in the schema for that to be possible.
    declared = _props(spec, "FirewallRule")

    assert FIREWALL_RULE["name"] == "name"
    assert FIREWALL_RULE["ruleset"] == "ruleset"
    assert "ruleset" in declared


def test_a_firewall_rule_names_networks_and_firewall_groups(spec: dict[str, Any]) -> None:
    # A rule that named a network or a firewall group by a field the controller
    # does not declare would be rejected at apply time.
    declared = _props(spec, "FirewallRule")

    for field in (
        "src_networkconf_id",
        "src_networkconf_type",
        "src_firewallgroup_ids",
        "dst_networkconf_id",
        "dst_networkconf_type",
        "dst_firewallgroup_ids",
    ):
        assert field in declared


def test_a_firewall_rule_protocol_is_free_form() -> None:
    # The schema describes protocol as a regex with numeric ranges, so it fails
    # the verbatim check every choice must pass and is deliberately absent.
    assert "FirewallRule.protocol" not in ENUM_VALUES


# The projection itself, which is what a module actually calls.


def test_an_option_is_renamed_into_the_controllers_field_name() -> None:
    assert project({"subnet": "10.0.20.1/24"}, NETWORK) == {"ip_subnet": "10.0.20.1/24"}


def test_an_unset_option_is_not_sent() -> None:
    # Sending None would ask the controller to clear a field the task never
    # mentioned, which is how managing one setting ends up clearing another.
    assert project({"name": "IoT", "subnet": None}, NETWORK) == {"name": "IoT"}


def test_an_option_with_no_table_entry_is_not_sent() -> None:
    # A field name this collection does not know must not reach the controller as
    # a guess.
    assert project({"not_a_field": "x"}, NETWORK) == {}


def test_a_nested_field_produces_a_nested_payload() -> None:
    # The controller nests these, so a flat key would be dropped silently.
    payload = project({"source_zone_id": "z1", "destination_zone_id": "z2"}, FIREWALL_POLICY)

    assert payload == {"source": {"zone_id": "z1"}, "destination": {"zone_id": "z2"}}


def test_two_options_on_one_side_share_the_side_rather_than_replacing_it() -> None:
    payload = project(
        {"source_zone_id": "z1", "source_port_list": "80,443"},
        FIREWALL_POLICY,
    )

    assert payload == {"source": {"zone_id": "z1", "port": "80,443"}}


def test_a_false_value_is_projected() -> None:
    # Skipping falsy values would make it impossible to turn a flag off.
    assert project({"enabled": False}, NETWORK) == {"enabled": False}


def test_an_empty_list_is_projected() -> None:
    # Emptying a list is how a task says "no tagged networks", and dropping it
    # would leave the old ones in place.
    assert project({"tagged_network_ids": []}, PORT_OVERRIDE) == {"tagged_networkconf_ids": []}


def test_a_profile_has_no_tagged_list_because_it_names_networks_by_exclusion(
    spec: dict[str, Any],
) -> None:
    # The asymmetry is the controller's, and a module that assumed otherwise
    # would send a field the controller silently drops.
    declared = _props(spec, "PortProfile")

    assert "excluded_networkconf_ids" in declared
    assert "tagged_networkconf_ids" not in declared


def test_zero_is_projected() -> None:
    assert project({"index": 0}, FIREWALL_POLICY) == {"index": 0}
