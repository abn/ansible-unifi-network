# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall zone module, against the throwaway controller.

The v2 policy engine is a separate surface from the site's ``rest/`` collections,
reached above the site through its own base. This suite proves the endpoint, the
projection and the reporting through the module's own ``main``, and every case is
a question only the controller can answer, such as whether the zone collection is
served and whether a custom zone created, read back and deleted behaves.

The suite addresses reads through a client on the policy engine's own base, so a
module that addressed a different base would fail to read back what it wrote
rather than quietly agreeing with this file.

It writes, and it removes everything it creates, before each test and after it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import POLICY_ENGINE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.module import build_client
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_zone
from tests.live.cleanup import remove_by_prefix
from tests.live.harness import call
from tests.live.settings import connection

#: The names this suite owns, so a run that fails part-way leaves objects it can
#: recognise and remove rather than ones that accumulate.
OWNED = "verify-fwz-"
NAME = f"{OWNED}custom"

#: The policy engine's zone collection, relative to its own base. Written out
#: rather than imported from the module, so a module addressing a different path
#: fails to read back what it wrote instead of agreeing with this file.
ZONES = "/firewall/zone"

#: The site's own base, where a zone's network membership is read from.
NETWORKS = "/rest/networkconf"


@pytest.fixture(scope="session")
def engine() -> Any:
    """A session against the policy engine rather than the site.

    The credential, the site and the login are the site's own; only the base path
    differs, so the same builder composes it from the standard connection options.
    """
    return build_client(connection(), base=POLICY_ENGINE)


@pytest.fixture(scope="session", autouse=True)
def _require_zbf(engine: Any) -> None:
    """Skip where the zone-based firewall is not configured.

    The endpoint serves a site only once ZBF is switched on; without it a create
    answers api.err.CouldNotFindHotspotFirewallZone, and a suite that ran and failed
    would read as a defect rather than a target that cannot host it.
    """
    try:
        zones = engine.get(ZONES)
    except UniFiError:
        pytest.skip("the zone-based firewall is not configured on this target")
    if not isinstance(zones, list) or not zones:
        pytest.skip("the zone-based firewall is not configured on this target")


@pytest.fixture(scope="session")
def network_id(controller: Any) -> str:
    """A network the site already has, which the zone under test holds.

    A zone names its networks by identifier rather than by name, so the value is
    read from the controller rather than invented: an invented identifier is a
    field only the controller can refuse.
    """
    for row in rows(controller.get(NETWORKS)):
        return str(row["_id"])
    pytest.skip("the site holds no network for a zone to hold")


@pytest.fixture(autouse=True)
def _remove_everything(controller: Any, engine: Any) -> Any:
    remove_by_prefix(engine, ZONES, prefix=OWNED)
    yield
    remove_by_prefix(engine, ZONES, prefix=OWNED)


def _task(network_id: str, **overrides: Any) -> dict[str, Any]:
    task = connection(name=NAME, network_ids=[network_id])
    task.update(overrides)
    return task


def test_the_policy_engine_serves_the_zone_collection(engine: Any) -> None:
    # The zone is a v2 resource above the site, and only the controller can say
    # whether this deployment serves the collection.
    body = engine.get(ZONES)

    assert isinstance(body.get("data"), list), body


def test_a_task_creates_the_zone_and_a_second_run_does_not(network_id: str) -> None:
    first = call(unifi_firewall_zone, _task(network_id))
    assert not first.get("failed"), first.get("msg")
    assert first["changed"] is True, first

    second = call(unifi_firewall_zone, _task(network_id))
    assert not second.get("failed"), second.get("msg")
    assert second["changed"] is False, second.get("changed_fields")


def test_the_options_reach_the_controller_under_their_own_field_names(network_id: str) -> None:
    created = call(unifi_firewall_zone, _task(network_id))
    assert not created.get("failed"), created.get("msg")
    obj = created["obj"]

    # The diff is keyed by the controller fields the payload carried, so naming
    # them is how a table that got one wrong shows: a zone with none of these
    # fields, or a change on every run afterwards.
    assert created.get("changed_fields") == ["name", "network_ids"]
    assert obj["name"] == NAME
    assert obj["network_ids"] == [network_id]


def test_a_create_does_not_send_the_controller_derived_flag(network_id: str) -> None:
    # The controller derives default_zone and refuses a create that carries it
    # with an unrecognized field error, so the created zone is not the site's
    # default and comes back marked false by the controller.
    created = call(unifi_firewall_zone, _task(network_id))
    assert not created.get("failed"), created.get("msg")

    assert created["obj"].get("default_zone") is False


def test_check_mode_reports_the_change_without_creating(network_id: str) -> None:
    reported = call(unifi_firewall_zone, _task(network_id, _ansible_check_mode=True))
    assert reported["changed"] is True
    assert reported["diff"]["after"]["name"] == NAME

    # Check mode that has written leaves nothing for the next run to find.
    afterwards = call(unifi_firewall_zone, _task(network_id))
    assert afterwards["changed"] is True, "check mode appears to have created the zone"


def test_absent_removes_and_a_second_run_reports_no_change(network_id: str) -> None:
    call(unifi_firewall_zone, _task(network_id))
    removed = call(unifi_firewall_zone, _task(network_id, state="absent"))
    assert removed["changed"] is True

    again = call(unifi_firewall_zone, _task(network_id, state="absent"))
    assert again["changed"] is False, "removing twice reported a change"


def test_absent_actually_stops_the_site_listing_the_zone(engine: Any, network_id: str) -> None:
    call(unifi_firewall_zone, _task(network_id))
    call(unifi_firewall_zone, _task(network_id, state="absent"))

    # A delete answered with a success status is not proof the controller stopped
    # listing the object.
    assert [row for row in rows(engine.get(ZONES)) if row.get("name") == NAME] == []


def test_a_credential_is_never_echoed_in_a_failure(network_id: str) -> None:
    result = call(
        unifi_firewall_zone,
        _task(network_id, controller="127.0.0.1:1", api_key="a-secret-not-to-appear"),
    )

    assert "a-secret-not-to-appear" not in json.dumps(result)
    assert result.get("failed") is True
