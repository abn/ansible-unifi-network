---
type: Log
title: Knowledge base log
description: Evolution of this documentation bundle, kept separate from software release notes.
status: draft
tags:
  - documentation
---

# Knowledge base log

This file records how the **documentation bundle** changes: pages added, pages
deprecated, structural refactors. It is deliberately not a changelog. Software
release notes live in `CHANGELOG.md`, generated from `changelogs/fragments/`.

## 2026-10-06

- Invariant 1 is amended. A real controller the operator administers may now be
  used for verification, but only on the operator's explicit approval, asked for
  in the session and given for one named target, and only when the throwaway stack
  cannot answer the question. The default is unchanged, and the conditions live in
  `AGENTS.md`, which is the canonical home.
- The amendment is grounded in a measurement: the emulator can describe a modern
  gateway but cannot inform one. It sends AES-CBC where the controller requires
  AES-GCM, the latest emulator release adds no way to change that, and a legacy
  gateway does not bring the zone-based firewall up at all. So the firewall zone
  and policy modules had no target that could verify them.
- `unifi_firewall_zone` and `unifi_firewall_policy` are shipped, reversing the
  2026-09-30 conclusion that they could not be. The zone-based firewall was enabled
  on a gateway and the v2 policy engine measured, so both are now `overview.md`
  entries rather than a not-designed row. `unifi_firewall_zone` manages the zone
  resource at `v2/api/site/{site}/firewall/zone`; `unifi_firewall_policy` manages
  the chain at `v2/api/site/{site}/firewall-policies`, both on the policy engine's
  own base.
- Two measured corrections shape the policy module, and both are recorded on it.
  A create must state `create_allow_respond` false, or the controller refuses it
  with `api.err.FirewallPolicyCreateRespondTrafficPolicyNotAllowed`, so the module
  asserts it on a create rather than exposing it as an option. And the controller
  assigns `index` (a created policy received 10000), so the position is optional
  and is not sent when a task does not name it.
- `default_zone` is not a zone option. The controller derives it, and a create that
  carries it is refused with `Unrecognized field "default_zone"`. A system zone
  still comes back marked, and a removal of one is still refused.

## 2026-10-02

- `unifi_port_profile` and `unifi_port_override` are recorded in `overview.md` as
  designed resources, separate from the undesigned per-site configuration.
- `unifi_port_profile` manages a switch port profile at `rest/portconf`. A task
  names a native network and the tagged networks by name; the console stores a
  profile as the native network plus a list of excluded networks, so the module
  computes `excluded_networkconf_ids` as the complement of every network the site
  holds. The consequence, documented on the module, is that a network added to the
  site later is excluded by every profile that does not name it. The native
  reference is required when `state=present`, because the console marks no default
  network in a field the module can read.
- `unifi_port_override` manages one port's override on a device by `mac` and
  `port_idx`, and `unifi_device` takes a `port_overrides` list. A port takes a
  port profile or its own settings and never both; ports a task does not name keep
  their entries; removing one port's override is `unifi_port_override` with
  `state=absent`, which the merge cannot express.
- `forward` is not a task option on either port surface. The controller derives it
  from whether the port or its profile names networks, reading it back as `all`
  when it names none and `customize` when it does, and it overwrites a value that
  does not match what it derived, so a task changes forward by changing the
  networks.
- The kernel reconciles a keyed list embedded in a parent document. The reconciler
  merges the task's entries into the list the controller holds by the list's
  identity field, preserves entries the task did not name, compares entry by entry
  rather than as a normalised list, and rebuilds the merge from a fresh read on
  every convergence attempt. That is what lets `unifi_device` and
  `unifi_port_override` write the device document without owning ports they were
  not asked to change.
- **Correction to the port field tables.** `speed` and `full_duplex` are settable
  on a port profile and a port override, so neither belongs in the
  server-generated exclusion set: a difference in either has to reach the
  comparison or a port profile cannot fix a link speed. Excluding a name by name
  is safe only when no managed resource holds it as a setting.
