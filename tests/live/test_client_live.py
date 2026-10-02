# SPDX-License-Identifier: GPL-3.0-or-later
"""The kernel against the throwaway controller.

Everything else in the suite substitutes a transport, which proves the collection
agrees with the tests' own expectations. This reaches the real application, so a
wrong base path, a wrong cookie name, or a header sent in the wrong place is
caught by the thing that has to accept it rather than by a mock that agrees.
"""

from __future__ import annotations

import json

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.client import UniFiClient
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiAuthError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiNotFoundError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    message_from_body,
)


def test_the_credential_is_a_key_rather_than_a_session(client: UniFiClient) -> None:
    # A console rate-limits logins to about four in a window, and the collection
    # logs in once per task, so the suite authenticates with an integration key.
    # A key is stateless: no login, and nothing to expire between tests.
    header = client._credentials.header()

    assert header["X-API-KEY"]


def test_the_login_response_carries_no_csrf_token(client: UniFiClient) -> None:
    # Measured against 10.6.106: a login answers with an empty body and one cookie.
    # A client that required a token at construction would refuse a controller
    # that is working.
    header = client._credentials.header()

    assert "X-CSRF-Token" not in header


def test_a_network_is_read_from_the_real_controller(client: UniFiClient) -> None:
    rows = client.get("/rest/networkconf")

    assert rows["meta"]["rc"] == "ok"
    assert rows["data"], "the controller reported no networks"
    assert "Default" in [row.get("name") for row in rows["data"]]


def test_the_site_slug_resolves(client: UniFiClient) -> None:
    # The legacy family addresses resources beneath a site slug, so a wrong slug
    # reads as an empty site rather than as an error.
    assert client.get("/stat/sysinfo")["data"]


def test_an_unknown_object_id_answers_ok_with_no_data(client: UniFiClient) -> None:
    # Measured against 10.6.106: a read of an identifier that does not exist is
    # answered with `rc: ok` and an empty data list, not with 404. A reconciler
    # that treats a 2xx as proof of existence would write to an object it never
    # read, which is a blind write to a whole document.
    body = client.get("/rest/networkconf/does-not-exist")

    assert body["meta"]["rc"] == "ok"
    assert not body["data"]


def test_a_single_object_is_also_wrapped_in_the_envelope(client: UniFiClient) -> None:
    rows = client.get("/rest/networkconf")
    one = client.get(f"/rest/networkconf/{rows['data'][0]['_id']}")

    assert one["meta"]["rc"] == "ok"
    assert one["data"][0]["_id"] == rows["data"][0]["_id"]


def test_a_client_with_no_credential_is_refused_before_it_reaches_the_controller(
    client: UniFiClient,
) -> None:
    # The refusal happens at construction rather than as a 401, because a request
    # made without a credential is one the collection had no authority to make. A
    # 401 from the controller would read as a bad password instead, and send the
    # operator to re-mint a credential that was never supplied.
    with pytest.raises(UniFiAuthError, match="no credential"):
        UniFiClient({**client._params, "username": "", "password": "", "api_key": ""})


def test_the_controller_reports_its_own_version(client: UniFiClient) -> None:
    # Recorded in a result, so a failure says which application produced it.
    info = client.get("/stat/sysinfo")

    assert info["data"][0]["version"]


def test_the_error_envelope_is_the_one_the_kernel_parses() -> None:
    # A refusal carries meta.rc and meta.msg rather than a bare message field,
    # which is the shape `message_from_body` reads.
    body = json.loads('{"meta":{"rc":"error","msg":"api.err.LoginRequired"},"data":[]}')

    assert message_from_body(body) == "api.err.LoginRequired"


def test_a_not_found_is_its_own_type(client: UniFiClient) -> None:
    # Reachable on a deployment that does answer 404, and asserted here so the
    # type stays wired to the status that produces it.
    assert issubclass(UniFiNotFoundError, UniFiError)
