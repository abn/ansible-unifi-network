#!/usr/bin/env python
"""Mint an integration API key on the throwaway UniFi OS Server.

The console has no scriptable key endpoint on the legacy Network Server, and its
UI is the only way in. UniFi OS Server does have one, and this drives it with the
console account rather than a browser: the console API takes a username and
password, and the key service sits behind the users proxy.

Prints the key on stdout and nothing else, so the caller can pipe it into a file
without tripping over a progress line.

Reads UOS_URL, UOS_USERNAME and UOS_CONSOLE_PASSWORD from the environment. The
console account is created during setup; see setup.py in this directory.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 30

#: The console answers on its URL before the services behind it are ready, so a
#: single attempt on a fresh machine times out and succeeds on the next run. A
#: reset that works on the second run is a reset that gets called flaky.
ATTEMPTS = 20
INTERVAL_SECONDS = 15.0


def _opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    # The console serves a self-signed certificate, which is the whole point of a
    # throwaway: nothing it presents is trusted by anything else.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )


def _header(headers: dict, wanted: str) -> str:
    """One header by name, matched without regard to case.

    ``dict(response.headers)`` keeps whatever casing the server sent, which is
    ``X-Csrf-Token`` here, and a lookup that guesses the casing finds nothing and
    reports a missing token that was present all along.
    """
    wanted = wanted.lower()
    for name, value in headers.items():
        if name.lower() == wanted:
            return value
    return ""


def _call(opener, base, method, path, body=None, csrf=""):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def _call_when_ready(opener, base, method, path, body=None, csrf=""):
    """Call once the service behind the path is answering.

    A timeout or a connection refusal both mean "not yet": the console is
    reachable well before the service underneath it. Every other answer is
    returned as it is, so a real refusal is not retried into hiding.
    """
    last = (0, "")
    for attempt in range(ATTEMPTS):
        try:
            return _call(opener, base, method, path, body, csrf=csrf)
        except (TimeoutError, urllib.error.URLError) as error:
            last = (0, str(error))
            if attempt + 1 < ATTEMPTS:
                print(
                    f"the console is not answering yet ({error}); retrying",
                    file=sys.stderr,
                )
                time.sleep(INTERVAL_SECONDS)
    return last


def main() -> int:
    base = os.environ.get("UOS_URL", "https://localhost:11443").rstrip("/")
    username = os.environ.get("UOS_USERNAME", "admin")
    password = os.environ.get("UOS_CONSOLE_PASSWORD")
    name = os.environ.get("UOS_KEY_NAME", "verify-stack")

    if not password:
        print("UOS_CONSOLE_PASSWORD is not set", file=sys.stderr)
        return 2

    opener = _opener()

    status, _headers, body = _call_when_ready(
        opener,
        base,
        "POST",
        "/api/auth/login",
        {"username": username, "password": password, "token": "", "rememberMe": False},
    )
    if status != 200:
        print(f"login failed with {status}: {body[:200]}", file=sys.stderr)
        return 1

    # The CSRF token arrives on a response header rather than in the body, and the
    # key service refuses a write without it.
    status, headers, body = _call_when_ready(opener, base, "GET", "/api/users/self")
    csrf = _header(headers, "X-CSRF-Token")
    user = json.loads(body)
    if not csrf:
        print("no CSRF token on the users response", file=sys.stderr)
        return 1

    # The users service is proxied at /proxy/users and its own API prefix is
    # /api, so the key endpoint is three segments deeper than the proxy root.
    path = f"/proxy/users/api/v2/user/{user['unique_id']}/keys"
    status, _headers, body = _call_when_ready(opener, base, "POST", path, {"name": name}, csrf=csrf)
    if status != 200:
        print(f"key creation failed with {status}: {body[:200]}", file=sys.stderr)
        return 1

    key = json.loads(body)["data"]["full_api_key"]
    print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
