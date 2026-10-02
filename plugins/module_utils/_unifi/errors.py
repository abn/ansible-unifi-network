# SPDX-License-Identifier: BSD-2-Clause
"""Typed failures for the UniFi controller client.

Internal to this collection. The package path carries a leading underscore, which
declares the kernel private: it may be refactored in any release without a major
version bump. See ``.agents/rules/ansible.md``.

One exception per failure the caller can act on differently. The classification
that matters is the boundary between *the task is wrong* and *the controller
refused*. They look alike in a traceback and they send the operator to opposite
places: a bad argument is fixed in the playbook, an upstream refusal is fixed on
the appliance or by waiting. Collapsing them into one error type is how an
operator ends up re-minting a credential that was never the problem.

Every upstream string passes through :func:`sanitise` before it reaches a
message. A controller's error body carries request data, and a data field can
hold a client address or a submitted value, so the message is taken from the one
field meant for humans and the rest is dropped rather than logged.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "UniFiAuthError",
    "UniFiConcurrencyError",
    "UniFiConnectionError",
    "UniFiError",
    "UniFiNotFoundError",
    "UniFiRateLimitedError",
    "UniFiServerError",
    "UniFiTlsError",
    "UniFiValidationError",
    "from_response",
    "message_from_body",
    "sanitise",
]

#: Anything resembling a credential, wherever it appears in an upstream string.
_CREDENTIAL = re.compile(
    r"(?i)\b(?:token|api[_ -]?key|secret|password|passwd|authorization|bearer)\b\s*[:=]?\s*\S+"
)

#: Collapses a message onto one bounded line.
_WHITESPACE = re.compile(r"\s+")

#: The longest upstream fragment kept in a message. Past this a message stops
#: being readable in a play recap and starts being a data dump.
_MAX_LENGTH = 400


def sanitise(text: object, *, limit: int = _MAX_LENGTH) -> str:
    """Return ``text`` as a single bounded line with credentials removed.

    Redaction happens before truncation, or a long message would be cut in the
    middle of the secret it was supposed to lose.
    """
    if not isinstance(text, str):
        return ""
    cleaned = _CREDENTIAL.sub("[redacted]", text)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "…"
    return cleaned


class UniFiError(Exception):
    """Base for every failure raised by the kernel.

    Carries the request's own coordinates so a message can name the call that
    failed, and holds no response headers: an object carrying headers would carry
    the credential into every transcript that printed it.
    """

    def __init__(self, message: str, *, method: str = "", path: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.method = method
        self.path = path
        self.status = status

    def __str__(self) -> str:
        where = f"{self.method} {self.path}".strip()
        if not where:
            return self.message
        status = f" (HTTP {self.status})" if self.status else ""
        return f"{self.message} [{where}{status}]"


class UniFiValidationError(UniFiError):
    """The controller rejected the request as malformed.

    Usually a field the collection sent is wrong for the object's version, which
    is a collection-side or task-side problem and is fixed in the playbook.
    """


class UniFiAuthError(UniFiError):
    """The credential was refused.

    Distinct from :class:`UniFiConnectionError` on purpose. A legacy session
    expires mid-run and a wrong API key are both refusals, and neither is fixed
    by retrying.
    """


class UniFiNotFoundError(UniFiError):
    """The named object does not exist.

    For a resource addressed by name this usually means the name matched nothing,
    which is a task error rather than an upstream fault. The distinction from a
    genuinely missing object is the caller's to make.
    """


class UniFiConcurrencyError(UniFiError):
    """The document changed between the read and the write.

    The controller exposes no version token on the surfaces this collection
    writes, so the only available strategy is to re-read, recompute, and write
    again, within a bounded number of attempts. Every attempt losing means a
    human or the console changed it in between, and continuing would overwrite
    work this run did not author.
    """


class UniFiTlsError(UniFiError):
    """The controller's certificate did not verify.

    Almost always a self-signed certificate, which is the default on a UniFi
    console. The answer is a CA bundle, not a disabled check.
    """


class UniFiConnectionError(UniFiError):
    """The request never produced a status.

    The controller was not reached, or stopped answering part-way. A retry may or
    may not help, which is why this type exists separately from every status the
    controller produced deliberately.
    """


class UniFiServerError(UniFiError):
    """The controller failed on its own side."""


class UniFiRateLimitedError(UniFiServerError):
    """The controller is rate-limiting this client.

    Distinct from every other server-side failure because the remedy is different
    and nothing else suggests it: the controller is overloaded, the request is
    fine, and the fix is to slow down rather than to change anything. A concurrent
    Ansible run against one controller is the ordinary cause.
    """


def from_response(
    status: int,
    method: str,
    path: str,
    upstream_message: object = "",
) -> UniFiError:
    """Build the error for a refusal, from what the controller said.

    The message is read out of the body by hand rather than by decoding the whole
    body, because the shape differs between the two API families and the one field
    meant for humans is the only part safe to echo.
    """
    detail = sanitise(upstream_message)
    if status in (401, 403):
        # A 403 on the legacy family is the CSRF token going stale, which reads
        # as a permission problem and is not one. Naming the likely cause costs
        # nothing when it is wrong and saves the operator a wild goose chase.
        text = "the controller refused the credential"
        if detail:
            text = f"{text}: {detail}"
        return UniFiAuthError(text, method=method, path=path, status=status)
    if status == 404:
        text = "no such object on the controller"
        if detail:
            text = f"{text}: {detail}"
        return UniFiNotFoundError(text, method=method, path=path, status=status)
    if status == 412:
        # The controller's only lost-update signal on the surfaces it guards.
        return UniFiConcurrencyError(
            "the document changed before the write was applied",
            method=method,
            path=path,
            status=status,
        )
    if status in (400, 409):
        text = "the controller rejected the request"
        if detail:
            text = f"{text}: {detail}"
        return UniFiValidationError(text, method=method, path=path, status=status)
    if status == 429:
        # Named as its own thing because the remedy is different: the controller
        # is overloaded and the answer is to slow down, not to change the request.
        text = "the controller is rate-limiting this client"
        if detail:
            text = f"{text}: {detail}"
        return UniFiRateLimitedError(text, method=method, path=path, status=status)
    text = "the controller failed" if status >= 500 else "the controller refused the request"
    if detail:
        text = f"{text}: {detail}"
    return UniFiError(text, method=method, path=path, status=status)


def message_from_body(body: Any) -> str:
    """Return the human-readable message from a decoded controller body.

    Both families nest the text differently, and the legacy family also uses a
    ``meta`` envelope for some resources. Anything unrecognised yields the empty
    string, because a body shape we do not know is a reason to say less, not to
    guess.
    """
    if not isinstance(body, dict):
        return ""
    for key in ("message", "msg", "error", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    meta = body.get("meta")
    if isinstance(meta, dict):
        value = meta.get("msg")
        if isinstance(value, str) and value:
            return value
    return ""
