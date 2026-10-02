# SPDX-License-Identifier: BSD-2-Clause
"""Reconciling one object on the controller.

Internal to this collection. See :mod:`._api` for what the private package path
means.

Every mutating module in this collection performs the same five steps in the same
order, and a module that varies the order varies the bugs. Factoring them here is
what makes each module a thin adapter over an argument spec and a field map, and
what makes "a second run reports no change" a property of the collection rather
than of each module's author.

The order is not arbitrary:

1. Read the object as it stands, or take the caller's word for it.
2. Reduce the task's options to the fields that object actually holds.
3. Compare only those fields, canonically.
4. Stop, reporting the change, if this is a check-mode run.
5. Write, then re-read, and report what the controller now holds.

**A field holding a list of keyed documents is merged, not replaced.** A device
carries ``port_overrides`` as an array keyed by ``port_idx``, and a task setting
one port does not own the others. ``embed`` names such a field together with its
key, and ``drop`` names keyed identities to remove from it. On every attempt the
field is rebuilt from the document just read, the task's entries merged in and the
dropped identities removed, so an entry the task did not name survives a concurrent
change rather than being written over with a list computed earlier. The comparison
of such a field is keyed as well: normalising the array strips the key, because
``port_idx`` is server generated for the hardware port table, so two ports with
their settings swapped would otherwise read as equal.

The re-read in step 5 is what makes the reported result true rather than
optimistic. A controller may normalise a value on the way in, may fill a field in,
and may reject part of a document while accepting the rest; reporting what was sent
would report something the network does not have.

A caller that already holds the current document passes it through ``current``, and
that skips only the read at step 1. The document it passes must be a fresh read of
the object, not one the caller has held across other work: a stale document makes
``differences`` report no change without the controller being consulted at all, so
a conflict the controller would have reported never reaches the caller. The
concurrency retry still re-reads and recomputes regardless of ``current``, because
the point of the retry is to look at what the controller holds now.

**The diff is top-level.** ``before`` and ``after`` are siblings, not nested under
a ``diff`` key. The callback that renders a changed task reads the top level and
nothing else, and a diff nested one level down renders as nothing at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import SECRET_FIELDS
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import compare
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.canon import differences
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiConcurrencyError,
)
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import UniFiError
from ansible_collections.abn.unifi_network.plugins.module_utils._unifi.errors import (
    UniFiNotFoundError,
)

__all__ = [
    "Outcome",
    "apply",
    "merge_embedded",
    "redact",
    "reference",
    "remove",
    "resolve_id",
    "rows",
    "select",
    "select_one",
]


def rows(body: Any) -> list[dict[str, Any]]:
    """Public alias, so a module selects from a response it already holds."""
    return _rows(body)


def select_one(
    client: Any,
    collection: str,
    *,
    key: str = "name",
    name: str = "",
    match: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Public alias, so a module finds one object without writing one.

    The selection is the one :func:`apply` and :func:`remove` use, so a caller
    deciding whether to create reports on the same row the reconciler would act on,
    and an ambiguous identity is refused here as it is there.
    """
    return _select_one(client, collection, key=key, name=name, match=match)


