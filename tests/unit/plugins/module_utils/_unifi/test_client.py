# SPDX-License-Identifier: GPL-3.0-or-later
"""Where each API family lives on each kind of deployment.

The base path is a property of where the application is mounted, not of which
API is being spoken. A self-hosted application serves its own API at the root and
answers 404 for the console path; a console proxies it beneath the OS, where the
same path is correct.

These are the combinations a task can ask for, and the ones that cannot exist.
Refusing an impossible combination here is what keeps it from arriving as a 403 on
an operator's network.
"""

from __future__ import annotations

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import APPLIANCE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import CONSOLE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import LEGACY
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import OFFICIAL
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import api_root
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import base_url_for
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import control_root
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import (
    policy_engine_base,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError

HOST = "unifi.example.invalid"


def test_an_appliance_serves_the_legacy_family_at_the_root() -> None:
    # A request for the console path on a self-hosted appliance answers 404, so a
    # base path carrying the proxy prefix reads as a missing object rather than as
    # a wrong address.
    assert base_url_for(LEGACY, HOST, "default", APPLIANCE) == f"https://{HOST}/api/s/default"


def test_a_console_proxies_the_legacy_family_beneath_the_os() -> None:
    assert base_url_for(LEGACY, HOST, "default", CONSOLE) == (
        f"https://{HOST}/proxy/network/api/s/default"
    )


def test_a_console_serves_the_official_family_under_the_same_prefix() -> None:
    assert base_url_for(OFFICIAL, HOST, site="", mount=CONSOLE) == (
        f"https://{HOST}/proxy/network/integration"
    )


def test_an_appliance_cannot_serve_the_official_family() -> None:
    # The endpoint is mounted and answers 403, but there is nowhere on a
    # self-hosted appliance to create the key it requires. Failing here says so;
    # failing at apply time says it as a permission error on someone's network.
    with pytest.raises(UniFiError, match="key cannot be created"):
        base_url_for(OFFICIAL, HOST, "default", APPLIANCE)


def test_the_refusal_names_what_the_deployment_offers() -> None:
    with pytest.raises(UniFiError, match="legacy"):
        base_url_for(OFFICIAL, HOST, "default", APPLIANCE)


def test_an_unknown_mount_is_refused() -> None:
    with pytest.raises(UniFiError, match="api_mount"):
        base_url_for(LEGACY, HOST, "default", "cloud")


def test_the_legacy_family_needs_a_site() -> None:
    # Legacy resources are addressed beneath a site slug. The official family does
    # not use one, which is why this is checked only for legacy.
    with pytest.raises(UniFiError, match="site"):
        base_url_for(LEGACY, HOST, "", APPLIANCE)


def test_the_official_family_needs_no_site() -> None:
    # It addresses sites by UUID, so requiring a slug of it would be a fiction.
    assert base_url_for(OFFICIAL, HOST, site="", mount=CONSOLE).endswith("/integration")


def test_a_host_that_carries_its_own_scheme_is_not_given_another() -> None:
    base = base_url_for(LEGACY, "https://unifi.example.invalid:8443", "default", APPLIANCE)

    assert base == "https://unifi.example.invalid:8443/api/s/default"


def test_a_bare_host_is_given_https() -> None:
    # The application serves TLS, so a bare host means https rather than whatever
    # the module happens to default to.
    assert base_url_for(LEGACY, HOST, "default", APPLIANCE).startswith("https://")


def test_a_port_in_the_host_survives() -> None:
    base = base_url_for(LEGACY, HOST + ":8443", "default", APPLIANCE)

    assert base == f"https://{HOST}:8443/api/s/default"


@pytest.mark.parametrize("mount", [APPLIANCE, CONSOLE])
def test_no_base_path_ends_in_a_slash(mount: str) -> None:
    # A doubled separator at the join point reads as a 404 that names the resource
    # rather than the path.
    for family in (LEGACY, OFFICIAL):
        try:
            base = base_url_for(family, HOST, "default", mount)
        except UniFiError:
            continue
        assert not base.endswith("/"), (mount, family)


def test_the_policy_engine_sits_above_the_site_rather_than_beneath_it() -> None:
    # The configuration endpoints hang under /api/s/{site}; the policy engine is
    # served from above it, so a module addressing one cannot use the site's base.
    assert base_url_for(LEGACY, HOST, "default", APPLIANCE).endswith("/api/s/default")
    assert policy_engine_base(LEGACY, HOST, site="default", mount=APPLIANCE).endswith(
        "/v2/api/site/default"
    )


def test_the_policy_engine_base_carries_no_dot_segments() -> None:
    # Reaching the policy engine by climbing out of the site base with `..` works
    # only while that base has exactly the shape it has today, and a change to it
    # would break the path silently.
    base = policy_engine_base(LEGACY, HOST, site="default", mount=CONSOLE)

    assert ".." not in base
    assert base == f"https://{HOST}/proxy/network/v2/api/site/default"


def test_the_policy_engine_needs_a_site() -> None:
    with pytest.raises(UniFiError, match="site"):
        policy_engine_base(LEGACY, HOST, site="", mount=APPLIANCE)


def test_the_login_is_addressed_above_the_application_prefix() -> None:
    # A console serves its login above /proxy/network and every resource beneath
    # it, so composing the login onto the application root asks a path that does
    # not exist. The answer is a 401, which reads like a wrong credential.
    assert api_root(CONSOLE, HOST) == f"https://{HOST}/proxy/network"
    assert control_root(HOST) == f"https://{HOST}"


def test_the_login_root_and_the_application_root_agree_on_an_appliance() -> None:
    # On an appliance the login is at the application root, so the two are the
    # same string.
    assert api_root(APPLIANCE, HOST) == f"https://{HOST}"
    assert control_root(HOST) == api_root(APPLIANCE, HOST)


def test_an_official_key_on_an_appliance_is_refused_where_the_mount_is_resolved() -> None:
    # The combination cannot exist: an appliance has nowhere to issue an official
    # key. Refusing here names the reason rather than arriving as a permission
    # error on an operator's network.
    with pytest.raises(UniFiError, match="key"):
        base_url_for(OFFICIAL, HOST, "default", APPLIANCE)
