#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_port_profile
short_description: Manage a port profile on a UniFi controller
version_added: 1.0.0
description:
  - Manages a port profile, which is the switching configuration a switch port is
    set to rather than the configuration of a port itself.
  - A profile names the networks it carries by naming the native network and the
    tagged ones. The console holds that as a native network and a list of the
    networks the profile excludes, so a task says which networks it wants and the
    module computes the exclusion list from the site's networks.
  - Because the exclusion list is computed from everything the site holds, adding
    a network to the site changes what every profile that does not name it
    excludes. That is the console's own model rather than this module's choice.
  - Only the fields named by a task are compared. The controller fills in the rest
    of the object itself, and comparing them would report a change on every run
    against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The port profile's name, which is how a task selects it.
      - Must be unique within the site. Two profiles with one name make the one a
        task means ambiguous, and an ambiguous selector is refused rather than
        resolved by picking one.
    type: str
    required: true
  state:
    description:
      - Whether the port profile should exist.
    type: str
    choices: [present, absent]
    default: present
  native_network:
    description:
      - The name of the network the profile treats as native, resolved to its
        identifier by the controller.
      - The same reference as O(native_network_id) by name. One of the two is
        required when C(state=present), and naming both is refused rather than
        resolved by picking one.
    type: str
  native_network_id:
    description:
      - The identifier of the network the profile treats as native.
      - The same reference as O(native_network) by identifier. One of the two is
        required when C(state=present), and naming both is refused rather than
        resolved by picking one.
    type: str
  tagged_networks:
    description:
      - The names of the networks the profile tags, resolved to their identifiers
        by the controller.
      - Names only. A network is named here rather than given as an identifier,
        because a list of identifiers read out of the console is a list nothing
        checks.
      - Left unset, the profile tags no network, which excludes every network on
        the site apart from the native one.
    type: list
    elements: str
  tagged_vlan_mgmt:
    description:
      - How tagged VLAN management frames are handled on a port using the profile.
    type: str
    choices: [auto, block_all, custom]
  autoneg:
    description:
      - Whether the port negotiates its speed and duplex itself.
    type: bool
  poe_mode:
    description:
      - Whether the port supplies power to the device attached to it.
    type: str
    choices: [auto, "off"]
  op_mode:
    description:
      - Which operation the port profile describes.
    type: str
    choices: [switch]
  fec_mode:
    description:
      - Which forward error correction the port uses.
    type: str
    choices: [rs-fec, fc-fec, default, disabled]
  isolation:
    description:
      - Whether ports using the profile cannot reach each other.
    type: bool
  speed:
    description:
      - The link speed the port is fixed to, in Mbps.
    type: int
  full_duplex:
    description:
      - Whether the fixed link is full duplex rather than half.
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
    choices:
      - auto
      - force_authorized
      - force_unauthorized
      - mac_based
      - multi_host
  dot1x_idle_timeout:
    description:
      - How long, in seconds, an authenticated session may be idle before it is
        re-authenticated.
    type: int
  stormctrl_type:
    description:
      - Whether the storm control thresholds below are a percentage of the link or
        a rate in packets per second.
    type: str
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
  - The exclusion list is computed from every network the site holds, so a
    network added to the site later is excluded from a profile that does not name
    it, and a run after that addition reports a change while the site's set of
    networks has changed.
  - A task always writes the native network and the computed exclusion list,
    whatever else it names, because the two are what the profile's membership
    means.
  - The controller derives C(forward) from whether the profile names a network,
    reading it back as C(all) when it names none and as C(customize) when it does.
    It is not a task option, because the controller overwrites any value that does
    not match what it derived; a task changes forward by changing the networks.
"""

EXAMPLES = r"""
- name: An access profile for IoT devices
  abn.unifi_network.unifi_port_profile:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT access
    native_network: IoT
    tagged_networks:
      - Management
    poe_mode: auto
    isolation: true

