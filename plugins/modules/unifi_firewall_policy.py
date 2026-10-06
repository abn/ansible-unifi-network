#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_firewall_policy
short_description: Manage a policy in the site's firewall
version_added: 1.0.0
description:
  - Manages one policy in the zone based firewall the controller evaluates, which
    is a newer surface than the site settings the rest of this collection manages
    and is reached at C(v2/api/site/{site}/firewall-policies) rather than beneath
    the site's C(rest/) base.
  - A policy is one rule in a chain, and the controller evaluates the chain in
    order from the first policy to the last.
  - Only the fields named by a task are compared. The controller fills in the rest
    of the policy itself, and comparing them would report a change on every run.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The policy's name, which is how a task selects it.
      - Must be unique within the site. Two policies with one name make the one a
        task means ambiguous, and an ambiguous selector is refused rather than
        resolved by picking one.
    type: str
    required: true
  state:
    description:
      - Whether the policy should exist.
    type: str
    choices: [present, absent]
    default: present
  action:
    description:
      - What the controller does with traffic the policy matches.
    type: str
    choices: [ALLOW, BLOCK, REJECT]
  protocol:
    description:
      - The IP protocol the policy matches.
    type: str
    choices: [all, tcp, udp, tcp_udp]
  index:
    description:
      - The policy's position in the chain, counting from one.
      - The controller assigns a position to a policy it creates, so this is
        optional and is not sent when a task does not name it. A newly created
        policy received C(10000).
      - Set it only where the position is the point, because a position shared with
        another policy leaves the order between the two to the controller.
    type: int
  enabled:
    description:
      - Whether the policy is evaluated.
      - An explicit C(false) is a change, not an absence.
    type: bool
  logging:
    description:
      - Whether the controller records the traffic the policy matches.
    type: bool
  ip_version:
    description:
      - Which IP version the policy matches.
    type: str
    choices: [BOTH, IPV4, IPV6]
  connection_state_type:
    description:
      - Whether the policy applies to a connection regardless of its state, or
        only to one the controller has already seen.
    type: str
    choices: [ALL, RESPOND_ONLY]
  source_zone_id:
    description:
      - The identifier of the zone traffic must come from.
    type: str
  source_match:
    description:
      - What in the source the policy matches on.
      - The controller's own values are C(ANY), C(DEVICE), C(IP), C(NETWORK),
        C(CLIENT), C(MAC) and C(WEB).
    type: str
  source_network_ids:
    description:
      - The identifiers of the networks traffic must come from.
    type: list
    elements: str
  source_port_list:
    description:
      - The port traffic must come from, which the controller holds as one number
        rather than as a list.
      - The collection's field table names the option for a list because the
        console offers a list, and a task wanting more than one port names the
        networks or the zone the ports belong to instead.
    type: int
  destination_zone_id:
    description:
      - The identifier of the zone traffic must reach.
    type: str
  destination_match:
    description:
      - What in the destination the policy matches on.
      - The controller's own values are C(ANY), C(DEVICE), C(IP), C(NETWORK),
        C(CLIENT), C(MAC) and C(WEB).
    type: str
  destination_network_ids:
    description:
      - The identifiers of the networks traffic must reach.
    type: list
    elements: str
  destination_port_list:
    description:
      - The port traffic must reach, which the controller holds as one number
        rather than as a list.
      - The collection's field table names the option for a list because the
        console offers a list, and a task wanting more than one port names the
        networks or the zone the ports belong to instead.
    type: int
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - The controller evaluates the chain in O(index) order, and it permits two
    policies to hold one index. Which of the two is evaluated first is then the
    controller's decision rather than the task's, and a change to either moves the
    traffic the other governs.
  - Nothing here renumbers a chain. A task that needs a position sets O(index) and
    owns the collision that a duplicate index is.
  - The source and the destination are one nested document on the controller, each
    of which may be absent. The options here are flat and the collection nests them,
    so a task names O(source_zone_id) rather than a structure.
  - The controller refuses a create that does not state C(create_allow_respond) as
    false, answering C(api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed).
    It is not a task option, and the module asserts it false on a create. An update
    does not name it and leaves the controller's own value in place, so creating a
    respond policy through this endpoint is not possible.
  - A create needs more than an update does. The controller requires C(action) and a
    zone on each side, which only the task can choose, plus a schedule and an
    address family it will not default. The module supplies an always-on schedule
    and the address family C(BOTH), and refuses a create that omits the action or a
    zone, naming the option. An update may omit all of them and keeps the value the
    controller holds.
"""

EXAMPLES = r"""
- name: A policy allowing the IoT zone to reach the internal zone
  abn.unifi_network.unifi_firewall_policy:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT to internal
    action: ALLOW
    protocol: all
    ip_version: BOTH
    connection_state_type: ALL
    enabled: true
    logging: false
    source_zone_id: "{{ iot_zone_id }}"
    destination_zone_id: "{{ internal_zone_id }}"

- name: Keep the servers apart, and say so in the log
  abn.unifi_network.unifi_firewall_policy:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: No servers to guests
    action: BLOCK
    protocol: tcp
    logging: true
    source_zone_id: "{{ server_zone_id }}"
    destination_zone_id: "{{ guest_zone_id }}"
    destination_port_list: 22

