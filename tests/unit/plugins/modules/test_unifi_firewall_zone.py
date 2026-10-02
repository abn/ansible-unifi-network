# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall zone module's options and reconciliation, checked against the controller.

A zone is a small v2 resource, so the interesting parts are that a task cannot set
the fields the controller derives, that a create sends only what the controller
declares, and that a system zone is refused rather than removed. The behaviour
cases drive the module against a stub client, which is the transport substituted
rather than a model of the controller.

What only a controller can answer, and what the live suite therefore asks instead,
is whether the policy engine endpoint is served, whether the controller stores the
network membership as sent, and whether a delete stops it listing the zone.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any
from typing import cast

import pytest
import yaml
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_ZONE
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_zone

SPEC = Path(__file__).resolve().parents[3] / "fixtures" / "unifi-local-api.yaml"

#: The option the module declares that is its own rather than the controller's.
LIFECYCLE = "state"

#: The connection options, which are not this module's and so are not in its table.
_CONNECTION = frozenset(
    {
        "api_family",
        "api_key",
        "api_mount",
        "ca_path",
        "controller",
        "login_path",
        "password",
        "site",
        "timeout",
        "username",
        "validate_certs",
    }
)


@pytest.fixture(scope="module")
def declared() -> dict[str, Any]:
    document = yaml.safe_load(SPEC.read_text())
    return document["components"]["schemas"]["FirewallZone"]["properties"]


def test_every_field_the_table_names_is_one_the_controller_declares(
    declared: dict[str, Any],
) -> None:
    for option, field in FIREWALL_ZONE.items():
        assert field in declared, f"{option} maps to {field!r}, which FirewallZone does not declare"


def test_the_table_carries_every_option_the_module_lets_a_task_set() -> None:
    # An option absent from the table is not sent, so one a task can name and the
    # table does not carry is a field the collection silently drops.
    settable = {
        name
        for name in unifi_firewall_zone.ARGUMENT_SPEC
        if name not in _CONNECTION and name != LIFECYCLE
    }

    assert settable == set(FIREWALL_ZONE)


def test_no_two_options_map_to_the_same_field() -> None:
    fields = list(FIREWALL_ZONE.values())

    assert len(fields) == len(set(fields))


def test_no_zone_option_carries_a_default() -> None:
    # A default makes "not mentioned" indistinguishable from "set", which on a
    # resource the controller fills in turns every undeclared option into a change.
    defaulted = {
        name
        for name, spec in unifi_firewall_zone.ARGUMENT_SPEC.items()
        if "default" in spec and name not in _CONNECTION and name != LIFECYCLE
    }

    assert defaulted == set()


def test_the_collection_is_the_policy_engine_zone_endpoint() -> None:
    # The zone is served by the policy engine above the site, not beneath the
    # site's rest base, so a path against the wrong base is a 404.
    assert unifi_firewall_zone.COLLECTION == "/firewall/zone"


def test_the_controller_derived_fields_are_not_settable() -> None:
    # default_zone is controller derived and the controller refuses a create that
    # sends it, and zone_key and the attr flags are the controller's own. A task
    # setting one writes metadata or is refused.
    for field in ("default_zone", "zone_key", "_id", "site_id", "attr_no_delete", "attr_no_edit"):
        assert field not in FIREWALL_ZONE.values(), field


def test_a_task_naming_a_name_and_networks_sends_exactly_those() -> None:
    wanted = project({"name": "IoT", "network_ids": ["n1", "n2"]}, FIREWALL_ZONE)

    assert wanted == {"name": "IoT", "network_ids": ["n1", "n2"]}


def test_an_unset_option_is_not_sent() -> None:
    assert project({"name": "IoT", "network_ids": None}, FIREWALL_ZONE) == {"name": "IoT"}


def test_an_empty_network_list_is_projected() -> None:
    # Emptying the list is how a task says the zone holds no networks, and dropping
    # it would leave the old membership in place.
    assert project({"network_ids": []}, FIREWALL_ZONE) == {"network_ids": []}


