# SPDX-License-Identifier: GPL-3.0-or-later
"""The meta/runtime.yml action group, checked against the module directory.

A playbook shares the connection options once under
``module_defaults: group/abn.unifi_network.unifi``. Each name in the group is
resolved against this collection, and a name no module answers to is dropped,
which silently leaves the task without the defaults. The list is asserted here
against the modules the collection ships, so a module added without a matching
group entry fails this test.

This file needs no controller and no network.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COLLECTION = Path(__file__).resolve().parents[2]
RUNTIME = COLLECTION / "meta" / "runtime.yml"
MODULES = COLLECTION / "plugins" / "modules"


def _shipped_modules() -> set[str]:
    return {path.stem for path in MODULES.glob("*.py") if path.name != "__init__.py"}


def test_the_unifi_group_lists_every_shipped_module_and_nothing_else() -> None:
    group = yaml.safe_load(RUNTIME.read_text())["action_groups"]["unifi"]

    assert set(group) == _shipped_modules()
