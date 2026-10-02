#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_device
short_description: Manage an adopted device on a UniFi controller
version_added: 0.1.0
description:
  - Manages the properties a task may set on a device the controller already holds,
    which are its name, whether it is enabled, its status LED, its outdoor mode,
    the network it is administered over, and the overrides of its ports.
  - A device is hardware rather than configuration. It reaches a site when the
    controller sees it on the network, so this module cannot create one, and a
    task naming a device that was never adopted fails with the reason rather than
    reporting a change.
  - A device is selected by O(mac) rather than by O(name). A name is settable
    here and two adopted devices can carry one, while the controller records the
    MAC address as the device's identity.
  - Only the fields named by a task are compared. The rest of a device document
    is its hardware, its runtime and its statistics, and comparing those would
    report a change on every run against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  mac:
    description:
      - The device's MAC address, which is how a task selects it.
      - Not settable. The controller records it when the device is adopted, so a
        task that sent one would be asking to change the identity of the
        hardware rather than its configuration.
    type: str
    required: true
  name:
    description:
      - The device's name, as the console displays it.
      - Not an identity. Two adopted devices can carry one name, and O(mac) is
        what tells them apart.
    type: str
  enabled:
    description:
      - Whether the controller manages the device.
      - The controller holds the opposite flag, C(disabled), so a task naming
        C(enabled=false) sets it and a task naming C(enabled=true) clears it.
      - A property of the device rather than a step in its lifecycle, so
        disabling one changes the device and leaves it on the site.
      - Omitted leaves the controller's own value in place, because the field is
        not sent unless the task names the option.
    type: bool
  led:
    description:
      - What the device's status LED does, overriding what the hardware does by
        itself.
      - A display setting rather than a security control. C(default) leaves the
        LED as the hardware was shipped.
    type: str
    choices: ["default", "on", "off"]
  led_colour:
    description:
      - The LED's colour, as C(#RGB) or C(#RRGGBB), which is the form the
        controller's own validation accepts.
    type: str
  led_brightness:
    description:
      - The LED's brightness, as a percentage from 0 to 100.
    type: int
  outdoor_mode:
    description:
      - Whether the device is told that it is outdoors, overriding what the site
        says.
      - C(default) leaves the decision to the site.
    type: str
    choices: ["default", "on", "off"]
  management_network:
    description:
      - The name of the network the device is administered over, resolved to its
        identifier by the controller.
      - The same reference as O(management_network_id) by name. Naming both is
        refused rather than resolved by picking one.
    type: str
  management_network_id:
    description:
      - The identifier of the network the device is administered over.
      - The identifier a network task reports as its C(_id), so a play passes the
        one value between them rather than a name.
      - The same reference as O(management_network) by identifier. Naming both is
        refused rather than resolved by picking one.
    type: str
  port_overrides:
    description:
      - The per-port overrides to set on the device, merged into the ports the
        controller already holds by port index.
      - A port the list does not name keeps its entry. Removing one port's
        override is C(unifi_port_override)'s job with C(state=absent), so an
        empty list is not a request to clear the device.
      - Each element takes a profile or its own fields, never both, and each
        O(port_overrides[].port_idx) appears once in the list.
      - The field names are the ones C(unifi_port_override) offers, so a task can
        move between managing one port and several without renaming anything.
    type: list
    elements: dict
    version_added: 0.1.0
    suboptions:
      port_idx:
        description:
          - The index of the port on the device, as the controller numbers its
            port table.
        type: int
        required: true
      name:
        description:
          - The name the console shows for the port.
        type: str
      port_profile:
        description:
          - The name of the port profile the port is set to, resolved to its
            identifier by the controller.
          - The same reference as O(port_overrides[].port_profile_id) by name.
            Naming both is refused.
          - Mutually exclusive with the individual fields below.
        type: str
      port_profile_id:
        description:
          - The identifier of the port profile the port is set to.
        type: str
      native_network:
        description:
          - The name of the network the port treats as native.
        type: str
      native_network_id:
        description:
          - The identifier of the network the port treats as native.
        type: str
      tagged_networks:
        description:
          - The names of the networks the port tags.
        type: list
        elements: str
      excluded_networks:
        description:
          - The names of the networks the port excludes.
        type: list
        elements: str
      multicast_router_networks:
        description:
          - The names of the networks whose multicast is routed through this port.
        type: list
        elements: str
      tagged_vlan_mgmt:
        description:
          - How tagged VLAN management frames are handled on the port.
        type: str
        choices: [auto, block_all, custom]
      op_mode:
        description:
          - Which operation the port override describes.
        type: str
        choices: [switch, mirror, aggregate]
      poe_mode:
        description:
          - Whether the port supplies power to the device attached to it.
        type: str
        choices: [auto, pasv24, passthrough, "off"]
      autoneg:
        description:
          - Whether the port negotiates its speed and duplex itself.
        type: bool
      fec_mode:
        description:
          - Which forward error correction the port uses.
        type: str
        choices: [rs-fec, fc-fec, default, disabled]
      isolation:
        description:
          - Whether the port cannot reach the other ports on the switch.
        type: bool
      speed:
        description:
          - The link speed the port is fixed to, in Mbps.
        type: int
      full_duplex:
        description:
          - Whether the fixed link is full duplex rather than half.
        type: bool
      flow_control_enabled:
        description:
          - Whether the port negotiates flow control.
        type: bool
      port_security_enabled:
        description:
          - Whether the port admits only the hardware addresses in
            O(port_overrides[].port_security_mac_address).
        type: bool
      port_security_mac_address:
        description:
          - The hardware addresses the port admits.
        type: list
        elements: str
      dot1x_ctrl:
        description:
          - How 802.1X authentication is enforced on the port.
        type: str
      dot1x_idle_timeout:
        description:
          - How long, in seconds, an authenticated session may be idle before it
            is re-authenticated.
        type: int
      mirror_port_idx:
        description:
          - The port whose traffic this port mirrors, when
            O(port_overrides[].op_mode) is C(mirror).
        type: int
      aggregate_members:
        description:
          - The ports aggregated with this one, when O(port_overrides[].op_mode)
            is C(aggregate).
        type: list
        elements: int
      stormctrl_type:
        description:
          - Whether the storm control thresholds below are a percentage of the
            link or a rate in packets per second.
        type: str
        choices: [level, rate]
      stormctrl_bcast_enabled:
        description:
          - Whether broadcast storm control is enforced.
        type: bool
      stormctrl_bcast_level:
        description:
          - The broadcast threshold as a percentage of the link.
        type: int
      stormctrl_mcast_enabled:
        description:
          - Whether multicast storm control is enforced.
        type: bool
      stormctrl_mcast_level:
        description:
          - The multicast threshold as a percentage of the link.
        type: int
      stormctrl_ucast_enabled:
        description:
          - Whether unknown unicast storm control is enforced.
        type: bool
      stormctrl_ucast_level:
        description:
          - The unknown unicast threshold as a percentage of the link.
        type: int
      lldpmed_enabled:
        description:
          - Whether LLDP-MED is advertised on the port.
        type: bool
      lldpmed_notify_enabled:
        description:
          - Whether a topology change is reported to the LLDP-MED controller.
        type: bool
      port_keepalive_enabled:
        description:
          - Whether the port sends keepalive frames.
        type: bool
      stp_port_mode:
        description:
          - Whether the port takes part in spanning tree.
        type: bool
      egress_rate_limit_kbps_enabled:
        description:
          - Whether the egress rate limit below is enforced.
        type: bool
      egress_rate_limit_kbps:
        description:
          - The egress rate limit, in kilobits per second.
        type: int
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - This module manages a device the controller already holds. It cannot create
    one and it cannot adopt one. Adoption is a command the controller issues
    against hardware on the network rather than a resource this API exposes, so a
    task naming a device that is not there fails and says which device and why,
    and nothing is written.
  - There is no C(state) option, because there is no lifecycle here for one to
    express. A device is either adopted or it is not, and both of those are
    decided by the controller rather than by a task.
  - Devices are read from C(/stat/device) and written to C(/rest/device). The two
    are different paths, and the vendored schema the collection checks its field
    names against declares only the read side, so the write follows the family's
    own convention that a writable object is addressed under C(/rest/<resource>).
    A deployment serving no such path answers 404 rather than writing somewhere
    else.
  - Removing a device from the controller is not offered here. The console forgets
    a device, and this API's equivalent is not exercised by any suite in this
    collection, so offering it would be a claim nothing here backs.
  - O(port_overrides) merges by port index, so a task that names one port leaves
    every other port's entry as the controller holds it. Removing one port's
    override is C(unifi_port_override)'s job with C(state=absent), which is the
    operation a merge cannot express.
  - The controller derives a port's C(forward) from whether the port or its
    profile names a network, reading it back as C(all) when it names none and as
    C(customize) when it does. It is not a suboption, because the controller
    overwrites any value that does not match what it derived; a task changes
    forward by changing the networks.
