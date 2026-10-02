# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall rule module, against the throwaway controller.

The classic rule engine is the one the console itself uses, and each of its
writes was measured before this module was built: a POST, a PUT and a DELETE each
answer 200 with an ok envelope, and the DELETE genuinely stops the controller
listing the rule. What only the controller can answer is whether the classic
endpoint is served on this deployment, whether the six fields a create sends are
stored as sent, whether an update may omit the fields only a create requires, and
whether a change to the position is held and read back as the reorder it claims
to be.

A rule is a security control, so the suite removes what it creates before each
test and after it, and a run that dies part-way leaves nothing behind. Every rule
here accepts rather than drops, so a leftover misconfiguration cannot break the
stack it is measured against. The module runs through a stand-in for
``AnsibleModule``, so the argument spec, the check mode handling and the
reporting are under test rather than assumed.

What only the controller can answer about the references is whether a name
resolution reaches the object it means: a network named on a side, and a firewall
group named on a side, are resolved against the collection that holds them.

It writes, and it removes what it creates.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_rule
from tests.live.cleanup import find_named
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

#: Names created here, so a run that failed before it recorded one leaves a rule
#: this suite recognises and removes rather than one that accumulates.
OWNED = "verify-fw-"

#: The positions this suite uses. The controller stores rule_index exactly as
#: sent and does not renumber the rules around it, so the pair must not collide
#: with a rule another suite in the run owns. The schema admits 2000-29999 and
#: 40000-49999, and these sit near the top of the first range.
RULE_INDEX = 22900
OTHER_RULE_INDEX = 22910

#: The two rulesets the suite uses. They are separate chains, so a name repeated
#: across them is two rules and not a collision.
RULESET = "LAN_IN"
OTHER_RULESET = "WAN_IN"

NAME = f"{OWNED}accept"
OTHER_NAME = f"{OWNED}other"

#: Written out rather than imported from the module, so a module addressing a
#: different path fails to read back what it wrote instead of quietly agreeing
#: with this file.
FIREWALL_RULES = "/rest/firewallrule"

#: Where a network or a firewall group named on a side is resolved. A group is a
#: resource of its own, so a test that needs one creates it and removes it.
NETWORKS = "/rest/networkconf"
FIREWALL_GROUPS = "/rest/firewallgroup"

#: The site's own default network, which is always present, so a network name
#: reference can be exercised without creating one. The name is the console's.
DEFAULT_NETWORK = "Default"

#: A firewall group a rule can name. The site holds none, and a group is a
#: resource of its own, so the name reference can only be exercised against one
#: this suite makes. The prefix is distinct from the port forward suite's groups.
GROUP_NAME = "verify-fw-group"


def _task(**overrides: Any) -> dict[str, Any]:
    task = connection(
        name=NAME,
        ruleset=RULESET,
        rule_index=RULE_INDEX,
        action="accept",
        protocol="all",
        enabled=True,
    )
    task.update(overrides)
    return task


@pytest.fixture(autouse=True)
def _remove_everything(controller: Any) -> Any:
    remove_by_prefix(controller, FIREWALL_RULES, prefix=OWNED)
    yield
    remove_by_prefix(controller, FIREWALL_RULES, prefix=OWNED)


@pytest.fixture(scope="module")
def firewall_group(controller: Any) -> Any:
    """A firewall group for a rule to name, created and removed here.

    The site holds none, and a group is a resource of its own, so the name
    reference can only be exercised against one this suite makes. The group is
    removed on the way out whatever the run did in between.
    """
    remove_by_prefix(controller, FIREWALL_GROUPS, prefix=GROUP_NAME)
    controller.post(
        FIREWALL_GROUPS,
        {"name": GROUP_NAME, "group_type": "address-group", "group_members": ["10.0.0.0/8"]},
    )
    yield find_named(controller, FIREWALL_GROUPS, name=GROUP_NAME)
    remove_by_prefix(controller, FIREWALL_GROUPS, prefix=GROUP_NAME)


