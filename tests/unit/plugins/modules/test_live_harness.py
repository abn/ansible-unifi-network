# SPDX-License-Identifier: GPL-3.0-or-later
"""The live suite's argument stand-in, checked without a controller.

A live suite replaces ``AnsibleModule`` with the stand-in in
``tests/live/harness.py``, and the stand-in validates a task's payload against the
module's spec before the module runs. Its refusals are the property tested here:
an undeclared option, a canonical option named with its alias, and a term split
across a required pair are caught rather than reaching the module. The stand-in
counts key presence for a required, required_if or required_together term, as the
framework does, so an explicit ``null`` satisfies one.

No controller and no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.tests.live.harness import _validated

SPEC: dict[str, Any] = {
    "name": {"type": "str", "required": True},
    "state": {"type": "str", "default": "present"},
    "native": {"type": "str"},
    "username": {"type": "str"},
    "password": {"type": "str"},
    "logging": {"type": "bool", "aliases": ["log_enabled"]},
}


def test_an_undeclared_option_is_refused_by_name() -> None:
    # A misspelled or unknown option is refused here, naming the offending key,
    # rather than being dropped so the run ignores it.
    with pytest.raises(ValueError, match="enabledd"):
        _validated(SPEC, {"name": "rule", "enabledd": True})


def test_a_canonical_option_and_its_alias_named_together_is_refused() -> None:
    with pytest.raises(ValueError, match="both given"):
        _validated(SPEC, {"name": "rule", "logging": True, "log_enabled": True})


def test_a_required_term_is_satisfied_by_an_explicit_null() -> None:
    resolved = _validated(SPEC, {"name": None})

    assert resolved.get("name") is None


def test_a_required_if_term_is_satisfied_by_an_explicit_null() -> None:
    _validated(
        SPEC,
        {"name": "rule", "state": "present", "native": None},
        required_if=[("state", "present", ["native"], True)],
    )


def test_a_term_split_across_a_required_together_pair_is_refused() -> None:
    task = {"name": "rule", "username": "verify"}

    with pytest.raises(ValueError, match="required together"):
        _validated(SPEC, task, required_together=[("username", "password")])


def test_a_required_together_pair_supplied_with_a_null_counts_as_present() -> None:
    _validated(
        SPEC,
        {"name": "rule", "username": None, "password": "verify"},
        required_together=[("username", "password")],
    )
