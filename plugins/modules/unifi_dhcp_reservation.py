#!/usr/bin/python
# Copyright (c) 2026 Arun
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: unifi_dhcp_reservation
short_description: Manage a static DHCP reservation on a UniFi controller
version_added: 0.1.0
description:
  - Manages a static DHCP reservation, which is a hardware address the controller
    always answers with one address rather than with one from the pool.
  - The controller holds a reservation as a row in its client registry with the
    fixed address and the flag that makes it serve that address, not as a resource
    of its own. There is no reservations collection to address, and a task
    addresses this one by the hardware address rather than by a name.
  - A reservation can be created for a hardware address that has never connected.
    Nothing has to be adopted, seen or named before the address is held for it.
  - Only the fields named by a task are compared. The rest of a client document is
    what the controller observed about the hardware, and comparing those would
    report a change on every run against a controller nobody has touched.
author:
  - Arun (@abn)
options:
  mac:
    description:
      - The hardware address the reservation is for, which is how a task selects
        the record.
      - The identity of the record. O(name) is a label the console shows and two
        records can carry one, so it is not a selector.
      - Accepted in either case and stored in lower case, because that is how the
        controller records it and a task writing it in upper case would otherwise
        create a second record rather than find the first.
    type: str
    required: true
  state:
    description:
      - Whether the address should be reserved for this hardware address.
      - C(absent) releases the reservation rather than removing the record. See
        the notes for why, and for what that leaves behind.
    type: str
    choices: [present, absent]
    default: present
  fixed_ip:
    description:
      - The address to reserve, which must lie in the range of the network below.
      - Optional when updating a record that already carries an address, because
        the controller keeps C(fixed_ip) on a write that does not restate it. A
        task that only relabels a client leaves this out.
      - Required when creating a record, because a client with a hardware address
        and no address is not a reservation.
      - The controller refuses an address outside the network's range, and refuses
        a second record claiming an address already reserved. Both refusals are the
        controller's own and are reported as it words them.
    type: str
    aliases: [ip, address]
  network:
    description:
      - The name of the network the reservation lives on, whose range the
        address above has to fall in.
      - The network a task can name, resolved to its identifier by the controller.
        Naming both this and O(network_id) is refused rather than resolved by
        picking one.
      - Optional on an existing record, whose own C(network_id) is kept when
        neither this nor O(network_id) is named. A task must name one when it
        creates a reservation, or sets an address or a local DNS record on a
        record that carries no network.
    type: str
  network_id:
    description:
      - The identifier of the network the reservation lives on, as a network task
        reports its C(_id).
      - Distinct from O(network), which is the same reference by name.
      - Optional on an existing record, whose own C(network_id) is kept when
        neither this nor O(network) is named. A task must name one when it
        creates a reservation, or sets an address or a local DNS record on a
        record that carries no network.
    type: str
  local_dns_record:
    description:
      - The name the site's local DNS server answers for the client.
      - The controller resolves the name against the address the reservation
        holds, and refuses the name without one. The address may come from this
        run's O(fixed_ip) or from a reservation the record already carries.
    type: str
  name:
    description:
      - The label the console shows for the record.
      - Not an identity, and not what the reservation is selected by.
      - A task that names a record it has already found may change this alone,
        without restating the address or the network it is not changing.
    type: str
extends_documentation_fragment:
  - abn.unifi_network._connection
