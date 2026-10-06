#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_wlan
short_description: Manage a wireless network on a UniFi controller
version_added: 1.0.0
description:
  - Manages a wireless network, which the controller holds as a flat object where
    the security mode, the band and the passphrase sit beside each other rather
    than in a nested document, and validates each of them separately.
  - A wireless network rides on a network, which the controller holds as
    C(networkconf_id) and a task names with O(network_id). It cannot exist without
    one, and the network it names is the one that carries the addressing.
  - Only the fields named by a task are compared. The controller fills in the rest
    of the object itself, and comparing them would report a change on every run
    against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The wireless network's name, which is how a task selects it.
      - Must be unique within the site. Two wireless networks with one name make
        the one a task means ambiguous, and an ambiguous selector is refused
        rather than resolved by picking one.
    type: str
    required: true
  state:
    description:
      - Whether the wireless network should exist.
    type: str
    choices: [present, absent]
    default: present
  enabled:
    description:
      - Whether the wireless network is broadcast.
      - An explicit C(false) is a change, not an absence. Clients already
        associated keep their session until they roam or the association expires,
        so this hides the network rather than disconnecting anybody.
    type: bool
  network:
    description:
      - The name of the network this wireless network rides on, resolved to its
        identifier by the controller.
      - The same reference as O(network_id) by name. Naming both is refused rather
        than resolved by picking one.
      - Left unset, the controller attaches the wireless network to the network
        it regards as the default, which is rarely the one intended.
    type: str
  network_id:
    description:
      - The identifier of the network this wireless network rides on.
      - The same reference as O(network) by identifier. Naming both is refused
        rather than resolved by picking one.
      - Left unset, the controller attaches the wireless network to the network
        it regards as the default, which is rarely the one intended.
    type: str
  vlan:
    description:
      - The VLAN identifier the wireless network tags its traffic with.
      - Only meaningful with O(vlan_enabled=true), and it has to be one the
        network named by O(network_id) admits, because the network carries the
        addressing and the wireless network carries the tag.
    type: int
  vlan_enabled:
    description:
      - Whether the traffic is tagged rather than untagged.
    type: bool
  band:
    description:
      - Which radio bands the network is broadcast on.
      - C(both) is one wireless network answering on two bands rather than two
        networks, so a client roams between them itself.
    type: str
    choices: [2g, 5g, both]
  security:
    description:
      - The security mode the network is broadcast with.
      - Every mode other than C(open) and C(osen) requires O(passphrase) on this
        module, which includes C(wpaeap) even though that mode authenticates
        against a RADIUS profile rather than with the passphrase.
    type: str
    choices: [open, wpapsk, wep, wpaeap, osen]
  wpa_mode:
    description:
      - Which generation of WPA the network offers.
    type: str
    choices: [auto, wpa1, wpa2]
  wpa_enc:
    description:
      - Which cipher the network offers.
    type: str
    choices: [auto, ccmp, gcmp, ccmp-256, gcmp-256]
  passphrase:
    description:
      - The shared secret clients authenticate with.
      - Between 8 and 255 characters, which is what the controller accepts.
      - Never reported. Neither the value a task passes nor the copy the
        controller stores appears in a result.
    type: str
  pmf_mode:
    description:
      - How strongly protected management frames are required.
    type: str
    choices: [disabled, optional, required]
  pmf_cipher:
    description:
      - Which cipher protected management frames use.
    type: str
    choices: [auto, aes-128-cmac, bip-gmac-256]
  priority:
    description:
      - How a client chooses between this network and others it can see.
      - A client picks the highest priority it can use, so this is how a
        preferred network is named over one that is merely available.
    type: str
    choices: [medium, high, low]
  hide_ssid:
    description:
      - Whether the network's name is withheld from a passive scan.
    type: bool
  is_guest:
    description:
      - Whether clients are treated as guests, which is what confines them to the
        internet and to each other.
      - Distinct from O(l2_isolation), which confines clients to each other.
    type: bool
  l2_isolation:
    description:
      - Whether clients on this network cannot reach each other.
    type: bool
  mac_filter_enabled:
    description:
      - Whether the client list below is enforced.
      - An explicit C(false) is a change, not an absence, and it leaves the list
        on the object for the next task that enables the filter.
    type: bool
  mac_filter_list:
    description:
      - The hardware addresses the filter admits or refuses.
      - Only meaningful with O(mac_filter_enabled=true).
    type: list
    elements: str
  mac_filter_policy:
    description:
      - Whether the addresses in O(mac_filter_list) are admitted or refused.
      - C(allow) or C(deny), which is the controller's own wording.
    type: str
  uapsd_enabled:
    description:
      - Whether UPnP discovery is answered on this network.
    type: bool
  bss_transition:
    description:
      - Whether clients are steered towards the bands this network offers.
    type: bool
  wpa3_transition:
    description:
      - Whether WPA2 clients are moved to WPA3 when the network offers both.
    type: bool
  ap_groups:
    description:
      - The names of the access point groups that broadcast this network,
        resolved to their identifiers by the controller.
      - The same reference as O(ap_group_ids) by name. Naming both is refused
        rather than resolved by picking one.
      - Left unset, every group in the site does.
    type: list
    elements: str
  ap_group_ids:
    description:
      - The access point groups that broadcast this network, by identifier.
      - The same reference as O(ap_groups) by identifier. Naming both is refused
        rather than resolved by picking one.
      - Left unset, every group in the site does.
    type: list
    elements: str
  schedule_enabled:
    description:
      - Whether the schedule below is enforced.
    type: bool
  schedule:
    description:
      - When the network is broadcast, as C(day) or C(day-day|hhmm-hhmm) entries
        such as C(mon-fri|0800-1700), with a leading C(!) reversing the window.
      - Only meaningful with O(schedule_enabled=true).
    type: list
    elements: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - A wireless network whose security mode is anything other than C(open) or
    C(osen) is refused without a passphrase, and an empty passphrase is refused
    as well. The controller does not answer a write it refuses in a way this
    collection reads as a refusal, so a task that would create a network no
    client can join is stopped here instead.
  - Naming neither O(security) nor O(passphrase) sends neither, which leaves
    whatever the controller holds in place and, on creation, whatever it defaults
    to. That is how a wireless network is created without naming a mode at all.
  - A wireless network rides on a network, so the network named by O(network_id)
    has to exist. The network is usually the one created by the C(unifi_network)
    module, and it carries the addressing this module's O(vlan) tag rides on.