- name: Remove it again
  abn.unifi_network.unifi_port_profile:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: IoT access
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The port profile as the controller holds it after the change.
    - Absent when the task removed it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: IoT access
    native_networkconf_id: 6a1c0d8e5b4a3c2b1d0e9f8a
    excluded_networkconf_ids: ["7b2d1e9f6c5b4a3d2e1f0a9b"]
    forward: customize
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["native_networkconf_id", "excluded_networkconf_ids"]
"""

from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_PROFILE
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    native_network={"type": "str"},
    native_network_id={"type": "str"},
    tagged_networks={"type": "list", "elements": "str"},
    tagged_vlan_mgmt={"type": "str", "choices": list(ENUM_VALUES["PortProfile.tagged_vlan_mgmt"])},
    autoneg={"type": "bool"},
    poe_mode={"type": "str", "choices": list(ENUM_VALUES["PortProfile.poe_mode"])},
    op_mode={"type": "str", "choices": list(ENUM_VALUES["PortProfile.op_mode"])},
    fec_mode={"type": "str", "choices": list(ENUM_VALUES["PortProfile.fec_mode"])},
    isolation={"type": "bool"},
    speed={"type": "int"},
    full_duplex={"type": "bool"},
    port_security_enabled={"type": "bool"},
    port_security_mac_address={"type": "list", "elements": "str"},
    dot1x_ctrl={"type": "str", "choices": list(ENUM_VALUES["PortProfile.dot1x_ctrl"])},
    dot1x_idle_timeout={"type": "int"},
    stormctrl_type={"type": "str"},
    stormctrl_bcast_enabled={"type": "bool"},
    stormctrl_bcast_level={"type": "int"},
    stormctrl_mcast_enabled={"type": "bool"},
    stormctrl_mcast_level={"type": "int"},
    stormctrl_ucast_enabled={"type": "bool"},
    stormctrl_ucast_level={"type": "int"},
    lldpmed_enabled={"type": "bool"},
    lldpmed_notify_enabled={"type": "bool"},
    egress_rate_limit_kbps_enabled={"type": "bool"},
    egress_rate_limit_kbps={"type": "int"},
)

#: ``rest/portconf``. A port profile is keyed by name on the legacy family, which
#: is the only family that can write one at all.
COLLECTION = "/rest/portconf"

#: The networks a profile names, and the set the exclusion list is computed from.
NETWORKS = "/rest/networkconf"

#: A present profile names a native network, by name or by identifier, because the
#: exclusion list is computed against it. The controller marks no network as the
#: site's default in a field this module can read, so there is nothing to fall
#: back to and one of the two is required when the profile is managed.
NATIVE_ONE_OF = ("native_network", "native_network_id")


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)

    if module.params["state"] == "absent":
        outcome = remove(
            client,
            collection=COLLECTION,
            name=module.params["name"],
            what="port profile",
            check_mode=module.check_mode,
        )
        module.exit_json(**outcome.as_result())

    wanted = _wanted(client, module.params)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _wanted(client: Any, params: dict[str, Any]) -> dict[str, Any]:
    """The document a task asks for, with the exclusion list computed.

    The site's networks are read once and every name is selected out of that one
    read, so the native network and the exclusion list are computed against the
    same set. Two reads could straddle a network being added and store a profile
    whose native network the exclusion list also names.
    """
    networks = client.get(NETWORKS)
    native = _native_id(params, networks)
    tagged = _tagged_ids(params, networks)

    wanted = project(params, PORT_PROFILE)
    wanted[PORT_PROFILE["native_network_id"]] = native
    wanted[PORT_PROFILE["excluded_network_ids"]] = _complement(networks, native, tagged)
    return wanted


def _native_id(params: dict[str, Any], networks: Any) -> str:
    """The identifier of the native network a task named."""
    name = str(params.get("native_network") or "")
    identifier = str(params.get("native_network_id") or "")
    if name and identifier:
        raise UniFiError(
            "the native network was given both as a name and as an identifier; a reference "
            "is one or the other, and a task stating both has two answers to one question"
        )
    if identifier:
        return identifier
    return _resolve(networks, name, what="network")


def _tagged_ids(params: dict[str, Any], networks: Any) -> list[str]:
    """The identifiers of the networks a task named as tagged."""
    return [
        _resolve(networks, str(name), what="network")
        for name in params.get("tagged_networks") or []
    ]


def _resolve(networks: Any, name: str, *, what: str) -> str:
    """The identifier of the one network a name refers to."""
    return str(select(networks, key="name", wanted=name, what=what)["_id"])


def _complement(networks: Any, native: str, tagged: list[str]) -> list[str]:
    """Every network on the site apart from the native one and the tagged ones."""
    every = [str(row["_id"]) for row in rows(networks) if row.get("_id")]
    excluded = set(every) - {native, *tagged}
    return sorted(excluded)


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        # One of the pair, not both: the fourth element makes the framework read
        # the requirement as "any of" rather than "all of".
        required_if=[("state", "present", NATIVE_ONE_OF, True)],
        mutually_exclusive=[
            *connection_mutually_exclusive(),
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
