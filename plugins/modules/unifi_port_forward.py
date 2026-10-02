#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_port_forward
short_description: Manage a port forward on a UniFi controller
version_added: 0.1.0
description:
  - Manages a port forward, which admits traffic arriving on a WAN interface and
    delivers it to an address and a port inside the site.
  - The two ends of a forward are separate options because the controller holds
    them separately. O(destination_port) is the port the outside world connects
    to, and O(forward_port) is the port on the internal host that answers.
  - A port forward is a security control, so a task that manages one owns it
    whole. The three options the controller requires on every document are
    always sent, whatever the task names, and a task that names none of them
    still asserts the defaults below.
  - Only the fields named by a task are compared, apart from those three. The
    controller fills in the rest of the object itself, and comparing them would
    report a change on every run against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  name:
    description:
      - The port forward's name, which is how a task selects it.
      - Must be unique within the site. Two port forwards with one name make the
        one a task means ambiguous, and an ambiguous selector is refused rather
        than resolved by picking one.
    type: str
    required: true
  state:
    description:
      - Whether the port forward should exist.
      - Removing one closes a path into the site that nothing else closes, so
        C(absent) removes it from the controller rather than only disabling it.
    type: str
    choices: [present, absent]
    default: present
  enabled:
    description:
      - Whether the controller delivers the traffic this forward admits.
      - Always sent, because the controller requires the field on every
        document. An explicit C(false) is a change, not an absence, and it stops
        the traffic without removing the forward.
    type: bool
    default: true
  log_enabled:
    description:
      - Whether the controller records the traffic this forward matches.
      - Always sent, because the controller requires the field on every
        document. An explicit C(false) is a change, not an absence.
      - Because it is always sent, a play that never names it turns logging off
        on a forward where the console had it on.
    type: bool
    default: false
  source_limiting_enabled:
    description:
      - Whether the forward admits only the sources named by
        O(source_limiting_type).
      - Always sent, because the controller requires the field on every
        document. An explicit C(false) is a change, not an absence, and it leaves
        O(source_limiting_type) on the object for the next task that enables the
        limit.
    type: bool
    default: false
  source_limiting_type:
    description:
      - What O(source) is read as when the limiting is enabled.
      - C(ip) reads O(source) as an address or a range, and C(firewall_group)
        reads it as the group named by O(source_firewall_group) or
        O(source_firewall_group_id).
      - Only meaningful with O(source_limiting_enabled=true).
    type: str
    choices: [ip, firewall_group]
  source_firewall_group:
    description:
      - The name of the firewall group O(source) names, when
        O(source_limiting_type=firewall_group), resolved to its identifier by the
        controller.
      - The same reference as O(source_firewall_group_id) by name. Naming both is
        refused rather than resolved by picking one.
      - Only meaningful with O(source_limiting_enabled=true).
    type: str
  source_firewall_group_id:
    description:
      - The identifier of the firewall group O(source) names, when
        O(source_limiting_type=firewall_group).
      - The same reference as O(source_firewall_group) by identifier. Naming both
        is refused rather than resolved by picking one.
      - Only meaningful with O(source_limiting_enabled=true).
    type: str
  source:
    description:
      - Which sources may use the forward, as an address, a range, a network in
        CIDR form, or any of those with a leading C(!) to exclude rather than
        admit.
      - C(any) admits every source, which is the controller's own value for no
        limit at all.
      - Also accepted as C(src) and C(src_ip).
      - Only meaningful with O(source_limiting_enabled=true).
    type: str
    aliases: [src, src_ip]
  forward_address:
    description:
      - The address inside the site the traffic is delivered to.
      - Required in practice. A forward with no address to deliver to forwards
        nothing, and the controller refuses the document.
      - Also accepted as C(fwd), C(fwd_ip), C(to_address) and C(target_ip).
    type: str
    aliases: [fwd, fwd_ip, to_address, target_ip]
  forward_port:
    description:
      - The port on the internal host that answers.
      - A string, because the controller holds it as one. Its own validation
        admits a single port, a range such as C(8000-8010), and a
        comma-separated list of either, so a task wanting more than one port
        names the range rather than a second forward.
      - Also accepted as C(fwd_port) and C(to_port).
    type: str
    aliases: [fwd_port, to_port]
  destination_port:
    description:
      - The port the outside world connects to, which the forward then delivers
        to O(forward_port) on O(forward_address).
      - A string, and accepts a range or a list for the same reason
        O(forward_port) does.
      - Also accepted as C(dst_port) and C(from_port).
    type: str
    aliases: [dst_port, from_port]
  protocol:
    description:
      - The IP protocol the forward carries.
      - C(tcp_udp) carries both, which is one forward answering on two protocols
        rather than two forwards.
      - Also accepted as C(proto).
    type: str
    choices: [tcp_udp, tcp, udp]
    aliases: [proto]
  interface:
    description:
      - Which WAN interface the forward admits traffic on.
      - The controller's own values are C(wan) through C(wan9) for a named WAN
        interface, and C(both) and C(all), which the collection exposes without
        choosing between and does not claim to distinguish.
      - Not given as a choice list, because the controller describes this field
        as a pattern rather than as a set of values, and a list of the values
        this collection can read would refuse the ones the pattern admits.
    type: str
  destination_ip:
    description:
      - The WAN address the forward answers on, or C(any) to answer on all of
        them.
      - The controller holds a second field for the same purpose, an array of
        address and interface pairs, which this module does not manage. Sending
        both would leave the controller two answers to which address the forward
        answers on.
    type: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - The controller requires O(enabled), O(log_enabled) and
    O(source_limiting_enabled) on every document, so a body that omits one is
    refused rather than defaulted. The module always sends all three, and the
    defaults above are what it sends, which means a play that names none of them
    still asserts them on every run. On a forward where the console had logging
    or source limiting on, a play that only meant to change a port will turn it
    off. Naming the three explicitly is the way to keep them.
  - O(enabled) defaults to C(true) rather than to C(false), because a port
    forward a task asked for and the controller then refuses to deliver is a
    forward that exists and does nothing, and O(state=absent) is how a task says
    it is not wanted.
  - A port forward is a path into the site, so a suite that creates one removes
    it. A forward left open on a WAN interface is a live exposure, not a
    leftover.
  - Nothing here is rate limited, and the controller evaluates no order between
    forwards, so two forwards admitting the same port on the same interface both
    exist and which one answers is the controller's decision rather than the
    task's.
