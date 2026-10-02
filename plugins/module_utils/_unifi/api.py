# SPDX-License-Identifier: BSD-2-Clause
"""The HTTP transport for the UniFi controller.

Internal to this collection. See :mod:`._errors` for what the private package
path means.

This is the only file in the collection that opens a socket, so a test that needs
no network replaces exactly one callable and has then intercepted every possible
request.

**Only reads are ever retried.** A retried write is the one failure that cannot
be taken back: the controller may have applied the change and then lost the
answer, so a second attempt turns a visible failure into a silent divergence
between what the playbook asked for and what the network holds. A ``PUT`` being
idempotent in the HTTP sense is not the question. The question is whether the
collection can distinguish "did not happen" from "happened, and the answer was
lost", and for a write to a network appliance it cannot. Reads are free to
repeat, so they repeat.

**A dropped connection is not a refusal.** A request that never produced a status
raises :class:`._errors.UniFiConnectionError` and never reaches the
status-to-error mapping, because a caller that treats a blip as a 500 will report
a controller fault that did not happen.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import urlencode

from ansible.module_utils.urls import open_url
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiAuthError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiConnectionError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiValidationError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import from_response
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    message_from_body,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import sanitise

__all__ = [
    "RETRYABLE_METHODS",
    "Api",
    "ApiOptions",
    "RawResponse",
    "Response",
    "Transport",
]

#: The only verbs repeated after a rate limit. See the module docstring.
RETRYABLE_METHODS = frozenset({"GET", "HEAD"})

#: How many times a rate-limited read is repeated. One, on purpose: a run should
#: not sit in a retry loop against a controller somebody is administering at the
#: same time, and the operator needs to see real pressure rather than have it
#: hidden behind a loop.
RATE_LIMIT_RETRIES = 1

#: Used when a 429 arrives with no ``Retry-After`` the collection can act on.
DEFAULT_RETRY_AFTER_SECONDS = 1.0

#: A ceiling on a server-supplied ``Retry-After``, so a mistaken or hostile value
#: cannot park a module run for an hour.
MAX_RETRY_AFTER_SECONDS = 30.0

#: Everything that means the request never produced a status. ``URLError`` is a
#: subclass of ``OSError`` and covers a refused connection, a name that does not
#: resolve and a refused TLS handshake. The rest arrive from the response side:
#: ``OSError`` covers a connection accepted and then reset and a read timeout,
#: because ``urllib`` wraps only the request itself and leaves ``getresponse()``
#: and ``read()`` to raise what they raise, and ``IncompleteRead`` is not an
#: ``OSError`` at all and needs ``HTTPException`` alongside it.
TRANSPORT_ERRORS = (OSError, HTTPException)


class RawResponse(NamedTuple):
    """What a transport hands back. Lives for the length of one call."""

    status: int
    text: str
    headers: Mapping[str, str]


class Response(NamedTuple):
    """A successful reply, reduced to what a caller may keep.

    ``headers`` is a mapping of names to values that the caller has explicitly
    asked to keep, not the response's header object. The legacy family rotates
    its CSRF token during a session and returns the current one on every response,
    so the one header that has to survive to the next request is carried here.
    Keeping a single named value is the whole of the exception: a response object
    holding a header mapping would carry the session cookie into every transcript
    that printed it, and printing it is the normal way a failure gets reported.
    """

    status: int
    body: Any
    csrf: str = ""


class Transport(NamedTuple):
    """One request, and the reply as the wire produced it."""

    method: str
    url: str
    data: bytes | None
    headers: Mapping[str, str]
    validate_certs: bool
    ca_path: str
    timeout: int


#: The one thing a test replaces to make the collection network-free.
TransportCall = Callable[[Transport], RawResponse]


@dataclass(frozen=True)
class ApiOptions:
    """Everything about a request that is not the request itself.

    Verification is on by default. ``ca_path`` is the preferred way to accept a
    self-signed certificate, because it keeps verification on and checks the
    certificate the appliance actually presents. ``validate_certs=False`` is a
    supported fallback for an appliance that ships a default self-signed
    certificate and cannot be given a bundle; it accepts any certificate for the
    run. There is deliberately no fingerprint pinning: a pinning implementation
    that gets its own comparison wrong accepts every certificate rather than none.
    """

    base_url: str
    validate_certs: bool = True
    ca_path: str = ""
    timeout: int = 30


def open_transport(request: Transport) -> RawResponse:
    """Perform one request and return the reply.

    The read is inside the ``try`` deliberately. A connection reset after it was
    accepted, a body truncated mid-read and a read timeout all arrive from
    ``getresponse()`` and ``read()`` as ``OSError`` or ``http.client.HTTPException``
    rather than as ``URLError``, and catching only ``URLError`` leaves the three
    commonest network failures reaching the operator as a traceback.
    """
    try:
        response = open_url(
            request.url,
            data=request.data,
            headers=dict(request.headers),
            method=request.method,
            validate_certs=request.validate_certs,
            ca_path=request.ca_path or None,
            timeout=request.timeout,
        )
        status = int(response.status)
        response_headers = dict(response.headers or {})
        text = response.read().decode("utf-8", "replace")
    except HTTPError as error:
        status = int(error.code)
        response_headers = dict(error.headers or {})
        text = error.read().decode("utf-8", "replace")
    except TRANSPORT_ERRORS as error:
        raise UniFiConnectionError(
            f"the controller was not reached: {type(error).__name__}",
            method=request.method,
        ) from error
    return RawResponse(status=status, text=text, headers=response_headers)


class Api:
    """The controller as the collection talks to it.

    Holds the connection options and a transport, and adds only what the
    transport does not: JSON encoding, decoding, and the status policy.
    """

    def __init__(self, options: ApiOptions, transport: TransportCall = open_transport) -> None:
        self._options = options
        self._transport = transport

    def call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str | Sequence[str]] | None = None,
    ) -> Response:
        """Send one request and return the parsed body of a success.

        The path is joined onto ``base_url`` here and nowhere else. A call site
        that assembled its own URL would be free to forget the deployment's base
        path, and on a console that difference is a 404 that reads like a missing
        object.
        """
        verb = method.upper()
        url = self._options.base_url.rstrip("/") + path
        # Carried apart from the path so a failure reports the resource rather
        # than the filters. A filter can hold a client address, and a request line
        # in a message outlives the run.
        failure_path = path
        if query:
            url = f"{url}?{_query_of(query)}"

        request_headers = dict(headers or {})
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = Transport(
            method=verb,
            url=url,
            data=data,
            headers=request_headers,
            validate_certs=self._options.validate_certs,
            ca_path=self._options.ca_path,
            timeout=self._options.timeout,
        )

        raw = self._once_with_retries(request, failure_path)
        body = _decode(raw.text)
        _refuse_if_error(raw, body, request.method, failure_path)
        return Response(status=raw.status, body=body, csrf=_csrf_of(raw.headers))

    def _once_with_retries(self, request: Transport, failure_path: str) -> RawResponse:
        """Send a request, repeating a rate-limited read once.

        A write is never repeated, so a rate limit on one surfaces as a failure
        rather than as a second attempt at something that may already have
        applied.
        """
        attempt = 0
        while True:
            raw = self._transport(request)
            if raw.status != 429:
                return self._check(raw, request.method, failure_path)
            if request.method not in RETRYABLE_METHODS or attempt >= RATE_LIMIT_RETRIES:
                raise from_response(raw.status, request.method, failure_path, _upstream(raw.text))
            attempt += 1
            time.sleep(_retry_after(raw))

    def _check(self, raw: RawResponse, method: str, path: str) -> RawResponse:
        if 200 <= raw.status < 300:
            return raw
        raise from_response(raw.status, method, path, _upstream(raw.text))


def _query_of(query: Mapping[str, str | Sequence[str]]) -> str:
    """A request's query string.

    ``doseq`` is required rather than convenient: a repeated name is how the
    controller expresses more than one filter, so a joined value would be one
    filter matching nothing. A string is excluded explicitly, because it is itself
    a sequence and would otherwise be exploded into its characters.
    """
    if not query:
        return ""
    return urlencode([(k, v) for k, v in query.items() if v not in (None, "")], doseq=True)


def _refuse_if_error(raw: RawResponse, body: Any, method: str, path: str) -> None:
    """Raise when a successful status carries a refusal in the body.

    The controller signals a refusal two ways: the status, which this module
    already reads, and an error code in the body's own envelope. Measured against
    10.6.106 they agree, so reading only the status is sufficient today. Reading
    only the status is also how a controller that answers a refusal with a
    successful status would be believed, and the result would be a module that
    reports a change the controller declined to make.
    """
    if not isinstance(body, Mapping):
        return
    meta = body.get("meta")
    if not isinstance(meta, Mapping) or meta.get("rc") != "error":
        return
    detail = sanitise(meta.get("msg")) or "no reason given"
    if "login" in detail.lower():
        raise UniFiAuthError(detail, method=method, path=path, status=raw.status)
    raise UniFiValidationError(detail, method=method, path=path, status=raw.status)


def _csrf_of(headers: Mapping[str, str]) -> str:
    """The CSRF token a response carries, if it carries one.

    The legacy family replaces this token during a session and returns the current
    one, so a credential that keeps the one it logged in with starts being refused
    part-way through a run. Only this value is lifted out of the response; the
    session cookie in the same headers is deliberately not kept.
    """
    for name, value in headers.items():
        if name.lower() == "x-csrf-token" and value:
            return value
    return ""


def _retry_after(raw: RawResponse) -> float:
    """How long to wait before the one permitted retry."""
    for name, value in raw.headers.items():
        if name.lower() == "retry-after":
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                return DEFAULT_RETRY_AFTER_SECONDS
            if seconds < 0:
                return DEFAULT_RETRY_AFTER_SECONDS
            return min(seconds, MAX_RETRY_AFTER_SECONDS)
    return DEFAULT_RETRY_AFTER_SECONDS


def _decode(text: str) -> Any:
    """Parse a response body, or return the raw text when it is not JSON.

    A controller that answers a write with an empty body is normal, and a write
    that returns HTML is a proxy's idea of an error page. Neither is worth
    failing to represent, so the caller receives what actually arrived.
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _upstream(text: str) -> str:
    """The human-readable part of a refusal, if the body carries one."""
    return message_from_body(_decode(text))