- The throwaway stack emulates a fleet of two devices, an access point and a
  switch. The switch is what lets a port profile and a port override be verified
  against the real application rather than only a mock.
- The request model is documented in `overview.md`, where a consumer would look.
  A writing task reads the collection it manages once, re-reads it after the
  write, and pays one read per reference it names by name; nothing is cached. A
  loop therefore multiplies the cost. A plural module and an action-plugin cache
  were considered and are deliberately not shipped, the first because it is a
  second reconciler whose collection-wide write reverts to the lost-update
  surface, the second because a cached document is that surface in a new place and
  defeats the convergence retry. The concurrency policy both depend on remains not
  designed (invariant 3).
- The `api_family` description states that no shipped module speaks the official
  family and that naming it is refused with a clear message rather than reaching
  the wrong endpoint. It does not list what the official family covers, which
  would invite a choice the collection cannot serve.
- The `api_key` description reads "an integration key accepted on both families on
  a console". `api_key`, `username` and `password` warn that a console rate-limits
  logins, so a play that logs in can throttle itself and the refusal reads as a
  wrong password. The `api_mount` description gives the recognition cue: a console
  has an OS settings area and serves the application under `/proxy/network`, while
  a self-hosted Network Application serves it at the root.
- The `diff_mode` attribute describes what the modules return: a top-level `diff`
  with whole-document `before` and `after`, and the changed field names in
  `changed_fields`. `README.md` carries a console-plus-integration-key connection
  block, the deployment the live suite measures, alongside the self-hosted
  username and password shape.
- Secret redaction covers every secret field of the resources whose raw rows the
  modules report. `SECRET_FIELDS` names the network keys and passwords, the device
  passwords and the WLAN keys in the vendored schema, including the nested
  `WLANPrivatePresharedKeys.password` and `WLANSaePsk.psk` that recursion removes
  at any depth. The collection reports the controller's re-read row minus that
  list rather than projecting each resource's return to a whitelist: the module
  documents `obj` as the document the controller holds, and a per-resource
  projection would duplicate every schema in the kernel, where it would drift from
  the resources. A fixture-driven unit test walks the reported resources' schemas
  in `tests/fixtures/unifi-local-api.yaml` and fails on any secret-looking
  property a human has not classified, so a new secret is classified before it can
  ship silently.
- **Correction to the firewall rule contract.** `rule_index`, `action`, `protocol`
  and `enabled` are not required whenever `state=present`. The four are required
  only to create a rule, because the controller refuses a new document without
  them, and each is preserved when an update omits it: the reconciler merges the
  task into the document it read, so a task removing a rule is not asked for them
  either.

## 2026-10-01

- `unifi_firewall_rule` manages a classic rule at `rest/firewallrule`. A rule is
  selected by the pair `ruleset` and `name`, since the same name may appear in
  more than one chain. `overview.md` records classic firewall rules as a designed
  per-object collection, separate from the zone-based firewall.
- `unifi_port_forward` has aliases for its port, address, protocol and source
  options. `unifi_network` has `dhcp_dns`, a list that expands to the controller's
  four resolver slots and is mutually exclusive with the scalar `dhcp_dns_1`
  through `dhcp_dns_4`. `unifi_dhcp_reservation` has `local_dns_record`, the `ip`
  and `address` aliases for `fixed_ip`, can relabel a record without restating its
  address, and can omit the network reference on a record that already holds one.
- **Correction to the firewall conclusion.** The zone-based firewall was never an
  engine that refuses writes. On the deployment the collection is measured against
  it is simply unconfigured, answering
  `api.firewall.zone-based-firewall-not-configured`, and the earlier reading of a
  rebuilt site was a deployment state rather than an API limit. The classic engine
  at `rest/firewallrule` answers 200 to GET, POST, PUT and DELETE, and its DELETE
  genuinely removes the rule, which is why `unifi_firewall_rule` is built on it.
