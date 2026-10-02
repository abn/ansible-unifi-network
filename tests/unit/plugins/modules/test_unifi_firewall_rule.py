# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall rule module's options and selection, checked against the controller.

A name the controller does not declare is a write refused on an operator's
network at apply time, with nothing earlier saying so. The source of truth is the
vendored OpenAPI description, generated from the same field-validation metadata
that validates the request, so a field declared there exists.

Selection is the part only this resource needs: a rule is keyed by its name
within a ruleset, so the module matches on the pair and the reconciler refuses a
pair that fits more than one rule. The behaviour cases below drive the module
against a stub client, which is the transport substituted rather than a model of
the controller.

What only a controller can answer, and what the live suite therefore asks
instead, is whether the classic endpoint is served, whether the controller stores
the required fields as sent, and whether a delete stops it listing the rule.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any
from typing import cast

import pytest
import yaml
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_RULE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_rule

SPEC = Path(__file__).resolve().parents[3] / "fixtures" / "unifi-local-api.yaml"

#: The option the module declares that is its own rather than the controller's.
#: The controller has no field for whether an object should exist.
LIFECYCLE = "state"

#: The options the module resolves rather than sends. A reference by name is
#: turned into the identifier the controller holds, so it has no field of its own.
REFERENCES = frozenset({"src_network", "dst_network", "src_firewall_group", "dst_firewall_group"})


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())["components"]["schemas"]["FirewallRule"]


@pytest.fixture(scope="module")
def declared(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]


def test_every_field_the_table_names_is_one_the_controller_declares(
    declared: dict[str, Any],
) -> None:
    for option, field in FIREWALL_RULE.items():
        assert field in declared, f"{option} maps to {field!r}, which FirewallRule does not declare"


def test_the_table_carries_every_option_the_module_lets_a_task_set() -> None:
    # An option absent from the table is not sent, so one a task can name and the
    # table does not carry is a field the collection silently drops. Read from the
    # module's own spec, so a new option nobody added to the table fails here.
    settable = {
        name
        for name in unifi_firewall_rule.ARGUMENT_SPEC
        if name not in _CONNECTION and name != LIFECYCLE and name not in REFERENCES
    }

    assert settable == set(FIREWALL_RULE)


def test_no_two_options_map_to_the_same_field() -> None:
    # Two options writing one field is a coin toss at apply time, and the losing
    # option is whichever was not named in the play.
    fields = list(FIREWALL_RULE.values())

    assert len(fields) == len(set(fields))


def test_no_rule_option_carries_a_default() -> None:
    # A default makes "not mentioned" indistinguishable from "set", and on an
    # update that is how a play that only meant to change an address overwrites
    # the protocol the console set or re-enables a disabled rule. The fields the
    # controller requires on a write are required when present instead, so an
    # omitted one is refused rather than defaulted.
    defaulted = {
        name
        for name, spec in unifi_firewall_rule.ARGUMENT_SPEC.items()
        if "default" in spec and name not in _CONNECTION and name != LIFECYCLE
    }

    assert defaulted == set()


def test_a_task_naming_some_options_sends_exactly_those() -> None:
    wanted = project(
        {
            "name": "Allow web",
            "ruleset": "LAN_IN",
            "rule_index": 2001,
            "action": "accept",
            "protocol": "tcp",
            "enabled": True,
            "dst_address": "10.0.20.10",
        },
        FIREWALL_RULE,
    )

    assert wanted == {
        "name": "Allow web",
        "ruleset": "LAN_IN",
        "rule_index": 2001,
        "action": "accept",
        "protocol": "tcp",
        "enabled": True,
        "dst_address": "10.0.20.10",
    }


def test_a_task_that_names_only_an_address_sends_no_protocol_or_enabled() -> None:
    # An unset option is absent from the payload, so an update leaves the
    # controller's own protocol and enabled in place instead of overwriting them
    # with values the task never named.
    wanted = project(
        {
            "name": "Allow web",
            "ruleset": "LAN_IN",
            "rule_index": 2001,
            "action": "accept",
            "dst_address": "10.0.20.10",
        },
        FIREWALL_RULE,
    )

    assert "protocol" not in wanted
    assert "enabled" not in wanted


