---
type: Overview
title: Overview
description: What this collection manages, how the UniFi controller API is shaped, and what is
  not designed yet.
status: draft
tags:
  - unifi
  - ubiquiti
  - ansible
  - collection
---

# Overview

`abn.unifi_network` manages UniFi Network devices declaratively, through the
UniFi controller API. A playbook declares the state it wants and the modules bring
the network to it, writing only what differs.

Thirteen modules exist. Ten manage a resource: `unifi_network`, `unifi_wlan`,
`unifi_device`, `unifi_dhcp_reservation`, `unifi_port_forward`,
`unifi_firewall_rule`, `unifi_firewall_zone`, `unifi_firewall_policy`,
`unifi_port_profile` and `unifi_port_override`. Three
read one: `unifi_network_info`, `unifi_device_info` and `unifi_client_info`.
Each is verified against the throwaway controller
described in [contribution/live-testing.md](contribution/live-testing.md). The
table below maps each resource to its module, or records that no module covers
it. The statements about shape are what the collection is designed around; where
code and this page disagree, the code wins and the correction goes in
[log.md](log.md).

## What is being managed

| Resource | Shape in the controller API | Status |
|---|---|---|
| Site settings | A single settings object, read and written as one document | Not designed |
| Networks | A collection, created and deleted individually | `unifi_network` |
| WLANs | A collection, with a configuration that a restore overwrites as a whole | `unifi_wlan` |
| Clients and their DHCP reservations | One collection at `rest/user`, keyed by MAC, which a playbook may create for a device it has never seen | `unifi_dhcp_reservation` |
| Client groups | A collection at `rest/usergroup`, holding rate limits rather than identities | Not designed |
| Port forwards | A collection at `rest/portforward`, with per-object endpoints | `unifi_port_forward` |
| Devices and their adoption | Discovered, with adoption an action rather than a field | `unifi_device`, refusing rather than adopting |
| Classic firewall rules | A collection at `rest/firewallrule`, selected by ruleset and name | `unifi_firewall_rule` |
| Switch port profiles | A collection at `rest/portconf`, storing a profile's networks as a native network plus an excluded list | `unifi_port_profile` |
| Port overrides | A keyed list on the device document, merged by port index rather than an endpoint of its own | `unifi_port_override`, and `unifi_device`'s `port_overrides` |
| Firewall zones and policies | A separate engine above the site, addressed per object | `unifi_firewall_zone`, `unifi_firewall_policy` |
| The rest of the per-site configuration | A large settings surface with no per-object endpoints | Not designed |
| Network, device and client inventory | Projections of the controller's own rows | `unifi_network_info`, `unifi_device_info`, `unifi_client_info` |

Two properties of the controller shape the design more than anything else, and
both are stated here because they explain the module boundaries.

**The collection's resources are per-object collections, with one exception that
is handled explicitly.** A network, a wireless network, a device, a port forward,
a classic firewall rule and a port profile are each a collection with per-object
endpoints, so a task addresses the one object it names. A port profile is stored
differently again: the console keeps its networks as a native network plus a list
of the networks the profile excludes, so a task names the native and tagged
networks and the module computes the exclusion list as the complement of
everything the site holds. A network added to the site later is therefore
excluded by every profile that does not name it, which is the console's own model
rather than a choice the module makes.

A port override is not a collection of its own: it is one keyed element of the
`port_overrides` list on the device document. `unifi_port_override` reads the
device, replaces the one element and writes the document back, and `unifi_device`
merges a list of them by port index. Both preserve the entries a task does not
name, and the reconciler re-reads and recomputes when the controller reports a
concurrent change, so a stale merge is not written over another writer's entry.
That is a mechanism, not a policy: how the collection handles a concurrent change
to an entry a task did name is not designed (invariant 3).

The classic firewall rule engine is separate from the zone-based firewall, which
is a different engine above the site and is managed by `unifi_firewall_zone` and
`unifi_firewall_policy`. The rest of the per-site configuration has no per-object
endpoint and is a read-modify-write document; no module covers it, and its
concurrency behaviour is not designed either (invariant 3).

**The API surface differs by deployment, and the choice is configured rather than
probed.** A UniFi OS console serves the application behind `/proxy/network` and
offers both families: the legacy one and an official one that takes a stateless
API key. A self-hosted Network Application serves its own API at the root and
offers the legacy family alone, because an official key cannot be created there. A
task states the mount and the family; a wrong family is refused rather than probed
for, because a probe is a network call made before the credential is even checked.
No shipped module speaks the official family yet: every module in this collection
addresses the legacy family, and a task naming the official family is refused with
a clear message rather than sent to an endpoint no module implements.

## What the collection does not do

- Adopt, provision or factory-reset a device. Those actions have no end state a
  second run could compare against, and they take the site offline.
- Delete a client record. A client is discovered by the controller, and
  `DELETE rest/user/{id}` answers `api.err.NotFound` for a record that is there,
  so a task releases a reservation by clearing `use_fixedip` rather than by
  removing the record. What a reservation means is in scope; removing the
  controller's knowledge that a device exists is not.
- Manage anything through the UniFi Site Manager or the cloud-hosted admin
  surface. That is an account-level API with different authentication and
  different blast radius from the local controller.

## What a task costs the controller

Every task manages exactly one object, and no response is cached between tasks. A
writing task reads the collection it manages once to select the object, writes,
and reads it again to report what the controller now holds. Each reference a
task names by name is resolved with its own read of that reference's collection;
a reference named by identifier costs no read, because the identifier is already
in the task. A task may share one read across several names:
`unifi_port_profile` reads the network collection once and selects each named
network from that single read, and `unifi_port_override` shares one network read
across its list references. A singular reference is its own read.

The cost therefore multiplies with a loop. A play that loops a task over twenty
networks issues twenty selections, twenty writes and twenty re-reads, not one
collection read and one bulk write. A plural module and an action-plugin cache
were both considered and are deliberately not shipped:

- A plural module would be a second reconciler. It would have to read each
  element, diff each element against the document the controller holds, and merge
  each element's per-object surface, which is the work the per-object modules
  already do. A single collection-wide write would either replace the collection
  or reintroduce the lost-update surface the per-object merge exists to avoid.
- An action-plugin cache would hold one read of a reference collection across a
  loop of tasks. The reconciler re-reads and recomputes on every attempt
  precisely so that a stale document cannot make a run report no change, and a
  cache would defeat that. A cached document is the lost-update surface in a new
  place.

The concurrency policy the cache decision depends on is not designed yet. When it
is, the sibling collection's policy file is the model, and it fails closed rather
than proceeding (invariant 3).

## Where to read next

- [Contributing](contribution/README.md): how to set up, what the gates run, and
  the rule about live controllers.
- The module reference: `ansible-doc abn.unifi_network.unifi_network`, and the
  same command against each module name listed above.

## Pages still owed

The user-facing pages the collection does not have yet are named in
[`.agents/rules/documentation.md`](../.agents/rules/documentation.md) under "What
the collection will owe its users", so their absence is a known gap rather than
an oversight and the list has one home.

## Where the facts come from

Nothing in this collection is written from memory of the UniFi API. The field
tables and request paths live in `plugins/module_utils/_unifi/` and are asserted
against vendored copies of the controller's own API descriptions,
`tests/fixtures/unifi-integration-api.json` and
`tests/fixtures/unifi-local-api.yaml`, the way the sibling collection asserts
against Tailscale's. The spec-drift check that re-reads upstream is not written
yet; the sibling's `make spec/drift` is the model for it.
