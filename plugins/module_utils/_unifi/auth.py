# SPDX-License-Identifier: BSD-2-Clause
"""Credentials for the UniFi controller.

Internal to this collection. See :mod:`._api` for what the private package path
means.

This module opens no socket and imports nothing from ``ansible``. The exchange it
performs is injected, so the whole of it is exercisable with a plain function and
no network, which is what makes the expiry behaviour testable at all: it depends
on a clock, and a clock that cannot be replaced is a clock nobody can test.

The two API families authenticate differently and the difference is not cosmetic.
The official API takes a stateless key in a header. The legacy API takes a
username and password, hands back a session cookie, and expects a CSRF token
with every mutating request, which the controller rotates during the session.
That rotation is why this module captures a token from a response rather than
holding the one it logged in with.

A credential that cannot reach a log is not a convenience here. A controller
refusal is reported to the operator, an operator pastes it into an issue, and a
credential inside that text is a credential in a public place. :class:`Secret`
makes every read of the value a line a review can point at.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiAuthError

__all__ = [
    "ApiKey",
    "Credentials",
    "Password",
    "Secret",
    "Session",
    "SessionOptions",
    "credentials_from",
]

#: Re-mint this long before the controller's own expiry rather than at it. The
#: controller's lifetime is not a promise about clock agreement between it and
#: the host running the play, and a token that expires between the check and the
#: use reads to the operator as a permissions problem.
EXPIRY_MARGIN_SECONDS = 60.0

#: How long a session the controller gave no lifetime for is reused. Long enough
#: to cover a module run and short enough that a genuinely dead session is not
#: carried across many runs.
UNSTATED_LIFETIME_SECONDS = 3600.0

#: The cookie a session arrives in. The application sends it `HttpOnly`, so it
#: cannot be read back out of a browser document and has to be captured from the
#: login response.
SESSION_COOKIE = "unifises"

#: What a login returned. The body alone is not enough: a self-hosted application
#: answers with an empty body and puts the session in a ``Set-Cookie`` header.
Login = tuple[dict[str, Any], str]


#: Where a value came from, for the exchange. Not a credential.
Post = Callable[[str, dict[str, str]], Login]


class Secret:
    """A string that cannot be printed by accident.

    Reachable only through :meth:`expose`. The three dunders are overridden
    because the common ways a value escapes into a log are an f-string, a
    ``%``-format, and a traceback rendering a container.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def expose(self) -> str:
        """Return the value. Every call site is a decision to reveal it."""
        return self._value

    def __repr__(self) -> str:
        return "Secret([redacted])"

    def __str__(self) -> str:
        return "[redacted]"

    def __format__(self, spec: str) -> str:
        return "[redacted]"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class SessionOptions:
    """The deployment details a login needs.

    The base path and the login path are configuration rather than something to
    probe for. A probe is a network call made before the credential has been
    checked, and the deployments differ in exactly the detail a probe would be
    guessing at.
    """

    base_url: str
    login_path: str = "/api/login"
    api_key_header: str = "X-API-KEY"
    username: str = ""


class Credentials:
    """A credential that can produce the header a request carries."""

    def header(self) -> dict[str, str]:
        """The headers this credential adds to every request."""
        raise NotImplementedError


@dataclass(frozen=True)
class ApiKey(Credentials):
    """A stateless key, as the official integration API takes.

    Nothing to exchange and nothing to expire, which is most of why that family
    is preferred wherever it covers the object.
    """

    key: Secret
    header_name: str = "X-API-KEY"

    def header(self) -> dict[str, str]:
        return {self.header_name: self.key.expose()}


