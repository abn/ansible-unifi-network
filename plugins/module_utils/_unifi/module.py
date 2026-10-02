# SPDX-License-Identifier: BSD-2-Clause
"""The options every module in this collection shares.

Internal to this collection. See :mod:`._api` for what the private package path
means.

Each module repeats these in its own ``ARGUMENT_SPEC`` even though this is where
they are defined. That is deliberate: ``validate-modules`` cross-checks a module's
effective spec against its documentation, and a spec assembled here and referenced
there would leave the documentation describing options the checker never sees.

**No option carries a default unless absence would be meaningless.** A default
makes "not mentioned" indistinguishable from "set to false", which on an object
where unspecified means leave-as-is turns every undeclared option into a change.
Where a task wants to say "do not manage this", the option is ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import ApiOptions
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import open_transport
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import APPLIANCE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import CONSOLE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import LEGACY
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import OFFICIAL
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import api_root
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import base_url_for
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import control_root
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import (
    policy_engine_base,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError

__all__ = [
    "CONNECTION_ARGUMENTS",
    "connection_arguments",
]

#: The controller to talk to and how to authenticate to it.
CONNECTION_ARGUMENTS: dict[str, dict[str, Any]] = {
    "controller": {"type": "str", "required": True},
    "api_mount": {
        "type": "str",
        "choices": [APPLIANCE, CONSOLE],
        "required": True,
    },
    "api_family": {
        "type": "str",
        "choices": [OFFICIAL, LEGACY],
        "required": True,
    },
    "site": {"type": "str"},
    "login_path": {
        "type": "str",
        "choices": ["/api/login", "/api/auth/login"],
    },
    "api_key": {"type": "str", "no_log": True},
    "username": {"type": "str"},
    "password": {"type": "str", "no_log": True},
    "ca_path": {"type": "path"},
    "validate_certs": {"type": "bool", "default": True},
    "timeout": {"type": "int", "default": 30},
}


def connection_arguments(**own: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The shared options, plus a module's own.

    Copied rather than merged in place, because a shared constant handed back
    directly would leak a default from one module into the next if anything ever
    mutated the spec it was given.
    """
    return {**deepcopy(CONNECTION_ARGUMENTS), **own}


#: Which set of collections a module addresses. The configuration endpoints sit
#: beneath the site and the policy engine sits above it, so a module says which
#: it means rather than assembling a path out of dot segments.
SITE_COLLECTIONS = "legacy"
POLICY_ENGINE = "policy_engine"

_BASES = {
    SITE_COLLECTIONS: base_url_for,
    POLICY_ENGINE: policy_engine_base,
}


def build_client(
    params: Mapping[str, Any],
    *,
    site: str = "",
    base: str = SITE_COLLECTIONS,
) -> UniFiClient:
    """Build a client from a module's parameters.

    Takes the parameter mapping rather than the ``AnsibleModule``, so this file
    never imports the heaviest thing in the collection. A module calls this once,
    at the top of its ``run``.

    ``base`` names which set of collections the module addresses. The credential,
    the site and the login are the same either way; only the path below the
    deployment root differs. The site collections are refused for the official
    family, because every module in this collection addresses the legacy paths
    there and the official family serves neither of them.
    """
    if base not in _BASES:
        raise UniFiError(f"base must be one of {sorted(_BASES)}, not {base!r}")
    controller = str(params["controller"])
    family = str(params["api_family"])
    if base == SITE_COLLECTIONS and family == OFFICIAL:
        # Every shipped module addresses the legacy collection paths, so an
        # official family here would compose /proxy/network/integration/rest/...,
        # which the controller answers with a 404 that reads like a missing
        # resource rather than a family that cannot serve it.
        raise UniFiError(
            "api_family=official cannot address the site collections the shipped "
            "modules speak; those modules use the legacy family, and the official "
            "integration API does not serve these endpoints"
        )
    mount = str(params.get("api_mount") or APPLIANCE)
    resolved_site = site or str(params.get("site") or "")
    merged = dict(params)
    merged["base_url"] = _BASES[base](family, controller, site=resolved_site, mount=mount)
    # The login is addressed at the deployment root, above any site, so the two
    # are separate values rather than one path with the site stripped off it.
    merged["api_root"] = api_root(mount, controller)
    # The login is above the prefix the applications live under, which on a
    # console is a different string from the application root.
    merged["control_root"] = control_root(controller)
    merged.setdefault("login_path", default_login_path(mount))
    return UniFiClient(merged, open_transport)


def default_login_path(mount: str) -> str:
    """Where a deployment accepts a login.

    A self-hosted application takes it at the root and a console proxies it with
    the rest of the application, so the two addresses different paths. Asking the
    wrong one draws a 404 that names nothing useful.
    """
    return "/api/login" if mount == APPLIANCE else "/api/auth/login"


def connection_required_together() -> list[tuple[str, str]]:
    """Constraint pairs for a module's ``AnsibleModule``.

    Returned rather than declared so the pairs are stated once. A username with
    no password is a task error, not a login attempt that fails with a 401 the
    operator would blame on their credential.
    """
    return [("username", "password")]


def connection_mutually_exclusive() -> list[tuple[str, str]]:
    """Constraint pairs that cannot both be given."""
    return [("api_key", "username"), ("api_key", "password")]


def api_options(client: UniFiClient) -> ApiOptions:
    """The connection options a client was built with.

    Exposed so a module can report them in a fact module without reaching into
    the client's private attributes.
    """
    return client.options