"""

EXAMPLES = r"""
- name: Forward a web service on the first WAN interface
  abn.unifi_network.unifi_port_forward:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Web
    forward_address: 192.168.1.50
    forward_port: "8443"
    destination_port: "443"
    protocol: tcp
    interface: wan
    destination_ip: any
    log_enabled: true

- name: Admit one network only, and say so in the log
  abn.unifi_network.unifi_port_forward:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Web
    source_limiting_enabled: true
    source_limiting_type: ip
    source: 10.20.0.0/16
    log_enabled: true

- name: Carry both protocols on a range of ports
  abn.unifi_network.unifi_port_forward:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Media
    forward_address: 192.168.1.60
    forward_port: 8000-8010
    destination_port: 8000-8010
    protocol: tcp_udp
    interface: wan

- name: Stop delivering without removing it
  abn.unifi_network.unifi_port_forward:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Web
    enabled: false

- name: Remove it again
  abn.unifi_network.unifi_port_forward:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    name: Web
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The port forward as the controller holds it after the change.
    - Absent when the task removed it.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    name: Web
    enabled: true
    fwd: 192.168.1.50
    fwd_port: "8443"
    dst_port: "443"
    proto: tcp
    pfwd_interface: wan
    destination_ip: any
    log: false
    src_limiting_enabled: false
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it, apart from the three the controller requires and the module
      therefore always sends.
  returned: when changed
  type: list
  elements: str
  sample: ["dst_port", "fwd_port"]
"""

from collections.abc import Mapping
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_FORWARD
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
#:
#: The three defaults below are the exception the option descriptions state: the
#: controller requires those fields on every document, so they are sent whatever
#: a task names and a play that omits them still asserts them.
ARGUMENT_SPEC = connection_arguments(
    name={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    enabled={"type": "bool", "default": True},
    log_enabled={"type": "bool", "default": False},
    source_limiting_enabled={"type": "bool", "default": False},
    source_limiting_type={
        "type": "str",
        "choices": list(ENUM_VALUES["PortForward.src_limiting_type"]),
    },
    source_firewall_group={"type": "str"},
    source_firewall_group_id={"type": "str"},
    source={"type": "str", "aliases": ["src", "src_ip"]},
    forward_address={"type": "str", "aliases": ["fwd", "fwd_ip", "to_address", "target_ip"]},
    forward_port={"type": "str", "aliases": ["fwd_port", "to_port"]},
    destination_port={"type": "str", "aliases": ["dst_port", "from_port"]},
    protocol={
        "type": "str",
        "choices": list(ENUM_VALUES["PortForward.proto"]),
        "aliases": ["proto"],
    },
    interface={"type": "str"},
    destination_ip={"type": "str"},
)

#: ``rest/portforward``, on the site's own base. It is not beneath the policy
#: engine's base, so the client this module builds is the one the site's
#: configuration endpoints live on.
COLLECTION = "/rest/portforward"

#: The firewall groups a source limit can name. A group is addressed by
#: identifier, so a task naming one gives its name and the controller supplies the
#: identifier.
FIREWALL_GROUPS = "/rest/firewallgroup"


def run(module: AnsibleModule) -> None:
    client = build_client(module.params)

    if module.params["state"] == "absent":
        outcome = remove(
            client,
            collection=COLLECTION,
            name=module.params["name"],
            what="port forward",
            check_mode=module.check_mode,
        )
        module.exit_json(**outcome.as_result())

    wanted = project(module.params, PORT_FORWARD)
    _attach_source_firewall_group(client, module.params, wanted)
    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=wanted,
        name=module.params["name"],
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _attach_source_firewall_group(
    client: Any, params: Mapping[str, Any], wanted: dict[str, Any]
) -> None:
    """Resolve a named firewall group into the identifier the forward holds.

    The reference is optional, so a task naming neither leaves the field absent
    rather than asking the controller to resolve an empty name.
    """
    if not (params.get("source_firewall_group") or params.get("source_firewall_group_id")):
        return
    wanted["src_firewall_group_id"] = reference(
        client,
        FIREWALL_GROUPS,
        name=str(params.get("source_firewall_group") or ""),
        identifier=str(params.get("source_firewall_group_id") or ""),
        what="firewall group",
    )


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=[
            *connection_mutually_exclusive(),
            ("source_firewall_group", "source_firewall_group_id"),
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
