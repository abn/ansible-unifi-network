#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_network
short_description: Manage a network on a UniFi controller
version_added: 0.1.0
description:
  - Manages a network object, which is the root of most other configuration, since
    a wireless network, a port profile and a firewall policy all address networks
    by their identifier.
  - The controller holds DHCP settings inline on the network rather than as
    resources of their own, so they are options here rather than a separate
    module.
  - Only the fields named by a task are compared. The controller fills in the rest
    of the object itself, and comparing them would report a change on every run
    against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The network's name, which is how a task selects it.
      - Must be unique within the site. Two networks with one name make the one a
        task means ambiguous, and an ambiguous selector is refused rather than
        resolved by picking one.
    type: str
    required: true
  state:
    description:
      - Whether the network should exist.
    type: str
    choices: [present, absent]
    default: present
  purpose:
    description:
      - What the network is for, which decides which fields the controller uses.
    type: str
    choices: [corporate, guest, remote-user-vpn, site-vpn, vlan-only, vpn-client, wan]
  enabled:
    description:
      - Whether the network is enabled.
      - An explicit C(false) is a change, not an absence.
    type: bool
  network_group:
    description:
      - Which group the network belongs to.
    type: str
    choices: [LAN]
  vlan:
    description:
      - The VLAN identifier.
      - Required in practice. A network created without one is refused by the
        controller, which falls back to a VLAN already in use.
    type: int
  vlan_enabled:
    description:
      - Whether the VLAN is tagged.
    type: bool
  subnet:
    description:
      - The network's address range, in CIDR form.
    type: str
  domain_name:
    description:
      - The domain offered to clients by DHCP.
    type: str
  dhcp_enabled:
    description:
      - Whether the controller serves DHCP on this network.
    type: bool
  dhcp_start:
    description:
      - The first address in the pool.
    type: str
  dhcp_stop:
    description:
      - The last address in the pool.
    type: str
  dhcp_lease_time:
    description:
      - How long a lease is held, in seconds.
    type: int
  dhcp_dns_enabled:
    description:
      - Whether the controller hands out the addresses below as resolvers.
      - Set to C(true) implicitly when O(dhcp_dns) is named, and it is
        O(dhcp_dns_enabled=false) that stops the controller serving resolvers.
    type: bool
  dhcp_dns:
    description:
      - The resolvers the controller hands out, in order, as an alternative to
        the four scalar options below.
      - At most four addresses. The controller holds exactly four resolver slots,
        and the module writes all four whatever the length of the list, padding
        the unused slots with an empty string so a list shorter than a previous
        one clears the resolvers it dropped.
      - Naming it sets O(dhcp_dns_enabled=true) and is mutually exclusive with
        O(dhcp_dns_1) through O(dhcp_dns_4).
      - An empty list is refused. To stop the controller serving resolvers, set
        O(dhcp_dns_enabled=false) instead.
    type: list
    elements: str
    version_added: 0.1.0
  dhcp_dns_1:
    description:
      - The first resolver to hand out.
    type: str
  dhcp_dns_2:
    description:
      - The second resolver to hand out.
    type: str
  dhcp_dns_3:
    description:
      - The third resolver to hand out.
    type: str
  dhcp_dns_4:
    description:
      - The fourth resolver to hand out.
    type: str
  dhcp_gateway:
    description:
      - The gateway handed to clients.
    type: str
  dhcp_gateway_enabled:
    description:
      - Whether the gateway above is handed out.
    type: bool
  dhcp_guarding:
    description:
      - Whether the controller answers a request for an address outside the
        range above.
    type: bool
  igmp_snooping:
    description:
      - Whether multicast is tracked per port rather than flooded.
    type: bool
  firewall_zone_id:
    description:
      - The identifier of the firewall zone this network belongs to.
      - The zone-based firewall is not shipped and this collection offers no info
        module that exposes zone identifiers, so the option is effectively
        paste-only.
    type: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - The controller refuses a network whose address range does not contain the
    address it is given, so a subnet built from a VLAN identifier has to be a
    range that contains the addresses derived from it.
  - A wireless network, a port profile and a firewall policy all address a network
    by its identifier, so this module is usually the first of a set to run.
"""

EXAMPLES = r"""
- name: A network for IoT devices
  abn.unifi_network.unifi_network:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT
    purpose: corporate
    vlan: 20
    vlan_enabled: true
    subnet: 10.0.20.1/24
    dhcp_enabled: true
    dhcp_start: 10.0.20.100
    dhcp_stop: 10.0.20.200
    dhcp_lease_time: 86400

