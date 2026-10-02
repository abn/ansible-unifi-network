#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_port_override
short_description: Manage one port override on a UniFi device
version_added: 0.1.0
description:
  - Manages the override of a single port on a device the controller already
    holds, which is the per-port configuration that departs from the port's
    profile.
  - The override is not an object with its own endpoint. It is one element of the
    C(port_overrides) array on the device document, so this module reads the
    device, replaces the one element and writes the array back. Ports the task
    does not name are preserved.
  - A device is selected by O(mac) and the port by O(port_idx), because a port
    index is what the controller keys the override by and a device is what owns
    the array.
  - A port may take either a port profile, by reference, or its own settings
    named field by field. Naming both is refused, because a profile already
    names the networks the port carries and a field beside it leaves the
    controller two answers to one question.
author:
  - Arun (@abn)
options:
  mac:
    description:
      - The MAC address of the device the port belongs to.
      - Not settable. It selects the device whose override is managed.
    type: str
    required: true
  port_idx:
    description:
      - The index of the port on the device, as the controller numbers its port
        table.
      - Not settable. It selects the entry within C(port_overrides).
    type: int
    required: true
  state:
    description:
      - Whether the port override should exist.
      - C(absent) drops the entry for O(port_idx) and leaves every other port's
        entry alone.
    type: str
    choices: [present, absent]
    default: present
  name:
    description:
      - The name the console shows for the port.
      - A label rather than membership, so it may be given beside a profile.
    type: str
  port_profile:
    description:
      - The name of the port profile the port is set to, resolved to its
        identifier by the controller.
      - The same reference as O(port_profile_id) by name. Naming both is refused
        rather than resolved by picking one.
      - Mutually exclusive with every individual field below, because a profile
        already names the port's networks.
    type: str
  port_profile_id:
    description:
      - The identifier of the port profile the port is set to.
      - The same reference as O(port_profile) by identifier. Naming both is
        refused rather than resolved by picking one.
    type: str
  native_network:
    description:
      - The name of the network the port treats as native, resolved to its
        identifier by the controller.
      - The same reference as O(native_network_id) by name. Naming both is
        refused rather than resolved by picking one.
    type: str
  native_network_id:
    description:
      - The identifier of the network the port treats as native.
    type: str
  tagged_networks:
    description:
      - The names of the networks the port tags, resolved to their identifiers
        by the controller.
      - Names only, because a list of identifiers read out of the console is a
        list nothing checks.
    type: list
    elements: str
  excluded_networks:
    description:
      - The names of the networks the port excludes, resolved to their
        identifiers by the controller.
    type: list
    elements: str
  multicast_router_networks:
    description:
      - The names of the networks whose multicast is routed through this port,
        resolved to their identifiers by the controller.
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
        O(port_security_mac_address).
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
      - How long, in seconds, an authenticated session may be idle before it is
        re-authenticated.
    type: int
  mirror_port_idx:
    description:
      - The port whose traffic this port mirrors, when O(op_mode) is C(mirror).
    type: int
  aggregate_members:
    description:
      - The ports aggregated with this one, when O(op_mode) is C(aggregate).
    type: list
    elements: int
  stormctrl_type:
    description:
      - Whether the storm control thresholds below are a percentage of the link
        or a rate in packets per second.
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
  - Devices are read from C(/stat/device) and written to C(/rest/device). The
    write is the whole device document, because the override is one element of
    an array on it rather than a resource with its own path.
  - A port override and a port profile are alternatives. Setting a profile sets
    the port's networks as one object, and naming an individual field beside it
    is refused before anything is written.
  - Removing one port's override is what C(state=absent) does here. The
    C(unifi_device) module's C(port_overrides) list merges by port and does not
    offer removal.
  - The controller derives C(forward) from whether the port or its profile names
    a network, reading it back as C(all) when it names none and as C(customize)
    when it does. It is not a task option, because the controller overwrites any
    value that does not match what it derived; a task changes forward by changing
    the networks.
"""

EXAMPLES = r"""
- name: Give port 2 of a switch a port profile
  abn.unifi_network.unifi_port_override:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:02
    port_idx: 2
    name: Uplink
    port_profile: Trunk

