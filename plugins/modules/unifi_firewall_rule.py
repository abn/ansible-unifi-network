#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_firewall_rule
short_description: Manage a firewall rule on a UniFi controller
version_added: 0.1.0
description:
  - Manages a rule in the controller's classic firewall engine, addressed at
    C(/rest/firewallrule) beneath the site.
  - The classic engine is the path the console itself uses for these rules, and
    its delete genuinely removes a rule. The zone-based firewall is a separate
    engine with its own surface, and is not used here. On the deployment this
    collection is verified against, the zone-based surface refuses a zone on a
    console that has no zone-based firewall configured, so a module built on it
    could not create anything.
  - A network or a firewall group the rule matches on either side may be named
    or given by identifier. A name is resolved through the controller, which is
    the only thing that knows the identifier, and naming both is refused rather
    than resolved by picking one.
  - A rule has no identity of its own beyond its identifier. The console keys it
    by its name within a ruleset, and two rules may share a name across
    rulesets, so a task selects a rule by the pair C(ruleset) and C(name). An
    ambiguous pair, two rules in one ruleset sharing a name, is refused rather
    than resolved by picking one.
  - Only the fields named by a task are compared. The controller fills in the
    rest of the object itself, and comparing them would report a change on every
    run against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The rule's name, which selects it within O(ruleset).
      - Two rules in different rulesets may share a name, so the name alone does
        not identify a rule.
    type: str
    required: true
  state:
    description:
      - Whether the rule should exist.
      - C(absent) removes it from the controller rather than only disabling it.
    type: str
    choices: [present, absent]
    default: present
  ruleset:
    description:
      - The chain the rule belongs to, which is half of what identifies it.
      - The value is one of the controller's own ruleset names, and the choice
        list is read from the controller's validation rather than written here.
    type: str
    required: true
    choices:
      - WAN_IN
      - WAN_OUT
      - WAN_LOCAL
      - LAN_IN
      - LAN_OUT
      - LAN_LOCAL
      - GUEST_IN
      - GUEST_OUT
      - GUEST_LOCAL
      - WANv6_IN
      - WANv6_OUT
      - WANv6_LOCAL
      - LANv6_IN
      - LANv6_OUT
      - LANv6_LOCAL
      - GUESTv6_IN
      - GUESTv6_OUT
      - GUESTv6_LOCAL
  rule_index:
    description:
      - The rule's position within its ruleset.
      - The controller stores this exactly as sent and does not renumber the
        rules around it, so a change to it is a change to the order the rules are
        evaluated in, and is reconciled like any other field.
      - Required when creating a rule, because the controller refuses a document
        that omits it. Optional when updating a rule that already exists, whose
        own C(rule_index) the controller keeps when the option is not named.
    type: int
  action:
    description:
      - What the controller does with a packet the rule matches.
      - Required when creating a rule, because the controller refuses a document
        that omits it. Optional when updating a rule that already exists, whose
        own C(action) the controller keeps when the option is not named.
    type: str
    choices: [drop, reject, accept]
  protocol:
    description:
      - The IP protocol the rule matches.
      - Free-form rather than a choice list, because the controller describes the
        field as a pattern admitting protocol names and numbers, and a list
        written here would refuse values the controller accepts. Values such as
        C(all), C(tcp), C(udp) and C(tcp_udp) are accepted.
      - Required when creating a rule, because the controller refuses a document
        that omits it. Optional when updating a rule that already exists, whose
        own C(protocol) the controller keeps when the option is not named. It is
        not defaulted, so on an update an omitted protocol leaves the controller's
        own value in place rather than asserting C(all).
    type: str
  enabled:
    description:
      - Whether the controller applies the rule.
      - Required when creating a rule, because the controller refuses a document
        that omits it. Optional when updating a rule that already exists, whose
        own C(enabled) the controller keeps when the option is not named. It is
        not defaulted, so on an update an omitted value leaves the controller's
        own value in place rather than re-enabling a disabled rule. An explicit
        C(false) is a change, not an absence, and it leaves the rule in place
        without applying it.
    type: bool
  logging:
    description:
      - Whether the controller records the traffic the rule matches.
      - Also accepted as C(log_enabled), the spelling the port forward module
        uses for the same field.
    type: bool
    aliases: [log_enabled]
  src_address:
    description:
      - The source address the rule matches.
    type: str
  dst_address:
    description:
      - The destination address the rule matches.
    type: str
  src_port:
    description:
      - The source port the rule matches.
      - A string, because the controller holds it as one and accepts a range or a
        list as well as a single port.
    type: str
  dst_port:
    description:
      - The destination port the rule matches.
      - A string, for the same reason O(src_port) is.
    type: str
  src_network:
    description:
      - The name of the network the rule matches on the source side, resolved to
        its identifier by the controller.
      - A named network is a network, so naming it asserts
        O(src_network_type=NETv4), and an explicit C(ADDRv4) beside it is refused
        rather than silently overridden.
      - The same reference as O(src_network_id) by name. Naming both is refused
        rather than resolved by picking one.
    type: str
  src_network_id:
    description:
      - The identifier of the network the rule matches on the source side.
      - The controller refuses a network identifier without O(src_network_type),
        with C(api.err.FirewallRuleNetworkConfTypeRequired), so the two are
        required together.
    type: str
  src_network_type:
    description:
      - How the controller reads O(src_network_id), as an address or as a
        network.
      - The controller's values are C(ADDRv4) and C(NETv4), taken from its own
        validation.
    type: str
    choices:
      - ADDRv4
      - NETv4
  src_firewall_group:
    description:
      - The name of the firewall group the rule matches on the source side,
        resolved to its identifier by the controller.
      - Resolved against C(/rest/firewallgroup), the collection the group lives
        in. A group named this way becomes the one-element list the controller's
        field holds.
      - The same reference as O(src_firewall_group_ids) by name. Naming both is
        refused rather than resolved by picking one.
    type: str
  src_firewall_group_ids:
    description:
      - The identifiers of the firewall groups the rule matches on the source
        side.
      - A list, because a rule may name several groups on one side.
    type: list
    elements: str
  dst_network:
    description:
      - The name of the network the rule matches on the destination side,
        resolved to its identifier by the controller.
      - A named network is a network, so naming it asserts
        O(dst_network_type=NETv4), and an explicit C(ADDRv4) beside it is refused
        rather than silently overridden.
      - The same reference as O(dst_network_id) by name. Naming both is refused
        rather than resolved by picking one.
    type: str
  dst_network_id:
    description:
      - The identifier of the network the rule matches on the destination side.
      - The controller refuses a network identifier without O(dst_network_type),
        with C(api.err.FirewallRuleNetworkConfTypeRequired), so the two are
        required together.
    type: str
  dst_network_type:
    description:
      - How the controller reads O(dst_network_id), as an address or as a
        network.
      - The controller's values are C(ADDRv4) and C(NETv4), taken from its own
        validation.
    type: str
    choices:
      - ADDRv4
      - NETv4
  dst_firewall_group:
    description:
      - The name of the firewall group the rule matches on the destination side,
        resolved to its identifier by the controller.
      - Resolved against C(/rest/firewallgroup), the collection the group lives
        in. A group named this way becomes the one-element list the controller's
        field holds.
      - The same reference as O(dst_firewall_group_ids) by name. Naming both is
        refused rather than resolved by picking one.
    type: str
  dst_firewall_group_ids:
    description:
      - The identifiers of the firewall groups the rule matches on the
        destination side.
      - A list, because a rule may name several groups on one side.
    type: list
    elements: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - The controller requires O(name), O(ruleset), O(rule_index), O(action),
    O(protocol) and O(enabled) on a document that creates a rule. O(name) and
    O(ruleset) are required in every case because the pair is how a task selects
    the rule, including for C(absent). The other four are required only when the
    rule is created and are refused rather than defaulted.
  - The four are optional when updating a rule that already exists. The
    controller keeps each of them on a write that does not restate it, so an
    update that only meant to change an address leaves the protocol the console
    set in place and does not re-enable a disabled rule.
  - A removal names only O(name) and O(ruleset). O(rule_index), O(action),
    O(protocol) and O(enabled) are required only to create a rule and are
    ignored on C(absent).
  - O(src_network_id) and O(src_network_type) are required together, and so are
    O(dst_network_id) and O(dst_network_type). The controller refuses a network
    identifier without the type saying whether it names an address or a network,
    with C(api.err.FirewallRuleNetworkConfTypeRequired). A network named through
    O(src_network) or O(dst_network) resolves to a network and supplies
    C(NETv4) itself.
