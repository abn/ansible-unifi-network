# SPDX-License-Identifier: BSD-2-Clause
"""The shared UniFi controller client.

Internal to this collection. See :mod:`._api` for what the private package path
means.

This is the seam every module goes through, and it exists so that no module
carries a credential, builds a URL, or decides what a status means. Those three
things are the ones that go wrong in ways a test must catch, and putting them
here means they are testable once rather than per module.

The two API families are configured, not sniffed. The choice is per object rather
than per collection, because the families do not overlap: the official
integration API takes a stateless key and has no CSRF, and cannot write a
wireless network, a port profile, a per-port override, a DHCP configuration or
any layer-3 switching, while the legacy local API reaches all of those and needs a
cookie plus a token it rotates. An unset or wrong family is refused rather than
probed for, because a silent fallback onto the other one would authenticate
successfully and then write the wrong document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import Api
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import ApiOptions
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import RawResponse
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import Transport
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import open_transport
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import Credentials
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import Password
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import credentials_from
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import from_response
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    message_from_body,
)

__all__ = [
    "APPLIANCE",
    "CONSOLE",
    "LEGACY",
    "OFFICIAL",
    "UniFiClient",
    "UniFiError",
    "base_url_for",
    "legacy_base",
    "official_base",
]

#: Where the application is mounted, which is a property of the deployment and
#: not of the API family.
#:
#: A self-hosted Network Application serves its own API at the root, and a
#: request for `/proxy/network` there answers 404. A UniFi OS console proxies the
#: application beneath the OS, so the same request is correct there. The vendored
#: schema declares both: one server at `/proxy/network` described as a console,
#: and one at the root described as a self-hosted controller.
APPLIANCE = "appliance"
CONSOLE = "console"

#: The proxy prefix a UniFi OS console puts in front of the application.
CONSOLE_PREFIX = "/proxy/network"

#: The two endpoint families. The choice is the operator's because no probe can
#: make it safely: a wrong family answers 401 the same way a wrong credential
#: does, and discovering which is in use by watching what fails is how a play
#: writes to the wrong surface.
OFFICIAL = "official"
LEGACY = "legacy"

#: Families each deployment offers. An official API key cannot be created on a
#: self-hosted appliance, and the cloud connector's key is documented read-only,
#: so offering a family a deployment cannot serve would fail at apply time on a
#: network rather than at argument validation.
FAMILIES_BY_MOUNT = {
    APPLIANCE: (LEGACY,),
    CONSOLE: (LEGACY, OFFICIAL),
}


def api_root(mount: str, host: str) -> str:
    """The deployment's root, above any site.

    A login is not addressed beneath a site, so the root and the site-scoped base
    are separate values. Composing a login onto the site base produces a URL that
    does not exist, and the controller answers it with a 404 that names a site
    rather than a login.
    """
    prefix = CONSOLE_PREFIX if mount == CONSOLE else ""
    return f"{_origin(host)}{prefix}"


def official_base(mount: str, host: str) -> str:
    """The base path of the official family for a deployment."""
    return f"{api_root(mount, host)}/integration"


def control_root(host: str) -> str:
    """The deployment root, above the prefix the applications live under.

    A console serves its login above that prefix, so a login composed onto the
    application root asks a path that does not exist and is answered with a 401.
    That reads like a wrong credential and is a wrong address.

    An appliance serves the login at its application root, so the two are the same
    string there and nothing about this changes.
    """
    return _origin(host)


def legacy_base(mount: str, host: str, *, site: str) -> str:
    """The base path of the legacy family for a deployment.

    ``site`` is the site's internal slug, which the official family does not use:
    it addresses sites by UUID instead.
    """
    if not site:
        raise UniFiError("the legacy API addresses resources under a site, which was not given")
    return f"{api_root(mount, host)}/api/s/{site}"


def policy_engine_base(_family: str, host: str, *, site: str, mount: str) -> str:
    """The base path of the policy engine, which sits above the site.

    The policy engine is not addressed beneath ``/api/s/{site}`` the way the
    configuration endpoints are. Climbing out of the site base with dot segments
    reaches it, and every one of those segments is a property of the base that a
    change elsewhere can invalidate, so the path is composed here instead.

    The family is accepted and ignored: the policy engine is served by the legacy
    family on every deployment, and taking the argument keeps every base
    interchangeable at the call site.
    """
    if not site:
        raise UniFiError("the policy engine addresses resources under a site, which was not given")
    return f"{api_root(mount, host)}/v2/api/site/{site}"


def _origin(host: str) -> str:
    """The scheme and authority, whether or not the caller supplied a scheme.

    Assumed rather than defaulted to plain http: the application serves TLS, and a
    bare host that silently lost its scheme would produce a request the controller
    answers with something unrelated to the object being managed.
    """
    for prefix in ("http://", "https://"):
        if host.startswith(prefix):
            return host.rstrip("/")
    return f"https://{host.rstrip('/')}"


def base_url_for(
    family: str, controller: str, site: str = "default", mount: str = APPLIANCE
) -> str:
    """Return the base path for one API family on one deployment.

    Refuses a combination the deployment cannot serve rather than defaulting. The
    official family needs a console to have issued a key, and a self-hosted
    appliance has nowhere to issue one, so the refusal belongs here rather than
    arriving as a 403 on an operator's network.
    """
    if mount not in FAMILIES_BY_MOUNT:
        raise UniFiError(f"api_mount must be {APPLIANCE!r} or {CONSOLE!r}, not {mount!r}")
    if family not in FAMILIES_BY_MOUNT[mount]:
        offered = ", ".join(FAMILIES_BY_MOUNT[mount])
        raise UniFiError(
            f"a {mount} deployment serves {offered}, not {family!r}; "
            "an official API key cannot be created on a self-hosted appliance"
        )
    if family == OFFICIAL:
        return official_base(mount, controller)
    return legacy_base(mount, controller, site=site)


def authenticate(
    params: Mapping[str, Any],
    transport: Any = open_transport,
) -> Credentials:
    """Resolve a credential from module parameters.

    Exposed for a module that must prove a connection before doing real work, so
    it need not reach past the client to do it.
    """
    return credentials_from(dict(params), _poster(params, transport))


def _poster(params: Mapping[str, Any], transport: Any) -> Any:
    """Build the login exchange, for a caller that supplies only a transport.

    The exchange is a request through the same transport as everything else, so a
    test that replaces the transport has replaced the login too. That is the
    point: a login that went by a different path would be a live call a test
    could not see.
    """

    def post(path: str, form: dict[str, str]) -> tuple[dict[str, Any], str]:
        # Addressed at the deployment root, not at the application root. A console
        # puts its login above /proxy/network and every resource beneath it, so
        # composing onto the application root asks a path that does not exist.
        # An appliance serves the login at its application root, where the two are
        # the same string.
        control = str(params.get("control_root") or "").rstrip("/")
        if not control:
            controller = str(params.get("controller") or "")
            control = (
                control_root(controller)
                if controller
                else str(params.get("api_root") or params["base_url"]).rstrip("/")
            )
        request = Transport(
            method="POST",
            url=control + path,
            data=json.dumps(form).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            validate_certs=bool(params.get("validate_certs", True)),
            ca_path=str(params.get("ca_path") or ""),
            timeout=int(params.get("timeout") or 30),
        )
        raw: RawResponse = transport(request)
        if raw.status >= 400:
            # The login does not go through the retry and refusal path the rest of
            # a run uses: it is a POST, so it is not retried, and its body is read
            # for a cookie rather than for data. A refusal therefore has to be
            # raised here. A 429 left to fall through becomes "returned no
            # session", which points at the credential and is a rate limit.
            raise from_response(raw.status, "POST", path, message_from_body(raw.text))
        return _as_dict(raw.text), _header_of(raw.headers, "set-cookie")

    return post


def _header_of(headers: Mapping[str, str], wanted: str) -> str:
    """One header's value, matched without regard to case.

    A response's header names arrive with whatever casing the server used, and the
    application sends ``Set-Cookie`` where a test's fake sends ``set-cookie``.
    Matching case-sensitively finds neither reliably, and a missing session cookie
    is reported as a refused login rather than as a lookup that missed.
    """
    for name, value in headers.items():
        if name.lower() == wanted:
            return value
    return ""


def _as_dict(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class UniFiClient:
    """The controller, as one module run sees it.

    Constructed from a parameter mapping rather than from an ``AnsibleModule``, so
    that this file imports nothing heavier than the transport. Every caller in the
    collection is expected to build one of these in a single place.
    """

    def __init__(self, params: Mapping[str, Any], transport: Any = open_transport) -> None:
        self._params = dict(params)
        self._transport = transport
        self.options = ApiOptions(
            base_url=str(params["base_url"]),
            validate_certs=bool(params.get("validate_certs", True)),
            ca_path=str(params.get("ca_path") or ""),
            timeout=int(params.get("timeout") or 30),
        )
        self._credentials = credentials_from(
            self._params,
            _poster(self._params, transport),
        )
        self._api = Api(self.options, self._transport)

    def rebased(self, mount: str = "", *, site: str = "") -> UniFiClient:
        """The same deployment, addressed at a different set of collections.

        The credential, the site and the deployment are the same either way, so a
        caller that needs the policy engine from a site-scoped client composes it
        here rather than reaching for the client's own attributes.

        The mount defaults to the client's own. A caller that restates it can get
        it wrong, and getting it wrong drops the console's proxy prefix, which
        answers 404 and reads like the collection not existing.
        """
        controller = self._params["controller"]
        family = self._params["api_family"]
        resolved = site or str(self._params.get("site") or "")
        resolved_mount = mount or str(self._params.get("api_mount") or APPLIANCE)
        return UniFiClient(
            {
                **self._params,
                "base_url": policy_engine_base(
                    family, controller, site=resolved, mount=resolved_mount
                ),
            },
            self._transport,
        )

    def get(self, resource: str) -> Any:
        """Read the resource named by ``resource``, relative to the base path."""
        return self._call("GET", resource)

    def post(self, resource: str, payload: Mapping[str, Any]) -> Any:
        """Create a resource. Never retried, like every other write."""
        return self._call("POST", resource, dict(payload))

    def set(self, resource: str, payload: Mapping[str, Any]) -> Any:
        """Replace the resource named by ``resource`` with ``payload``.

        A replacement rather than a merge. The controller's own objects are whole
        documents, so a partial update is not offered on most of them and a caller
        that assumed it was would silently clear the fields it did not name.
        """
        return self._call("PUT", resource, dict(payload))

    def delete(self, resource: str) -> Any:
        """Remove a resource. Never retried."""
        return self._call("DELETE", resource)

    def _call(self, method: str, resource: str, body: Any = None) -> Any:
        response = self._api.call(
            method,
            resource,
            body=body,
            headers=self._credentials.header(),
        )
        # The controller replaces the CSRF token during a session and returns the
        # current one, so the credential is told about each reply rather than
        # holding the token the login produced. Skipping this is how a long run
        # starts failing on writes that worked at the start.
        if isinstance(self._credentials, Password):
            self._credentials.observe(response.csrf)
        return response.body
