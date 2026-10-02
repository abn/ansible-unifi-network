# SPDX-License-Identifier: GPL-3.0-or-later
"""Credentials, exercised with the login exchange injected.

No test here opens a socket. The exchange is a function, so a login is a return
value and the interesting behaviour, which is what happens as the session ages
and the controller rotates its CSRF token, is directly reachable.

The cases are the ones that would otherwise surface during a long play against
the real controller: a token that expires mid-run, one that rotates without
warning, a session the controller gave no lifetime for, and a credential that is
present in the variables but empty.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import (
    EXPIRY_MARGIN_SECONDS,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import ApiKey
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import Password
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import Secret
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import SessionOptions
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import _session_from
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.auth import credentials_from
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiAuthError

BASE = {"base_url": "https://unifi.invalid/proxy/network"}


#: What a self-hosted application actually returns from `/api/login`: an empty
#: body, the session in a `Set-Cookie` header under `unifises`, and the CSRF token
#: in a readable cookie of its own.
SET_COOKIE = "unifises=session-value; Path=/; HttpOnly, csrf_token=token-value; Path=/"


class LoginSpy:
    """A login exchange that records what it was asked for.

    A class rather than a function with an attribute bolted on, so the type
    checker can see the recording and a test can assert on it without a cast.
    """

    def __init__(
        self,
        returning: dict[str, Any] | None = None,
        set_cookie: str = SET_COOKIE,
    ) -> None:
        self.returning = returning if returning is not None else {}
        self.set_cookie = set_cookie
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, path: str, form: dict[str, str]) -> tuple[dict[str, Any], str]:
        self.calls.append((path, form))
        return self.returning, self.set_cookie


def a_session_credential(post: LoginSpy, **extra: Any) -> Password:
    """A password credential, narrowed so the session API is visible to the checker."""
    credential = credentials_from(
        {**BASE, "username": "admin", "password": "pw", **extra},
        post,
    )
    assert isinstance(credential, Password)
    return credential


def test_an_api_key_becomes_one_header() -> None:
    credential = credentials_from({**BASE, "api_key": "key-value"}, LoginSpy({}))

    assert isinstance(credential, ApiKey)
    assert credential.header() == {"X-API-KEY": "key-value"}


def test_a_username_and_password_become_a_session() -> None:
    credential = a_session_credential(LoginSpy())

    headers = credential.header()

    assert headers["Cookie"] == "unifises=session-value"
    assert headers["X-CSRF-Token"] == "token-value"


def test_a_secret_cannot_be_printed() -> None:
    secret = Secret("hunter2")

    assert str(secret) == "[redacted]"
    assert repr(secret) == "Secret([redacted])"
    assert f"{secret}" == "[redacted]"
    assert secret.expose() == "hunter2"


def test_no_credential_is_an_auth_error_naming_the_option() -> None:
    with pytest.raises(UniFiAuthError, match="api_key"):
        credentials_from(dict(BASE), LoginSpy({}))


def test_a_whitespace_credential_is_treated_as_absent() -> None:
    # This is what an undefined template variable expands to, and treating it as a
    # credential produces a request with an empty header instead of a task error.
    with pytest.raises(UniFiAuthError, match="empty"):
        credentials_from({**BASE, "api_key": "   "}, LoginSpy({}))


def test_the_session_is_reused_rather_than_logged_in_per_request() -> None:
    post = LoginSpy()
    credential = a_session_credential(post)

    credential.header()
    credential.header()
    credential.header()

    assert len(post.calls) == 1


def test_a_rotated_csrf_token_is_used_by_the_next_write() -> None:
    # The controller replaces this token during a session. Holding the one the
    # login returned is how a long run starts failing on writes that worked at the
    # start.
    credential = a_session_credential(LoginSpy())

    credential.header()
    credential.observe("rotated")

    assert credential.header()["X-CSRF-Token"] == "rotated"


def test_an_empty_observation_does_not_clear_the_token() -> None:
    credential = a_session_credential(LoginSpy())
    credential.header()

    credential.observe("")

    assert credential.header()["X-CSRF-Token"] == "token-value"


def test_an_expiring_session_is_replaced_before_the_token_expires() -> None:
    now = [0.0]
    post = LoginSpy({"expires_in": 300.0})
    credential = a_session_credential(post)
    credential.set_clock(lambda: now[0])

    credential.header()

    # One second before the controller's own lifetime elapses, which is already
    # inside the margin.
    now[0] = 300.0 - EXPIRY_MARGIN_SECONDS - 1
    credential.header()
    assert len(post.calls) == 1

    # Past the margin, so a new session is minted before the old one dies.
    now[0] = 300.0 - EXPIRY_MARGIN_SECONDS + 1
    credential.header()
    assert len(post.calls) == 2


def test_a_login_returning_no_cookie_is_an_auth_failure() -> None:
    # An empty session would produce a request with no session, which the
    # controller refuses as an auth problem and misreports as a permission one.
    credential = a_session_credential(LoginSpy(set_cookie="csrf_token=token-value; Path=/"))

    with pytest.raises(UniFiAuthError, match="no session"):
        credential.header()


def test_a_login_that_says_nothing_about_expiry_is_not_re_logged_in_every_call() -> None:
    # Guessing a short expiry would re-login on every request, which is a
    # rate-limit problem wearing a correctness costume.
    post = LoginSpy()
    credential = a_session_credential(post)
    credential.set_clock(lambda: 0.0)

    credential.header()
    credential.header()

    assert len(post.calls) == 1


def test_the_login_path_comes_from_the_deployment_not_a_probe() -> None:
    post = LoginSpy()

    a_session_credential(post, login_path="/api/login").header()

    assert post.calls[0][0] == "/api/login"


def test_the_login_form_carries_the_password_and_nothing_else() -> None:
    post = LoginSpy()

    a_session_credential(post).header()

    assert post.calls[0][1] == {"username": "admin", "password": "pw"}


def test_the_session_options_carry_the_configured_base() -> None:
    options = SessionOptions(base_url=BASE["base_url"])

    assert options.base_url == BASE["base_url"]
    assert options.api_key_header == "X-API-KEY"


def test_a_password_credential_does_not_print_its_secret() -> None:
    credential = Password(
        username="admin",
        password=Secret("hunter2"),
        post=LoginSpy(),
        options=SessionOptions(base_url=BASE["base_url"]),
    )

    assert "hunter2" not in str(credential.__dict__)


def test_a_session_remembers_the_cookie_name_it_arrived_under() -> None:
    # A console names the session cookie TOKEN where an appliance names it
    # unifises. A request that sends the value under the wrong name is refused
    # exactly as a wrong password is, so the name is carried rather than assumed.
    session = _session_from({}, set_cookie="TOKEN=abc123; Path=/; HttpOnly")

    assert session.cookie_name == "TOKEN"


def test_a_carried_session_sends_its_cookie_under_its_own_name() -> None:
    def no_login(path: str, form: dict[str, str]) -> tuple[dict[str, Any], str]:
        raise AssertionError("a live session was replaced by a login")

    credential = Password(
        options=SessionOptions(base_url=BASE["base_url"]),
        username="admin",
        password=Secret("hunter2"),
        post=no_login,
    )
    # The credential reuses a live session, so the one planted here is the one the
    # header is built from. The expiry is set because a session past its expiry is
    # replaced by a real login rather than used.
    credential._live = _session_from({}, set_cookie="TOKEN=abc123; Path=/")
    credential._expires_at = float("inf")

    assert credential.header()["Cookie"] == "TOKEN=abc123"


def test_an_appliance_session_keeps_its_own_cookie_name() -> None:
    session = _session_from({}, set_cookie="unifises=xyz; Path=/")

    assert session.cookie_name == "unifises"
