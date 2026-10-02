# SPDX-License-Identifier: GPL-3.0-or-later
"""The stack's address and credentials, for the live suites.

Separate from the fixtures so a test can import a value without importing a
fixture, and so there is one place a value is written rather than one per suite.
"""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: The stack publishes on loopback, named rather than written as an address
#: because the repository rejects a literal controller endpoint.
LOOPBACK_NAME = "localhost"

#: UniFi OS Server serves its console on 11443 inside the machine, which is how it
#: avoids needing a privileged port, and the VM forwards it to the same number.
UOS_UI_PORT = os.environ.get("UOS_UI_PORT", "11443")

#: The throwaway console account, created by `make uos/up` through the setup API.
#: Throwaway values for a loopback VM; `make uos/up` reads the same variables.
ADMIN = (
    os.environ.get("UOS_USERNAME", "admin"),
    os.environ.get("UOS_CONSOLE_PASSWORD", "throwaway-not-a-secret"),
)

#: A console serves the legacy application behind its proxy prefix and takes the
#: login above that prefix. Both differ from a self-hosted appliance, so they are
#: stated rather than derived from the address.
API_MOUNT = "console"
API_FAMILY = "legacy"
LOGIN_PATH = "/api/auth/login"

#: A MAC address no adopted device on the throwaway stack carries, used to ask
#: for a device the controller does not hold. Locally administered and unicast,
#: so it is an address documentation may use and a device is not holding it.
UNADOPTED_MAC = "de:ad:be:ef:00:01"

#: The address the emulated device announces itself under. `make uos/device`
#: starts it and the controller adopts it, so this one is in the inventory.
EMULATED_MAC = "00:27:22:e0:00:01"

#: The emulated switch. It reports a port table, so it is the device a
#: port-configuration case writes to. Both MACs are declared in
#: tests/live/stack-uos/devices.json and adopted together by `make uos/device`.
EMULATED_SWITCH_MAC = "00:27:22:e0:00:02"

#: The name the write-path cases leave on the emulated device, so a run converges
#: rather than drifting a little each time.
EMULATED_NAME = "verify-emulated"


def controller_host() -> str:
    """The console's address, which is the only thing a run needs to know."""
    return f"{LOOPBACK_NAME}:{UOS_UI_PORT}"


def stack_env() -> Path:
    """The stack's own environment file, which is not committed."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "live" / "stack-uos" / ".env"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / "live" / "stack-uos" / ".env"


def api_key() -> str:
    """The integration key the suite authenticates with.

    A console rate-limits logins to about four in a window, and the collection
    logs in once per task, so a suite of any size refuses itself. The key is
    stateless, so it is not a preference here: without one the suite cannot run.

    Written by `make uos/up`, which mints one after creating the account.
    """
    key = os.environ.get("UOS_API_KEY", "")
    if not key:
        env = stack_env()
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("UOS_API_KEY"):
                    key = line.partition("=")[2].strip()
                    break
    return key


def console_reachable() -> bool:
    """Whether the console answers at all.

    A suite that cannot reach the stack and a suite that ran and failed are
    different states, and only one of them is a defect. Every live fixture is
    session-scoped behind this, so an absent VM skips rather than fails.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(f"https://{controller_host()}/")
    try:
        with urllib.request.urlopen(request, context=context, timeout=10):
            return True
    except urllib.error.HTTPError:
        # An answer is an answer, whatever its status.
        return True
    except Exception:
        return False


def connection(**overrides: Any) -> dict[str, Any]:
    """The connection options every task in the live suites starts from."""
    params: dict[str, Any] = {
        "controller": controller_host(),
        "api_mount": API_MOUNT,
        "api_family": API_FAMILY,
        "site": "default",
        "api_key": api_key(),
        "validate_certs": False,
    }
    params.update(overrides)
    return params


def wlan_network(**overrides: Any) -> dict[str, Any]:
    """The network a wireless network under test rides on.

    Stated once so the suites that need a network to exist agree on its shape,
    and so a suite that names an identifier of its own does not collide with
    another suite's.
    """
    params: dict[str, Any] = {
        "name": "verify-wlan-network",
        "purpose": "corporate",
        "vlan": 150,
        "vlan_enabled": True,
        "subnet": "10.30.150.1/24",
        "dhcp_enabled": True,
        "dhcp_start": "10.30.150.100",
        "dhcp_stop": "10.30.150.200",
        "dhcp_lease_time": 86400,
    }
    params.update(overrides)
    return params


def dhcp_network(**overrides: Any) -> dict[str, Any]:
    """The network a static reservation under test is held on.

    Its own VLAN and range, so a suite reserving an address here cannot collide
    with one reserving in another suite's range, and so that an address outside it
    is outside every network this suite knows about.
    """
    params: dict[str, Any] = {
        "name": "verify-dhcp-network",
        "purpose": "corporate",
        "vlan": 161,
        "vlan_enabled": True,
        "subnet": "10.30.161.1/24",
        "dhcp_enabled": True,
        "dhcp_start": "10.30.161.100",
        "dhcp_stop": "10.30.161.200",
        "dhcp_lease_time": 86400,
    }
    params.update(overrides)
    return params
