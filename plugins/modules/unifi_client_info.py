#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_client_info
short_description: List the clients and stations on a UniFi controller
version_added: 1.0.0
description:
  - Reads the controller's client registry and its list of currently connected
    stations, and returns them as two separate lists.
  - The two lists are not merged. A client can be connected without a registry
    record, and a registry record can exist for a client that is not connected,
    so a merged list would have to invent a de-duplication key the controller
    does not provide.
  - Each list is a projection of the controller's own rows rather than the rows
    themselves. A field this module does not declare is not returned.
  - Read-only. It reports C(changed) as false and writes nothing.
author:
  - Arun (@abn)
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - Clients are read from C(/rest/user), which is the registry a static DHCP
    reservation lives in.
  - Active stations are read from C(/stat/sta), which lists what the controller
    currently sees.
"""

EXAMPLES = r"""
- name: List the clients the controller holds and the stations it sees
  abn.unifi_network.unifi_client_info:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
  register: clients

- name: Show every reserved address
  ansible.builtin.debug:
    msg: "{{ clients.clients | selectattr('use_fixedip') | map(attribute='fixed_ip') | list }}"

- name: Show every station on the guest network
  ansible.builtin.debug:
    msg: "{{ clients.active | selectattr('network', 'equalto', 'Guest') | list }}"
"""

RETURN = r"""
clients:
  description:
    - Every client record the controller holds in the site, which is the registry
      a static DHCP reservation lives in.
    - Each entry is a projection of one row from C(/rest/user), and only the
      keys listed below are ever present.
    - The controller's own C(_id) is reported as C(id).
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: The controller's C(_id).
      type: str
    mac:
      description: The controller's C(mac), which is the record's identity.
      type: str
    name:
      description: The controller's C(name), which is the console's label for the
        client.
      type: str
    fixed_ip:
      description: The controller's C(fixed_ip), which is the reserved address.
      type: str
    use_fixedip:
      description: The controller's C(use_fixedip), which is whether the
        controller serves the reserved address. The field is tri-state, so a
        record that has never reserved an address reports C(null) rather than
        C(false).
      type: bool
    local_dns_record:
      description: The controller's C(local_dns_record), which is the name the
        site's local DNS server answers for the client.
      type: str
    local_dns_record_enabled:
      description: The controller's C(local_dns_record_enabled), which is whether
        the site's DNS server answers C(local_dns_record).
      type: bool
    network_id:
      description: The controller's C(network_id), which is the identifier of the
        network the reservation is held on.
      type: str
  sample:
    - id: 5f2b1c9e4d3a2b1c0d9e8f7a
      mac: de:ad:be:ef:00:01
      name: printer
      fixed_ip: 10.0.20.50
      use_fixedip: true
      local_dns_record: printer.example.invalid
      local_dns_record_enabled: true
      network_id: 6a3c2d8f4e5b6c7d8e9f0001
active:
  description:
    - Every station the controller currently sees on the network.
    - Each entry is a projection of one row from C(/stat/sta), and only the keys
      listed below are ever present.
  returned: always
  type: list
  elements: dict
  contains:
    mac:
      description: The controller's C(mac).
      type: str
    ip:
      description: The controller's C(ip).
      type: str
    hostname:
      description: The controller's C(hostname), which is the name the client
        announces.
      type: str
    network:
      description: The controller's C(network), which is the name of the network
        the station is on.
      type: str
  sample:
    - mac: de:ad:be:ef:00:01
      ip: 10.0.20.51
      hostname: printer
      network: IoT
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

#: The client registry, which is where a static reservation lives.
CLIENTS = "/rest/user"

#: The stations the controller currently sees, which is a different collection
#: from the registry and is not deduplicated against it.
ACTIVE = "/stat/sta"

#: The fields reported for a registry record, mapped onto the names they are
#: reported under. Declared here rather than in the shared field tables: those
#: map a task's options onto writable fields, and a read result is a projection
#: rather than a write.
CLIENT_FIELDS: dict[str, str] = {
    "_id": "id",
    "mac": "mac",
    "name": "name",
    "fixed_ip": "fixed_ip",
    "use_fixedip": "use_fixedip",
    "local_dns_record": "local_dns_record",
    "local_dns_record_enabled": "local_dns_record_enabled",
    "network_id": "network_id",
}

#: The fields reported for a currently connected station.
ACTIVE_FIELDS: dict[str, str] = {
    "mac": "mac",
    "ip": "ip",
    "hostname": "hostname",
    "network": "network",
}


def export(body: Any, fields: dict[str, str]) -> list[dict[str, Any]]:
    """Project the controller's rows onto one list of declared fields.

    A field the controller abstains from is absent from the projection rather
    than reported as null, so a caller can tell the two apart.
    """
    return [
        {name: row[field] for field, name in fields.items() if field in row} for row in rows(body)
    ]


def collect(client: Any) -> dict[str, list[dict[str, Any]]]:
    """Read both collections and project each into its own list."""
    return {
        "clients": export(client.get(CLIENTS), CLIENT_FIELDS),
        "active": export(client.get(ACTIVE), ACTIVE_FIELDS),
    }


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)
    module.exit_json(changed=False, **collect(client))


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