- **Correction to the API key claim.** The official alternative is reachable: the
  throwaway stack is a UniFi OS Server, which mints an integration key, and that
  key also authenticates on the legacy family, so the deployment this collection
  is measured against serves both families.
- `overview.md` no longer places a firewall rule in a per-site settings document.
  Classic rules are a per-object collection, not a settings key. The
  read-modify-write caution names only the surfaces that have no per-object
  endpoint, and says their concurrency handling is not designed.
- The two API families are described consistently as the application's own
  (legacy) and an additional surface for integrations (official). An unverified
  `X-Unifi-Control-Origin` header claim is not made.
- The no-live-controller rule in `contribution/README.md` is a short statement
  that points at invariant 1 in `AGENTS.md`, its single home.

## 2026-09-30

- Established the bundle: the root `index.md`, this log, `overview`, and
  `contribution` with the docsite configuration.
- The pages the collection owes its users are named rather than written as empty
  stubs that would drift from the code.
- The no-live-endpoint rule is recorded in `contribution` before any credential
  handling exists to get wrong. It is the first thing a contributor meets.
- The owner authorised a throwaway UniFi application, started by this repository
  from a digest-pinned installer on loopback. The prohibition on a controller the
  operator administers is unchanged.
- `.agents/rules/testing.md` records that a kernel change is verified against the
  application and not only against a green unit suite, because a mock encodes the
  expectations of whoever wrote it.
- `unifi_dhcp_reservation` and `unifi_port_forward` address the two blockers a
  prospective user named. `/rest/user` is the client registry, not a local user
  database, and a static reservation is a record there with `use_fixedip` set.
  `state: absent` releases the reservation rather than removing the record, because
  `DELETE rest/user/{id}` answers `api.err.NotFound` for a record that is present,
  and a client is the controller's knowledge that a device exists.
- `reconcile.resolve_id()` and `reconcile.reference()` let a task name the object
  it points at instead of pasting an identifier. Naming both or neither is refused
  rather than resolved by precedence.
- `unifi_firewall_zone` and `unifi_firewall_policy` are not shipped. The
  zone-based engine is unconfigured on the deployment the collection is measured
  against, so a module built on it cannot be verified, and shipping one would mean
  a `state: absent` that reports a removal which never happened.
- `api_mount: console` with `api_family: legacy` and an API key is a valid
  combination, which the code permits. It is not verified against UniFi OS
  hardware, because this project has no such deployment and inventing one is not
  available.
- The integration suite, `tests/integration/targets/stub_controller`, drives a
  module through a real `ansible-playbook`. It is the only level that enforces an
  argument spec: the unit suite replaces the transport, and the live suite
  replaces `AnsibleModule`.
- The throwaway stack is a UniFi OS Server in a disposable Lima VM, not a
  self-hosted Network Application in a container. An integration API key, and with
  it the official Integration API, exists only on UniFi OS. `sudo` is confined to a
  machine that disappears with `limactl delete`.
- The suite authenticates with an integration key rather than a login. A console
  rate-limits logins to about four in a window, and the collection logs in once per
  task, so a suite of any size refused itself. The key is stateless and also works
  on the legacy family.
- `rebased()` takes no mount. Restating it let a caller drop the console's proxy
  prefix, which answers 404 and reads like the collection not existing.
- The two API families are not an old path replaced by a modern one. The Network
  application's own user interface calls the legacy family for everything it does,
  including `rest/portforward` and `rest/networkconf`, and calls the official
  family not at all; that was measured by capturing its traffic rather than
  inferred. The official family is an additional, narrower surface for external
  integrations. A collection that manages port forwards or DHCP reservations
  therefore has to speak legacy, which is the vendor's own choice rather than a
  compromise.
- The split is a measurement of one version of one deployment and must be
  re-checked against each new Network application release, because UniFi moves.
  `docs/contribution/live-testing.md` says where the split is asserted and what the
  cheap re-check is, and maps how the live suite reaches CI: three tiers, the
  `/dev/kvm` constraint that keeps it off hosted runners, what to cache, and the
  container path as the fallback if a KVM runner is hard to get.