def test_an_option_the_task_left_out_is_not_sent() -> None:
    # Unset is absent rather than None, because sending None would ask the
    # controller to clear a field the task never mentioned.
    assert project({"name": "Allow web", "dst_address": None}, FIREWALL_RULE) == {
        "name": "Allow web"
    }


def test_the_collection_is_the_classic_rule_endpoint() -> None:
    # The classic engine is what the console itself uses and what its delete
    # works against. A module addressing the zone-based policy surface instead
    # would be refused on a console with no zone-based firewall configured.
    assert unifi_firewall_rule.COLLECTION == "/rest/firewallrule"


def test_the_enumerated_options_carry_the_controllers_own_choices() -> None:
    # The spec's choices are the field table's enum, so a controller that renamed
    # a value cannot leave this module offering the old one.
    assert unifi_firewall_rule.ARGUMENT_SPEC["action"]["choices"] == ["drop", "reject", "accept"]
    assert "LAN_IN" in unifi_firewall_rule.ARGUMENT_SPEC["ruleset"]["choices"]
    assert "GUEST_LOCAL" in unifi_firewall_rule.ARGUMENT_SPEC["ruleset"]["choices"]
    assert unifi_firewall_rule.ARGUMENT_SPEC["src_network_type"]["choices"] == ["ADDRv4", "NETv4"]
    assert unifi_firewall_rule.ARGUMENT_SPEC["dst_network_type"]["choices"] == ["ADDRv4", "NETv4"]


def test_the_protocol_is_not_given_a_choice_list() -> None:
    # The controller describes the field as a pattern admitting protocol names and
    # numbers, so a list here would refuse values the controller accepts and would
    # look checked when it is not.
    assert "choices" not in unifi_firewall_rule.ARGUMENT_SPEC["protocol"]


def test_the_rule_index_is_a_number(declared: dict[str, Any]) -> None:
    # The controller holds the position as a number and compares it as order, so a
    # module sending a string would either be refused or stored in a form the
    # comparison cannot see.
    assert unifi_firewall_rule.ARGUMENT_SPEC["rule_index"]["type"] == "int"
    assert declared["rule_index"]["type"] == ["integer", "null"]


def test_only_the_selector_is_required_in_the_spec() -> None:
    # name and ruleset are the pair that identifies a rule, needed for a removal
    # as well as a write. The fields the controller requires of a new rule are not
    # in the spec's required set: a task that omits one is refused at run time only
    # when the rule does not exist, so an update may leave what it is not changing.
    required = {
        name
        for name, spec in unifi_firewall_rule.ARGUMENT_SPEC.items()
        if spec.get("required") and name not in _CONNECTION
    }

    assert required == {"name", "ruleset"}


def test_the_create_fields_are_the_controller_required_ones() -> None:
    # The controller refuses a document missing any of these four when it creates
    # a rule, and only then.
    assert unifi_firewall_rule.PRESENT_REQUIRED == (
        "rule_index",
        "action",
        "protocol",
        "enabled",
    )


def _validated(task: dict[str, Any]) -> dict[str, Any]:
    """The parameters the framework validates a task into, with the module's spec."""
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    return basic.AnsibleModule(
        argument_spec=unifi_firewall_rule.ARGUMENT_SPEC,
        required_together=[
            ("username", "password"),
            *unifi_firewall_rule.REQUIRED_TOGETHER,
        ],
        mutually_exclusive=[
            ("api_key", "username"),
            ("api_key", "password"),
            *unifi_firewall_rule.MUTUALLY_EXCLUSIVE,
        ],
    ).params


def _connection() -> dict[str, Any]:
    return {
        "controller": "unifi.example.invalid",
        "api_mount": "appliance",
        "api_family": "legacy",
    }


def test_a_removal_needs_neither_the_action_nor_the_position() -> None:
    # The selection is ruleset and name, so a removal is complete without the
    # fields only a write requires.
    params = _validated(
        {
            **_connection(),
            "name": "Allow web",
            "state": "absent",
            "ruleset": "LAN_IN",
        }
    )

    assert params["state"] == "absent"
    assert params["rule_index"] is None
    assert params["action"] is None
    assert params["protocol"] is None
    assert params["enabled"] is None