def _held(controller: Any) -> list[dict[str, Any]]:
    return [
        row for row in rows(controller.get(FIREWALL_RULES)) if OWNED in str(row.get("name", ""))
    ]


def test_the_site_serves_the_classic_firewall_rule_collection(controller: Any) -> None:
    # The module reads and writes the classic engine rather than the zone-based
    # surface, and only the controller can say whether this deployment serves it.
    body = controller.get(FIREWALL_RULES)

    assert "meta" in body, body
    assert isinstance(body.get("data"), list), body


def test_a_task_creates_the_rule_and_a_second_run_does_not() -> None:
    first = call(unifi_firewall_rule, _task())
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_firewall_rule, _task())
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_six_required_fields_reach_the_controller_as_sent() -> None:
    created = call(unifi_firewall_rule, _task())
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    # The controller refuses a document missing any of these, and the module
    # always sends all six. If it stored one as anything other than the value
    # sent, a run that sends it and one that did not would differ on every pass.
    assert obj["name"] == NAME
    assert obj["ruleset"] == RULESET
    assert obj["rule_index"] == RULE_INDEX
    assert obj["action"] == "accept"
    assert obj["protocol"] == "all"
    assert obj["enabled"] is True


def test_the_optional_fields_reach_the_controller_under_their_own_names() -> None:
    created = call(
        unifi_firewall_rule,
        _task(protocol="tcp", logging=True, dst_address="192.0.2.10", dst_port="443"),
    )
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    assert obj["logging"] is True
    assert obj["dst_address"] == "192.0.2.10"
    assert obj["dst_port"] == "443"


def test_an_update_may_omit_a_create_field_and_keeps_the_controllers_value() -> None:
    # The four fields the controller requires of a new rule are optional on an
    # update: the reconciler merges the task into the document it read, so a run
    # that only meant to change the logging flag leaves the protocol and enabled
    # the controller already holds in place.
    created = call(unifi_firewall_rule, _task(protocol="tcp", enabled=False))
    assert not created.get("failed"), created.get("msg")
    assert created["obj"]["protocol"] == "tcp"
    assert created["obj"]["enabled"] is False

    updated = call(unifi_firewall_rule, _task(protocol=None, enabled=None, logging=True))
    assert not updated.get("failed"), updated.get("msg")
    assert updated["changed"] is True, updated
    assert updated["obj"]["protocol"] == "tcp"
    assert updated["obj"]["enabled"] is False


def test_a_create_without_a_create_field_is_refused_before_a_write(controller: Any) -> None:
    # A present task naming no rule yet must state what the controller requires of
    # a new one. The refusal names the option and reaches no write, so the site is
    # not left with a rule the controller filled in for itself.
    result = call(unifi_firewall_rule, _task(protocol=None))

    assert result.get("failed") is True, result
    assert "protocol" in str(result.get("msg", ""))
    assert _held(controller) == []


def test_changing_the_rule_index_is_held_as_a_reorder() -> None:
    first = call(unifi_firewall_rule, _task())
    assert not first.get("failed"), first.get("msg")

    moved = call(unifi_firewall_rule, _task(rule_index=OTHER_RULE_INDEX))
    assert not moved.get("failed"), moved.get("msg")
    assert moved["changed"] is True, moved
    assert moved["obj"]["rule_index"] == OTHER_RULE_INDEX

    settled = call(unifi_firewall_rule, _task(rule_index=OTHER_RULE_INDEX))
    assert settled["changed"] is False, settled.get("changed_fields")


def test_two_rules_sharing_a_name_in_different_rulesets_are_distinct(controller: Any) -> None:
    # The console keys a rule by its name within a ruleset, so the same name in
    # two rulesets is two rules. A module selecting on the name alone would aim a
    # write or a removal at one of two.
    call(unifi_firewall_rule, _task())
    call(unifi_firewall_rule, _task(ruleset=OTHER_RULESET, rule_index=OTHER_RULE_INDEX))

    assert len(_held(controller)) == 2

    removed = call(unifi_firewall_rule, _task(state="absent"))
    assert removed["changed"] is True

    remaining = [str(row["ruleset"]) for row in _held(controller)]
    assert remaining == [OTHER_RULESET], remaining


