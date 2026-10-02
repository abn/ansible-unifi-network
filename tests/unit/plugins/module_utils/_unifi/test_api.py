# SPDX-License-Identifier: GPL-3.0-or-later
"""The transport, exercised entirely through an injected fake.

Every test here replaces the one callable that opens a socket, so the suite
cannot reach a controller even by accident. That is the property being asserted
by construction rather than by inspection: there is no network call in these
tests to point at.

The cases chosen are the ones that would otherwise be found in production. A
retried write, a lost response, a rotated CSRF token and an unknown family are
all invisible in a happy-path test and all expensive when they happen.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import (
    MAX_RETRY_AFTER_SECONDS,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import Api
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import ApiOptions
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import RawResponse
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import Transport
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiAuthError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiConcurrencyError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiNotFoundError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiRateLimitedError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiValidationError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import sanitise


def reply(
    status: int = 200,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> RawResponse:
    text = "" if body is None else json.dumps(body)
    return RawResponse(status=status, text=text, headers=headers or {})


@pytest.fixture
def sent() -> list[Transport]:
    return []


@pytest.fixture
def options() -> ApiOptions:
    # A base URL with no host, so a test that somehow reaches the transport fails
    # loudly instead of dialling somewhere.
    return ApiOptions(base_url="https://unifi.invalid/proxy/network")


def test_a_get_returns_the_parsed_body(options: ApiOptions, sent: list[Transport]) -> None:
    api = Api(options, lambda request: (sent.append(request), reply(200, {"name": "Default"}))[1])

    response = api.call("GET", "/v1/networks")

    assert response.status == 200
    assert response.body == {"name": "Default"}


def test_the_path_is_joined_onto_the_base_url(options: ApiOptions, sent: list[Transport]) -> None:
    api = Api(options, lambda request: (sent.append(request), reply(200))[1])

    api.call("GET", "/v1/networks")

    assert sent[0].url == "https://unifi.invalid/proxy/network/v1/networks"


def test_a_trailing_slash_on_the_base_is_not_doubled(
    options: ApiOptions, sent: list[Transport]
) -> None:
    api = Api(ApiOptions(base_url="https://unifi.invalid/proxy/network/"), _record(sent, reply()))

    api.call("GET", "/v1/networks")

    assert "//v1" not in sent[0].url


def test_a_write_sends_json_and_says_so(options: ApiOptions, sent: list[Transport]) -> None:
    api = Api(options, _record(sent, reply(200)))

    api.call("PUT", "/rest/networkconf/abc", body={"name": "IoT"})

    body = sent[0].data
    assert body is not None
    assert json.loads(body) == {"name": "IoT"}
    assert sent[0].headers["Content-Type"] == "application/json"


def test_a_read_is_retried_once_after_a_rate_limit(
    options: ApiOptions, sent: list[Transport]
) -> None:
    replies = [reply(429, headers={"Retry-After": "0"}), reply(200, {"ok": True})]
    api = Api(options, lambda request: (sent.append(request), replies.pop(0))[1])

    response = api.call("GET", "/v1/networks")

    assert response.status == 200
    assert len(sent) == 2


def test_a_write_is_never_retried(options: ApiOptions, sent: list[Transport]) -> None:
    api = Api(options, _record(sent, reply(429, headers={"Retry-After": "0"})))

    with pytest.raises(UniFiRateLimitedError):
        api.call("PUT", "/rest/networkconf/abc", body={"name": "IoT"})

    assert len(sent) == 1


def test_a_read_giving_up_on_a_rate_limit_says_so() -> None:
    # The remedy here is to slow down, which nothing else in the message suggests.
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: reply(429, headers={"Retry-After": "0"}),
    )

    with pytest.raises(UniFiRateLimitedError, match="rate-limiting"):
        api.call("GET", "/v1/networks")


def test_a_read_gives_up_after_one_retry(options: ApiOptions, sent: list[Transport]) -> None:
    api = Api(options, _record(sent, reply(429, headers={"Retry-After": "0"})))

    with pytest.raises(UniFiRateLimitedError):
        api.call("GET", "/v1/networks")

    assert len(sent) == 2


def test_a_hostile_retry_after_is_clamped() -> None:
    from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.api import _retry_after

    clamped = _retry_after(reply(429, headers={"Retry-After": "86400"}))

    assert clamped == MAX_RETRY_AFTER_SECONDS


def test_a_rotated_csrf_token_is_lifted_off_the_response(options: ApiOptions) -> None:
    api = Api(options, lambda request: reply(200, {"ok": True}, {"X-CSRF-Token": "rotated"}))

    response = api.call("GET", "/v1/networks")

    assert response.csrf == "rotated"


def test_a_response_without_a_csrf_token_reports_none() -> None:
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"), lambda request: reply(200, {"ok": True})
    )

    assert api.call("GET", "/x").csrf == ""


def test_a_404_is_not_a_missing_object_ambiguity() -> None:
    api = Api(ApiOptions(base_url="https://unifi.invalid"), lambda request: reply(404, {}))

    with pytest.raises(UniFiNotFoundError):
        api.call("GET", "/rest/networkconf/missing")


def test_a_401_is_an_auth_failure() -> None:
    api = Api(ApiOptions(base_url="https://unifi.invalid"), lambda request: reply(401, {}))

    with pytest.raises(UniFiAuthError):
        api.call("GET", "/v1/sites")


def test_a_412_is_a_lost_update() -> None:
    api = Api(ApiOptions(base_url="https://unifi.invalid"), lambda request: reply(412, {}))

    with pytest.raises(UniFiConcurrencyError):
        api.call("PUT", "/rest/device/abc", body={})


def test_the_upstream_message_reaches_the_operator() -> None:
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: reply(400, {"meta": {"msg": "vlan_id is out of range"}}),
    )

    with pytest.raises(UniFiValidationError, match="vlan_id is out of range"):
        api.call("PUT", "/rest/networkconf/abc", body={})


def test_a_non_json_body_reaches_the_caller_rather_than_raising() -> None:
    # A proxy's error page is not a controller answer, and failing to represent it
    # loses the only evidence that something other than the controller answered.
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: RawResponse(status=200, text="<html>gateway</html>", headers={}),
    )

    assert api.call("GET", "/v1/networks").body == "<html>gateway</html>"


def test_an_empty_body_is_none_rather_than_a_parse_error() -> None:
    api = Api(ApiOptions(base_url="https://unifi.invalid"), lambda request: reply(204))

    assert api.call("PUT", "/rest/networkconf/abc", body={}).body is None


def test_a_repeated_query_value_is_repeated_not_joined() -> None:
    sent: list[Transport] = []
    api = Api(ApiOptions(base_url="https://unifi.invalid"), _record(sent, reply(200)))

    api.call("GET", "/stat/device", query={"mac": ["aa", "bb"]})

    assert sent[0].url.count("mac=") == 2


def test_an_empty_query_value_is_dropped() -> None:
    sent: list[Transport] = []
    api = Api(ApiOptions(base_url="https://unifi.invalid"), _record(sent, reply(200)))

    api.call("GET", "/stat/device", query={"mac": "", "vlan": "20"})

    assert "mac=" not in sent[0].url
    assert "vlan=20" in sent[0].url


def test_a_credential_in_an_upstream_message_is_redacted() -> None:
    redacted = sanitise("failed for token=abc123secret at 10:00")

    assert "abc123secret" not in redacted
    assert "[redacted]" in redacted


def test_a_long_message_is_bounded() -> None:
    assert len(sanitise("x" * 1000)) <= 400


def test_redaction_happens_before_truncation() -> None:
    # Truncating first would cut the message in the middle of the secret it was
    # supposed to lose, which is the one ordering that defeats the whole measure.
    padded = "y" * 500 + " token=abc123secret"
    assert "abc123secret" not in sanitise(padded)


def _record(sent: list[Transport], response: RawResponse) -> Any:
    def call(request: Transport) -> RawResponse:
        sent.append(request)
        return response

    return call


def test_a_refusal_in_a_successful_status_is_still_a_refusal() -> None:
    # The controller signals a refusal with the status today, and also with an
    # error code in its own envelope. Believing the status alone is how a
    # controller that answered a refusal with a 200 would be taken at its word,
    # and the module would report a change it never made.
    body = json.dumps({"meta": {"rc": "error", "msg": "api.err.VlanUsed"}, "data": []})
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: RawResponse(status=200, text=body, headers={}),
    )

    with pytest.raises(UniFiValidationError, match="VlanUsed"):
        api.call("POST", "/rest/networkconf")


def test_a_login_refusal_in_a_successful_status_is_an_auth_failure() -> None:
    body = json.dumps({"meta": {"rc": "error", "msg": "api.err.LoginRequired"}, "data": []})
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: RawResponse(status=200, text=body, headers={}),
    )

    with pytest.raises(UniFiAuthError):
        api.call("GET", "/rest/networkconf")


def test_a_successful_envelope_is_not_mistaken_for_a_refusal() -> None:
    body = json.dumps({"meta": {"rc": "ok"}, "data": [{"name": "Default"}]})
    api = Api(
        ApiOptions(base_url="https://unifi.invalid"),
        lambda request: RawResponse(status=200, text=body, headers={}),
    )

    assert api.call("GET", "/rest/networkconf").body["data"][0]["name"] == "Default"
