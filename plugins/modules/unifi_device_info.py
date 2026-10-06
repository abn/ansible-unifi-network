#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_device_info
short_description: List the adopted devices on a UniFi controller
version_added: 1.0.0
description:
  - Reads every device the controller holds in the site, which is every device it
    has adopted.
  - The result is a projection of the controller's own rows rather than the rows
    themselves. A field this module does not declare is not returned, so the
    runtime and statistics a controller folds into a device document do not reach
    a play.
  - Read-only. It reports C(changed) as false and writes nothing.
author:
  - Arun (@abn)
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - Devices are read from C(/stat/device), which is the listing path. The write
    path C(/rest/device) answers 404 on a deployment that serves only the listing.
  - "A device document carries runtime fields such as C(version) that the write
    schema does not declare. They are read fields rather than writable ones, and
    this module returns them because the controller holds them."
"""

EXAMPLES = r"""
- name: List the site's devices
  abn.unifi_network.unifi_device_info:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
  register: devices

- name: Show every device whose firmware differs from the rest
  ansible.builtin.debug:
    msg: "{{ devices.resources | map(attribute='version') | unique | list }}"
"""

RETURN = r"""
resources:
  description:
    - Every device the controller holds in the site.
    - Each entry is a projection of one row from C(/stat/device), and only the
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
      description: The controller's C(mac).
      type: str
    name:
      description: The controller's C(name), which is the console's label for the
        device.
      type: str
    model:
      description: The controller's C(model).
      type: str
    type:
      description: The controller's C(type), which is the device family.
      type: str
    ip:
      description: The controller's C(ip), which is the last address the device
        was seen at.
      type: str
    version:
      description: The controller's C(version), which is the firmware the device
        is running.
      type: str
    state:
      description: The controller's C(state), which is its own view of the device.
      type: int
    adopted:
      description: The controller's C(adopted).
      type: bool
  sample:
    - id: 5f2b1c9e4d3a2b1c0d9e8f7a
      mac: de:ad:be:ef:00:01
      name: Reception AP
      model: U6Lite
      type: uap
      ip: 10.0.20.5
      version: 6.6.55.15138
      state: 1
      adopted: true
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

#: Where a site's devices are read from, which is a different path from the one
#: they are written to.
EXPORT = "/stat/device"

#: The controller fields this module reports, mapped onto the names it reports
#: them under. Declared here rather than in the shared field tables: those map a
#: task's options onto writable fields, and a read result is a projection rather
#: than a write.
FIELDS: dict[str, str] = {
    "_id": "id",
    "mac": "mac",
    "name": "name",
    "model": "model",
    "type": "type",
    "ip": "ip",
    "version": "version",
    "state": "state",
    "adopted": "adopted",
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
    """Read the device inventory and project it."""
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
