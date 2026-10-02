# SPDX-License-Identifier: BSD-2-Clause
"""Canonical comparison for controller state.

Internal to this collection. See :mod:`._api` for what the private package path
means.

This is the part of the collection most likely to be wrong, and it is the part a
unit test can cover completely, so it is written to be tested rather than
trusted.

**Compare only what the user declared.** A controller's object carries hundreds
of fields, most of them server-managed: identifiers, counters, timestamps, the
statistics the console itself displays. Comparing a whole document against a
task's options reports a difference on nearly every field, on every run, which is
the failure mode idempotency exists to prevent. So the comparison is projected
onto the keys the task actually named, and the rest of the object is not evidence
of anything.

**Types are not meaning.** The controller answers a VLAN id as ``20`` on one
endpoint and ``"20"`` on another, and a DHCP lease time as ``86400`` on one
version and ``"86400"`` on the next. A comparison that treats those as different
reports a change every run against a controller that has not changed.

**Some lists are sets.** The radio bands of a wireless network are ``["2g","5g"]``
or ``["5g","2g"]`` depending on how the object was built, and both mean the same
network. The port list of a firewall policy is ``"80, 443"`` or ``"443,80"``. Order
is not meaning in either. It *is* meaning for a policy's position, which is why
that case is asked for explicitly rather than guessed.

None of this is inference about the controller. Each rule names the field it
applies to, because a generic normaliser would have to guess, and a guess here is
a false "changed" or a missed one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

__all__ = [
    "ORDERED_FIELDS",
    "SECRET_FIELDS",
    "SERVER_GENERATED",
    "compare",
    "differences",
    "normalise",
]

#: Never compared and never written. A task names none of these, and treating any
#: of them as a difference is the single largest source of a perpetual "changed".
#:
#: The identifiers and envelopes first: an object has to be addressable and to
#: carry its own metadata, and none of that is configuration. Then the counters
#: and timestamps, which change on a timer rather than because of anything the
#: collection did, so comparing them would report a change on a controller nobody
#: had touched. The last group is state the controller owns outright: adoption
#: state, uptime, and the statistics the console reads.
#:
#: A name is excluded across every resource, so the set may only hold names that
#: are never configuration on a resource this collection manages. ``speed`` and
#: ``full_duplex`` are negotiated by the controller on a device's hardware port
#: table, but they are settable on a port profile and a port override, so excluding
#: them by name would make those options impossible to change.
SERVER_GENERATED = frozenset(
    {
        "_id",
        "id",
        "uuid",
        "site_id",
        "siteId",
        "obj_id",
        "attr_no_delete",
        "attr_hidden_id",
        "attr_no_edit",
        "setting_preference",
        "version",
        "datetime",
        "last_seen",
        "uptime",
        "_uptime",
        "uptime_since",
        "stat",
        "stats",
        "meta",
        "mac",
        "model",
        "model_name",
        "type",
        "adopted",
        "state",
        "status",
        "ip",
        "lan_ip",
        "wan_ip",
        "num_sta",
        "num_user",
        "num_guest",
        "num_alert",
        "satisfaction",
        "tx_bytes_r",
        "rx_bytes_r",
        "tx_bytes",
        "rx_bytes",
        "tx_packets",
        "rx_packets",
        "tx_dropped",
        "rx_dropped",
        "tx_errors",
        "rx_errors",
        "cpu",
        "mem",
        "temperature",
        "general_temperature",
        "poe_enable",
        "poe_power",
        "link_status",
        "port_idx",
        "default_zone",
        "zone_key",
        "external_id",
        "cloud_template",
        "created_at",
        "updated_at",
    }
)

#: The secret fields of the resources whose controller rows are reported back.
#:
#: A returned secret has to be opt-in because ``no_log`` masks only the value a
#: task itself supplied. An update that does not restate a passphrase carries the
#: value the controller already holds, and the re-read document reports it, so the
#: mask has nothing to match on and the stored secret travels to the caller.
#:
#: This is a name list, not a projection of each resource's returned document. The
#: reported ``obj`` is deliberately the controller's own re-read row, and a
#: projection would restate every resource's schema in the kernel, where it would
#: drift from the resources it mirrors. The list names only the secrets of the
#: resources whose raw rows are reported, and a test walks those resources' schemas
#: in the vendored fixture and fails on any secret-looking property a human has not
#: classified, so a new secret cannot ship silently.
SECRET_FIELDS = frozenset(
    {
        "lte_password",
        "password",
        "psk",
        "x_auth_key",
        "x_baresip_password",
        "x_ca_key",
        "x_dh_key",
        "x_iapp_key",
        "x_ipsec_pre_shared_key",
        "x_openvpn_password",
        "x_openvpn_shared_secret_key",
        "x_passphrase",
        "x_pptpc_password",
        "x_server_key",
        "x_shared_client_key",
        "x_wan_password",
        "x_wep",
        "x_wireguard_private_key",
        "wireguard_client_preshared_key",
    }
)

#: Fields whose list order is meaning. A firewall policy's index is its position
#: in the chain, and reordering the list is a change to the network rather than a
#: cosmetic difference. Everything else is a set.
ORDERED_FIELDS = frozenset({"index", "position", "order"})

#: Fields the controller stores as one comma-separated string and a task may give
#: as several. Order in either is not meaning, so they are split and sorted.
COMMA_LIST_FIELDS = frozenset({"port_list", "ports"})

#: A comma-separated list the controller stores as one string and a task may give
#: as several. Order in either is not meaning.
_COMMA_LIST = re.compile(r"\s*,\s*")


def compare(wanted: Any, current: Any, *, path: str = "") -> bool:
    """Whether ``wanted`` and ``current`` mean the same thing.

    ``path`` names the field being compared and selects the rules that apply to
    it. Comparing a wireless network's bands and comparing a policy's position use
    different rules for the same types, and the difference is not detectable from
    the values.
    """
    normal = normalise(wanted, path)
    have = normalise(current, path)
    if normal == have:
        return True
    return _both_ways(wanted, current, path)


def differences(wanted: Any, current: Any, *, path: str = "") -> dict[str, Any]:
    """The subset of ``wanted`` that ``current`` does not already hold.

    Keyed by dotted path, so a caller can say which option was wrong rather than
    only that something was. Only keys present in ``wanted`` appear: an absent key
    is not a difference, and reporting one would tell the operator to supply an
    option they deliberately left out.
    """
    if not isinstance(wanted, Mapping):
        return {} if compare(wanted, current, path=path) else {path: wanted}

    found: dict[str, Any] = {}
    for key, value in wanted.items():
        leaf = f"{path}.{key}" if path else str(key)
        if key in SERVER_GENERATED:
            continue
        have = current.get(key) if isinstance(current, Mapping) else None
        if isinstance(value, Mapping):
            found.update(differences(value, have, path=leaf))
        elif not compare(value, have, path=leaf):
            found[leaf] = value
    return found


def normalise(value: Any, path: str = "") -> Any:
    """Reduce a value to the form it is compared in.

    Applied to both sides, because a rule that only cleaned one side would make
    the comparison depend on which side the value came from.
    """
    if isinstance(value, Mapping):
        return {
            str(key): normalise(item, f"{path}.{key}" if path else str(key))
            for key, item in value.items()
            if str(key) not in SERVER_GENERATED
        }
    if isinstance(value, str):
        return _text(value, path)
    if isinstance(value, bool | int | float):
        # A bool is not a number for this purpose. True and 1 compare equal in
        # Python, and a controller answering a boolean flag as 1 is describing
        # something other than a flag.
        return str(value).strip()
    if isinstance(value, Sequence):
        return _sequence(value, path, ordered=_is_ordered(path))
    return value


def _both_ways(wanted: Any, current: Any, path: str) -> bool:
    """Whether two values match, allowing a list and its joined string.

    A task may express a port list as a list while the controller stores it as one
    comma-separated string. Normalising each side on its own cannot reconcile that,
    because they are different types before any rule applies, so the string is
    split and compared as a list. Only for the fields that hold such a string;
    anywhere else a comma in a value is a comma in a value.
    """
    if path.rsplit(".", 1)[-1] not in COMMA_LIST_FIELDS:
        return False
    left, right = wanted, current
    if isinstance(left, str) and not isinstance(right, str):
        left = [part for part in _COMMA_LIST.split(left) if part]
    elif isinstance(right, str) and not isinstance(left, str):
        right = [part for part in _COMMA_LIST.split(right) if part]
    else:
        return False
    return normalise(left, path) == normalise(right, path)


def _is_ordered(path: str) -> bool:
    """Whether a list at this path has a meaningful order.

    Only a policy's position does, and it is named here rather than inferred from
    the value: a list of ids and a list of ids look identical, and only the field
    says which is which.
    """
    leaf = path.rsplit(".", 1)[-1]
    return leaf in ORDERED_FIELDS


def _text(value: str, path: str) -> str:
    """Normalise a string.

    A number rendered as a string and the number itself are the same answer, which
    is what makes ``20`` and ``"20"`` the same VLAN. Empty and absent are not
    unified here: a task that sets an empty string asked for an empty string, and
    silently treating it as "leave it alone" would drop a request.
    """
    text = value.strip()
    leaf = path.rsplit(".", 1)[-1]
    if leaf in COMMA_LIST_FIELDS:
        return ",".join(sorted(part for part in _COMMA_LIST.split(text) if part))
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return text
    return text


def _sequence(value: Sequence[Any], path: str, *, ordered: bool = False) -> Any:
    """Normalise a list.

    Sorted unless the caller says the order is meaning, which only the position of
    a firewall policy does. Sorting is by the normalised form, so ``[2, 5]`` and
    ``["2","5"]`` are one list either way.
    """
    items = [normalise(item, path) for item in value]
    if ordered:
        return items
    return sorted(items, key=_sort_key)


def _sort_key(item: Any) -> tuple[str, str]:
    """Order mixed and unorderable elements.

    A list may hold strings and numbers, or nested lists, and Python cannot sort
    those against each other. Comparing their rendered form is stable and total,
    which is all that is needed: the order is a canonicalisation, not a
    collation for a human to read.
    """
    if isinstance(item, list):
        return ("list", str(item))
    return ("scalar", str(item))