def test_a_present_task_resolves_the_create_fields() -> None:
    params = _validated(
        {
            **_connection(),
            "name": "Allow web",
            "state": "present",
            "ruleset": "LAN_IN",
            "rule_index": 2001,
            "action": "accept",
            "protocol": "tcp",
            "enabled": False,
        }
    )

    assert params["rule_index"] == 2001
    assert params["action"] == "accept"
    assert params["protocol"] == "tcp"
    assert params["enabled"] is False


def test_the_module_offers_a_removal() -> None:
    # A rule is a security control, and disabling it is not the same as removing
    # it, so the module has to be able to remove one.
    assert "absent" in unifi_firewall_rule.ARGUMENT_SPEC["state"]["choices"]


def test_the_controller_owned_fields_are_not_settable() -> None:
    # The identifiers, the enclosing site and the no-edit flags are the
    # controller's own. A task setting one writes metadata rather than
    # configuration, and the console offers no way to do it.
    for field in ("_id", "site_id", "attr_hidden", "attr_hidden_id", "attr_no_edit"):
        assert field not in FIREWALL_RULE.values(), field


# Selecting a rule is a composite, because a name alone is not unique.

_RULES = [
    {
        "_id": "r1",
        "ruleset": "LAN_IN",
        "name": "Block",
        "rule_index": 2000,
        "action": "drop",
        "protocol": "all",
        "enabled": True,
    },
    {
        "_id": "r2",
        "ruleset": "WAN_IN",
        "name": "Block",
        "rule_index": 2000,
        "action": "drop",
        "protocol": "all",
        "enabled": True,
    },
]


