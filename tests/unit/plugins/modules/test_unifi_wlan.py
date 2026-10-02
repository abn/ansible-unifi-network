# SPDX-License-Identifier: GPL-3.0-or-later
"""The wireless network module's reporting, without a controller.

The passphrase is the resource's own secret and the controller returns it on every
read. What a run reports is checked here, because no_log masks only the value a
task supplied while an update that does not restate the passphrase reads the
controller's stored copy back. What only a controller can answer is asked in the
live suite instead.
"""

from __future__ import annotations

import contextlib
from typing import Any
from typing import cast

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.modules import unifi_wlan


class _Store:
    """A client holding one collection and applying writes to it."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]
        self.posts = 0
        self.sets = 0
        self.deletes = 0

    def get(self, resource: str) -> Any:
        return {"data": [dict(row) for row in self.rows]}

    def set(self, resource: str, body: Any) -> None:
        self.sets += 1
        self.rows = [dict(body)]

    def post(self, resource: str, body: Any) -> None:
        self.posts += 1
        row = dict(body)
        row.setdefault("_id", f"new{self.posts}")
        self.rows.append(row)

    def delete(self, resource: str) -> None:
        self.deletes += 1
        self.rows = []


class _Module:
    """A stand-in for ``AnsibleModule`` recording what the module reports."""

    def __init__(self, params: dict[str, Any], *, check_mode: bool = False) -> None:
        self.params = params
        self.check_mode = check_mode
        self.result: dict[str, Any] | None = None

    def exit_json(self, **kwargs: Any) -> None:
        self.result = kwargs
        # The real module leaves the process here, so a run that continued past it
        # would overwrite the result with the work after the exit.
        raise SystemExit(0)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    store: _Store,
    overrides: dict[str, Any],
    *,
    check_mode: bool = False,
) -> dict[str, Any]:
    monkeypatch.setattr(unifi_wlan, "build_client", lambda _params: store)
    module = _Module({"name": "Office", "state": "present", **overrides}, check_mode=check_mode)
    with contextlib.suppress(SystemExit):
        unifi_wlan.run(cast(Any, module))
    assert module.result is not None
    return module.result


def test_the_stored_passphrase_is_removed_from_the_reported_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store([{"_id": "w1", "name": "Office", "enabled": True, "x_passphrase": "stored"}])

    result = _run(monkeypatch, store, {"enabled": False})

    assert "x_passphrase" not in result["obj"]
    assert "x_passphrase" not in result["diff"]["before"]
    assert "x_passphrase" not in result["diff"]["after"]
    # Redaction is reporting only: the write still carries what the controller held.
    assert store.rows[0]["x_passphrase"] == "stored"


def test_check_mode_reports_the_wireless_network_it_would_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store([])

    result = _run(monkeypatch, store, {}, check_mode=True)

    assert result["obj"] == result["diff"]["after"]
    assert result["obj"]["name"] == "Office"
    assert store.posts == 0


def test_check_mode_reports_the_wireless_network_it_would_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store([{"_id": "w1", "name": "Office", "enabled": True}])

    result = _run(monkeypatch, store, {"enabled": False}, check_mode=True)

    assert result["obj"] == result["diff"]["after"]
    assert result["obj"]["enabled"] is False
    assert store.sets == 0


def test_two_wireless_networks_with_one_name_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store([{"_id": "w1", "name": "Office"}, {"_id": "w2", "name": "Office"}])

    with pytest.raises(UniFiError, match="ambiguous"):
        _run(monkeypatch, store, {})


def test_a_removal_reports_no_object(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store([{"_id": "w1", "name": "Office"}])

    result = _run(monkeypatch, store, {"state": "absent"})

    assert result["changed"] is True
    assert "obj" not in result
    assert store.deletes == 1
