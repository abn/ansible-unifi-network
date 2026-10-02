# SPDX-License-Identifier: GPL-3.0-or-later
"""Removing what a live suite owns from the shared controller.

The live suite runs against one site, so isolation is each test's own
responsibility. Objects carry a recognisable prefix, removal matches on that
prefix, and every suite removes before and after so a run that failed part-way is
repeatable.
"""

from __future__ import annotations

from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import rows


def remove_by_prefix(client: Any, collection: str, *, prefix: str) -> None:
    """Delete every object in a collection whose name starts with ``prefix``."""
    for row in rows(client.get(collection)):
        if str(row.get("name", "")).startswith(prefix):
            client.delete(f"{collection}/{row['_id']}")


def find_named(client: Any, collection: str, *, name: str) -> dict[str, Any]:
    """The one object carrying ``name``, which a leftover from an earlier run matches too."""
    for row in rows(client.get(collection)):
        if str(row.get("name", "")) == name:
            return dict(row)
    raise AssertionError(f"{name!r} is not on the controller")