- name: Hand out two resolvers from a list
  abn.unifi_network.unifi_network:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT
    dhcp_dns:
      - 10.0.20.1
      - 1.1.1.1

- name: Remove it again
  abn.unifi_network.unifi_network:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The network as the controller holds it after the change.
    - Absent when the task removed it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: IoT
    purpose: corporate
    vlan: 20
    ip_subnet: 10.0.20.1/24
    dhcpd_enabled: true
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it, apart from C(dhcpd_dns_enabled) and the four C(dhcpd_dns_*)
      slots O(dhcp_dns) expands into and the module therefore always sends.
  returned: when changed
  type: list
  elements: str
  sample: ["vlan", "ip_subnet"]
"""

from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import NETWORK
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import remove

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    purpose={"type": "str", "choices": list(ENUM_VALUES["Network.purpose"])},
    enabled={"type": "bool"},
    network_group={"type": "str", "choices": list(ENUM_VALUES["Network.networkgroup"])},
    vlan={"type": "int"},
    vlan_enabled={"type": "bool"},
    subnet={"type": "str"},
    domain_name={"type": "str"},
    dhcp_enabled={"type": "bool"},
    dhcp_start={"type": "str"},
    dhcp_stop={"type": "str"},
    dhcp_lease_time={"type": "int"},
    dhcp_dns_enabled={"type": "bool"},
    dhcp_dns_1={"type": "str"},
    dhcp_dns_2={"type": "str"},
    dhcp_dns_3={"type": "str"},
    dhcp_dns_4={"type": "str"},
    dhcp_dns={"type": "list", "elements": "str"},
    dhcp_gateway={"type": "str"},
    dhcp_gateway_enabled={"type": "bool"},
    dhcp_guarding={"type": "bool"},
    igmp_snooping={"type": "bool"},
    firewall_zone_id={"type": "str"},
)

#: The collection reads and writes the legacy family only, so it says so at
#: argument validation rather than discovering it as a 403 on a network.
COLLECTION = "/rest/networkconf"


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)

    if module.params["state"] == "absent":
        outcome = remove(
            client,
            collection=COLLECTION,
            name=module.params["name"],
            what="network",
            check_mode=module.check_mode,
            protect_default=True,
        )
        module.exit_json(**outcome.as_result())

    _expand_dhcp_dns(module.params)
    wanted = project(module.params, NETWORK)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


#: The controller's four resolver slots, in the order a task's list fills them.
DHCP_DNS_SLOTS = ("dhcp_dns_1", "dhcp_dns_2", "dhcp_dns_3", "dhcp_dns_4")

#: O(dhcp_dns) and the four scalar slots are two spellings of one setting, so a
#: task naming both leaves the module two answers to which resolvers to serve,
#: and it is refused rather than resolved by precedence.
DNS_MUTUALLY_EXCLUSIVE = [("dhcp_dns", slot) for slot in DHCP_DNS_SLOTS]


def _expand_dhcp_dns(params: dict[str, Any]) -> None:
    """Turn the resolver list into the four scalar slots the controller holds.

    Every slot is written, so a list shorter than the one the controller held
    clears the resolvers it dropped. An unused slot is written as an empty
    string rather than left absent, because the controller stores an empty slot
    that way and a slot it has never been given stays absent, which would compare
    as a difference on every run.
    """
    resolvers = params.get("dhcp_dns")
    if resolvers is None:
        return

    if not resolvers:
        raise UniFiError(
            "dhcp_dns needs at least one resolver; set dhcp_dns_enabled to false to "
            "stop the controller serving resolvers"
        )
    if len(resolvers) > len(DHCP_DNS_SLOTS):
        raise UniFiError(
            f"dhcp_dns holds at most {len(DHCP_DNS_SLOTS)} resolvers, but the task named "
            f"{len(resolvers)}"
        )

    if params.get("dhcp_dns_enabled") is False:
        raise UniFiError(
            "dhcp_dns and dhcp_dns_enabled=false disagree; the list asks the "
            "controller to serve resolvers and the flag asks it not to, and a task "
            "stating both has two answers to one question"
        )

    params["dhcp_dns_enabled"] = True
    for index, slot in enumerate(DHCP_DNS_SLOTS):
        params[slot] = str(resolvers[index]) if index < len(resolvers) else ""


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=[*connection_mutually_exclusive(), *DNS_MUTUALLY_EXCLUSIVE],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
