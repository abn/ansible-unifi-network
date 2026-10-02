# SPDX-License-Identifier: BSD-2-Clause
"""Building one port override entry, shared by its two surfaces.

Internal to this collection. See :mod:`._api` for what the private package path
means.

A port override is one keyed element of the ``port_overrides`` array on a device
document, and two modules write it: ``unifi_port_override`` for one port and
``unifi_device``'s ``port_overrides`` list for several. Both offer the same option
names and resolve the same references, so the entry they build has one
implementation here rather than two that drift apart. The two collection paths are
arguments because each module holds its own constant for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import PORT_OVERRIDE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import reference
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import select

__all__ = [
    "IDENTITY",
    "INDIVIDUAL",
    "LIST_NETWORKS",
    "build_override_entries",
    "build_override_entry",
    "override_options",
]

#: The controller's own field the entry is keyed by. It is the identity the
#: reconciler merges and drops by, and never a field a task sets on its own.
IDENTITY = "port_idx"

#: The options that describe a port's own settings rather than selecting it. Every
#: one of them is an answer a port profile already gives, so any of them beside a
#: profile is a contradiction rather than a merge. O(name) is absent because it is
#: a label rather than membership and sits beside a profile rather than opposing it.
INDIVIDUAL = (
    "native_network",
    "native_network_id",
    "tagged_networks",
    "excluded_networks",
    "multicast_router_networks",
    "tagged_vlan_mgmt",
    "op_mode",
    "poe_mode",
    "autoneg",
    "fec_mode",
    "isolation",
    "speed",
    "full_duplex",
    "flow_control_enabled",
    "port_security_enabled",
    "port_security_mac_address",
    "dot1x_ctrl",
    "dot1x_idle_timeout",
    "mirror_port_idx",
    "aggregate_members",
    "stormctrl_type",
    "stormctrl_bcast_enabled",
    "stormctrl_bcast_level",
    "stormctrl_mcast_enabled",
    "stormctrl_mcast_level",
    "stormctrl_ucast_enabled",
    "stormctrl_ucast_level",
    "lldpmed_enabled",
    "lldpmed_notify_enabled",
    "port_keepalive_enabled",
    "stp_port_mode",
    "egress_rate_limit_kbps_enabled",
    "egress_rate_limit_kbps",
)

#: The three list references, option name to controller field. The singular native
#: reference goes through :func:`reference`, which also gives the
#: name-or-identifier pair its refusal.
LIST_NETWORKS = {
    "tagged_networks": "tagged_networkconf_ids",
    "excluded_networks": "excluded_networkconf_ids",
    "multicast_router_networks": "multicast_router_networkconf_ids",
}


def override_options() -> dict[str, Any]:
    """The option spec both surfaces offer for one override entry.

    Returned rather than shared as a constant, because the two modules place it
    differently: one nests it under ``port_overrides`` as suboptions and one
    spreads it into the flat argument spec. A caller gets a fresh mapping, so a
    mutation in one module cannot reach the other.

    Anything absent here is not sent, so a field the collection does not know
    cannot reach the controller as a guess. The controller keys the entry by
    O(port_idx), so a task supplies it to select rather than to configure.
    """
    return {
        "port_idx": {"type": "int", "required": True},
        "name": {"type": "str"},
        "port_profile": {"type": "str"},
        "port_profile_id": {"type": "str"},
        "native_network": {"type": "str"},
        "native_network_id": {"type": "str"},
        "tagged_networks": {"type": "list", "elements": "str"},
        "excluded_networks": {"type": "list", "elements": "str"},
        "multicast_router_networks": {"type": "list", "elements": "str"},
        "tagged_vlan_mgmt": {
            "type": "str",
            "choices": list(ENUM_VALUES["DevicePortOverrides.tagged_vlan_mgmt"]),
        },
        "op_mode": {"type": "str", "choices": list(ENUM_VALUES["DevicePortOverrides.op_mode"])},
        "poe_mode": {"type": "str", "choices": list(ENUM_VALUES["DevicePortOverrides.poe_mode"])},
        "autoneg": {"type": "bool"},
        "fec_mode": {"type": "str", "choices": list(ENUM_VALUES["DevicePortOverrides.fec_mode"])},
        "isolation": {"type": "bool"},
        "speed": {"type": "int"},
        "full_duplex": {"type": "bool"},
        "flow_control_enabled": {"type": "bool"},
        "port_security_enabled": {"type": "bool"},
        "port_security_mac_address": {"type": "list", "elements": "str"},
        "dot1x_ctrl": {"type": "str"},
        "dot1x_idle_timeout": {"type": "int"},
        "mirror_port_idx": {"type": "int"},
        "aggregate_members": {"type": "list", "elements": "int"},
        "stormctrl_type": {
            "type": "str",
            "choices": list(ENUM_VALUES["DevicePortOverrides.stormctrl_type"]),
        },
        "stormctrl_bcast_enabled": {"type": "bool"},
        "stormctrl_bcast_level": {"type": "int"},
        "stormctrl_mcast_enabled": {"type": "bool"},
        "stormctrl_mcast_level": {"type": "int"},
        "stormctrl_ucast_enabled": {"type": "bool"},
        "stormctrl_ucast_level": {"type": "int"},
        "lldpmed_enabled": {"type": "bool"},
        "lldpmed_notify_enabled": {"type": "bool"},
        "port_keepalive_enabled": {"type": "bool"},
        "stp_port_mode": {"type": "bool"},
        "egress_rate_limit_kbps_enabled": {"type": "bool"},
        "egress_rate_limit_kbps": {"type": "int"},
    }


def build_override_entries(
    client: Any,
    elements: Sequence[Mapping[str, Any]],
    *,
    collection: str,
    profiles: str,
) -> list[dict[str, Any]]:
    """Every override entry a task asks for, refusing a repeated port index.

    The reconciler merges by port index, so a port named twice in one task is a
    contradiction rather than two writes: the second would silently replace the
    first.
    """
    seen: set[int] = set()
    entries: list[dict[str, Any]] = []
    for element in elements:
        port_idx = _port_index(element)
        if port_idx in seen:
            raise UniFiError(
                f"port_idx {port_idx} is named twice in port_overrides; a port takes one "
                "entry, and a second would replace the first"
            )
        seen.add(port_idx)
        entries.append(
            build_override_entry(client, element, collection=collection, profiles=profiles)
        )
    return entries


def build_override_entry(
    client: Any,
    element: Mapping[str, Any],
    *,
    collection: str,
    profiles: str,
    networks: Any = None,
) -> dict[str, Any]:
    """One override entry in the controller's field names, references resolved.

    ``collection`` is where a network is named, ``profiles`` where a port profile
    is named, and ``networks`` is the site's network listing when the caller
    already holds one. A listing is read from ``collection`` when a list reference
    needs one and none was supplied.

    The refusals happen before any reference is resolved, so a task that
    contradicts itself is refused without a network call, let alone a write.
    """
    port_idx = _port_index(element)
    _refuse_profile_beside_fields(element, port_idx)
    entry = project(dict(element), PORT_OVERRIDE)
    entry[IDENTITY] = port_idx
    _attach_references(
        client,
        element,
        entry,
        collection=collection,
        profiles=profiles,
        networks=networks,
    )
    return entry


def _refuse_profile_beside_fields(element: Mapping[str, Any], port_idx: int) -> None:
    """Refuse a profile and a field of the port together, naming both.

    A profile already names the port's networks. A field beside it shadows that
    as a second answer to the same question, and the controller has no basis for
    choosing between them.
    """
    named = [option for option in INDIVIDUAL if element.get(option) is not None]
    if not named:
        return
    profile = _profile_forms(element)
    if not profile:
        return
    raise UniFiError(
        f"the port override for port_idx {port_idx} names {profile[0]} and the field "
        f"{named[0]}; a port takes a profile or its own settings, not both, because the "
        "profile already names the settings the field would override"
    )


def _profile_forms(element: Mapping[str, Any]) -> list[str]:
    """Whichever of the profile options an element named."""
    return [option for option in ("port_profile", "port_profile_id") if element.get(option)]


def _attach_references(
    client: Any,
    element: Mapping[str, Any],
    entry: dict[str, Any],
    *,
    collection: str,
    profiles: str,
    networks: Any,
) -> None:
    """Resolve the named networks into the identifiers the controller holds.

    The site's networks are read once and every list name is selected out of that
    one read, so two list references cannot be resolved against different sets. The
    profile reference resolves against its own collection.
    """
    if element.get("port_profile") or element.get("port_profile_id"):
        entry[PORT_OVERRIDE["port_profile_id"]] = reference(
            client,
            profiles,
            name=str(element.get("port_profile") or ""),
            identifier=str(element.get("port_profile_id") or ""),
            what="port profile",
        )

    singular = element.get("native_network") or element.get("native_network_id")
    list_names = {
        option: element.get(option) for option in LIST_NETWORKS if element.get(option) is not None
    }
    if not singular and not list_names:
        return

    if list_names and networks is None:
        networks = client.get(collection)
    if singular:
        entry[PORT_OVERRIDE["native_network_id"]] = reference(
            client,
            collection,
            name=str(element.get("native_network") or ""),
            identifier=str(element.get("native_network_id") or ""),
            what="network",
        )
    for option, names in list_names.items():
        entry[LIST_NETWORKS[option]] = [_network_id(networks, str(name)) for name in names or []]


def _network_id(networks: Any, name: str) -> str:
    """The identifier of the one network a name refers to."""
    return str(select(rows(networks), key="name", wanted=name, what="network")["_id"])


def _port_index(element: Mapping[str, Any]) -> int:
    """The port index an element names, as an integer.

    The argument spec marks it required, so a real play never reaches here without
    one. The check is for a caller that assembled the element itself, where a
    missing index would otherwise become a merge key of ``None``.
    """
    if element.get(IDENTITY) is None:
        raise UniFiError(f"an element of port_overrides names no {IDENTITY}")
    return int(element[IDENTITY])
