# SPDX-License-Identifier: GPL-3.0-or-later
"""The firewall policy module's options and reconciliation, checked against the controller.

A policy is the interesting v2 resource: its source and destination are nested
documents, its position is assigned by the controller, and a create is refused
unless it states that it is not a respond policy. The behaviour cases drive the
module against a stub client, which is the transport substituted rather than a
model of the controller.

What only a controller can answer, and what the live suite therefore asks instead,
is whether the policy engine endpoint is served, whether the controller stores the
nested documents and the position as sent, and whether a delete stops it listing
the policy.
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
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import ENUM_VALUES
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import FIREWALL_POLICY
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.fields import project
from ansible_collections.abn.unifi_network.plugins.modules import unifi_firewall_policy

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
    return document["components"]["schemas"]["FirewallPolicy"]["properties"]


def test_every_field_the_table_names_is_one_the_controller_declares(
    declared: dict[str, Any],
) -> None:
    # A dotted value names a nested document, so the root is what the policy
    # declares and the leaf is what the side schemas declare.
    for option, field in FIREWALL_POLICY.items():
        root = field.split(".", maxsplit=1)[0]
        assert root in declared, f"{option} maps to {root!r}, which FirewallPolicy does not declare"


def test_the_nested_sides_are_what_the_controller_declares() -> None:
    # The module nests these, so a leaf the side schema does not declare would be
    # dropped by the controller rather than reaching the policy.
    document = yaml.safe_load(SPEC.read_text())
    source = document["components"]["schemas"]["FirewallPolicySource"]["properties"]
    destination = document["components"]["schemas"]["FirewallPolicyDestination"]["properties"]

    for field in FIREWALL_POLICY.values():
        parts = field.split(".", maxsplit=1)
        root = parts[0]
        leaf = parts[1] if len(parts) > 1 else ""
        if root == "source":
            assert leaf in source, field
        elif root == "destination":
            assert leaf in destination, field


def test_the_table_carries_every_option_the_module_lets_a_task_set() -> None:
    # create_allow_respond is deliberately absent from both: it is required on a
    # create but is not a task option, so the module asserts it rather than exposing
    # it.
    settable = {
        name
        for name in unifi_firewall_policy.ARGUMENT_SPEC
        if name not in _CONNECTION and name != LIFECYCLE
    }

    assert settable == set(FIREWALL_POLICY)
    assert unifi_firewall_policy.CREATE_ALLOW_RESPOND not in unifi_firewall_policy.ARGUMENT_SPEC
    assert unifi_firewall_policy.CREATE_ALLOW_RESPOND not in FIREWALL_POLICY


def test_no_two_options_map_to_the_same_field() -> None:
    fields = list(FIREWALL_POLICY.values())

    assert len(fields) == len(set(fields))


def test_the_collection_is_the_policy_engine_policy_endpoint() -> None:
    # The chain is served by the policy engine above the site, not beneath the
    # site's rest base, so a path against the wrong base is a 404.
    assert unifi_firewall_policy.COLLECTION == "/firewall-policies"


def test_the_enumerated_options_carry_the_controllers_own_choices() -> None:
    assert unifi_firewall_policy.ARGUMENT_SPEC["action"]["choices"] == list(
        ENUM_VALUES["FirewallPolicy.action"]
    )
    assert unifi_firewall_policy.ARGUMENT_SPEC["protocol"]["choices"] == list(
        ENUM_VALUES["FirewallPolicy.protocol"]
    )
    assert unifi_firewall_policy.ARGUMENT_SPEC["ip_version"]["choices"] == list(
        ENUM_VALUES["FirewallPolicy.ip_version"]
    )
    assert unifi_firewall_policy.ARGUMENT_SPEC["connection_state_type"]["choices"] == list(
        ENUM_VALUES["FirewallPolicy.connection_state_type"]
    )


def test_the_index_is_optional_and_a_number(declared: dict[str, Any]) -> None:
    # The controller assigns a position to a create, so a task must not have to
    # supply it, and the field it stores is a number.
    assert unifi_firewall_policy.ARGUMENT_SPEC["index"]["type"] == "int"
    assert "required" not in unifi_firewall_policy.ARGUMENT_SPEC["index"]
    assert declared["index"]["type"] == ["integer", "null"]


def test_the_source_and_destination_are_projected_as_nested_documents() -> None:
    wanted = project(
        {
            "source_zone_id": "z1",
            "source_match": "NETWORK",
            "source_network_ids": ["n1"],
            "source_port_list": 443,
            "destination_zone_id": "z2",
        },
        FIREWALL_POLICY,
    )

    assert wanted == {
        "source": {
            "zone_id": "z1",
            "matching_target": "NETWORK",
            "network_ids": ["n1"],
            "port": 443,
        },
        "destination": {"zone_id": "z2"},
    }


def test_the_source_options_share_the_source_side() -> None:
    # Two options on one side nest under the one document rather than replacing it.
    wanted = project({"source_zone_id": "z1", "source_port_list": 80}, FIREWALL_POLICY)

    assert wanted == {"source": {"zone_id": "z1", "port": 80}}


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
        "name": "IoT to internal",
        "state": "present",
        "action": "ALLOW",
        "protocol": "tcp",
        "enabled": True,
        "logging": False,
        "source_zone_id": "z1",
        "destination_zone_id": "z2",
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
    monkeypatch.setattr(unifi_firewall_policy, "build_client", lambda params, **kwargs: store)
    module = _Module(_params(**overrides), check_mode=check_mode)
    with contextlib.suppress(SystemExit):
        unifi_firewall_policy.run(cast(Any, module))
    assert module.result is not None, "the module reported nothing"
    return module.result


def test_creating_a_policy_sends_the_fields_only_a_create_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The controller refuses a create that omits create_allow_respond with
    # api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed, and one that
    # omits the schedule with NotNull.schedule, so the module supplies both on the
    # one write that needs them.
    store = _Store()

    result = _run(monkeypatch, store)

    assert result["changed"] is True
    assert store.posts == 1
    assert store.rows[0]["create_allow_respond"] is False
    assert store.rows[0]["schedule"] == {"mode": "ALWAYS"}
    assert store.rows[0]["ip_version"] == "BOTH"


def test_a_create_without_a_chosen_field_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # The controller refuses a policy with no action or no zone on a side, and an
    # update keeps what it holds, so the module refuses a create that omits one.
    store = _Store()

    with pytest.raises(UniFiError, match="action"):
        _run(monkeypatch, store, action=None)

    assert store.posts == 0


def test_a_create_does_not_send_an_index_the_task_did_not_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The controller assigns the position, so a create that sent one would take
    # that position from the controller's own chain.
    store = _Store()

    _run(monkeypatch, store)

    assert "index" not in store.rows[0]


def test_a_create_sends_the_index_the_task_named(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    _run(monkeypatch, store, index=160)

    assert store.rows[0]["index"] == 160


def test_a_second_run_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    _run(monkeypatch, store)
    second = _run(monkeypatch, store)

    assert second["changed"] is False, second.get("changed_fields")
    assert store.posts == 1
    assert store.sets == 0


def test_an_update_leaves_the_controllers_create_flag_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # create_allow_respond is asserted only on a create. An update carries the
    # controller's own value rather than forcing it, so a policy the controller
    # already holds is not rewritten with a flag the task never named.
    store = _Store(
        [
            {
                "_id": "p1",
                "name": "IoT to internal",
                "action": "BLOCK",
                "create_allow_respond": True,
            }
        ]
    )

    result = _run(monkeypatch, store, action="ALLOW")

    assert result["changed"] is True
    assert store.rows[0]["action"] == "ALLOW"
    assert store.rows[0]["create_allow_respond"] is True


def test_changing_the_action_is_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([{"_id": "p1", "name": "IoT to internal", "action": "BLOCK"}])

    result = _run(monkeypatch, store, action="ALLOW")

    assert result["changed"] is True
    assert store.sets == 1
    assert store.rows[0]["action"] == "ALLOW"


def test_check_mode_reports_the_change_without_creating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()

    result = _run(monkeypatch, store, check_mode=True)

    assert result["changed"] is True
    assert store.posts == 0


def test_absent_removes_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([{"_id": "p1", "name": "IoT to internal"}])

    result = _run(monkeypatch, store, state="absent")

    assert result["changed"] is True
    assert store.deletes == 1
    assert store.rows == []


def test_removing_an_absent_policy_reports_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()

    result = _run(monkeypatch, store, state="absent")

    assert result["changed"] is False
    assert store.deletes == 0


def test_removing_a_predefined_policy_is_refused_before_the_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A predefined policy is one the site shipped with, so a removal is refused
    # rather than forced.
    store = _Store([{"_id": "p1", "name": "IoT to internal", "predefined": True}])

    with pytest.raises(UniFiError, match="predefined"):
        _run(monkeypatch, store, state="absent")

    assert store.deletes == 0
    assert len(store.rows) == 1


def test_two_policies_sharing_a_name_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # A name fitting more than one policy is too broad to act on, and picking one
    # changes the traffic the task never named.
    store = _Store(
        [
            {"_id": "p1", "name": "IoT to internal"},
            {"_id": "p2", "name": "IoT to internal"},
        ]
    )

    with pytest.raises(UniFiError, match="ambiguous"):
        _run(monkeypatch, store)


def test_only_the_name_is_required_in_the_spec() -> None:
    # The controller requires several fields of a create, but none is required by
    # the spec: a task that omits one is refused at run time only when the policy
    # does not exist, so an update may leave what it is not changing.
    required = {
        name
        for name, spec in unifi_firewall_policy.ARGUMENT_SPEC.items()
        if spec.get("required") and name not in _CONNECTION
    }

    assert required == {"name"}


def test_no_policy_option_carries_a_default() -> None:
    defaulted = {
        name
        for name, spec in unifi_firewall_policy.ARGUMENT_SPEC.items()
        if "default" in spec and name not in _CONNECTION and name != LIFECYCLE
    }

    assert defaulted == set()


def _validated(task: dict[str, Any]) -> dict[str, Any]:
    """The parameters the framework validates a task into, with the module's spec."""
    basic._ANSIBLE_PROFILE = "legacy"
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    return basic.AnsibleModule(
        argument_spec=unifi_firewall_policy.ARGUMENT_SPEC,
        required_together=unifi_firewall_policy.connection_required_together(),
        mutually_exclusive=unifi_firewall_policy.connection_mutually_exclusive(),
    ).params


def test_the_connection_options_are_shared_and_required_together() -> None:
    params = _validated(
        {
            "controller": "unifi.example.invalid",
            "api_mount": "appliance",
            "api_family": "legacy",
            "username": "admin",
            "password": "secret",
            "name": "IoT to internal",
        }
    )

    assert params["username"] == "admin"