def test_absent_removes_and_a_second_run_reports_no_change() -> None:
    call(unifi_firewall_rule, _task())
    removed = call(unifi_firewall_rule, _task(state="absent"))
    assert removed["changed"] is True

    again = call(unifi_firewall_rule, _task(state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_absent_actually_stops_the_site_listing_the_rule(controller: Any) -> None:
    call(unifi_firewall_rule, _task())
    call(unifi_firewall_rule, _task(state="absent"))

    # A delete answered with a success status is not proof the controller stopped
    # listing the object, and a rule left listed still governs traffic.
    assert _held(controller) == []


def test_check_mode_reports_the_change_without_creating() -> None:
    reported = call(unifi_firewall_rule, _task(_ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME

    # Check mode that wrote leaves nothing for the next run to find.
    afterwards = call(unifi_firewall_rule, _task())
    assert afterwards["changed"] is True, "check mode appears to have created the rule"


def test_an_action_outside_the_controllers_values_is_refused() -> None:
    # `choices` is the framework's constraint, so the real AnsibleModule refuses
    # this at argument validation and names the option. The live stand-in enforces
    # the constraint too, but by raising rather than by calling fail_json, so the
    # refusal arrives as an exception here. Both are refusals before any request,
    # which is the property under test; what differs is only how the stand-in
    # reports it.
    with pytest.raises(ValueError, match="action"):
        call(unifi_firewall_rule, _task(action="permit"))


def test_a_credential_is_never_echoed_in_a_failure() -> None:
    # The key is the credential the run authenticates with, so it is the one the
    # result may not carry. A password beside a key is refused by the spec before
    # the module runs.
    result = call(
        unifi_firewall_rule,
        _task(
            controller="127.0.0.1:1",
            api_key="a-secret-not-to-appear",
        ),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True


def test_a_network_named_in_the_task_reaches_the_network_it_means(controller: Any) -> None:
    # The point of the name reference: a play that knows the network's name and
    # not its ObjectId still matches the right network, and a named network is a
    # network, so the controller is told the reference is NETv4.
    network = find_named(controller, NETWORKS, name=DEFAULT_NETWORK)
    task = _task(src_network=DEFAULT_NETWORK)

    first = call(unifi_firewall_rule, task)
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_firewall_rule, task)
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")
    assert second["obj"]["src_networkconf_id"] == network["_id"]
    assert second["obj"]["src_networkconf_type"] == "NETv4"


def test_a_network_named_both_ways_is_refused(controller: Any) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    network = find_named(controller, NETWORKS, name=DEFAULT_NETWORK)

    with pytest.raises(ValueError, match="src_network"):
        call(
            unifi_firewall_rule,
            _task(src_network=DEFAULT_NETWORK, src_network_id=network["_id"]),
        )


def test_a_network_name_the_controller_does_not_hold_is_refused() -> None:
    result = call(unifi_firewall_rule, _task(src_network="verify-no-such-network"))

    assert result.get("failed") is True
    assert "verify-no-such-network" in str(result.get("msg", ""))


def test_a_firewall_group_named_in_the_task_reaches_the_group_it_means(
    firewall_group: dict[str, Any],
) -> None:
    # The controller holds groups in a list, so a single named group becomes the
    # one-element list the field expects, and a second run finds it already there.
    task = _task(src_firewall_group=GROUP_NAME)

    first = call(unifi_firewall_rule, task)
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_firewall_rule, task)
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")
    assert second["obj"]["src_firewallgroup_ids"] == [firewall_group["_id"]]


def test_a_firewall_group_named_both_ways_is_refused(firewall_group: dict[str, Any]) -> None:
    # The pair is declared mutually exclusive, so the framework refuses it before
    # the module runs, exactly as a playbook would.
    with pytest.raises(ValueError, match="src_firewall_group"):
        call(
            unifi_firewall_rule,
            _task(src_firewall_group=GROUP_NAME, src_firewall_group_ids=[firewall_group["_id"]]),
        )
