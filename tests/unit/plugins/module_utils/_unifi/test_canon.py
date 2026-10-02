# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical comparison, against the equivalence classes that matter.

Every test here is an equivalence class: two values that mean the same thing and
must compare equal, or two that differ and must not. Those are the cases a
reconciler gets wrong, and they are all decidable without a controller, which is
the reason this file can be tested completely before a single module exists.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import SECRET_FIELDS
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import SERVER_GENERATED
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import compare
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import differences
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import normalise

SPEC = Path(__file__).resolve().parents[4] / "fixtures" / "unifi-local-api.yaml"

#: A property name that could hold a secret. Every name matching this on a reported
#: resource is either a secret in :data:`SECRET_FIELDS` or a documented lookalike in
#: :data:`NOT_SECRET`; a name in neither fails the test.
SECRET_SHAPED = re.compile(r"pass|secret|psk|wep|_key$")

#: The schemas whose rows a module reports through ``obj`` or ``diff``. A secret on
#: one of these leaks into a result; a secret on an unshipped schema does not,
#: because no module reports that row.
REPORTED_SCHEMAS = (
    "Network",
    "WLAN",
    "Device",
    "Client",
    "PortForward",
    "FirewallRule",
    "PortProfile",
    "DevicePortOverrides",
)

#: Secret-shaped names that hold no secret, each with the reason it is not one.
NOT_SECRET = {
    "ipsec_key_exchange": "an ikev1 or ikev2 choice, not key material",
    "radius_macacl_empty_password": "a boolean accepting an empty RADIUS password",
    "sae_psk": "a list of WLANSaePsk documents, whose nested psk is the secret",
    "sae_psk_vlan_required": "a boolean policy flag",
    "wan_pppoe_password_enabled": "a boolean enabling the PPPoE password field",
    "wep_idx": "a slot number selecting which WEP key is active, not key material",
    "wireguard_client_peer_public_key": "a peer public key, public by definition",
    "wireguard_public_key": "this interface's public key, public by definition",
    "wpa_psk_radius": "a disabled, optional or required choice",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


def _secret_shaped_names(spec: dict[str, Any]) -> set[str]:
    """Every secret-shaped property reachable from a reported schema.

    Follows ``$ref`` so a field nested in a referenced schema, such as
    ``WLANPrivatePresharedKeys.password``, is collected with the schema that carries
    it.
    """
    schemas = spec["components"]["schemas"]
    found: set[str] = set()
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    visit(schemas[name])
                return
            properties = node.get("properties")
            if isinstance(properties, dict):
                found.update(name for name in properties if SECRET_SHAPED.search(name))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for name in REPORTED_SCHEMAS:
        seen.add(name)
        visit(schemas[name])
    return found


@pytest.mark.parametrize(
    ("wanted", "current"),
    [
        # A VLAN id is an int on one endpoint and a string on another. Comparing
        # them strictly reports a change on every run against a controller that
        # has not changed.
        (20, "20"),
        ("20", 20),
        (20, " 20 "),
        (0, "0"),
        (-1, "-1"),
        # A DHCP lease time crosses the same boundary between versions.
        (86400, "86400"),
    ],
)
def test_a_number_is_the_same_whatever_its_type(wanted: object, current: object) -> None:
    assert compare(wanted, current)


@pytest.mark.parametrize(
    ("wanted", "current"),
    [
        # The radio bands of one wireless network, built two ways.
        (["2g", "5g"], ["5g", "2g"]),
        (["2g", "5g", "6g"], ["6g", "2g", "5g"]),
        # Numeric membership, where the two sides cross the type boundary.
        (["20", "30"], [30, "20"]),
    ],
)
def test_order_is_not_meaning_in_a_list(wanted: object, current: object) -> None:
    assert compare(wanted, current)


def test_a_number_and_a_name_that_happens_to_start_with_it_are_different() -> None:
    # 5 and "5g" are a band id and a radio generation. Reading them as equal would
    # silently drop a requested band because its index happened to match.
    assert not compare(["2g", "5g"], [5, 2])


@pytest.mark.parametrize(
    ("wanted", "current"),
    [
        # A port list, given as the comma string the controller stores, in either
        # order and with either spacing. The field name is what selects the rule:
        # without it this is two different strings.
        ("80,443", "443,80"),
        ("80, 443", "443 , 80"),
        ("443, 80", "80,443"),
    ],
)
def test_order_is_not_meaning_in_a_comma_separated_list(
    wanted: str,
    current: str,
) -> None:
    assert compare(wanted, current, path="port_list")


def test_a_comma_separated_list_outside_its_fields_is_compared_as_text() -> None:
    # The rule is per field, not per shape. A name that happens to contain a
    # comma is a name, not a list.
    assert not compare("a,b", "b,a", path="name")


def test_a_list_given_as_a_list_matches_the_comma_string_the_controller_stores() -> None:
    # A task may give a list where the controller holds a string, and that is one
    # answer rather than two.
    assert compare(["80", "443"], "443,80", path="port_list")


def test_a_different_set_of_values_is_a_difference() -> None:
    assert not compare(["2g", "5g"], ["2g"])


def test_a_duplicate_is_still_a_difference() -> None:
    # Sorting does not deduplicate, and it must not: a task asking for a band
    # twice is asking for something the controller will not hold.
    assert not compare(["2g", "2g"], ["2g"])


@pytest.mark.parametrize(
    "field",
    ["index", "position", "order"],
)
def test_a_position_is_meaning_where_it_is_named(field: str) -> None:
    # A policy's index is its place in the chain. Reordering it changes the
    # network, so the order is compared even though every other list is a set.
    assert not compare(["a", "b"], ["b", "a"], path=field)


def test_a_server_generated_field_is_never_a_difference() -> None:
    wanted = {"name": "IoT", "vlan": 20}

    assert not differences(wanted, {"name": "IoT", "vlan": "20", "stat": {"rx_bytes_r": 999}})


def test_every_server_generated_field_is_ignored_wherever_it_appears() -> None:
    for field in SERVER_GENERATED:
        assert not differences({field: "wanted"}, {field: "different"}), field


def test_a_reported_secret_is_named_apart_from_a_server_generated_field() -> None:
    # The comparison has to see a secret: excluding it there would make a changed
    # passphrase read as no change and never be written. Redaction removes it from
    # what is reported, which is a different question from what is compared.
    assert "x_passphrase" in SECRET_FIELDS
    assert "x_passphrase" not in SERVER_GENERATED


def test_every_secret_shaped_property_on_a_reported_resource_is_classified(
    spec: dict[str, Any],
) -> None:
    # A module reports the controller's raw re-read row, so a secret on any
    # reported resource reaches the caller unless it is redacted. A new
    # secret-looking property on one of those resources must be classified here,
    # as a secret or as a documented lookalike, before it can ship.
    candidates = _secret_shaped_names(spec)
    unclassified = candidates - SECRET_FIELDS - set(NOT_SECRET)

    assert not unclassified, (
        "classify these as a secret in canon.SECRET_FIELDS or as a lookalike in "
        f"NOT_SECRET: {sorted(unclassified)}"
    )
    assert not SECRET_FIELDS & set(NOT_SECRET), "a name cannot be both a secret and a lookalike"


@pytest.mark.parametrize(
    ("wanted", "current"),
    [
        # speed and full_duplex are negotiated link state on a device's hardware
        # port table, but they are settable on a port profile and a port override.
        # An exclusion by name cannot tell the two apart, so it may not hold them:
        # a change to either option would otherwise never be written.
        ({"speed": 1000}, {"speed": 100}),
        ({"full_duplex": True}, {"full_duplex": False}),
    ],
)
def test_an_option_sharing_a_name_with_hardware_state_is_a_difference(
    wanted: dict[str, object],
    current: dict[str, object],
) -> None:
    assert differences(wanted, current) == wanted


@pytest.mark.parametrize("field", ["_id", "id", "uuid", "site_id", "mac", "port_idx"])
def test_the_identifiers_and_envelopes_are_still_ignored(field: str) -> None:
    # The exclusion exists for an object's address and its metadata. mac selects a
    # client and port_idx is an embedded-list identity compared by key, not by name.
    assert differences({field: "wanted"}, {field: "different"}) == {}


def test_a_nested_server_generated_field_is_ignored() -> None:
    # The controller nests its metadata, and a task's options may be nested too.
    wanted = {"config": {"name": "uplink", "_id": "nope"}}

    assert not differences(wanted, {"config": {"name": "uplink", "_id": "yes"}})


def test_only_the_fields_a_task_named_are_reported() -> None:
    # Reporting an option the task deliberately omitted would tell the operator
    # to supply something they chose not to manage.
    found = differences({"name": "IoT"}, {"name": "IoT", "vlan": 20})

    assert found == {}


def test_a_difference_names_the_option_rather_than_the_object() -> None:
    found = differences({"vlan": 20}, {"vlan": 30})

    assert found == {"vlan": 20}


def test_a_nested_difference_is_named_by_its_dotted_path() -> None:
    found = differences(
        {"dhcpd": {"dhcpd_enabled": True}},
        {"dhcpd": {"dhcpd_enabled": False}},
    )

    assert found == {"dhcpd.dhcpd_enabled": True}


def test_a_nested_mapping_reports_only_the_leaf_that_differs() -> None:
    # Naming the leaf rather than the whole subdocument means a reader is told
    # which option was wrong, and a diff is one line rather than one object.
    found = differences({"dhcpd": {"a": 1, "b": 2}}, {"dhcpd": {"a": 1, "b": 9}})

    assert found == {"dhcpd.b": 2}


def test_a_field_the_task_did_not_name_is_not_a_difference() -> None:
    # The projection is what stops a module re-sending its whole document each
    # run: the controller carries fields a task never mentioned, and comparing
    # them would report a change on a controller nobody had touched.
    found = differences({"name": "IoT"}, {"name": "IoT", "is_nat": False})

    assert found == {}


def test_a_task_key_the_controller_omits_is_a_difference() -> None:
    assert differences({"name": "IoT"}, {}) == {"name": "IoT"}


def test_a_scalar_wanted_against_a_missing_field_is_reported() -> None:
    assert differences("IoT", None, path="name") == {"name": "IoT"}


def test_a_false_value_is_a_value_and_not_an_absence() -> None:
    # Skipping falsy values is the classic bug here: a task turning a flag off
    # would be treated as not having asked.
    found = differences({"enabled": False}, {"enabled": True})

    assert found == {"enabled": False}


def test_zero_is_a_value_and_not_an_absence() -> None:
    assert differences({"vlan": 0}, {"vlan": 1}) == {"vlan": 0}


def test_true_and_one_are_not_the_same_answer() -> None:
    # A flag the controller renders as 1 is describing something other than a
    # boolean, and reporting no change would leave it wrong.
    assert not compare(True, 1)
    assert not compare(1, True)


def test_a_list_of_mixed_types_can_still_be_compared() -> None:
    # Sorting a mixed list raises in Python, and a controller does hand back a
    # list mixing strings and numbers.
    assert compare([2, "5g"], ["5g", 2])


def test_a_nested_list_is_compared_without_raising() -> None:
    assert compare([[1, 2], [3]], [[3], [1, 2]])


def test_normalise_drops_server_generated_keys_at_the_top_level() -> None:
    assert normalise({"name": "IoT", "_id": "x"}) == {"name": "IoT"}


def test_an_empty_string_is_not_the_same_as_an_absent_value() -> None:
    # A task setting an empty string asked for an empty string. Treating it as
    # "leave it alone" would drop the request without saying so.
    assert not compare("", None)


def test_comparing_a_whole_document_is_the_error_the_projection_exists_to_avoid() -> None:
    # Comparing a task's options against a controller object field by field, with
    # no projection, reports a difference on nearly every run.
    current = {
        "_id": "abc",
        "site_id": "default",
        "name": "IoT",
        "vlan": 20,
        "uptime": 12345,
        "last_seen": 1700000000,
        "stat": {"rx_bytes_r": 1},
        "dhcpd_enabled": True,
    }

    assert differences({"name": "IoT", "vlan": 20}, current) == {}