notes:
  - A reservation is a client record carrying C(use_fixedip), and the controller
    holds the address and that flag apart. There is no option for the flag here,
    because the two together are what a reservation is. The module sets the flag
    only beside an address it was given, so a task that names no address sends no
    flag and leaves whatever the controller already held.
  - A task that names neither O(network) nor O(network_id) keeps the
    C(network_id) the record already carries. A network has to be named only when
    a write needs one, which is when the task creates a reservation or sets an
    address or a local DNS record on a record that carries none.
  - O(local_dns_record) needs O(fixed_ip), and the controller needs C(use_fixedip)
    set on the record, which the module sets whenever it sends an address. The
    controller holds the name beside a C(local_dns_record_enabled) flag and
    refuses the name without an address, answering
    C(api.err.LocalDnsRecordRequiresFixedIp). A task naming the record without an
    address is refused here rather than by the controller.
  - C(use_fixedip) is genuinely tri-state on the controller, and a record that
    never reserved an address answers C(null) rather than C(false). A release
    treats C(null) as already released, which is the state it would leave behind.
  - C(state=absent) clears C(use_fixedip) and leaves the record. The record is the
    controller's registry of devices, and an operator does not want a released
    reservation to make the controller forget that a device exists.
    C(DELETE rest/user/{id}) answers C(api.err.NotFound) for a record that is
    there, on a 10.6.106 controller, so there is no removal to report and none is
    attempted. A second run finds the record already released and reports no
    change, which is what it is.
  - O(state=absent) also clears O(local_dns_record), because the controller holds a
    local DNS name only beside the address it resolves against and refuses the
    release itself while a name is still set.
  - The controller validates the address against the network's own range and
    refuses a duplicate. Neither check is performed here, because the range belongs
    to the network rather than to the task, and a second module that computed it
    would disagree with the controller about a boundary the controller decides.
  - O(mac) is the identity and O(name) is a label, so a task changing the address
    names a record it has already found. Two tasks claiming one address for two
    hardware addresses is a conflict between the tasks, and the controller is where
    it is reported.
"""

EXAMPLES = r"""
- name: Hold an address for a printer that has not been installed yet
  abn.unifi_network.unifi_dhcp_reservation:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: aa:bb:cc:dd:ee:01
    network: Office
    fixed_ip: 10.0.20.50
    name: Reception printer

- name: Move it to another address
  abn.unifi_network.unifi_dhcp_reservation:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: aa:bb:cc:dd:ee:01
    fixed_ip: 10.0.20.51

- name: Relabel it without restating the address or the network
  abn.unifi_network.unifi_dhcp_reservation:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: aa:bb:cc:dd:ee:01
    name: Office printer

- name: Answer the name from the site's own DNS server too
  abn.unifi_network.unifi_dhcp_reservation:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: aa:bb:cc:dd:ee:01
    ip: 10.0.20.50
    local_dns_record: printer.example.invalid

- name: Release it again
  abn.unifi_network.unifi_dhcp_reservation:
    controller: unifi.example.invalid
    api_mount: appliance
    api_family: legacy
    site: default
    username: "{{ unifi_username }}"
    password: "{{ unifi_password }}"
    ca_path: /etc/ssl/certs/unifi-ca.pem
    mac: aa:bb:cc:dd:ee:01
    state: absent
"""

RETURN = r"""
obj:
  description:
    - The client record as the controller holds it after the change.
    - Empty when C(state=absent) found no record for the hardware address. A
      release is not a removal, so the record is reported where one was there.
  returned: always
  type: dict
  sample:
    _id: 5f2b1c9e4d3a2b1c0d9e8f7a
    mac: aa:bb:cc:dd:ee:01
    name: Reception printer
    fixed_ip: 10.0.20.50
    use_fixedip: true
    local_dns_record: printer.example.invalid
    local_dns_record_enabled: true
    network_id: 6a1c0d8e5b4a3c2b1d0e9f8a
changed_fields:
  description:
    - The controller fields this run changed, by dotted path.
    - A field the task did not name never appears here, whatever the controller
      did to it.
  returned: when changed
  type: list
  elements: str
  sample: ["fixed_ip"]