- name: Remove it again
  abn.unifi_network.unifi_firewall_policy:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: No servers to guests
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The policy as the controller holds it after the change.
    - Absent when the task removed it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: IoT to internal
    action: ALLOW
    protocol: all
    enabled: true
    source:
      zone_id: 5f2b1c9e4d3a2b1c0d9e8f7b
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it, so a change under a source or a destination is reported as
      C(source.zone_id) rather than as the whole nested document.
  returned: when changed
  type: list
  elements: str
  sample: ["action", "source.zone_id"]
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_POLICY
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import POLICY_ENGINE
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select_one

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    action={"type": "str", "choices": list(ENUM_VALUES["FirewallPolicy.action"])},
    protocol={"type": "str", "choices": list(ENUM_VALUES["FirewallPolicy.protocol"])},
    index={"type": "int"},
    enabled={"type": "bool"},
    logging={"type": "bool"},
    ip_version={"type": "str", "choices": list(ENUM_VALUES["FirewallPolicy.ip_version"])},
    connection_state_type={
        "type": "str",
        "choices": list(ENUM_VALUES["FirewallPolicy.connection_state_type"]),
    },
    source_zone_id={"type": "str"},
    source_match={"type": "str"},
    source_network_ids={"type": "list", "elements": "str"},
    source_port_list={"type": "int"},
    destination_zone_id={"type": "str"},
    destination_match={"type": "str"},
    destination_network_ids={"type": "list", "elements": "str"},
    destination_port_list={"type": "int"},
)

#: The policy chain, relative to the policy engine's base path. It is not beneath
#: the site's ``rest/`` base, so the client this module builds carries the policy
#: engine's base rather than the site's.
COLLECTION = "/firewall-policies"

#: The field the controller refuses a create without. A create must state it false,
#: with the controller answering ``api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed``
#: to a create that omits it or sends it true, so it is not a task option. The
#: module supplies it only on a create; an update carries the value the controller
#: already holds rather than forcing a flag the task never named.
CREATE_ALLOW_RESPOND = "create_allow_respond"

#: The schedule, which the controller requires on a create and refuses a document
#: without, answering ``NotNull.schedule``. A policy here has no option for it and
#: runs always, so the module supplies that mode on a create and leaves the field
#: alone on an update.
SCHEDULE = "schedule"
SCHEDULE_ALWAYS = {"mode": "ALWAYS"}

#: The address family, also required on a create. A policy that names none covers
#: both, which is what a console starts a rule as.
IP_VERSION = "ip_version"
IP_VERSION_BOTH = "BOTH"

#: The fields a create cannot omit and a task has to choose: the action and the
#: zone on each side. An update may omit any of them and keeps what the controller
#: holds, so the requirement is stated for a create only.
CREATE_REQUIRED = ("action", "source_zone_id", "destination_zone_id")


def _require_create_fields(params: dict) -> None:
    """Refuse a create that omits a field only a task can choose.

    The controller refuses a policy without an action or a zone on either side, and
    an update keeps what it holds, so the requirement is stated here rather than in
    the argument spec, which cannot tell a create from an update.
    """
    missing = [name for name in CREATE_REQUIRED if not params.get(name)]
    if missing:
        raise UniFiError(
            "creating a firewall policy needs "
            + ", ".join(missing)
            + "; an update may omit them and keeps what the controller holds"
        )


def run(module: AnsibleModule) -> None:
    client = build_client(module.params, base=POLICY_ENGINE)

    if module.params["state"] == "absent":
        module.exit_json(**_remove(client, module.params["name"], check_mode=module.check_mode))

    # Read once, so the create-only field is supplied only when the policy does not
    # exist. The document is handed to the reconciler as ``current``, which keeps
    # the read in one place.
    current = select_one(client, COLLECTION, name=module.params["name"])
    wanted = project(module.params, FIREWALL_POLICY)
    if current is None:
        _require_create_fields(module.params)
        wanted[CREATE_ALLOW_RESPOND] = False
        wanted[SCHEDULE] = dict(SCHEDULE_ALWAYS)
        wanted.setdefault(IP_VERSION, IP_VERSION_BOTH)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        current=current,
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _remove(client: UniFiClient, name: str, *, check_mode: bool) -> dict[str, object]:
    """Delete a policy, or report that it was already gone.

    A second run has to report no change, so an absent policy is not a change
    either. Removing a policy the controller holds as predefined is refused rather
    than forced, since that flag marks a policy the site shipped with rather than
    one a task created.
    """
    for row in rows(client.get(COLLECTION)):
        if str(row.get("name", "")) != name:
            continue
        if row.get("predefined") or row.get("attr_no_delete"):
            raise UniFiError(
                f"the policy {name!r} is one the controller holds as predefined; "
                "rename it in the console if it is no longer wanted"
            )
        if not check_mode:
            client.delete(f"{COLLECTION}/{row['_id']}")
            if any(str(left.get("name", "")) == name for left in rows(client.get(COLLECTION))):
                raise UniFiError(
                    f"the controller accepted the removal of {name!r} but still lists it"
                )
        return {"changed": True, "diff": {"before": row, "after": {}}, "obj": {}}
    return {"changed": False, "diff": {"before": {}, "after": {}}, "obj": {}}


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=connection_mutually_exclusive(),
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
