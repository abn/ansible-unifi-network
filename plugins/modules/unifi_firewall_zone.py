#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_firewall_zone
short_description: Manage a firewall zone on a UniFi controller
version_added: 1.0.0
description:
  - Manages a zone of the site's firewall, which is the group of networks between
    which the controller's policies are written.
  - A zone is a v2 Policy Engine resource rather than a legacy site-settings
    object, so it is served at its own path, outside C(rest/), and answers in a
    C(meta) and C(data) envelope.
  - The v2 zone resource is very small, and this module is thin because the
    controller's resource is. A task sets a name and the networks the zone holds,
    and the controller derives the rest, including the flag marking a system zone
    and the zone's own key. What the console shows about a zone beyond that is a
    field on a network or on a policy, and is managed by the module for that
    object.
  - Only the fields named by a task are compared. The controller fills in the rest
    of the object itself, and comparing them would report a change on every run
    against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The zone's name, which is how a task selects it and the only name a task
        can set.
      - The controller holds a zone under a key of its own, C(zone_key), which is
        the name the console displays. Nothing in the zone resource depends on it,
        so it is not managed here.
    type: str
    required: true
  state:
    description:
      - Whether the zone should exist.
      - C(absent) refuses to remove one of the controller's system zones, because
        the controller marks those undeletable.
    type: str
    choices: [present, absent]
    default: present
  network_ids:
    description:
      - The identifiers of the networks in the zone.
      - Order is not meaning, so a task may list them in any order.
    type: list
    elements: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - A network names the zone it belongs to with its own C(firewall_zone_id) option,
    and a policy names a zone as its source or as its destination, so a zone is
    usually created before the objects that reference it.
  - A zone that does not exist is answered with a success status and an empty list
    rather than with a refusal, so a create is what a first run performs and a
    second run has nothing to do.
  - The controller derives C(default_zone) and C(zone_key) itself and refuses a
    create that carries C(default_zone) with C(Unrecognized field), so neither is
    a task option. The system zones come back marked C(default_zone) and
    C(state=absent) refuses one rather than reporting a removal it will not
    perform.
"""

EXAMPLES = r"""
- name: A zone holding the IoT networks
  abn.unifi_network.unifi_firewall_zone:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT
    network_ids:
      - 5f2b1c9e4d3a2b1c0d9e8f7a

- name: Remove it again
  abn.unifi_network.unifi_firewall_zone:
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
    - The zone as the controller holds it after the change.
    - Absent when the task removed it. The controller answers with the fields it
      derived, such as C(default_zone) and C(zone_key), which the task did not
      set.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: IoT
    default_zone: false
    network_ids:
      - 5a1c0d9e8f7a4d3a2b1c0d9e
    zone_key: 5f2b1c9e4d3a2b1c0d9e8f7a
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["network_ids"]
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_ZONE
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

#: The options this resource manages, as a task names them. An option absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess. default_zone is absent because the controller derives it
#: and refuses a create that sends it.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    network_ids={"type": "list", "elements": "str"},
)

#: The v2 policy engine's zone collection, relative to the policy engine base the
#: client composes. The policy engine sits above the site and is addressed through
#: its own base rather than beneath the site's ``rest/`` base, so this module asks
#: the client for the policy engine base rather than climbing out of the site's
#: with dot segments.
COLLECTION = "/firewall/zone"


def run(module: AnsibleModule) -> None:
    client = build_client(module.params, base=POLICY_ENGINE)

    if module.params["state"] == "absent":
        module.exit_json(
            **_remove(client, COLLECTION, module.params["name"], check_mode=module.check_mode)
        )

    wanted = project(module.params, FIREWALL_ZONE)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _remove(
    client: UniFiClient, collection: str, name: str, *, check_mode: bool
) -> dict[str, object]:
    """Delete a zone, or report that it was already gone.

    A second run has to report no change, so an absent zone is not a change
    either. A system zone is marked undeletable by the controller, and removing one
    is refused the way the console refuses it rather than forced: the traffic the
    controller attributes to no other zone lands there.
    """
    for row in rows(client.get(collection)):
        if str(row.get("name", "")) != name:
            continue
        if row.get("attr_no_delete") or row.get("default_zone"):
            raise UniFiError(
                f"the zone {name!r} is one the controller will not remove; "
                "make another zone the default in the console if it is no longer wanted"
            )
        if not check_mode:
            client.delete(f"{collection}/{row['_id']}")
            if any(str(left.get("name", "")) == name for left in rows(client.get(collection))):
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
