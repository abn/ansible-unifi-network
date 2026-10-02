# SPDX-License-Identifier: BSD-2-Clause
"""The controller's field names, taken from its own validation definitions.

Internal to this collection. See :mod:`._api` for what the private package path
means.

Every module maps its options onto controller fields through a table here, and the
tables are the collection's copy of the controller's schema. Two reasons they live
in one place rather than in each module:

A field name written in a module is a field name nobody can check. The controller
documents itself in an OpenAPI description generated from the same field-validation
metadata that validates a request, so the names in
``tests/fixtures/unifi-local-api.yaml`` are the controller's own rather than one
collection author's belief. Keeping them in one table means a rename in the
controller is a diff against a vendored fixture rather than a grep.

An option with no table entry is not sent. A module that invented a field name
would produce a controller error at apply time, on an operator's network, with no
earlier signal that the name was wrong.

The tables therefore only name fields the fixture actually declares. A field that
is not in the fixture is not in a table, and a module wanting it does not get it
until the fixture carries it.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CLIENT",
    "DEVICE",
    "ENUM_VALUES",
    "FIREWALL_POLICY",
    "FIREWALL_RULE",
    "FIREWALL_ZONE",
    "NETWORK",
    "PORT_FORWARD",
    "PORT_OVERRIDE",
    "PORT_PROFILE",
    "WLAN",
    "project",
]

#: ``rest/networkconf``. The controller keys a network by name and holds its DHCP
#: settings inline, so every DHCP option is a field on this object rather than a
#: resource of its own.
NETWORK: dict[str, str] = {
    "name": "name",
    "purpose": "purpose",
    "enabled": "enabled",
    "network_group": "networkgroup",
    "vlan": "vlan",
    "vlan_enabled": "vlan_enabled",
    "subnet": "ip_subnet",
    "domain_name": "domain_name",
    "dhcp_enabled": "dhcpd_enabled",
    "dhcp_start": "dhcpd_start",
    "dhcp_stop": "dhcpd_stop",
    "dhcp_lease_time": "dhcpd_leasetime",
    "dhcp_dns_enabled": "dhcpd_dns_enabled",
    "dhcp_dns_1": "dhcpd_dns_1",
    "dhcp_dns_2": "dhcpd_dns_2",
    "dhcp_dns_3": "dhcpd_dns_3",
    "dhcp_dns_4": "dhcpd_dns_4",
    "dhcp_gateway": "dhcpd_gateway",
    "dhcp_gateway_enabled": "dhcpd_gateway_enabled",
    "dhcp_guarding": "dhcpguard_enabled",
    "igmp_snooping": "igmp_snooping",
    "firewall_zone_id": "firewall_zone_id",
}

#: ``rest/wlanconf``.
#:
#: The passphrase is ``x_passphrase`` and the security mode is the pair
#: ``security`` with ``wpa_mode`` and ``wpa_enc``, all flat on the object. There is
#: no nested security document; the controller validates these three separately
#: and a module that sent them nested would have every one of them silently
#: dropped.
WLAN: dict[str, str] = {
    "name": "name",
    "enabled": "enabled",
    "network_id": "networkconf_id",
    "vlan": "vlan",
    "vlan_enabled": "vlan_enabled",
    "band": "wlan_band",
    "security": "security",
    "wpa_mode": "wpa_mode",
    "wpa_enc": "wpa_enc",
    "passphrase": "x_passphrase",
    "pmf_mode": "pmf_mode",
    "pmf_cipher": "pmf_cipher",
    "priority": "priority",
    "hide_ssid": "hide_ssid",
    "is_guest": "is_guest",
    "l2_isolation": "l2_isolation",
    "mac_filter_enabled": "mac_filter_enabled",
    "mac_filter_list": "mac_filter_list",
    "mac_filter_policy": "mac_filter_policy",
    "uapsd_enabled": "uapsd_enabled",
    "bss_transition": "bss_transition",
    "wpa3_transition": "wpa3_transition",
    "ap_group_ids": "ap_group_ids",
    "schedule_enabled": "schedule_enabled",
    "schedule": "schedule",
}

#: ``rest/portconf``, the switching profile a port is set to.
#:
#: A profile has no ``tagged_networkconf_ids``. It names its networks by exclusion,
#: listing every network the site holds apart from the native one and the tagged
#: ones. That is the controller's model rather than a choice: adding a network to a
#: site changes what every profile that does not include it must exclude, so a
#: profile is not an independent object and two tasks editing different profiles
#: can interact. The override does carry a tagged list, so a port overridden
#: directly and a port taking a profile express membership differently.
PORT_PROFILE: dict[str, str] = {
    "name": "name",
    "native_network_id": "native_networkconf_id",
    "excluded_network_ids": "excluded_networkconf_ids",
    "tagged_vlan_mgmt": "tagged_vlan_mgmt",
    "forward": "forward",
    "autoneg": "autoneg",
    "poe_mode": "poe_mode",
    "op_mode": "op_mode",
    "fec_mode": "fec_mode",
    "isolation": "isolation",
    "speed": "speed",
    "full_duplex": "full_duplex",
    "port_security_enabled": "port_security_enabled",
    "port_security_mac_address": "port_security_mac_address",
    "dot1x_ctrl": "dot1x_ctrl",
    "dot1x_idle_timeout": "dot1x_idle_timeout",
    "stormctrl_type": "stormctrl_type",
    "stormctrl_bcast_enabled": "stormctrl_bcast_enabled",
    "stormctrl_bcast_level": "stormctrl_bcast_level",
    "stormctrl_mcast_enabled": "stormctrl_mcast_enabled",
    "stormctrl_mcast_level": "stormctrl_mcast_level",
    "stormctrl_ucast_enabled": "stormctrl_ucast_enabled",
    "stormctrl_ucast_level": "stormctrl_ucast_level",
    "lldpmed_enabled": "lldpmed_enabled",
    "lldpmed_notify_enabled": "lldpmed_notify_enabled",
    "egress_rate_limit_kbps_enabled": "egress_rate_limit_kbps_enabled",
    "egress_rate_limit_kbps": "egress_rate_limit_kbps",
}

#: One entry of the ``port_overrides`` array inside a device document.
#:
#: It is not a resource with its own endpoint. It is an element of an array on a
#: device, so writing one means reading the device, replacing one element and
#: writing the whole array back. That is why this table is used by a reconciler
#: that re-reads rather than by one that writes a single object.
#:
#: ``portconf_id`` is what binds an override to a profile. An override that also
#: carries ``native_networkconf_id``, ``tagged_networkconf_ids`` or ``forward``
#: shadows the profile it points at, so those four interact: setting a profile and
#: a network on the same port is a contradiction rather than a merge, and the
#: reconciler refuses it rather than picking one.
PORT_OVERRIDE: dict[str, str] = {
    "port_idx": "port_idx",
    "name": "name",
    "port_profile_id": "portconf_id",
    "native_network_id": "native_networkconf_id",
    "tagged_network_ids": "tagged_networkconf_ids",
    "excluded_network_ids": "excluded_networkconf_ids",
    "tagged_vlan_mgmt": "tagged_vlan_mgmt",
    "forward": "forward",
    "op_mode": "op_mode",
    "poe_mode": "poe_mode",
    "autoneg": "autoneg",
    "fec_mode": "fec_mode",
    "isolation": "isolation",
    "speed": "speed",
    "full_duplex": "full_duplex",
    "flow_control_enabled": "flow_control_enabled",
    "port_security_enabled": "port_security_enabled",
    "port_security_mac_address": "port_security_mac_address",
    "dot1x_ctrl": "dot1x_ctrl",
    "dot1x_idle_timeout": "dot1x_idle_timeout",
    "mirror_port_idx": "mirror_port_idx",
    "aggregate_members": "aggregate_members",
    "multicast_router_network_ids": "multicast_router_networkconf_ids",
    "stormctrl_type": "stormctrl_type",
    "stormctrl_bcast_enabled": "stormctrl_bcast_enabled",
    "stormctrl_bcast_level": "stormctrl_bcast_level",
    "stormctrl_mcast_enabled": "stormctrl_mcast_enabled",
    "stormctrl_mcast_level": "stormctrl_mcast_level",
    "stormctrl_ucast_enabled": "stormctrl_ucast_enabled",
    "stormctrl_ucast_level": "stormctrl_ucast_level",
    "lldpmed_enabled": "lldpmed_enabled",
    "lldpmed_notify_enabled": "lldpmed_notify_enabled",
    "port_keepalive_enabled": "port_keepalive_enabled",
    "stp_port_mode": "stp_port_mode",
    "egress_rate_limit_kbps_enabled": "egress_rate_limit_kbps_enabled",
    "egress_rate_limit_kbps": "egress_rate_limit_kbps",
}

#: ``rest/device``, by way of ``stat/device`` for reading. Only the properties a
#: task may set are listed; the rest of a device document is hardware, runtime and
#: statistics the controller owns.
DEVICE: dict[str, str] = {
    "name": "name",
    "disabled": "disabled",
    "led": "led_override",
    "led_colour": "led_override_color",
    "led_brightness": "led_override_color_brightness",
    "outdoor_mode": "outdoor_mode_override",
    "management_network_id": "mgmt_network_id",
}

#: ``rest/user``. This collection is the client registry, not a user database:
#: the vendored schema binds its request body to ``Client``, and a static DHCP
#: reservation is a record here with ``use_fixedip`` set rather than a resource of
#: its own. A record is keyed by ``mac``, which is why a task names an address and
#: not a name.
#:
#: ``name`` is the label the console shows and is not the identity. ``vlan`` and
#: ``oui`` are filled by the controller from the address, and ``blocked`` and
#: ``fixed_ap_*`` configure a client rather than a reservation. ``local_dns_record``
#: is set here: a reservation may also be the name the site's local DNS server
#: answers with, which is why the reservation task sets it.
CLIENT: dict[str, str] = {
    "mac": "mac",
    "name": "name",
    "fixed_ip": "fixed_ip",
    "network_id": "network_id",
    "local_dns_record": "local_dns_record",
}

#: ``rest/portforward``. The two ends of a forward are separate fields and are
#: not interchangeable: ``dst_port`` is what the outside world connects to and
#: ``fwd_port`` is what the inside host is listening on. Both are strings, which
#: is what the vendored schema declares, so a task naming one as a number is
#: refused by the controller rather than here.
#:
#: ``destination_ips`` is the plural, an array of address and interface pairs, and
#: is deliberately absent: sending it beside the singular ``destination_ip`` would
#: leave the controller two answers to which address answers the forward.
PORT_FORWARD: dict[str, str] = {
    "name": "name",
    "enabled": "enabled",
    "log_enabled": "log",
    "source_limiting_enabled": "src_limiting_enabled",
    "source_limiting_type": "src_limiting_type",
    "source_firewall_group_id": "src_firewall_group_id",
    "source": "src",
    "forward_address": "fwd",
    "forward_port": "fwd_port",
    "destination_port": "dst_port",
    "protocol": "proto",
    "destination_ip": "destination_ip",
    "interface": "pfwd_interface",
}

#: ``rest/firewallrule``, the classic rules engine.
#:
#: A rule has no identity of its own on this resource beyond ``_id``. The console
#: keys it by ``name`` within a ``ruleset``, and the same name may appear in more
#: than one ruleset, so a task selecting a rule matches on both. ``rule_index`` is
#: the rule's position within its ruleset, and moving it moves the traffic it
#: governs.
#:
#: ``src_networkconf_id`` and ``dst_networkconf_id`` are the network references on
#: each side, and ``src_networkconf_type`` and ``dst_networkconf_type`` carry
#: ``ADDRv4`` or ``NETv4``, matching whether the reference names an address or a
#: network. The firewall-group references are plural because a rule may name
#: several groups on one side.
#:
#: ``protocol`` is a regex with numeric ranges in the vendored schema rather than
#: an enumeration, so it is left free-form and is not in :data:`ENUM_VALUES`.
FIREWALL_RULE: dict[str, str] = {
    "name": "name",
    "ruleset": "ruleset",
    "rule_index": "rule_index",
    "action": "action",
    "protocol": "protocol",
    "enabled": "enabled",
    "logging": "logging",
    "src_address": "src_address",
    "dst_address": "dst_address",
    "src_port": "src_port",
    "dst_port": "dst_port",
    "src_network_id": "src_networkconf_id",
    "src_network_type": "src_networkconf_type",
    "src_firewall_group_ids": "src_firewallgroup_ids",
    "dst_network_id": "dst_networkconf_id",
    "dst_network_type": "dst_networkconf_type",
    "dst_firewall_group_ids": "dst_firewallgroup_ids",
}

#: ``v2/api/site/{site}/firewall/zone``.
#:
#: A zone's own key is ``zone_key``, not ``zone_key_id``, and the controller
#: fills it in beside the flag marking a system zone. Neither is managed here: a
#: task sets a zone's name and the networks it holds, and the controller derives
#: the rest. ``default_zone`` is deliberately absent for that reason. It is
#: controller derived, the system zones come back carrying it, and the controller
#: refuses a create that sends it.
FIREWALL_ZONE: dict[str, str] = {
    "name": "name",
    "network_ids": "network_ids",
}

#: ``v2/api/site/{site}/firewall-policies``.
#:
#: ``index`` is the policy's position in the chain, and the controller assigns it
#: (a created policy received ``10000``), so it is optional and is not sent when a
#: task does not name it. ``source`` and ``destination`` are nested documents, so
#: their options carry a dotted field and the projection nests them.
#:
#: ``create_allow_respond`` is required on a create and is not a task option: the
#: controller refuses a create that omits it or sends it true, with
#: ``api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed``, so the module
#: asserts it false rather than exposing it.
FIREWALL_POLICY: dict[str, str] = {
    "name": "name",
    "action": "action",
    "protocol": "protocol",
    "index": "index",
    "enabled": "enabled",
    "logging": "logging",
    "ip_version": "ip_version",
    "connection_state_type": "connection_state_type",
    "source_zone_id": "source.zone_id",
    "source_match": "source.matching_target",
    "source_network_ids": "source.network_ids",
    "source_port_list": "source.port",
    "destination_zone_id": "destination.zone_id",
    "destination_match": "destination.matching_target",
    "destination_network_ids": "destination.network_ids",
    "destination_port_list": "destination.port",
}

#: Values the controller's validation accepts, quoted from the vendored
#: description of each field.
#:
#: Held here so an argument spec's ``choices`` and the controller's own validation
#: cannot drift apart. A test asserts every choice appears in the fixture, so a
#: choice invented here fails the suite rather than failing on an operator's
#: network.
ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "PortForward.proto": ("tcp_udp", "tcp", "udp"),
    # The schema states this one as the pattern `ip|firewall_group` rather than as
    # an enumeration, so the two values are the pattern's own alternatives.
    "PortForward.src_limiting_type": ("ip", "firewall_group"),
    "Network.purpose": (
        "corporate",
        "guest",
        "remote-user-vpn",
        "site-vpn",
        "vlan-only",
        "vpn-client",
        "wan",
    ),
    "Network.networkgroup": ("LAN",),
    "WLAN.security": ("open", "wpapsk", "wep", "wpaeap", "osen"),
    "WLAN.wpa_mode": ("auto", "wpa1", "wpa2"),
    "WLAN.wpa_enc": ("auto", "ccmp", "gcmp", "ccmp-256", "gcmp-256"),
    "WLAN.wlan_band": ("2g", "5g", "both"),
    "WLAN.pmf_mode": ("disabled", "optional", "required"),
    "WLAN.pmf_cipher": ("auto", "aes-128-cmac", "bip-gmac-256"),
    "WLAN.priority": ("medium", "high", "low"),
    "PortProfile.poe_mode": ("auto", "off"),
    "PortProfile.op_mode": ("switch",),
    "PortProfile.forward": ("all", "native", "customize", "disabled"),
    "PortProfile.tagged_vlan_mgmt": ("auto", "block_all", "custom"),
    "PortProfile.fec_mode": ("rs-fec", "fc-fec", "default", "disabled"),
    "PortProfile.dot1x_ctrl": (
        "auto",
        "force_authorized",
        "force_unauthorized",
        "mac_based",
        "multi_host",
    ),
    "DevicePortOverrides.poe_mode": ("auto", "pasv24", "passthrough", "off"),
    "DevicePortOverrides.op_mode": ("switch", "mirror", "aggregate"),
    "DevicePortOverrides.forward": ("all", "native", "customize", "disabled"),
    "DevicePortOverrides.tagged_vlan_mgmt": ("auto", "block_all", "custom"),
    "DevicePortOverrides.fec_mode": ("rs-fec", "fc-fec", "default", "disabled"),
    "DevicePortOverrides.stormctrl_type": ("level", "rate"),
    "Device.led_override": ("default", "on", "off"),
    "Device.outdoor_mode_override": ("default", "on", "off"),
    "FirewallRule.action": ("drop", "reject", "accept"),
    "FirewallRule.src_networkconf_type": ("ADDRv4", "NETv4"),
    "FirewallRule.dst_networkconf_type": ("ADDRv4", "NETv4"),
    "FirewallRule.ruleset": (
        "WAN_IN",
        "WAN_OUT",
        "WAN_LOCAL",
        "LAN_IN",
        "LAN_OUT",
        "LAN_LOCAL",
        "GUEST_IN",
        "GUEST_OUT",
        "GUEST_LOCAL",
        "WANv6_IN",
        "WANv6_OUT",
        "WANv6_LOCAL",
        "LANv6_IN",
        "LANv6_OUT",
        "LANv6_LOCAL",
        "GUESTv6_IN",
        "GUESTv6_OUT",
        "GUESTv6_LOCAL",
    ),
    "FirewallPolicy.action": ("ALLOW", "BLOCK", "REJECT"),
    "FirewallPolicy.protocol": ("all", "tcp", "udp", "tcp_udp"),
    "FirewallPolicy.ip_version": ("BOTH", "IPV4", "IPV6"),
    "FirewallPolicy.connection_state_type": ("ALL", "RESPOND_ONLY"),
}


def project(options: dict[str, Any], table: dict[str, str]) -> dict[str, Any]:
    """Rename a task's options into controller fields, dropping what is absent.

    An option left unset is absent from the result rather than sent as ``None``.
    Sending ``None`` would ask the controller to clear a field the task never
    mentioned, which is how a module that manages one setting ends up clearing
    another.

    A dotted table value such as ``"source.zone_id"`` produces nested output,
    because the controller nests those and a flat key would be dropped.
    """
    payload: dict[str, Any] = {}
    for option, value in options.items():
        if value is None:
            continue
        field = table.get(option)
        if field is None:
            continue
        _put(payload, field, value)
    return payload


def _put(payload: dict[str, Any], field: str, value: Any) -> None:
    head, dot, tail = field.partition(".")
    if not dot:
        payload[head] = value
        return
    nested = payload.setdefault(head, {})
    if isinstance(nested, dict):
        _put(nested, tail, value)