"""

EXAMPLES = r"""
- name: Accept a service on an internal network
  abn.unifi_network.unifi_firewall_rule:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Allow web to the database
    ruleset: LAN_IN
    rule_index: 2001
    action: accept
    protocol: tcp
    enabled: true
    dst_address: 10.0.20.10
    dst_port: "5432"
    logging: true

- name: Drop a range on the WAN side
  abn.unifi_network.unifi_firewall_rule:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Drop the scanner range
    ruleset: WAN_IN
    rule_index: 2002
    action: drop
    protocol: all
    enabled: true
    src_address: 192.0.2.0/24

- name: Remove the rule again
  abn.unifi_network.unifi_firewall_rule:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Allow web to the database
    ruleset: LAN_IN
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The rule as the controller holds it after the change.
    - Absent when the task removed it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: Allow web to the database
    ruleset: LAN_IN
    rule_index: 2001
    action: accept
    protocol: tcp
    enabled: true
    logging: true
    dst_address: 10.0.20.10
    dst_port: "5432"
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it, because the module sends only the fields a task states.
  returned: when changed
  type: list
  elements: str
  sample: ["action", "rule_index"]
"""

from collections.abc import Mapping
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_RULE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import build_client
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import (
    connection_arguments,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import (
    connection_mutually_exclusive,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import (
    connection_required_together,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import apply
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import reference
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import remove
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select_one

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
#:
#: The controller refuses a document missing any of name, ruleset, rule_index,
#: action, protocol or enabled. name and ruleset are required options because
#: they select the rule for a removal as well as a write; the rest are required
#: only when the rule does not exist, so an omitted create field is refused
#: rather than silently asserted on an update.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    ruleset={"type": "str", "required": True, "choices": list(ENUM_VALUES["FirewallRule.ruleset"])},
    rule_index={"type": "int"},
    action={"type": "str", "choices": list(ENUM_VALUES["FirewallRule.action"])},
    protocol={"type": "str"},
    enabled={"type": "bool"},
    logging={"type": "bool", "aliases": ["log_enabled"]},
    src_address={"type": "str"},
    dst_address={"type": "str"},
    src_port={"type": "str"},
    dst_port={"type": "str"},
    src_network={"type": "str"},
    src_network_id={"type": "str"},
    src_network_type={
        "type": "str",
        "choices": list(ENUM_VALUES["FirewallRule.src_networkconf_type"]),
    },
    src_firewall_group={"type": "str"},
    src_firewall_group_ids={"type": "list", "elements": "str"},
    dst_network={"type": "str"},
    dst_network_id={"type": "str"},
    dst_network_type={
        "type": "str",
        "choices": list(ENUM_VALUES["FirewallRule.dst_networkconf_type"]),
    },
    dst_firewall_group={"type": "str"},
    dst_firewall_group_ids={"type": "list", "elements": "str"},
)

#: The fields the controller refuses a document without when it creates a rule.
#: They are required only when the rule does not yet exist: an update may omit any
#: of them and the controller keeps the value it already holds. A removal selects
#: by ruleset and name and names none of them.
PRESENT_REQUIRED = ("rule_index", "action", "protocol", "enabled")

#: The reference pairs the controller refuses one of without the other. A network
#: identifier without the type saying whether it names an address or a network is
#: refused with ``api.err.FirewallRuleNetworkConfTypeRequired``, so a task stating
#: one must state the other.
REQUIRED_TOGETHER = (
    ("src_network_id", "src_network_type"),
    ("dst_network_id", "dst_network_type"),
)

#: The reference pairs that name one thing two ways. A side given both by name and
#: by identifier leaves the module two answers to one question, and it is refused
#: rather than resolved by precedence.
MUTUALLY_EXCLUSIVE = (
    ("src_network", "src_network_id"),
    ("dst_network", "dst_network_id"),
    ("src_firewall_group", "src_firewall_group_ids"),
    ("dst_firewall_group", "dst_firewall_group_ids"),
)

#: ``rest/firewallrule``, the classic engine on the site's own base. The selection
#: and the write both address it.
COLLECTION = "/rest/firewallrule"

#: ``rest/networkconf``, where a network named on either side is resolved to the
#: identifier the rule holds. Only the controller knows that identifier.
NETWORKS = "/rest/networkconf"

#: ``rest/firewallgroup``, where a firewall group named on either side is resolved
#: to the identifier the rule holds.
FIREWALL_GROUPS = "/rest/firewallgroup"


def selection(params: Mapping[str, object]) -> dict[str, object]:
    """The pair that identifies a rule on the controller.

    A name alone is not unique here: the console keys a rule by its name within a
    ruleset, and the same name may appear in several rulesets. The pair is what a
    task means, and the reconciler refuses a pair that matches more than one rule.
    """
    return {"ruleset": params["ruleset"], "name": params["name"]}


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)

    if module.params["state"] == "absent":
        outcome = remove(
            client,
            collection=COLLECTION,
            what="firewall rule",
            match=selection(module.params),
            check_mode=module.check_mode,
        )
        module.exit_json(**outcome.as_result())

    # Read once, so a create is told the four fields it must name and an update is
    # not asked for what the controller already holds. The document read here is
    # handed to the reconciler as ``current``, which keeps the create path out of
    # a run whose rule exists and stops the selection being read twice.
    current = select_one(client, COLLECTION, match=selection(module.params))
    _require_create_fields(module.params, current)
    wanted = project(module.params, FIREWALL_RULE)
    _attach_references(client, module.params, wanted)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        match=selection(module.params),
        current=current,
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _require_create_fields(params: Mapping[str, object], current: Mapping[str, Any] | None) -> None:
    """Refuse to create a rule without the fields the controller requires.

    The four are required only when the rule does not exist. An update may omit
    any of them and the controller keeps the value it already holds, because the
    reconciler merges the task's fields into the document it read.
    """
    if current is not None:
        return
    missing = [name for name in PRESENT_REQUIRED if params.get(name) is None]
    if not missing:
        return
    raise UniFiError(
        f"creating the firewall rule {params['name']!r} in ruleset "
        f"{params['ruleset']!r} requires {', '.join(missing)} to be named; the "
        "controller refuses a new rule without rule_index, action, protocol and "
        "enabled, and an update that omits one leaves the value the controller "
        "already holds in place"
    )


def _attach_references(client: Any, params: Mapping[str, Any], wanted: dict[str, Any]) -> None:
    """Resolve a named network or firewall group into the identifier the rule holds.

    A reference given as an identifier is already the field the controller holds,
    so only a name is resolved, and only a name makes the controller answer. A
    named network is a network, so its type is asserted as ``NETv4``; a type the
    task states beside it that disagrees is refused rather than silently
    overridden.
    """
    for side in ("src", "dst"):
        _attach_network(client, params, wanted, side=side)
        _attach_firewall_group(client, params, wanted, side=side)


def _attach_network(
    client: Any,
    params: Mapping[str, Any],
    wanted: dict[str, Any],
    *,
    side: str,
) -> None:
    """Resolve one side's network reference, name or identifier."""
    name = params.get(f"{side}_network")
    identifier = params.get(f"{side}_network_id")
    if not name and not identifier:
        return
    if name:
        declared = params.get(f"{side}_network_type")
        if declared and declared != "NETv4":
            raise UniFiError(
                f"{side}_network names a network, so its type is NETv4, but "
                f"{side}_network_type is {declared}; a network is not an address"
            )
    wanted[FIREWALL_RULE[f"{side}_network_id"]] = reference(
        client,
        NETWORKS,
        name=str(name or ""),
        identifier=str(identifier or ""),
        what="network",
    )
    if name:
        wanted[FIREWALL_RULE[f"{side}_network_type"]] = "NETv4"


def _attach_firewall_group(
    client: Any,
    params: Mapping[str, Any],
    wanted: dict[str, Any],
    *,
    side: str,
) -> None:
    """Resolve one side's firewall group named in the task into the plural field.

    The controller holds groups in a list even when a task names one, so a name
    becomes the one-element list the field expects.
    """
    name = params.get(f"{side}_firewall_group")
    if not name:
        return
    if params.get(f"{side}_firewall_group_ids"):
        raise UniFiError(
            f"{side}_firewall_group and {side}_firewall_group_ids both name a firewall "
            "group reference; a reference is one or the other, and a task stating both "
            "has two answers to one question"
        )
    wanted[FIREWALL_RULE[f"{side}_firewall_group_ids"]] = [
        reference(
            client,
            FIREWALL_GROUPS,
            name=str(name),
            what="firewall group",
        )
    ]


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=[
            *connection_required_together(),
            *REQUIRED_TOGETHER,
        ],
        mutually_exclusive=[
            *connection_mutually_exclusive(),
            *MUTUALLY_EXCLUSIVE,
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