"""

import re
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import CLIENT
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import redact
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import reference
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows

#: The options this resource manages, as a task names them. Anything absent here
#: is not sent, so a field the collection does not know cannot reach the
#: controller as a guess.
ARGUMENT_SPEC = connection_arguments(
    mac={"type": "str", "required": True},
    state={"type": "str", "choices": ["present", "absent"], "default": "present"},
    fixed_ip={"type": "str", "aliases": ["ip", "address"]},
    network={"type": "str"},
    network_id={"type": "str"},
    local_dns_record={"type": "str"},
    name={"type": "str"},
)

#: The controller's own pattern for a hardware address on a client, quoted from
#: the vendored description of the field, which is the same metadata that
#: validates the write. A malformed address would create a record nothing can
#: select rather than a reservation.
MAC = re.compile(r"^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$")

#: The site base's client registry, which is where a reservation is written.
COLLECTION = "/rest/user"

#: The collection a reservation's network is named in.
NETWORKS = "/rest/networkconf"

#: The field the record is matched on rather than its name, because a name is
#: settable here and two records can carry one while the controller records the
#: hardware address as the identity.
SELECTOR = "mac"

#: The flag beside the address that makes the controller serve it. Named here
#: rather than taken from an option, so that a task asking for a reservation and a
#: task asking for the absence of one send it with opposite values.
USE_FIXED_IP = "use_fixedip"

#: The flag beside a local DNS name that makes the site's DNS server answer it.
#: Derived rather than taken from an option, because a name the server does not
#: answer is a name only the console shows.
LOCAL_DNS_ENABLED = "local_dns_record_enabled"


def run(module: AnsibleModule) -> None:
    # The selector is reduced before the client is built, so a task that cannot be
    # applied never gets as far as sending a credential. The address decision needs
    # the record, so it is made against the read below.
    mac = _mac(module.params["mac"])
    client = build_client(module.params)

    if module.params["state"] == "absent":
        module.exit_json(**_release(client, mac, check_mode=module.check_mode))

    current = _find(client, mac)
    _require_dns_address(module.params, mac, current)
    _require_address(module.params, mac, current)

    outcome = apply(
        client,
        collection=COLLECTION,
        wanted=_wanted(client, module.params, mac, current),
        key=SELECTOR,
        name=mac,
        current=current,
        check_mode=module.check_mode,
    )
    module.exit_json(**outcome.as_result())


def _mac(value: object) -> str:
    """The hardware address as the controller records it.

    Lower case, because the controller stores a hardware address in lower case and
    the reconciler matches a record on the address exactly. A task writing it in
    upper case would therefore not find the record it means and would post a
    second one beside it.
    """
    text = str(value).strip()
    if not MAC.match(text):
        raise UniFiError(
            f"{text!r} is not a hardware address; a reservation is selected by one, "
            "and the controller accepts six colon-separated pairs of hexadecimal digits"
        )
    return text.lower()


def _require_address(params: dict[str, Any], mac: str, current: dict[str, Any] | None) -> None:
    """Refuse to create a record that is not a reservation.

    A record that already exists can be updated without restating its address: the
    controller keeps C(fixed_ip), C(use_fixedip) and C(network_id) on a write that
    names none of them, so a task relabelling a client need not restate what it is
    not changing. A record that does not exist yet and carries no address is a
    client with a hardware address and nothing else, which the controller creates
    happily, and which is not a reservation.
    """
    if current is not None:
        return
    if not params.get("fixed_ip"):
        raise UniFiError(
            f"a reservation on {mac!r} needs an address to reserve, "
            "which is the fixed_ip option; naming a hardware address alone registers "
            "a client rather than reserving an address for it"
        )


def _require_dns_address(params: dict[str, Any], mac: str, current: dict[str, Any] | None) -> None:
    """Refuse a local DNS name with no address for the controller to resolve it to.

    The address may come from the task or from the record already held: the
    controller resolves the name against C(use_fixedip), which a task naming
    O(fixed_ip) asserts and an existing reservation already carries. A record that
    exists without the flag is not enough, because the controller refuses a local
    DNS name with no address it will serve, answering
    C(api.err.LocalDnsRecordRequiresFixedIp).
    """
    if not params.get("local_dns_record"):
        return
    if params.get("fixed_ip") or (current and current.get(USE_FIXED_IP)):
        return
    raise UniFiError(
        f"a local DNS record on {mac!r} needs an address, which is the fixed_ip "
        "option; the controller resolves the name against the address and refuses "
        "a local DNS record without one"
    )


def _wanted(
    client: Any, params: dict[str, Any], mac: str, current: dict[str, Any] | None
) -> dict[str, Any]:
    """The document a task asks the controller to hold for this hardware address.

    Only the fields the task named are set. The flag and the network reference are
    derived rather than projected from an option, and both are derived from what
    the task named: a rename-only task sends neither the address nor the flag, so
    the controller keeps what it already held for them.
    """
    wanted: dict[str, Any] = dict(project(params, CLIENT))
    wanted[SELECTOR] = mac
    if params.get("fixed_ip"):
        wanted[USE_FIXED_IP] = True
    if params.get("local_dns_record"):
        wanted[LOCAL_DNS_ENABLED] = True
    _attach_network(client, params, current, wanted)
    return wanted


def _attach_network(
    client: Any,
    params: dict[str, Any],
    current: dict[str, Any] | None,
    wanted: dict[str, Any],
) -> None:
    """Resolve the network the reservation lives on, or keep the one it already has.

    A task that names neither network option on a record that already carries a
    network keeps it, because relabelling a client does not move its reservation.
    The failure is therefore reached only when a write needs a network that is
    neither named nor already held.
    """
    if params.get("network") or params.get("network_id"):
        wanted["network_id"] = reference(
            client,
            NETWORKS,
            name=str(params.get("network") or ""),
            identifier=str(params.get("network_id") or ""),
            what="network",
        )
        return

    preserved = current.get("network_id") if current else None
    if preserved:
        wanted["network_id"] = preserved
        return

    if params.get("fixed_ip") or params.get("local_dns_record"):
        raise UniFiError(
            "a reservation needs the network it lives on, named by the network or "
            "network_id option; a fixed address cannot be reserved without one"
        )


def _release(client: Any, mac: str, *, check_mode: bool) -> dict[str, Any]:
    """Clear the flag that makes the controller serve an address, or report it clear.

    The record is left in place. It is the controller's registry of the devices on
    the site, and a reservation that is no longer wanted is not a device that
    stopped existing. A record already carrying no flag is reported as no change
    rather than written again, so a play running this every night is quiet.

    A local DNS name is cleared with the reservation. The controller refuses the
    release itself with C(api.err.LocalDnsRecordRequiresFixedIp) while the name is
    still set, because a name with no address to resolve against is not a record it
    will hold, and it clears the name when the flag beside it goes false.
    """
    current = _find(client, mac)
    if current is None:
        return {"changed": False, "diff": {"before": {}, "after": {}}, "obj": {}}
    if not current.get(USE_FIXED_IP):
        return {
            "changed": False,
            "diff": {"before": redact(current), "after": redact(current)},
            "obj": redact(current),
        }

    released = {**current, USE_FIXED_IP: False, LOCAL_DNS_ENABLED: False}
    if not check_mode:
        client.set(f"{COLLECTION}/{current['_id']}", released)
        after = _find(client, mac)
        if after is None or after.get(USE_FIXED_IP) or after.get(LOCAL_DNS_ENABLED):
            raise UniFiError(
                f"the controller accepted the release of {mac!r} but still holds an "
                "address reserved for it, or the local DNS name that hangs on one"
            )
    else:
        after = released
    return {
        "changed": True,
        "diff": {"before": redact(current), "after": redact(after)},
        "obj": redact(after),
        "changed_fields": [USE_FIXED_IP, LOCAL_DNS_ENABLED]
        if current.get(LOCAL_DNS_ENABLED)
        else [USE_FIXED_IP],
    }


def _find(client: Any, mac: str) -> dict[str, Any] | None:
    """The one record carrying this hardware address, or ``None``.

    Matched exactly, because the address arrives here already in the form the
    controller records it: :func:`_mac` is the single place a task's spelling is
    reduced, and a second reduction here would hide which of the two was wrong.
    """
    for row in rows(client.get(COLLECTION)):
        if str(row.get(SELECTOR, "")) == mac:
            return row
    return None


def main() -> None:
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        required_together=connection_required_together(),
        mutually_exclusive=[
            *connection_mutually_exclusive(),
            ("network", "network_id"),
        ],
        supports_check_mode=True,
    )
    try:
        run(module)
    except UniFiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
