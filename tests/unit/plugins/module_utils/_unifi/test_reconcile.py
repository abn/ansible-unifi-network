from __future__ import annotations

from typing import Any

import pytest
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiConcurrencyError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import apply
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import (
    merge_embedded,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import redact
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import reference
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import remove
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.reconcile import resolve_id


class _Stub:
    """A client that answers one collection, so the lookup is what is under test."""

    def __init__(self, body: Any) -> None:
        self._body = body

    def get(self, resource: str) -> Any:
        return self._body


def test_a_name_resolves_to_the_identifier_the_controller_holds() -> None:
    client = _Stub(
        {"data": [{"_id": "5f2b1c9e", "name": "LAN"}, {"_id": "6a3c2d8f", "name": "IoT"}]}
    )

    assert resolve_id(client, "/rest/networkconf", name="IoT", what="network") == "6a3c2d8f"


def test_a_reference_may_be_an_identifier_without_a_lookup() -> None:
    # A controller that cannot be reached must not be consulted for a reference
    # the task already spelled out, or a task holding every identifier would still
    # fail whenever the controller is down.
    client = _Stub(None)

    assert (
        reference(client, "/rest/networkconf", identifier="5f2b1c9e", what="network") == "5f2b1c9e"
    )


def test_a_reference_naming_both_is_refused() -> None:
    client = _Stub({"data": [{"_id": "5f2b1c9e", "name": "LAN"}]})

    with pytest.raises(UniFiError, match="both"):
        reference(client, "/rest/networkconf", name="LAN", identifier="5f2b1c9e", what="network")


def test_a_reference_naming_neither_is_refused() -> None:
    client = _Stub({"data": []})

    with pytest.raises(UniFiError, match="neither"):
        reference(client, "/rest/networkconf", what="network")


def test_a_name_matching_several_objects_is_refused() -> None:
    # The controller permits two networks with one name. Resolving to either would
    # aim a write at an object the task never named.
    client = _Stub(
        {"data": [{"_id": "5f2b1c9e", "name": "LAN"}, {"_id": "6a3c2d8f", "name": "LAN"}]}
    )

    with pytest.raises(UniFiError, match="ambiguous"):
        resolve_id(client, "/rest/networkconf", name="LAN", what="network")


def test_a_name_matching_nothing_names_what_was_looked_for() -> None:
    # An operator reading the failure has to be able to tell a task naming a
    # network the site does not have from one naming it wrongly.
    client = _Stub({"data": [{"_id": "5f2b1c9e", "name": "LAN"}]})

    with pytest.raises(UniFiError, match="IoT"):
        resolve_id(client, "/rest/networkconf", name="IoT", what="network")


class _TwoPath:
    """A client whose listing and write collections are different, as a device is."""

    def __init__(self) -> None:
        self.reads: list[str] = []

    def get(self, resource: str) -> Any:
        self.reads.append(resource)
        if resource == "/stat/device":
            return {"data": [{"_id": "d1", "mac": "aa:bb:cc:dd:ee:01", "name": "AP"}]}
        raise AssertionError(f"read from the write path: {resource}")


def test_the_current_document_is_read_from_the_listing_rather_than_the_write_path() -> None:
    # A device is listed at /stat/device and written at /rest/device, and reading
    # the write path answers 404 on a deployment that serves only the listing.
    # That 404 reads like the object being absent, which is a different problem.
    client = _TwoPath()
    outcome = apply(
        client,
        collection="/rest/device",
        read="/stat/device",
        wanted={"name": "AP"},
        key="mac",
        name="aa:bb:cc:dd:ee:01",
    )

    assert client.reads == ["/stat/device"]
    assert outcome.changed is False


class _Store:
    """A client holding one collection, so selection and writes both act on it."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]
        self.reads = 0
        self.sets = 0
        self.posts = 0
        self.deletes = 0

    def get(self, resource: str) -> Any:
        self.reads += 1
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


_TWO_RULES = [
    {"_id": "r1", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
    {"_id": "r2", "ruleset": "WAN_IN", "name": "Block", "action": "drop"},
]


def test_a_match_selects_the_one_row_holding_every_pair() -> None:
    # Both rules carry the name Block; only the ruleset tells them apart.
    client = _Store(_TWO_RULES)

    outcome = apply(
        client,
        collection="/rest/firewallrule",
        wanted={"action": "drop"},
        match={"ruleset": "WAN_IN", "name": "Block"},
    )

    assert outcome.changed is False
    assert outcome.before["_id"] == "r2"


def test_a_match_that_matches_nothing_creates() -> None:
    client = _Store(_TWO_RULES)

    outcome = apply(
        client,
        collection="/rest/firewallrule",
        wanted={"ruleset": "WAN_IN", "name": "Allow", "action": "accept"},
        match={"ruleset": "WAN_IN", "name": "Allow"},
    )

    assert client.posts == 1
    assert outcome.changed is True


def test_a_match_matching_several_rows_is_refused() -> None:
    # A match narrower than the identity must fail rather than pick the first,
    # because acting on the wrong rule changes traffic the task never named.
    client = _Store(
        [
            {"_id": "r1", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
            {"_id": "r2", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
        ]
    )

    with pytest.raises(UniFiError, match="ambiguous"):
        apply(
            client,
            collection="/rest/firewallrule",
            wanted={"action": "drop"},
            match={"ruleset": "LAN_IN", "name": "Block"},
        )


def test_a_match_only_call_does_not_select_by_name() -> None:
    # An empty name with a match is the firewall-rule case: the row is the one the
    # match names, not the first rule whose name is empty.
    client = _Store(
        [
            {"_id": "empty", "ruleset": "LAN_IN", "name": ""},
            {"_id": "r2", "ruleset": "WAN_IN", "name": "Block", "action": "drop"},
        ]
    )

    outcome = apply(
        client,
        collection="/rest/firewallrule",
        wanted={"action": "drop"},
        match={"ruleset": "WAN_IN", "name": "Block"},
    )

    assert outcome.before["_id"] == "r2"


def test_a_match_coerces_a_non_string_value() -> None:
    # A rule_index arrives from an argument spec as an int. A match that compared it
    # uncoerced would select nothing and create a second rule beside the one the task
    # named, which is the failure the ambiguity guard exists to prevent.
    client = _Store(
        [
            {"_id": "r1", "ruleset": "WAN_IN", "name": "Block", "rule_index": 2000},
            {"_id": "r2", "ruleset": "WAN_IN", "name": "Block", "rule_index": 2010},
        ]
    )

    outcome = apply(
        client,
        collection="/rest/firewallrule",
        wanted={"action": "drop"},
        match={"ruleset": "WAN_IN", "name": "Block", "rule_index": 2010},
    )

    assert outcome.before["_id"] == "r2"


def test_remove_selects_by_match() -> None:
    client = _Store(_TWO_RULES)

    outcome = remove(
        client,
        collection="/rest/firewallrule",
        what="firewall rule",
        match={"ruleset": "WAN_IN", "name": "Block"},
    )

    assert outcome.changed is True
    assert client.deletes == 1


def test_the_default_reads_the_object_it_reconciles() -> None:
    client = _Store([{"_id": "n1", "name": "LAN", "purpose": "corporate"}])

    outcome = apply(
        client,
        collection="/rest/networkconf",
        wanted={"purpose": "corporate"},
        name="LAN",
    )

    assert client.reads == 1
    assert outcome.changed is False


def test_a_supplied_current_document_skips_the_read() -> None:
    client = _Store([{"_id": "n1", "name": "LAN", "purpose": "corporate"}])

    outcome = apply(
        client,
        collection="/rest/networkconf",
        wanted={"purpose": "corporate"},
        name="LAN",
        current={"_id": "n1", "name": "LAN", "purpose": "corporate"},
    )

    assert client.reads == 0
    assert outcome.changed is False


def test_a_supplied_absent_object_is_created_without_a_read() -> None:
    # None is a real value meaning absent, distinct from the default that reads.
    client = _Store([])

    outcome = apply(
        client,
        collection="/rest/networkconf",
        wanted={"name": "IoT"},
        name="IoT",
        current=None,
        check_mode=True,
    )

    assert client.reads == 0
    assert client.posts == 0
    assert outcome.changed is True


class _Concurrent:
    """A client whose first write collides and whose read then reflects the move."""

    def __init__(self, after: dict[str, Any]) -> None:
        self._after = after
        self.reads = 0
        self.sets = 0

    def get(self, resource: str) -> Any:
        self.reads += 1
        return {"data": [dict(self._after)]}

    def set(self, resource: str, body: Any) -> None:
        self.sets += 1
        if self.sets == 1:
            raise UniFiConcurrencyError("the document moved")


def test_the_concurrency_retry_re_reads_even_when_current_was_supplied() -> None:
    # current skips only the initial read. A collision must still show what the
    # controller holds now, which is how the other writer's change survives.
    client = _Concurrent({"_id": "r1", "ruleset": "LAN_IN", "name": "Block", "action": "accept"})

    outcome = apply(
        client,
        collection="/rest/firewallrule",
        wanted={"action": "accept"},
        match={"ruleset": "LAN_IN", "name": "Block"},
        current={"_id": "r1", "ruleset": "LAN_IN", "name": "Block", "action": "drop"},
    )

    assert client.reads == 1
    assert outcome.changed is False


def test_merge_embedded_replaces_a_row_in_its_own_position() -> None:
    existing = [
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 2, "port_profile_id": "B"},
    ]

    merged = merge_embedded(existing, [{"port_idx": 2, "port_profile_id": "C"}], key="port_idx")

    assert merged == [
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 2, "port_profile_id": "C"},
    ]


def test_merge_embedded_appends_an_entry_no_row_carries() -> None:
    existing = [{"port_idx": 1, "port_profile_id": "A"}]

    merged = merge_embedded(existing, [{"port_idx": 2, "port_profile_id": "B"}], key="port_idx")

    assert merged == [
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 2, "port_profile_id": "B"},
    ]


def test_merge_embedded_preserves_the_order_of_unnamed_rows() -> None:
    existing = [
        {"port_idx": 3, "port_profile_id": "C"},
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 2, "port_profile_id": "B"},
    ]

    merged = merge_embedded(existing, [{"port_idx": 1, "port_profile_id": "X"}], key="port_idx")

    assert [row["port_idx"] for row in merged] == [3, 1, 2]
    assert merged[1]["port_profile_id"] == "X"


def test_merge_embedded_compares_the_key_as_text() -> None:
    # port_idx arrives from an argument spec as an int, and the controller may have
    # stored it as a string. Comparing the raw values would append a second row for
    # a port the task named.
    existing = [{"port_idx": "1", "port_profile_id": "A"}]

    merged = merge_embedded(existing, [{"port_idx": 1, "port_profile_id": "B"}], key="port_idx")

    assert merged == [{"port_idx": 1, "port_profile_id": "B"}]


def test_merge_embedded_of_an_empty_list_is_the_entries() -> None:
    entries = [{"port_idx": 1, "port_profile_id": "A"}]

    merged = merge_embedded([], entries, key="port_idx")

    assert merged == entries


def test_merge_embedded_of_no_entries_keeps_the_rows() -> None:
    existing = [{"port_idx": 1, "port_profile_id": "A"}]

    merged = merge_embedded(existing, [], key="port_idx")

    assert merged == existing


def test_merge_embedded_does_not_mutate_its_inputs() -> None:
    existing = [{"port_idx": 1, "port_profile_id": "A"}]
    entries = [{"port_idx": 1, "port_profile_id": "B"}]

    merge_embedded(existing, entries, key="port_idx")

    assert existing == [{"port_idx": 1, "port_profile_id": "A"}]
    assert entries == [{"port_idx": 1, "port_profile_id": "B"}]


def _device(*overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": "d1",
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "AP",
        "port_overrides": [dict(override) for override in overrides],
    }


_MAC = "aa:bb:cc:dd:ee:01"


def test_embedded_entries_are_merged_into_a_created_document() -> None:
    client = _Store([])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={"mac": _MAC, "name": "AP"},
        key="mac",
        name=_MAC,
        embed={"port_overrides": ("port_idx", [{"port_idx": 1, "port_profile_id": "A"}])},
    )

    assert client.posts == 1
    assert outcome.changed is True
    assert outcome.after["port_overrides"] == [{"port_idx": 1, "port_profile_id": "A"}]


def test_embedded_merge_in_check_mode_reports_without_writing() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        check_mode=True,
        embed={"port_overrides": ("port_idx", [{"port_idx": 1, "port_profile_id": "B"}])},
    )

    assert client.sets == 0
    assert outcome.changed is True
    assert outcome.before["port_overrides"][0]["port_profile_id"] == "A"
    assert outcome.after["port_overrides"][0]["port_profile_id"] == "B"


def test_a_changed_embedded_entry_is_written() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed={"port_overrides": ("port_idx", [{"port_idx": 1, "port_profile_id": "B"}])},
    )

    assert outcome.changed is True
    assert client.sets == 1
    assert client.rows[0]["port_overrides"] == [{"port_idx": 1, "port_profile_id": "B"}]


def test_a_second_run_with_the_same_embedded_entries_reports_no_change() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])
    embed = {"port_overrides": ("port_idx", [{"port_idx": 1, "port_profile_id": "B"}])}

    first = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed=embed,
    )
    second = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed=embed,
    )

    assert first.changed is True
    assert second.changed is False


def test_an_unnamed_embedded_entry_is_not_compared() -> None:
    # The task owns one port. Another port holding a different setting is not drift
    # the task expressed, so it must not read as a change.
    client = _Store(
        [
            _device(
                {"port_idx": 1, "port_profile_id": "A"},
                {"port_idx": 2, "port_profile_id": "B"},
            )
        ]
    )

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed={"port_overrides": ("port_idx", [{"port_idx": 1, "port_profile_id": "A"}])},
    )

    assert outcome.changed is False


def test_a_swap_of_two_embedded_entries_is_a_change() -> None:
    # Normalising the list strips port_idx, so two ports whose settings have been
    # swapped compare equal as a multiset. The keyed comparison has to see it.
    client = _Store(
        [
            _device(
                {"port_idx": 1, "port_profile_id": "A"},
                {"port_idx": 2, "port_profile_id": "B"},
            )
        ]
    )

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed={
            "port_overrides": (
                "port_idx",
                [
                    {"port_idx": 1, "port_profile_id": "B"},
                    {"port_idx": 2, "port_profile_id": "A"},
                ],
            )
        },
    )

    assert outcome.changed is True
    assert client.rows[0]["port_overrides"] == [
        {"port_idx": 1, "port_profile_id": "B"},
        {"port_idx": 2, "port_profile_id": "A"},
    ]


class _Racing:
    """A device whose first write collides with a change to another port."""

    def __init__(self, initial: dict[str, Any], moved: dict[str, Any]) -> None:
        self.row = dict(initial)
        self._moved = dict(moved)
        self.sets: list[dict[str, Any]] = []

    def get(self, resource: str) -> Any:
        return {"data": [dict(self.row)]}

    def set(self, resource: str, body: Any) -> None:
        self.sets.append(dict(body))
        if len(self.sets) == 1:
            self.row = dict(self._moved)
            raise UniFiConcurrencyError("the document moved")
        self.row = dict(body)


def test_the_retry_recomputes_the_embedded_merge_from_the_re_read_document() -> None:
    # The first attempt merged into the document as it stood before the collision.
    # A retry that reused that merge would write over the concurrent change to a
    # port the task never named, which is the lost update the retry exists to stop.
    client = _Racing(
        _device({"port_idx": 1, "port_profile_id": "A"}),
        _device({"port_idx": 1, "port_profile_id": "C"}),
    )

    outcome = apply(
        client,
        collection="/rest/device",
        read="/stat/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed={"port_overrides": ("port_idx", [{"port_idx": 2, "port_profile_id": "B"}])},
    )

    assert len(client.sets) == 2
    assert outcome.changed is True
    assert client.sets[0]["port_overrides"] == [
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 2, "port_profile_id": "B"},
    ]
    assert client.sets[1]["port_overrides"] == [
        {"port_idx": 1, "port_profile_id": "C"},
        {"port_idx": 2, "port_profile_id": "B"},
    ]


def test_dropping_an_existing_entry_is_a_change() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop={"port_overrides": ("port_idx", [1])},
    )

    assert outcome.changed is True
    assert client.sets == 1
    assert client.rows[0]["port_overrides"] == []


def test_dropping_an_absent_identity_is_not_a_change() -> None:
    # An identity the controller does not hold is already absent, so a removal
    # aimed at it has nothing to do and must not write.
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop={"port_overrides": ("port_idx", [2])},
    )

    assert outcome.changed is False
    assert client.sets == 0
    assert client.rows[0]["port_overrides"] == [{"port_idx": 1, "port_profile_id": "A"}]


def test_a_second_drop_reports_no_change() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])
    drop = {"port_overrides": ("port_idx", [1])}

    first = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop=drop,
    )
    second = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop=drop,
    )

    assert first.changed is True
    assert second.changed is False


def test_a_drop_preserves_the_entries_it_does_not_name() -> None:
    client = _Store(
        [
            _device(
                {"port_idx": 1, "port_profile_id": "A"},
                {"port_idx": 2, "port_profile_id": "B"},
                {"port_idx": 3, "port_profile_id": "C"},
            )
        ]
    )

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop={"port_overrides": ("port_idx", [2])},
    )

    assert outcome.changed is True
    assert client.rows[0]["port_overrides"] == [
        {"port_idx": 1, "port_profile_id": "A"},
        {"port_idx": 3, "port_profile_id": "C"},
    ]


def test_a_drop_in_check_mode_reports_without_writing() -> None:
    client = _Store([_device({"port_idx": 1, "port_profile_id": "A"})])

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        check_mode=True,
        drop={"port_overrides": ("port_idx", [1])},
    )

    assert client.sets == 0
    assert outcome.changed is True
    assert outcome.before["port_overrides"] == [{"port_idx": 1, "port_profile_id": "A"}]
    assert outcome.after["port_overrides"] == []


def test_the_retry_recomputes_the_drop_from_the_re_read_document() -> None:
    # The first attempt removed the target from the document as it stood before the
    # collision. A retry that reused that list would write over the entry another
    # writer added, so the removal is recomputed from the re-read document.
    client = _Racing(
        _device({"port_idx": 1, "port_profile_id": "A"}),
        _device(
            {"port_idx": 1, "port_profile_id": "A"},
            {"port_idx": 2, "port_profile_id": "B"},
        ),
    )

    outcome = apply(
        client,
        collection="/rest/device",
        read="/stat/device",
        wanted={},
        key="mac",
        name=_MAC,
        drop={"port_overrides": ("port_idx", [1])},
    )

    assert len(client.sets) == 2
    assert outcome.changed is True
    assert client.sets[0]["port_overrides"] == []
    assert client.sets[1]["port_overrides"] == [{"port_idx": 2, "port_profile_id": "B"}]


def test_embed_and_drop_on_one_field_merge_then_remove() -> None:
    client = _Store(
        [
            _device(
                {"port_idx": 1, "port_profile_id": "A"},
                {"port_idx": 2, "port_profile_id": "B"},
                {"port_idx": 3, "port_profile_id": "C"},
            )
        ]
    )

    outcome = apply(
        client,
        collection="/rest/device",
        wanted={},
        key="mac",
        name=_MAC,
        embed={"port_overrides": ("port_idx", [{"port_idx": 2, "port_profile_id": "X"}])},
        drop={"port_overrides": ("port_idx", [1])},
    )

    assert outcome.changed is True
    assert client.rows[0]["port_overrides"] == [
        {"port_idx": 2, "port_profile_id": "X"},
        {"port_idx": 3, "port_profile_id": "C"},
    ]


def test_a_secret_the_controller_holds_is_removed_from_what_is_reported() -> None:
    # no_log masks the value the task supplied, not the copy the controller already
    # holds, which an update that does not restate the secret still reads back.
    # Redaction is reporting only, so the write still carries the secret.
    client = _Store([{"_id": "w1", "name": "Office", "enabled": True, "x_passphrase": "stored"}])

    outcome = apply(
        client,
        collection="/rest/wlanconf",
        wanted={"enabled": False},
        name="Office",
    )
    result = outcome.as_result()

    assert "x_passphrase" not in result["obj"]
    assert "x_passphrase" not in result["diff"]["before"]
    assert "x_passphrase" not in result["diff"]["after"]
    assert client.rows[0]["x_passphrase"] == "stored"


def test_a_secret_is_removed_from_a_reported_document_at_any_depth() -> None:
    client = _Store(
        [
            {
                "_id": "w1",
                "name": "Office",
                "x_passphrase": "stored",
                "config": {"x_passphrase": "nested"},
            }
        ]
    )

    outcome = apply(client, collection="/rest/wlanconf", wanted={}, name="Office")

    assert "x_passphrase" not in outcome.as_result()["obj"]["config"]


def test_a_secret_nested_in_a_list_of_mappings_is_removed_by_redact() -> None:
    # The WLAN stores per-network and SAE secrets as arrays of mappings. The name
    # is what identifies a secret however deeply it is nested, so the list items
    # are redacted too.
    document = {
        "_id": "w1",
        "name": "Office",
        "private_preshared_keys": [{"networkconf_id": "n1", "password": "stored"}],
        "sae_psk": [{"id": "a", "psk": "stored"}],
    }

    reported = redact(document)

    assert reported["private_preshared_keys"] == [{"networkconf_id": "n1"}]
    assert reported["sae_psk"] == [{"id": "a"}]
    # Reporting only: the document that was handed in is untouched.
    assert document["private_preshared_keys"][0]["password"] == "stored"


def test_a_nested_secret_is_redacted_only_in_the_report() -> None:
    # The comparison and the write see the controller's own value. Redacting
    # either would make a restated secret read as a change and write a document
    # missing the secret the controller holds.
    client = _Store(
        [
            {
                "_id": "w1",
                "name": "Office",
                "enabled": True,
                "private_preshared_keys": [{"networkconf_id": "n1", "password": "stored"}],
            }
        ]
    )
    wanted = {
        "enabled": True,
        "private_preshared_keys": [{"networkconf_id": "n1", "password": "stored"}],
    }

    same = apply(client, collection="/rest/wlanconf", wanted=wanted, name="Office")

    assert same.changed is False
    assert client.sets == 0

    changed = apply(
        client,
        collection="/rest/wlanconf",
        wanted={"enabled": False},
        name="Office",
    )
    result = changed.as_result()

    assert changed.changed is True
    # The write carried the stored secret forward rather than writing a document
    # without it.
    assert client.rows[0]["private_preshared_keys"][0]["password"] == "stored"
    assert "password" not in result["obj"]["private_preshared_keys"][0]
    assert "password" not in result["diff"]["after"]["private_preshared_keys"][0]


def test_check_mode_reports_the_document_it_would_create() -> None:
    client = _Store([])

    outcome = apply(
        client,
        collection="/rest/networkconf",
        wanted={"name": "IoT"},
        name="IoT",
        check_mode=True,
    )
    result = outcome.as_result()

    assert result["obj"] == result["diff"]["after"]
    assert result["obj"]["name"] == "IoT"
    assert client.posts == 0


def test_check_mode_reports_the_document_it_would_write() -> None:
    client = _Store([{"_id": "n1", "name": "LAN", "purpose": "corporate"}])

    outcome = apply(
        client,
        collection="/rest/networkconf",
        wanted={"purpose": "guest"},
        name="LAN",
        check_mode=True,
    )
    result = outcome.as_result()

    assert result["obj"] == result["diff"]["after"]
    assert result["obj"]["purpose"] == "guest"
    assert client.sets == 0


def test_a_name_matching_several_rows_is_refused() -> None:
    # Two rows carrying the name the task stated make the object it means
    # ambiguous. Picking the first would aim a write at a row the task never named.
    client = _Store([{"_id": "n1", "name": "LAN"}, {"_id": "n2", "name": "LAN"}])

    with pytest.raises(UniFiError, match="ambiguous"):
        apply(client, collection="/rest/networkconf", wanted={"purpose": "corporate"}, name="LAN")


def test_a_selected_removal_reports_no_object() -> None:
    client = _Store([{"_id": "n1", "name": "LAN"}])

    result = remove(client, collection="/rest/networkconf", name="LAN", what="network").as_result()

    assert "obj" not in result


def test_a_removal_of_an_absent_object_reports_no_object() -> None:
    client = _Store([])

    result = remove(client, collection="/rest/networkconf", name="LAN", what="network").as_result()

    assert result["changed"] is False
    assert "obj" not in result