"""

EXAMPLES = r"""
- name: A personal wireless network for the office
  abn.unifi_network.unifi_wlan:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Office
    network_id: "{{ office_network_id }}"
    enabled: true
    band: both
    security: wpapsk
    wpa_mode: wpa2
    wpa_enc: ccmp
    passphrase: "{{ wlan_passphrase }}"
    hide_ssid: true
    priority: high

- name: Ride on a network the task names rather than one pasted by identifier
  abn.unifi_network.unifi_wlan:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Guest
    network: Guest
    enabled: true
    security: wpapsk
    passphrase: "{{ wlan_passphrase }}"

- name: Broadcast it on office hours only
  abn.unifi_network.unifi_wlan:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Office
    schedule_enabled: true
    schedule:
      - mon-fri|0800-1800

- name: Remove it again
  abn.unifi_network.unifi_wlan:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Office
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The wireless network as the controller holds it after the change.
    - Absent when the task removed it.
    - The passphrase is never reported, because the controller holds it as
      C(x_passphrase) and the result omits it, whether or not the task restated it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: Office
    networkconf_id: 6a1c0d8e5b4a3c2b1d0e9f8a
    security: wpapsk
    wpa_mode: wpa2
    wpa_enc: ccmp
    wlan_band: both
    hide_ssid: true
    priority: high
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["wlan_band", "hide_ssid"]
"""

from collections.abc import Mapping
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import WLAN
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

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    enabled={"type": "bool"},
    network={"type": "str"},
    network_id={"type": "str"},
    vlan={"type": "int"},
    vlan_enabled={"type": "bool"},
    band={"type": "str", "choices": list(ENUM_VALUES["WLAN.wlan_band"])},
    security={"type": "str", "choices": list(ENUM_VALUES["WLAN.security"])},
    wpa_mode={"type": "str", "choices": list(ENUM_VALUES["WLAN.wpa_mode"])},
    wpa_enc={"type": "str", "choices": list(ENUM_VALUES["WLAN.wpa_enc"])},
    passphrase={"type": "str", "no_log": True},
    pmf_mode={"type": "str", "choices": list(ENUM_VALUES["WLAN.pmf_mode"])},
    pmf_cipher={"type": "str", "choices": list(ENUM_VALUES["WLAN.pmf_cipher"])},
    priority={"type": "str", "choices": list(ENUM_VALUES["WLAN.priority"])},
    hide_ssid={"type": "bool"},
    is_guest={"type": "bool"},
    l2_isolation={"type": "bool"},
    mac_filter_enabled={"type": "bool"},
    mac_filter_list={"type": "list", "elements": "str"},
    mac_filter_policy={"type": "str"},
    uapsd_enabled={"type": "bool"},
    bss_transition={"type": "bool"},
    wpa3_transition={"type": "bool"},
    ap_groups={"type": "list", "elements": "str"},
    ap_group_ids={"type": "list", "elements": "str"},
    schedule_enabled={"type": "bool"},
    schedule={"type": "list", "elements": "str"},
)

#: ``rest/wlanconf``. A wireless network is keyed by name on the legacy family,
#: which is the only family that can write one at all.
COLLECTION = "/rest/wlanconf"

#: The collection the network a wireless network rides on is named in.
NETWORKS = "/rest/networkconf"

#: The AP groups, which the policy engine serves rather than the site's own base.
#: A group is keyed by identifier, so a task naming one gives its name and the
#: controller supplies the identifier.
AP_GROUPS = "/apgroups"

#: The security modes the controller holds no passphrase for. A task naming any
#: other mode and no passphrase is refused.
OPEN_SECURITY = ("open", "osen")


def run(module: AnsibleModule) -> None:
    present = module.params["state"] != "absent"
    if present:
        # Ahead of the client rather than behind it, so a task that cannot be
        # applied never gets as far as sending a credential.
        _check_passphrase(module.params)

    client = build_client(module.params)

    if not present:
        outcome = remove(
            client,
            collection=COLLECTION,
            name=module.params["name"],
            what="wireless network",
            check_mode=module.check_mode,
            protect_default=True,
        )
        module.exit_json(**outcome.as_result())

    wanted = project(module.params, WLAN)
    _attach_references(client, module.params, wanted)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _attach_references(client: Any, params: Mapping[str, Any], wanted: dict[str, Any]) -> None:
    """Resolve the objects this wireless network refers to into their identifiers.

    Both references are optional and the controller has a default for each, so a
    task naming neither leaves the field absent rather than asking the controller
    to resolve an empty name.
    """
    if params.get("network") or params.get("network_id"):
        wanted["networkconf_id"] = reference(
            client,
            NETWORKS,
            name=str(params.get("network") or ""),
            identifier=str(params.get("network_id") or ""),
            what="network",
        )
    if params.get("ap_groups") or params.get("ap_group_ids"):
        wanted["ap_group_ids"] = _ap_group_ids(client, params)


def _ap_group_ids(client: Any, params: Mapping[str, Any]) -> list[str]:
    """The ObjectIds of the AP groups a task named, or the ones it spelled out.

    The group is addressed by identifier and the collection offers no way to name
    one, so a task that named a group has the controller resolve it rather than
    pasting an identifier only the controller can supply.

    Naming both is an error rather than a precedence rule, for the reason
    :func:`reference` gives: a task stating both has two answers to one question.
    """
    names = params.get("ap_groups")
    identifiers = list(params.get("ap_group_ids") or [])
    if names and identifiers:
        raise UniFiError(
            "the AP groups were given both as names and as identifiers; a reference is "
            "one or the other, and a task stating both has two answers to one question"
        )
    if not names:
        return identifiers
    engine = client.rebased()
    return [reference(engine, AP_GROUPS, name=str(name), what="AP group") for name in names]


def _check_passphrase(params: Mapping[str, Any]) -> None:
    """Refuse a security mode with no passphrase to go with it.

    The controller reports a refusal as an error code inside the payload, and
    nothing on the way back reads it, so a network left unusable by a refused
    write would be reported here as created. An empty passphrase is the same defect
    written differently: the field is sent, the network exists, and no client can
    join it.
    """
    security = params.get("security")
    passphrase = params.get("passphrase")
    if security is not None and security not in OPEN_SECURITY and not passphrase:
        raise UniFiError(
            f"a wireless network with security {security!r} needs a passphrase, "
            "which the controller accepts as 8 to 255 characters"
        )
    if passphrase is not None and not passphrase.strip():
        raise UniFiError("the passphrase is empty, which leaves the network no client can join")


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=[
            *connection_mutually_exclusive(),
            ("network", "network_id"),
            ("ap_groups", "ap_group_ids"),
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