class _Store:
    """A client holding one collection, so selection and writes both act on it."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = [dict(row) for row in (rows or [])]
        self.posts = 0
        self.sets = 0
        self.deletes = 0

    def get(self, resource: str) -> Any:
        return {"data": [dict(row) for row in self.rows]}

    def post(self, resource: str, body: Any) -> None:
        self.posts += 1
        row = dict(body)
        row.setdefault("_id", f"new{self.posts}")
        self.rows.append(row)

    def set(self, resource: str, body: Any) -> None:
        self.sets += 1
        identifier = body.get("_id")
        self.rows = [dict(body) if row.get("_id") == identifier else row for row in self.rows]

    def delete(self, resource: str) -> None:
        self.deletes += 1
        identifier = resource.rsplit("/", 1)[-1]
        self.rows = [row for row in self.rows if row.get("_id") != identifier]


class _Module:
    """A stand-in for ``AnsibleModule`` holding the params the spec would resolve."""

    def __init__(self, params: dict[str, Any], *, check_mode: bool = False) -> None:
        self.params = params
        self.check_mode = check_mode
        self.result: dict[str, Any] | None = None

    def exit_json(self, **kwargs: Any) -> None:
        self.result = kwargs
        raise SystemExit(0)


def _params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "name": "IoT",
        "state": "present",
        "network_ids": ["n1"],
    }
    params.update(overrides)
    return params


def _run(
    monkeypatch: pytest.MonkeyPatch,
    store: _Store,
    *,
    check_mode: bool = False,
    **overrides: Any,
) -> dict[str, Any]:
    """Run the module once against ``store``, returning what it would report."""
    monkeypatch.setattr(unifi_firewall_zone, "build_client", lambda params, **kwargs: store)
    module = _Module(_params(**overrides), check_mode=check_mode)
    with contextlib.suppress(SystemExit):
        unifi_firewall_zone.run(cast(Any, module))
    assert module.result is not None, "the module reported nothing"
    return module.result


def test_creating_a_zone_posts_its_name_and_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    result = _run(monkeypatch, store)

    assert result["changed"] is True
    assert store.posts == 1
    assert store.rows[0]["name"] == "IoT"
    assert store.rows[0]["network_ids"] == ["n1"]


def test_a_create_does_not_send_the_controller_derived_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The controller refuses a create carrying default_zone with an unrecognized
    # field error, so the payload must not name it.
    store = _Store()

    _run(monkeypatch, store)

    assert "default_zone" not in store.rows[0]
    assert "zone_key" not in store.rows[0]


def test_a_second_run_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    _run(monkeypatch, store)
    second = _run(monkeypatch, store)

    assert second["changed"] is False, second.get("changed_fields")
    assert store.posts == 1
    assert store.sets == 0


def test_changing_the_network_membership_is_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([{"_id": "z1", "name": "IoT", "network_ids": ["n1"]}])

    result = _run(monkeypatch, store, network_ids=["n2"])

    assert result["changed"] is True
    assert store.sets == 1
    assert store.rows[0]["network_ids"] == ["n2"]


def test_check_mode_reports_the_change_without_creating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()

    result = _run(monkeypatch, store, check_mode=True)

    assert result["changed"] is True
    assert store.posts == 0


def test_absent_removes_the_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([{"_id": "z1", "name": "IoT", "network_ids": ["n1"]}])

    result = _run(monkeypatch, store, state="absent")

    assert result["changed"] is True
    assert store.deletes == 1
    assert store.rows == []


def test_removing_an_absent_zone_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    result = _run(monkeypatch, store, state="absent")

    assert result["changed"] is False
    assert store.deletes == 0


def test_removing_a_system_zone_is_refused_before_the_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A system zone is marked default_zone, and the controller marks it
    # undeletable. A removal that forced the delete would leave the traffic the
    # controller attributes to no other zone with nowhere to land.
    store = _Store([{"_id": "z1", "name": "IoT", "default_zone": True}])

    with pytest.raises(UniFiError, match="will not remove"):
        _run(monkeypatch, store, state="absent")

    assert store.deletes == 0
    assert len(store.rows) == 1


def test_two_zones_sharing_a_name_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # A name fitting more than one zone is too broad to act on, and picking one
    # changes the traffic the task never named.
    store = _Store(
        [
            {"_id": "z1", "name": "IoT"},
            {"_id": "z2", "name": "IoT"},
        ]
    )

    with pytest.raises(UniFiError, match="ambiguous"):
        _run(monkeypatch, store)


def test_the_module_offers_a_removal() -> None:
    assert "absent" in unifi_firewall_zone.ARGUMENT_SPEC["state"]["choices"]


def test_a_name_is_the_only_required_option() -> None:
    required = {
        name
        for name, spec in unifi_firewall_zone.ARGUMENT_SPEC.items()
        if spec.get("required") and name not in _CONNECTION
    }

    assert required == {"name"}


def test_a_network_membership_is_a_list_of_strings() -> None:
    assert unifi_firewall_zone.ARGUMENT_SPEC["network_ids"]["type"] == "list"
    assert unifi_firewall_zone.ARGUMENT_SPEC["network_ids"]["elements"] == "str"


def _validated(task: dict[str, Any]) -> dict[str, Any]:
    """The parameters the framework validates a task into, with the module's spec."""
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    return basic.AnsibleModule(
        argument_spec=unifi_firewall_zone.ARGUMENT_SPEC,
        required_together=unifi_firewall_zone.connection_required_together(),
        mutually_exclusive=unifi_firewall_zone.connection_mutually_exclusive(),
    ).params


def test_the_connection_options_are_shared_and_required_together() -> None:
    params = _validated(
        {
            "controller": "unifi.example.invalid",
            "api_mount": "appliance",
            "api_family": "legacy",
            "username": "admin",
            "password": "secret",
            "name": "IoT",
        }
    )

    assert params["username"] == "admin"