def merge_embedded(
    existing: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    """Merge keyed entries into an existing list, returning a new list.

    Each entry replaces the existing row carrying the same value under ``key``,
    keeping that row's position, or is appended when no row carries it. Rows the
    entries do not name are preserved in place, so a task setting one port does not
    disturb the others. A repeated identity in ``existing`` is not collapsed: the
    last row carrying it is replaced and the earlier duplicates remain. The key is
    compared as text because an index arrives from an argument spec as an integer
    while the controller may answer it as a string.
    """
    merged = [dict(row) for row in existing]
    position = {str(row.get(key, "")): index for index, row in enumerate(merged)}
    for entry in entries:
        identity = str(entry.get(key, ""))
        if identity in position:
            merged[position[identity]] = dict(entry)
        else:
            position[identity] = len(merged)
            merged.append(dict(entry))
    return merged


def redact(document: Any) -> Any:
    """A reported copy of a controller document, with the secret fields removed.

    The names removed are :data:`SECRET_FIELDS`, the secret fields of the resources
    whose rows are reported, at any depth, so a secret nested in a list of mappings
    does not escape.

    Reporting only: the value written and the value compared are the controller's
    own. Removing a secret before the comparison would make a changed passphrase
    read as unchanged, and removing it before the write would send a document the
    controller rejects.
    """
    if isinstance(document, Mapping):
        return {
            str(key): redact(value)
            for key, value in document.items()
            if str(key) not in SECRET_FIELDS
        }
    if isinstance(document, Sequence) and not isinstance(document, str | bytes):
        return [redact(item) for item in document]
    return document


#: How many times a write is attempted when the controller reports that the
#: document moved underneath us. Each attempt re-reads and recomputes rather than
#: resending, so a collision costs a round trip and not an overwrite.
CONVERGENCE_ATTEMPTS = 3


class _Unset:
    """Marks a keyword the caller did not supply, distinct from ``None``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "_UNSET"


#: The default for ``current``. ``None`` is a real value meaning the object is
#: absent, so it cannot double as "read it yourself".
_UNSET = _Unset()


class Outcome:
    """What a module reports about one object."""

    def __init__(
        self,
        *,
        changed: bool,
        before: Any = None,
        after: Any = None,
        found: bool = True,
        obj: Any = None,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.changed = changed
        self.before = before
        self.after = after
        self.found = found
        self.obj = obj
        self.changes = changes or {}

    def as_result(self) -> dict[str, Any]:
        """The keyword arguments a module hands to ``exit_json``.

        ``diff`` is emitted even when nothing changed, with ``after`` equal to
        ``before``. A check-mode run that reports a diff has to show what it would
        have done, and a diff whose two sides are equal is how that reads.

        Every reported document is passed through :func:`redact`, so a secret the
        controller holds and the task did not restate is not returned.
        """
        result: dict[str, Any] = {
            "changed": self.changed,
            "diff": {
                "before": redact(self.before),
                "after": redact(self.before if not self.changed else self.after),
            },
        }
        if self.obj is not None:
            result["obj"] = redact(self.obj)
        if self.changes:
            result["changed_fields"] = sorted(self.changes)
        return result


def apply(
    client: Any,
    *,
    collection: str,
    wanted: Mapping[str, Any],
    key: str = "name",
    name: str = "",
    match: Mapping[str, Any] | None = None,
    check_mode: bool = False,
    read: str = "",
    current: Any = _UNSET,
    embed: Mapping[str, tuple[str, Sequence[Mapping[str, Any]]]] | None = None,
    drop: Mapping[str, tuple[str, Sequence[Any]]] | None = None,
) -> Outcome:
    """Reconcile one object in a collection, creating it when absent.

    A collection is the addressable unit on these endpoints: the controller
    rejects a ``PUT`` to a collection with no identifier and answers
    ``api.err.IdRequired``, so a resource has to be selected out of a list before
    it can be written, and created by ``POST`` to the collection rather than
    replaced in place.

    ``name`` selects on ``key``. ``match`` selects on every pair it states and
    takes precedence when both are given, because an identity that is one field on
    one resource is several on another: a firewall rule is named within a ruleset,
    so two rules may share a name and the ruleset is what tells them apart.

    ``read`` is where the current document is read from, when that differs from
    where it is written. A device is listed at ``/stat/device`` and written at
    ``/rest/device``, and reading the write path answers 404 on deployments that
    serve only the listing, which reads like the object being absent.

    ``current`` is the document the caller already holds, and skips the initial
    read only. It must be a fresh read of the object, and ``None`` means the
    object is absent. A stale document makes ``differences`` report no change
    without the controller being consulted, so it never survives a concurrency
    report: the retry re-reads and recomputes whatever the caller supplied.

    ``embed`` names a field on the parent that holds a list of keyed documents.
    Each value is the identity field of an entry together with the entries the
    task manages. The list is merged into whatever the controller holds on every
    attempt, so entries the task does not name are preserved even when a collision
    forces a retry, and the field is compared entry by entry rather than as a
    normalised list.

    ``drop`` names the same kind of field together with the keyed identities to
    remove from it. The list is rebuilt from the document just read on every
    attempt, removals included, so a removal computed before a collision does not
    write over an entry another writer added. Removing an identity the controller
    does not hold is not a change, and a field may carry both ``embed`` entries and
    a ``drop`` in one call.

    ``obj`` is the document being reported, and in check mode it is the document
    the run would write: the payload for a create and the merged document for an
    update, so it equals ``diff.after`` whether or not a write happened. A
    removal reports no ``obj`` at all, because there is nothing left to describe.

    Two combinations are outside the contract. A field must not be named in both
    ``wanted`` and ``drop``: the plain field is discarded when a drop names it, so
    the wanted value never reaches the document. ``embed`` and ``drop`` must not
    name the same identity either: the merge runs before the drop, so the entry is
    written and then removed, and the run can report a change while writing a
    document equal to the current one.
    """
    if not name and not match:
        raise UniFiError(
            f"reconciling {collection} needs the {key} value or a match to select it by"
        )

    source = read or collection
    if current is _UNSET:
        current = _select_one(client, source, key=key, name=name, match=match)

    if current is None:
        return _create(
            client,
            collection,
            wanted,
            key=key,
            name=name,
            match=match,
            check_mode=check_mode,
            read=source,
            embed=embed,
            drop=drop,
        )

    payload, found = _document(current, wanted, embed=embed, drop=drop)
    if not found:
        return Outcome(changed=False, before=current, after=current, obj=current)

    if check_mode:
        return Outcome(changed=True, before=current, after=payload, obj=payload, changes=found)

    resource = f"{collection}/{current['_id']}"
    attempt = 0
    while True:
        attempt += 1
        try:
            client.set(resource, payload)
        except UniFiConcurrencyError:
            # The document moved between the read and the write. Re-read and
            # recompute rather than resending, so the other writer's change
            # survives. For an embedded field that means rebuilding the merged
            # list from the re-read document, not reusing the one already built.
            if attempt >= CONVERGENCE_ATTEMPTS:
                raise
            current = _select_one(client, source, key=key, name=name, match=match)
            if current is None:
                return _create(
                    client,
                    collection,
                    wanted,
                    key=key,
                    name=name,
                    match=match,
                    check_mode=check_mode,
                    read=source,
                    embed=embed,
                    drop=drop,
                )
            payload, found = _document(current, wanted, embed=embed, drop=drop)
            if not found:
                return Outcome(changed=False, before=current, after=current, obj=current)
            continue

        after = _select_one(client, source, key=key, name=name, match=match) or payload
        return Outcome(
            changed=True,
            before=current,
            after=after,
            obj=after,
            changes=found,
        )


def remove(
    client: Any,
    *,
    collection: str,
    name: str = "",
    what: str,
    match: Mapping[str, Any] | None = None,
    check_mode: bool = False,
    protect_default: bool = False,
) -> Outcome:
    """Delete one object, or report that it was already gone.

    ``name`` and ``match`` select the object exactly as they do in :func:`apply`,
    and ``match`` is what tells two firewall rules in different rulesets apart.

    A second run has to report no change, so an absent object is not a change
    either. A removal reports no ``obj``, because the object the result would
    describe no longer exists. The controller's own flag marks an object it refuses
    to remove, and a refusal here names the object rather than the payload a write
    would report.
    ``protect_default`` extends that to the site's default network, which the
    console will not remove either.
    """
    current = _select_one(client, collection, key="name", name=name, match=match)
    if current is None:
        return Outcome(changed=False, before={}, after={})

    label = _selection("name", name, match)
    if current.get("attr_no_delete") or (protect_default and current.get("default")):
        raise UniFiError(
            f"the {what} {label} is one the controller will not remove; "
            "rename it in the console if it is no longer wanted"
        )

    if not check_mode:
        client.delete(f"{collection}/{current['_id']}")
        # A delete answered with a success status is not proof that the
        # controller stopped listing the object.
        if _select_one(client, collection, key="name", name=name, match=match) is not None:
            raise UniFiError(f"the controller accepted the removal of {label} but still lists it")

    return Outcome(changed=True, before=current, after={})


def _select_one(
    client: Any,
    collection: str,
    *,
    key: str,
    name: str = "",
    match: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The one object in a collection selected by ``name`` or ``match``, or ``None``.

    Absence is decided from the payload rather than from the status, because the
    controller answers a read of an identifier that does not exist with a success
    status and no rows.

    Both paths refuse an identity that fits more than one row. A name is an
    identity the caller stated, so two rows carrying it are the caller saying which
    object it means without the object being unique, and picking the first would
    aim a write at a row the task never named. ``None`` is returned only when no
    row carries the name.
    """
    if not name and not match:
        raise UniFiError(
            f"reconciling {collection} needs the {key} value or a match to select it by"
        )
    body = client.get(collection)
    if match:
        matched = [
            row
            for row in rows(body)
            if all(str(row.get(k, "")) == str(v) for k, v in match.items())
        ]
        if len(matched) > 1:
            ids = ", ".join(sorted(str(row.get("_id", "?")) for row in matched))
            raise UniFiError(
                f"{len(matched)} rows in {collection} match {_selection(key, name, match)}, "
                f"so the one to change is ambiguous; narrow the match or name it by its "
                f"identifier (candidates: {ids})"
            )
        return matched[0] if matched else None
    named = [row for row in rows(body) if str(row.get(key, "")) == name]
    if len(named) > 1:
        ids = ", ".join(sorted(str(row.get("_id", "?")) for row in named))
        raise UniFiError(
            f"{len(named)} rows in {collection} have {key}={name!r}, so the one to "
            f"change is ambiguous; rename one or address it by its identifier "
            f"(candidates: {ids})"
        )
    return named[0] if named else None


def _selection(key: str, name: str, match: Mapping[str, Any] | None) -> str:
    """How a selection reads in a message."""
    if match:
        return ", ".join(f"{field}={value!r}" for field, value in match.items())
    return f"{key}={name!r}"


def select(
    rows: Any,
    *,
    key: str,
    wanted: str,
    what: str,
) -> Mapping[str, Any]:
    """Pick exactly one row by an exact key.

    Zero matches and more than one match are both errors, and neither is resolved
    by picking one. On a controller holding two networks with the same name,
    guessing which one a write is aimed at is how the wrong one is changed, and
    the mistake is only visible afterwards.
    """
    matched = [row for row in _rows(rows) if str(row.get(key, "")) == wanted]
    if not matched:
        raise UniFiNotFoundError(f"no {what} named {wanted!r} on the controller")
    if len(matched) > 1:
        ids = ", ".join(sorted(str(row.get("_id", "?")) for row in matched))
        raise UniFiError(
            f"{len(matched)} {what}s are named {wanted!r}, so the one to change is "
            f"ambiguous; name it by its identifier instead (candidates: {ids})"
        )
    return matched[0]


def resolve_id(
    client: Any,
    collection: str,
    *,
    name: str,
    what: str,
    key: str = "name",
) -> str:
    """The identifier of the one object a name refers to.

    A task that names an object the controller keys by identifier cannot be
    written without knowing that identifier, and an identifier read out of the
    console is a string in a playbook that nothing checks. Naming the object and
    letting the controller supply the identifier moves the one thing only the
    controller knows to the place that can answer it.

    Zero and several matches are errors here for the same reason they are in
    :func:`select`: a reference that resolved to an arbitrary member of a set
    would aim a write at an object the task never named.
    """
    return str(select(rows(client.get(collection)), key=key, wanted=name, what=what)["_id"])


def reference(
    client: Any,
    collection: str,
    *,
    name: str = "",
    identifier: str = "",
    what: str,
    key: str = "name",
) -> str:
    """One reference to another object, given as a name or as an identifier.

    Naming both is an error rather than a precedence rule, because a task that
    says ``network: LAN`` and ``network_id: 5f2b...`` has two answers to one
    question and the collection has no basis for choosing between them.
    """
    if name and identifier:
        raise UniFiError(
            f"{what} was given both as a name and as an identifier; a reference is one or "
            "the other, and a task stating both has two answers to one question"
        )
    if identifier:
        return identifier
    if not name:
        raise UniFiError(f"a {what} reference was given neither a name nor an identifier")
    return resolve_id(client, collection, name=name, what=what, key=key)


def _rows(body: Any) -> list[dict[str, Any]]:
    """Every object in a collection response."""
    if isinstance(body, Mapping):
        body = body.get("data", [])
    if not isinstance(body, list):
        return []
    return [dict(row) for row in body if isinstance(row, Mapping)]


def _create(
    client: Any,
    collection: str,
    wanted: Mapping[str, Any],
    *,
    key: str,
    name: str,
    match: Mapping[str, Any] | None = None,
    check_mode: bool,
    read: str = "",
    embed: Mapping[str, tuple[str, Sequence[Mapping[str, Any]]]] | None = None,
    drop: Mapping[str, tuple[str, Sequence[Any]]] | None = None,
) -> Outcome:
    """Create one object by posting to the collection.

    Creation is a POST to the collection rather than a PUT to a path, because a
    path that does not exist yet has no identifier to address.

    The created object is read back by name rather than by position. A POST
    answers with the object it made, but reading the collection and taking the
    first row would report whatever the site happened to list first, which on a
    site that already holds networks is never the one just created.

    A dropped identity contributes nothing to a created object, because the
    controller holds no entry to remove, so the drop only filters what ``embed``
    would have posted.
    """
    payload = dict(wanted)
    found = dict(wanted)
    for field, (identity, entries) in (embed or {}).items():
        payload[field] = merge_embedded([], entries, key=identity)
        found.pop(field, None)
        found.update(_embedded_differences([], entries, field=field, key=identity))
    for field, (identity, ids) in (drop or {}).items():
        found.pop(field, None)
        if field not in payload:
            continue
        removable = {str(value) for value in ids}
        payload[field] = _without(payload.get(field) or [], removable, key=identity)
    if check_mode:
        return Outcome(changed=True, before={}, after=payload, obj=payload, changes=found)

    client.post(collection, payload)
    after = _select_one(client, read or collection, key=key, name=name, match=match) or payload
    return Outcome(changed=True, before={}, after=after, obj=after, changes=found)


def _document(
    current: Mapping[str, Any],
    wanted: Mapping[str, Any],
    *,
    embed: Mapping[str, tuple[str, Sequence[Mapping[str, Any]]]] | None,
    drop: Mapping[str, tuple[str, Sequence[Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The document to write, and the differences it expresses.

    The document is rebuilt from ``current`` rather than kept between attempts, so
    an embedded field is merged into the list the controller holds at the moment
    of the write. A merge frozen before a collision would be written over the
    other writer's change to an entry the task never named. A drop is applied to
    the same freshly built list, so a removal does not write over an entry another
    writer added either.
    """
    embedded = embed or {}
    dropped = drop or {}
    plain = {
        field: value
        for field, value in wanted.items()
        if field not in embedded and field not in dropped
    }
    changes = differences(plain, current)
    payload = {**current, **plain}
    for field, (identity, entries) in embedded.items():
        existing = current.get(field) or []
        payload[field] = merge_embedded(existing, entries, key=identity)
        changes.update(_embedded_differences(existing, entries, field=field, key=identity))
    for field, (identity, ids) in dropped.items():
        if field not in payload:
            continue
        removable = {str(value) for value in ids}
        payload[field] = _without(payload.get(field) or [], removable, key=identity)
        changes.update(
            _dropped_differences(current.get(field) or [], removable, field=field, key=identity)
        )
    return payload, changes


def _without(
    rows: Sequence[Mapping[str, Any]],
    removable: set[str],
    *,
    key: str,
) -> list[dict[str, Any]]:
    """The rows left once the identified entries are removed."""
    return [dict(row) for row in rows if str(row.get(key, "")) not in removable]


def _dropped_differences(
    existing: Sequence[Mapping[str, Any]],
    removable: set[str],
    *,
    field: str,
    key: str,
) -> dict[str, Any]:
    """The dropped identities the controller currently holds.

    An identity the list does not carry is not a difference, so a second removal
    reports no change the same way removing an already absent object does. Rows that
    are neither dropped nor named by ``embed`` are not evidence of anything.
    """
    present = {str(row.get(key, "")) for row in existing}
    return {
        f"{field}[{key}={identity}]": None for identity in sorted(removable) if identity in present
    }


def _embedded_differences(
    existing: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    *,
    field: str,
    key: str,
) -> dict[str, Any]:
    """The named entries that differ from the list the controller holds.

    Compared by identity rather than as a normalised list. A normalised list loses
    the identity, so two entries with their settings swapped compare equal; here a
    named entry that does not match its row is a difference, and a row the task did
    not name is not evidence of anything.
    """
    rows = {str(row.get(key, "")): row for row in existing}
    found: dict[str, Any] = {}
    for entry in entries:
        identity = str(entry.get(key, ""))
        label = f"{field}[{key}={identity}]"
        row = rows.get(identity)
        if row is None:
            found[label] = dict(entry)
            continue
        for name, value in entry.items():
            if name != key and not compare(value, row.get(name)):
                found[f"{label}.{name}"] = value
    return found
