#!/usr/bin/env python
"""Create the console account on a fresh UniFi OS Server.

The console has a first-run wizard, and it is driven by two API calls that the
wizard itself makes. Scripting them means `purge` then `up` is a true reset; a
reset that needs a human in a browser is a reset that gets skipped.

Runs against a console that has never been set up. On one that has, `start`
answers differently and this reports that rather than corrupting anything.

Reads UOS_URL, UOS_DEVICE_NAME, UOS_USERNAME, UOS_CONSOLE_PASSWORD,
UOS_TIMEZONE and UOS_COUNTRY from the environment. Prints one line describing the
outcome.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 30

#: The console answers on / as soon as nginx is up, which is minutes before the
#: service that creates an account is ready. A single attempt therefore times out
#: on a fresh install and succeeds on the next run, which is a reset that only
#: works the second time.
SETUP_ATTEMPTS = 20
SETUP_INTERVAL_SECONDS = 15.0


def _post(base: str, path: str, body: dict) -> tuple[int, str]:
    context = ssl.create_default_context()
    # The console serves a self-signed certificate, which is the point of a
    # throwaway: nothing it presents is trusted by anything else.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(
        base + path,
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=TIMEOUT) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def _post_until_ready(base: str, path: str, body: dict) -> tuple[int, str]:
    """Post once the service behind the path is answering.

    A read timeout and a connection refusal both mean "not yet" here, because the
    console is reachable well before the service underneath it is. Every other
    answer is returned as it is, so a real refusal is not retried into hiding.
    """
    last: tuple[int, str] = (0, "")
    for attempt in range(SETUP_ATTEMPTS):
        try:
            return _post(base, path, body)
        except (TimeoutError, urllib.error.URLError) as error:
            last = (0, str(error))
            if attempt + 1 < SETUP_ATTEMPTS:
                print(
                    f"the setup service is not answering yet ({error}); retrying",
                    file=sys.stderr,
                )
                time.sleep(SETUP_INTERVAL_SECONDS)
    return last


def main() -> int:
    base = os.environ.get("UOS_URL", "https://localhost:11443").rstrip("/")
    name = os.environ.get("UOS_DEVICE_NAME", "verify-uos")
    username = os.environ.get("UOS_USERNAME", "admin")
    password = os.environ.get("UOS_CONSOLE_PASSWORD")
    timezone = os.environ.get("UOS_TIMEZONE", "Etc/UTC")
    # 840 is the United States, the same value the wizard sends when its country
    # picker is left alone. It is the picker's numeric code, not ISO 3166-1.
    country = int(os.environ.get("UOS_COUNTRY", "840"))

    if not password:
        print("UOS_CONSOLE_PASSWORD is not set", file=sys.stderr)
        return 2

    status, body = _post_until_ready(base, "/api/setup/start", {"sendTrace": True, "type": "webui"})
    if status in (401, 403):
        # A console that has been set up refuses this, which is how the wizard
        # stops running twice. Treating it as success makes `up` safe to re-run.
        print("console already set up")
        return 0
    if status != 200:
        print(f"setup/start failed with {status}: {body[:200]}", file=sys.stderr)
        return 1
    setup_id = json.loads(body).get("setupId")
    if not setup_id:
        print(f"setup/start returned no setupId: {body[:200]}", file=sys.stderr)
        return 1

    status, body = _post_until_ready(
        base,
        "/api/setup",
        {
            "name": name,
            "timezone": timezone,
            # Both are the wizard's own defaults. Network optimisation would make
            # the console change things it was not asked to change, and
            # diagnostics would send data off the machine.
            "optimizeNetwork": False,
            "sendDiagnostics": False,
            "newAccount": True,
            # dhcp rather than a static address: the VM's addressing belongs to
            # the VM, and pinning it here would be a second place to change it.
            "advancedSetup": {"mode": "dhcp"},
            "username": username,
            "password": password,
            "country": country,
            "setupId": setup_id,
            "raid": "raid5",
        },
    )
    # The console refuses a second setup with 500, and the refusal is not the
    # same shape as the 401 on `start`. Between `start` and this call the console
    # can become set up by another run, so the second guard is needed as well as
    # the first: one is a race with a slow service, the other a race with a second
    # caller.
    if status != 200 and "already setup" in body.lower():
        print("console already set up")
        return 0
    if status != 200:
        print(f"setup failed with {status}: {body[:300]}", file=sys.stderr)
        return 1

    created = json.loads(body)
    print(f"console account created: {created.get('username')} ({created.get('unique_id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