class _Store:
    """A client holding one collection, so selection and writes both act on it."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = [dict(row) for row in (rows or [])]
        self.posts = 0
        self.sets = 0
        self.deletes = 0

    def get(self, resource: str) -> Any:
        return {"data": [dict(row) for row in self.rows]}

    def post(self, resource: str, body: Any) -> None:
        self.posts += 1
        row = dict(body)
        row.setdefault("_id", f"new{self.posts}")
        self.rows.append(row)

    def set(self, resource: str, body: Any) -> None:
        self.sets += 1
        identifier = body.get("_id")
        self.rows = [dict(body) if row.get("_id") == identifier else row for row in self.rows]

    def delete(self, resource: str) -> None:
        self.deletes += 1
        identifier = resource.rsplit("/", 1)[-1]
        self.rows = [row for row in self.rows if row.get("_id") != identifier]


class _Module:
    """A stand-in for ``AnsibleModule`` holding the params the spec would resolve."""

    def __init__(self, params: dict[str, Any], *, check_mode: bool = False) -> None:
        self.params = params
        self.check_mode = check_mode
        self.result: dict[str, Any] | None = None

    def exit_json(self, **kwargs: Any) -> None:
        self.result = kwargs
        # The framework leaves the process here, and a run that only recorded the
        # result would fall through to the next branch.
        raise SystemExit(0)


def _params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "name": "Block",
        "state": "present",
        "ruleset": "LAN_IN",
        "rule_index": 2000,
        "action": "drop",
        "protocol": "all",
        "enabled": True,
    }
    params.update(overrides)
    return params


def _run(monkeypatch: pytest.MonkeyPatch, store: _Store, **overrides: Any) -> dict[str, Any]:
    """Run the module once against ``store``, returning what it would report."""
    monkeypatch.setattr(unifi_firewall_rule, "build_client", lambda params: store)
    module = _Module(_params(**overrides))
    with contextlib.suppress(SystemExit):
        unifi_firewall_rule.run(cast(Any, module))
    assert module.result is not None, "the module reported nothing"
    return module.result


def test_creating_a_rule_posts_the_six_fields_the_controller_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()

    result = _run(monkeypatch, store)

    assert result["changed"] is True
    assert store.posts == 1
    assert set(store.rows[0]) >= {
        "name",
        "ruleset",
        "rule_index",
        "action",
        "protocol",
        "enabled",
    }


def test_a_second_run_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    _run(monkeypatch, store)
    second = _run(monkeypatch, store)

    assert second["changed"] is False, second.get("changed_fields")
    assert store.posts == 1
    assert store.sets == 0


@pytest.mark.parametrize("missing", unifi_firewall_rule.PRESENT_REQUIRED)
def test_a_create_without_a_create_field_is_refused_before_a_write(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    # The four are required only when the rule does not exist. A create that omits
    # one is refused by name rather than posted as a document the controller would
    # reject, and nothing is written before the refusal.
    store = _Store()

    with pytest.raises(UniFiError, match=f"requires {missing} to be named"):
        _run(monkeypatch, store, **{missing: None})

    assert store.posts == 0


def test_an_update_may_omit_the_create_fields_the_controller_already_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An update is not a create: the fields the controller requires of a new rule
    # are optional here, and omitting one leaves the value the controller holds in
    # place rather than restating or resetting it.
    store = _Store([dict(_RULES[0])])

    result = _run(monkeypatch, store, protocol=None, enabled=None)

    assert result["changed"] is False, result.get("changed_fields")
    assert store.sets == 0
    assert store.rows[0]["protocol"] == "all"
    assert store.rows[0]["enabled"] is True


def test_an_update_that_omits_a_create_field_does_not_overwrite_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store([dict(_RULES[0])])

    result = _run(monkeypatch, store, action="accept", protocol=None, enabled=None)

    assert result["changed"] is True
    assert store.sets == 1
    assert store.rows[0]["action"] == "accept"
    assert store.rows[0]["protocol"] == "all"
    assert store.rows[0]["enabled"] is True


def test_changing_the_action_is_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([dict(_RULES[0])])

    result = _run(monkeypatch, store, action="accept")

    assert result["changed"] is True
    assert store.sets == 1
    assert store.rows[0]["action"] == "accept"


def test_changing_the_rule_index_is_a_reorder(monkeypatch: pytest.MonkeyPatch) -> None:
    # rule_index is the rule's position in its chain, so moving it moves the
    # traffic the rule governs and is reconciled like any other field.
    store = _Store([dict(_RULES[0])])

    result = _run(monkeypatch, store, rule_index=2010)

    assert result["changed"] is True
    assert store.sets == 1
    assert store.rows[0]["rule_index"] == 2010


def test_selection_is_by_the_ruleset_and_name_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both rules carry the name Block; only the ruleset tells them apart, so a
    # module selecting on the name alone would aim its write at one of two.
    store = _Store(_RULES)

    result = _run(monkeypatch, store, ruleset="WAN_IN")

    assert result["changed"] is False
    assert result["obj"]["_id"] == "r2"
    assert store.posts == 0


def test_two_same_named_rules_in_one_ruleset_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A pair fitting more than one rule is too broad to act on, and picking one
    # changes traffic the task never named.
    store = _Store(
        [
            {"_id": "r1", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
            {"_id": "r2", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
        ]
    )

    with pytest.raises(UniFiError, match="ambiguous"):
        _run(monkeypatch, store)


def test_absent_removes_only_the_selected_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store(_RULES)

    result = _run(monkeypatch, store, state="absent", ruleset="WAN_IN")

    assert result["changed"] is True
    assert store.deletes == 1
    assert [row["_id"] for row in store.rows] == ["r1"]


def test_removing_an_absent_rule_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    result = _run(monkeypatch, store, state="absent")

    assert result["changed"] is False
    assert store.deletes == 0


def test_logging_is_also_known_as_log_enabled() -> None:
    # The port forward module spells the same field log_enabled, so a play written
    # against that spelling works here without a second option to keep in step.
    params = _validated(
        {
            **_connection(),
            "name": "Allow web",
            "state": "present",
            "ruleset": "LAN_IN",
            "rule_index": 2001,
            "action": "accept",
            "protocol": "tcp",
            "enabled": True,
            "log_enabled": True,
        }
    )

    assert params["logging"] is True


def _present(**overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        **_connection(),
        "name": "Allow web",
        "state": "present",
        "ruleset": "LAN_IN",
        "rule_index": 2001,
        "action": "accept",
        "protocol": "tcp",
        "enabled": True,
    }
    task.update(overrides)
    return task


@pytest.mark.parametrize("side", ["src", "dst"])
def test_a_network_identifier_without_its_type_is_refused(side: str) -> None:
    # The controller refuses the document with
    # api.err.FirewallRuleNetworkConfTypeRequired, so the pair is refused here
    # before any request rather than on an operator's network.
    with pytest.raises(SystemExit):
        _validated(_present(**{f"{side}_network_id": "net1"}))


def test_a_named_network_needs_no_explicit_type() -> None:
    # Naming a network supplies NETv4 itself, so the required-together pair does
    # not apply to the name form.
    params = _validated(_present(src_network="LAN"))

    assert params["src_network"] == "LAN"


class _Named:
    """A client answering named collections, recording every read."""

    def __init__(self, bodies: dict[str, Any] | None = None) -> None:
        self._bodies = bodies or {}
        self.reads: list[str] = []

    def get(self, resource: str) -> Any:
        self.reads.append(resource)
        return self._bodies.get(resource, {"data": []})


def test_a_network_named_in_the_task_resolves_to_its_identifier_and_type() -> None:
    # The point of the reference: a play that knows the network's name and not its
    # ObjectId still matches it, and a named network is a network, so the type the
    # controller reads it under is NETv4.
    client = _Named({unifi_firewall_rule.NETWORKS: {"data": [{"_id": "net1", "name": "LAN"}]}})
    wanted: dict[str, Any] = {}

    unifi_firewall_rule._attach_network(client, {"src_network": "LAN"}, wanted, side="src")

    assert wanted["src_networkconf_id"] == "net1"
    assert wanted["src_networkconf_type"] == "NETv4"
    # The name is the task's own spelling of the reference and is not a field the
    # controller holds, so sending it would be a field the controller does not know.
    assert "src_network" not in wanted


def test_a_network_named_by_identifier_is_not_looked_up() -> None:
    # A controller that cannot be reached must not be consulted for a reference the
    # task already spelled out.
    client = _Named()
    wanted: dict[str, Any] = {}

    unifi_firewall_rule._attach_network(client, {"src_network_id": "net1"}, wanted, side="src")

    assert wanted == {"src_networkconf_id": "net1"}
    assert client.reads == []


def test_a_network_named_both_ways_is_refused() -> None:
    client = _Named({unifi_firewall_rule.NETWORKS: {"data": [{"_id": "net1", "name": "LAN"}]}})

    with pytest.raises(UniFiError, match="network"):
        unifi_firewall_rule._attach_network(
            client, {"src_network": "LAN", "src_network_id": "net1"}, {}, side="src"
        )


def test_a_named_network_beside_an_address_type_is_refused() -> None:
    # A network is not an address, so a task asserting ADDRv4 beside a network
    # name has two answers to one question, and the module refuses rather than
    # silently overriding the type the task stated.
    client = _Named({unifi_firewall_rule.NETWORKS: {"data": [{"_id": "net1", "name": "LAN"}]}})

    with pytest.raises(UniFiError, match="NETv4"):
        unifi_firewall_rule._attach_network(
            client, {"src_network": "LAN", "src_network_type": "ADDRv4"}, {}, side="src"
        )


def test_a_firewall_group_named_in_the_task_becomes_a_one_element_list() -> None:
    # The controller's field is a list even when a task names one group, so the
    # resolved identifier is wrapped rather than sent bare.
    client = _Named(
        {unifi_firewall_rule.FIREWALL_GROUPS: {"data": [{"_id": "gp1", "name": "Office"}]}}
    )
    wanted: dict[str, Any] = {}

    unifi_firewall_rule._attach_firewall_group(
        client, {"dst_firewall_group": "Office"}, wanted, side="dst"
    )

    assert wanted["dst_firewallgroup_ids"] == ["gp1"]
    assert "dst_firewall_group" not in wanted


def test_a_firewall_group_named_both_ways_is_refused() -> None:
    client = _Named(
        {unifi_firewall_rule.FIREWALL_GROUPS: {"data": [{"_id": "gp1", "name": "Office"}]}}
    )

    with pytest.raises(UniFiError, match="firewall group"):
        unifi_firewall_rule._attach_firewall_group(
            client,
            {"src_firewall_group": "Office", "src_firewall_group_ids": ["gp1"]},
            {},
            side="src",
        )


def test_naming_no_reference_makes_no_read() -> None:
    # The references are optional, so a task naming none leaves the fields absent
    # rather than asking the controller to resolve an empty name.
    client = _Named()
    wanted: dict[str, Any] = {}

    unifi_firewall_rule._attach_references(client, {}, wanted)

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
