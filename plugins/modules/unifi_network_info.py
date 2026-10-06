#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_network_info
short_description: List the networks on a UniFi controller
version_added: 1.0.0
description:
  - Reads every network the controller holds in the site.
  - The result is a projection of the controller's own rows rather than the rows
    themselves. A field this module does not declare is not returned, so what the
    controller stores beyond this set does not reach a play.
  - Read-only. It reports C(changed) as false and writes nothing.
author:
  - Arun (@abn)
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - Networks are read from C(/rest/networkconf).
"""

EXAMPLES = r"""
- name: List the site's networks
  abn.unifi_network.unifi_network_info:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
  register: networks

- name: Show the one named IoT
  ansible.builtin.debug:
    msg: "{{ networks.resources | selectattr('name', 'equalto', 'IoT') | list }}"
"""

RETURN = r"""
resources:
  description:
    - Every network the controller holds in the site.
    - Each entry is a projection of one row from C(/rest/networkconf), and only
      the keys listed below are ever present.
    - The controller's own C(_id) is reported as C(id).
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: The controller's C(_id).
      type: str
    name:
      description: The controller's C(name).
      type: str
    purpose:
      description: The controller's C(purpose).
      type: str
    enabled:
      description: The controller's C(enabled).
      type: bool
    vlan:
      description: The controller's C(vlan).
      type: int
    vlan_enabled:
      description: The controller's C(vlan_enabled).
      type: bool
    subnet:
      description: The controller's C(ip_subnet).
      type: str
    domain_name:
      description: The controller's C(domain_name).
      type: str
    dhcp_enabled:
      description: The controller's C(dhcpd_enabled).
      type: bool
    dhcp_start:
      description: The controller's C(dhcpd_start).
      type: str
    dhcp_stop:
      description: The controller's C(dhcpd_stop).
      type: str
    dhcp_lease_time:
      description: The controller's C(dhcpd_leasetime).
      type: int
    dhcp_dns_enabled:
      description: The controller's C(dhcpd_dns_enabled).
      type: bool
    dhcp_dns_1:
      description: The controller's C(dhcpd_dns_1).
      type: str
    dhcp_dns_2:
      description: The controller's C(dhcpd_dns_2).
      type: str
    dhcp_dns_3:
      description: The controller's C(dhcpd_dns_3).
      type: str
    dhcp_dns_4:
      description: The controller's C(dhcpd_dns_4).
      type: str
    dhcp_gateway:
      description: The controller's C(dhcpd_gateway).
      type: str
  sample:
    - id: 5f2b1c9e4d3a2b1c0d9e8f7a
      name: IoT
      purpose: corporate
      enabled: true
      vlan: 20
      vlan_enabled: true
      subnet: 10.0.20.1/24
      domain_name: iot.example.invalid
      dhcp_enabled: true
      dhcp_start: 10.0.20.100
      dhcp_stop: 10.0.20.200
      dhcp_lease_time: 86400
      dhcp_dns_enabled: true
      dhcp_dns_1: 10.0.20.1
      dhcp_gateway: 10.0.20.1
"""

from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows

ARGUMENT_SPEC = connection_arguments()

#: Where a site's networks are read from.
EXPORT = "/rest/networkconf"

#: The controller fields this module reports, mapped onto the names it reports
#: them under. Declared here rather than in the shared field tables: those map a
#: task's options onto writable fields, and a read result is a projection rather
#: than a write.
FIELDS: dict[str, str] = {
    "_id": "id",
    "name": "name",
    "purpose": "purpose",
    "enabled": "enabled",
    "vlan": "vlan",
    "vlan_enabled": "vlan_enabled",
    "ip_subnet": "subnet",
    "domain_name": "domain_name",
    "dhcpd_enabled": "dhcp_enabled",
    "dhcpd_start": "dhcp_start",
    "dhcpd_stop": "dhcp_stop",
    "dhcpd_leasetime": "dhcp_lease_time",
    "dhcpd_dns_enabled": "dhcp_dns_enabled",
    "dhcpd_dns_1": "dhcp_dns_1",
    "dhcpd_dns_2": "dhcp_dns_2",
    "dhcpd_dns_3": "dhcp_dns_3",
    "dhcpd_dns_4": "dhcp_dns_4",
    "dhcpd_gateway": "dhcp_gateway",
}


def export(body: Any) -> list[dict[str, Any]]:
    """Project the controller's rows onto the fields this module declares.

    A field the controller abstains from is absent from the projection rather
    than reported as null, so a caller can tell the two apart.
    """
    return [
        {name: row[field] for field, name in FIELDS.items() if field in row} for row in rows(body)
    ]


def collect(client: Any) -> list[dict[str, Any]]:
    """Read the network collection and project it."""
    return export(client.get(EXPORT))


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)
    module.exit_json(changed=False, resources=collect(client))


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