"""

EXAMPLES = r"""
- name: Give an access point a name and hold its LED off
  abn.unifi_network.unifi_device:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:01
    name: Reception AP
    # Quoted because YAML reads a bare off as a boolean, and the controller's
    # own value for this field is the string.
    led: "off"

- name: Put it back on the site's outdoor setting and re-enable it
  abn.unifi_network.unifi_device:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:01
    enabled: true
    outdoor_mode: default

- name: Set two ports on a switch, leaving the other six alone
  abn.unifi_network.unifi_device:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:02
    port_overrides:
      - port_idx: 2
        port_profile: Trunk
      - port_idx: 3
        native_network: LAN
        tagged_networks:
          - IoT
"""

RETURN = r"""
obj:
  description:
    - The device as the controller holds it after the change.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: Reception AP
    mac: de:ad:be:ef:00:01
    disabled: false
    led_override: "off"
    port_overrides:
      - port_idx: 2
        portconf_id: 6a1c0d8e5b4a3c2b1d0e9f8a
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["name", "led_override"]
"""

from collections.abc import Mapping
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiNotFoundError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import DEVICE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.ports import (
    build_override_entries,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.ports import override_options
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import apply
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import reference
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select

#: The options this resource manages, as a task names them. Anything absent from
#: the device table is not sent, so a field the collection does not know cannot
#: reach the controller as a guess. O(mac) is here and absent from that table:
#: the controller owns the field, and a task supplies it to select a device
#: rather than to configure one.
#:
#: O(port_overrides) is a list of keyed documents rather than a flat field, so it
#: is absent from the device table. The projection would carry the task's list as
#: a plain field, and the empty list would then be written as the whole field:
#: ``run`` supplies no embedded merge for an empty list, so the device's own
#: overrides would be cleared rather than left alone.
PORT_OVERRIDE_SUBOPTIONS: dict[str, Any] = override_options()

ARGUMENT_SPEC = connection_arguments(
    mac={"type": "str", "required": True},
    name={"type": "str"},
    enabled={"type": "bool"},
    led={"type": "str", "choices": list(ENUM_VALUES["Device.led_override"])},
    led_colour={"type": "str"},
    led_brightness={"type": "int"},
    outdoor_mode={"type": "str", "choices": list(ENUM_VALUES["Device.outdoor_mode_override"])},
    management_network={"type": "str"},
    management_network_id={"type": "str"},
    port_overrides={
        "type": "list",
        "elements": "dict",
        "options": PORT_OVERRIDE_SUBOPTIONS,
    },
)

#: Where a device is written, which the legacy family alone serves.
COLLECTION = "/rest/device"

#: Where a site's devices are read from, which is not the path they are written
#: to. The vendored schema declares this list and its per-object form, and
#: declares no write path for a device at all.
INVENTORY = "/stat/device"

#: The collection the device's management network is named in. The device holds
#: the network by identifier, so a task naming it gives a name and the controller
#: supplies the identifier.
NETWORKS = "/rest/networkconf"

#: The collection a port profile is named in, for the reference an override
#: element may carry.
PROFILES = "/rest/portconf"

#: The field a device is matched on rather than its name, because a name is
#: settable here and two adopted devices can carry one while a MAC address is
#: what the controller itself records the device by.
SELECTOR = "mac"

#: The field the reconciler merges, and the identity it merges by. Both are the
#: controller's own names rather than a task's.
EMBED_KEY = "port_overrides"
EMBED_IDENTITY = "port_idx"


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)
    mac = str(module.params["mac"])

    current = _require_adopted(client, mac)

    params = dict(module.params)
    _express_enabled(params)
    wanted = project(params, DEVICE)
    _attach_management_network(client, params, wanted)
    entries = build_override_entries(
        client,
        module.params.get("port_overrides") or [],
        collection=NETWORKS,
        profiles=PROFILES,
    )
    outcome = apply(
        client,
        collection=COLLECTION,
        read=INVENTORY,
        wanted=wanted,
        key=SELECTOR,
        name=mac,
        check_mode=module.check_mode,
        current=current,
        embed={EMBED_KEY: (EMBED_IDENTITY, entries)} if entries else None,
    )
    module.exit_json(**outcome.as_result())


def _express_enabled(params: dict[str, Any]) -> None:
    """Translate a task's ``enabled`` into the controller's ``disabled``.

    The controller holds the opposite flag, and a name-to-name table cannot
    express a negation, so the option is rewritten before the projection. A task
    that omits the option leaves ``disabled`` out of the projection, which leaves
    the controller's own value in place.
    """
    enabled = params.get("enabled")
    if enabled is None:
        return
    params["disabled"] = not enabled


def _attach_management_network(
    client: UniFiClient, params: dict[str, Any], wanted: dict[str, Any]
) -> None:
    """Resolve the named management network into the identifier the device holds.

    The reference is optional, so a task naming neither leaves the field absent
    rather than asking the controller to resolve an empty name.
    """
    if not (params.get("management_network") or params.get("management_network_id")):
        return
    wanted["mgmt_network_id"] = reference(
        client,
        NETWORKS,
        name=str(params.get("management_network") or ""),
        identifier=str(params.get("management_network_id") or ""),
        what="management network",
    )


def _require_adopted(client: UniFiClient, mac: str) -> Mapping[str, Any]:
    """The device the controller holds under ``mac``, or a refusal naming it.

    The reconciler posts an object it cannot find, which is what a network wants
    and what a device cannot have: nothing sent to the device endpoint brings
    hardware onto a site. Returning the document lets the caller hand it to the
    reconciler as ``current``, which skips the selection read and keeps the create
    path out of the ordinary run.
    """
    try:
        return select(rows(client.get(INVENTORY)), key=SELECTOR, wanted=mac, what="device")
    except UniFiNotFoundError:
        raise UniFiError(
            f"the controller holds no device with mac {mac!r}, and this module cannot "
            "create or adopt one: adoption is a command the controller issues against "
            "hardware on the network"
        ) from None


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=[
            *connection_mutually_exclusive(),
            ("management_network", "management_network_id"),
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