class Password(Credentials):
    """A username and password, as the legacy local API takes.

    The exchange is injected, so nothing here knows how to log in, only what to
    do with what logging in returned. The session is cached, because a module run
    addresses many objects and logging in per object would multiply requests
    against a controller that rate-limits them.

    Mutable state in a frozen dataclass is not expressible, so this is an ordinary
    class with one private attribute rather than a frozen one with a private
    attribute set behind its back.
    """

    def __init__(
        self,
        username: str,
        password: Secret,
        post: Post,
        options: SessionOptions,
        *,
        clock: Callable[[], float] = time.monotonic,
        margin: float = EXPIRY_MARGIN_SECONDS,
    ) -> None:
        self._username = username
        self._password = password
        self._post = post
        self._options = options
        self._clock = clock
        self._margin = margin
        self._live: Session | None = None
        self._expires_at = 0.0
        # Set by the transport on every response, so a rotated CSRF token is
        # picked up rather than a write being refused with a token the controller
        # has already replaced.
        self._latest_csrf = ""

    def header(self) -> dict[str, str]:
        session = self._live_session()
        # The rotated token wins over the one the login returned. Preferring the
        # session's own copy is what would send a token the controller has
        # already replaced, and the refusal that causes reads as a permission
        # problem rather than as an expired token.
        csrf = self._latest_csrf or session.csrf
        # The cookie name is part of the request, and the deployments do not agree
        # on it. Sending the bare value, or the right value under the other
        # deployment's name, produces a header the controller does not recognise,
        # and the refusal it answers with is indistinguishable from a bad
        # password.
        headers = {"Cookie": f"{session.cookie_name}={session.cookie}"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        return headers

    def set_clock(self, clock: Callable[[], float]) -> None:
        """Replace the clock the session ages against.

        A public seam rather than a test-only hook, because the behaviour it
        governs is genuinely about time, and the alternative is a test that sleeps,
        which is both slow and no clearer about the margin than this is.
        """
        self._clock = clock

    def observe(self, csrf: str) -> None:
        """Record the CSRF token the controller returned on a response.

        Called with the token rather than the whole header mapping on purpose. A
        mapping here would also carry the session cookie, and this object is the
        one most likely to end up in a message.
        """
        if csrf:
            self._latest_csrf = csrf

    def _live_session(self) -> Session:
        if self._live is not None and self._clock() < self._expires_at:
            return self._live

        response, set_cookie = self._post(
            self._options.login_path,
            {"username": self._username, "password": self._password.expose()},
        )
        session = _session_from(
            response,
            set_cookie=set_cookie,
            fallback_csrf=self._latest_csrf,
        )
        self._live = session
        # A session the controller gave no lifetime for is kept until something
        # says otherwise. Treating "no expiry stated" as "already expired" would
        # re-login on every request, which is a rate-limit problem against a
        # controller that rate-limits, and it would look like working code.
        self._expires_at = self._clock() + max(session.lifetime(), 0.0)
        return session


def _session_from(
    response: dict[str, Any],
    *,
    set_cookie: str = "",
    fallback_csrf: str = "",
) -> Session:
    """Read a session out of a login reply.

    A self-hosted application sets the session in a ``Set-Cookie`` header named
    ``unifises`` and returns an empty JSON body, so the header is the only place
    the value appears. The cookie is ``HttpOnly``, which is why it cannot be read
    back out of a browser document and has to be captured from the response.
    """
    cookie = ""
    cookie_name = SESSION_COOKIE
    for name in (SESSION_COOKIE, "TOKEN", "session_id", "cookie"):
        found = _cookie_value(set_cookie, name)
        if found:
            cookie, cookie_name = found, name
            break
    if not cookie:
        raise UniFiAuthError(
            "the controller accepted the request but returned no session; "
            f"no session cookie in {sorted(_cookie_names(set_cookie)) or 'the response headers'}"
        )

    csrf = fallback_csrf or _cookie_value(set_cookie, "csrf_token")
    if not csrf:
        for name in ("csrf_token", "csrfToken", "csrf", "x-csrf-token"):
            value = response.get(name)
            if isinstance(value, str) and value:
                csrf = value
                break
    if not csrf:
        # A read is accepted without one, so a login that returns no token is not
        # a failure here. The first write is where its absence shows, and it
        # shows as a refused credential rather than as a missing header.
        csrf = ""

    expires_in = response.get("expires_in")
    return Session(
        cookie=cookie,
        csrf=csrf,
        expires_in=expires_in if isinstance(expires_in, (int, float)) else None,
        cookie_name=cookie_name,
    )


def _cookie_names(header: str) -> list[str]:
    """The cookie names a ``Set-Cookie`` header carries.

    A header is several cookies separated by commas, and each carries attributes
    after a semicolon, so a value is the part between the first ``=`` and the
    first ``;`` of its own segment.
    """
    return [segment.partition("=")[0].strip() for segment in _segments(header) if ";" in segment]


def _cookie_value(header: str, wanted: str) -> str:
    """One cookie's value from a ``Set-Cookie`` header, or the empty string."""
    for segment in _segments(header):
        name, equals, rest = segment.partition("=")
        if name.strip() != wanted or not equals:
            continue
        return rest.partition(";")[0].strip()
    return ""


def _segments(header: str) -> list[str]:
    """The comma-separated segments of a ``Set-Cookie`` header."""
    return header.split(",")


@dataclass(frozen=True)
class Session:
    """What a login returned: the cookie and the current CSRF token.

    ``csrf`` is not necessarily the one the login produced, because the controller
    replaces it during the session. This is the one most recently seen.

    ``expires_in`` is the controller's own lifetime in seconds, or ``None`` when
    it did not say, in which case the session is treated as not expiring rather
    than as expiring immediately. Guessing the latter would re-login on every
    request, which is a rate-limit problem wearing a correctness costume.
    """

    cookie: str
    csrf: str
    expires_in: float | None = None

    #: The cookie's own name, which the deployments do not agree on. An appliance
    #: calls it ``unifises`` and a console calls it ``TOKEN``, and a request that
    #: sends the wrong name is refused in a way that reads like a bad password.
    cookie_name: str = SESSION_COOKIE

    def lifetime(self) -> float:
        """How long the session may be reused, in seconds.

        A stated lifetime is shortened by the margin so the session is replaced
        before the controller's own clock says it died. An unstated one is treated
        as very long rather than as zero, because the alternative is a login per
        request against a controller that rate-limits.
        """
        if self.expires_in is None:
            return UNSTATED_LIFETIME_SECONDS
        return self.expires_in - EXPIRY_MARGIN_SECONDS


def credentials_from(params: dict[str, Any], post: Post) -> Credentials:
    """Choose a credential from module parameters.

    Raises rather than returning nothing. A module that proceeds without a
    credential would make a request it had no authority to make, and the failure
    would arrive as a 401 from the controller, which points at the credential
    rather than at the missing option.
    """
    options = SessionOptions(
        base_url=params["base_url"],
        login_path=params.get("login_path") or "/api/auth/login",
        api_key_header=params.get("api_key_header") or "X-API-KEY",
        username=params.get("username") or "",
    )
    api_key = params.get("api_key")
    if api_key:
        return ApiKey(key=Secret(_require(api_key, "api_key")), header_name=options.api_key_header)
    username = params.get("username")
    password = params.get("password")
    if username and password:
        return Password(
            username=username,
            password=Secret(_require(password, "password")),
            post=post,
            options=options,
        )
    raise UniFiAuthError(
        "no credential was given: set api_key, or set username and password",
        method="POST",
        path=options.login_path,
    )


def _require(value: str, name: str) -> str:
    """Reject a value that is present but not usable.

    Whitespace counts as absent because that is what an undefined template
    variable expands to, and treating it as a credential produces a request
    carrying an empty header instead of a task error naming the variable.
    """
    if not value.strip():
        raise UniFiAuthError(f"{name} is set but empty")
    return value