- name: Tag two networks on port 3 instead of taking a profile
  abn.unifi_network.unifi_port_override:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:02
    port_idx: 3
    native_network: LAN
    tagged_networks:
      - IoT
      - Guest
    poe_mode: auto

- name: Drop the override from port 3 again
  abn.unifi_network.unifi_port_override:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: de:ad:be:ef:00:02
    port_idx: 3
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The device as the controller holds it after the change, with the port
      override in place or removed.
    - The run fails when the controller does not hold the device rather than
      reporting a result with this key absent.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    mac: de:ad:be:ef:00:02
    name: Switch
    port_overrides:
      - port_idx: 2
        name: Uplink
        portconf_id: 6a1c0d8e5b4a3c2b1d0e9f8a
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A port the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["port_overrides[port_idx=2].portconf_id"]
"""

from collections.abc import Mapping
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiNotFoundError,
)
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
    build_override_entry,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.ports import override_options
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import Outcome
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import apply
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select

#: The options this surface adds to one override entry, which the shared builder
#: also offers. O(port_idx) comes with them: the controller keys the entry by it,
#: so a task supplies it to select rather than to configure.
ARGUMENT_SPEC = connection_arguments(
    mac={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    **override_options(),
)

#: Where a device is read and written. The write is the whole document, because
#: the override is one element of an array on it.
INVENTORY = "/stat/device"
COLLECTION = "/rest/device"

#: The collections the references resolve against.
NETWORKS = "/rest/networkconf"
PROFILES = "/rest/portconf"

#: The field the device is matched on rather than its name, because a name is
#: settable and two adopted devices can carry one while a MAC address is what the
#: controller itself records the device by.
SELECTOR = "mac"

#: The field the reconciler merges, and the identity it merges by. Both are the
#: controller's own names rather than a task's.
EMBED_KEY = "port_overrides"
EMBED_IDENTITY = "port_idx"


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)
    mac = str(module.params["mac"])
    port_idx = int(module.params["port_idx"])

    if module.params["state"] == "absent":
        outcome = _remove(client, mac, port_idx, check_mode=module.check_mode)
    else:
        # A device is adopted hardware, so a task naming one the controller does
        # not hold is refused before a write rather than posted into being. The
        # document read here is handed to the reconciler as ``current``, so the
        # absent device cannot reach the create path and is not selected twice.
        current = _require_adopted(client, mac)
        entry = build_override_entry(client, module.params, collection=NETWORKS, profiles=PROFILES)
        outcome = apply(
            client,
            collection=COLLECTION,
            read=INVENTORY,
            wanted={},
            key=SELECTOR,
            name=mac,
            check_mode=module.check_mode,
            current=current,
            embed={EMBED_KEY: (EMBED_IDENTITY, [entry])},
        )
    module.exit_json(**outcome.as_result())


def _remove(client: UniFiClient, mac: str, port_idx: int, *, check_mode: bool) -> Outcome:
    """Drop one port's entry, leaving the others in place.

    The device is read once for existence and handed to the reconciler as the
    current document, so the reconciler does not read the device again before
    writing and the create path stays out of the ordinary run. ``apply`` still
    re-reads after the write, and a concurrency retry whose fresh read finds no
    device does take the create path. The removal goes through ``drop`` rather
    than a list computed here, so a retry recomputes it from the fresh document
    and does not write over an entry another writer added. No entry for the port
    is not a change, so a second removal reports none.
    """
    current = _require_adopted(client, mac)
    return apply(
        client,
        collection=COLLECTION,
        read=INVENTORY,
        wanted={},
        key=SELECTOR,
        name=mac,
        check_mode=check_mode,
        current=current,
        drop={EMBED_KEY: (EMBED_IDENTITY, [port_idx])},
    )


def _require_adopted(client: UniFiClient, mac: str) -> Mapping[str, Any]:
    """The device the controller holds under ``mac``, or a refusal naming it.

    A device is adopted hardware, so a task naming one the controller does not
    hold is refused rather than created. The refusal says so rather than only
    that the address was not found, which would read as a selector to correct.
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
            ("port_profile", "port_profile_id"),
            ("native_network", "native_network_id"),
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
