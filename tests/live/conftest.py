# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures shared by the live suites.

One controller, one session. The application rate-limits, and a suite that logged
in per test would be slower for no benefit and would look like a rate-limit
problem when it failed.
"""

from __future__ import annotations

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import api_root
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import base_url_for
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import control_root
from tests.live.settings import API_FAMILY
from tests.live.settings import API_MOUNT
from tests.live.settings import api_key
from tests.live.settings import console_reachable
from tests.live.settings import controller_host
from tests.live.settings import stack_env


@pytest.fixture(scope="session", autouse=True)
def _require_the_stack() -> None:
    """Skip rather than fail when the stack is absent.

    A suite that could not run and a suite that ran and failed are different
    states, and only one of them is a defect.
    """
    if not console_reachable():
        pytest.skip(
            f"the throwaway stack is not answering on https://{controller_host()}/; "
            "run `make uos/up`"
        )
    if not api_key():
        pytest.skip(
            f"no integration key; `make uos/up` mints one into {stack_env()} or set UOS_API_KEY"
        )


@pytest.fixture(scope="session")
def controller() -> UniFiClient:
    """A session against the throwaway controller.

    The base path is composed rather than passed, so this exercises the same path a
    module would resolve: the console at its prefix and the site beneath it. A key
    is stateless, so there is no login and nothing to reuse between tests.
    """
    host = controller_host()
    params = {
        "controller": host,
        "api_family": API_FAMILY,
        "api_mount": API_MOUNT,
        "site": "default",
        "api_key": api_key(),
        "validate_certs": False,
    }
    params["base_url"] = base_url_for(API_FAMILY, host, site=params["site"], mount=API_MOUNT)
    params["api_root"] = api_root(API_MOUNT, host)
    params["control_root"] = control_root(host)
    return UniFiClient(params)


@pytest.fixture(scope="session")
def client(controller: UniFiClient) -> UniFiClient:
    """Alias, so a test reads `client` rather than `controller`."""
    return controller
