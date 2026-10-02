---
type: Guide
title: Contributing
description: How to set up a development environment, run the checks, and submit a change.
status: draft
tags:
  - contributing
  - workflow
---

# Contributing

## Setup

```sh
git clone https://github.com/abn/ansible-unifi-network
cd ansible-unifi-network
make init
```

`make init` installs the Go-based `okf` validator, syncs the locked Python
tooling environment, installs the pre-commit hook, and stages the collection at
the `ansible_collections/abn/unifi_network` path that `ansible-test` requires.

`go` must be available; `GOTOOLCHAIN=auto` handles the version that `okf`
requires, which is newer than the host default.

## Checks

```sh
make check          # fast and hermetic: hooks, ansible-lint, okf, changelog, docs
make check/full     # adds ansible-test sanity, units and integration
make fmt            # apply formatting and safe fixes
```

`make check` never starts a container, which is why `check/full` exists as a
separate target.

## No real controllers by default

**By default nothing in this repository contacts a UniFi controller the operator
administers, and no agent uses a credential that reaches one.** The default target
is the throwaway console in `tests/live/stack-uos/`, which this repository starts
itself in a disposable virtual machine, from a digest-pinned installer, with only
the console and inform ports forwarded and both bound to loopback.

An operator may put a real controller in front of an agent for a specific
verification, when no virtual target can answer the question. That needs the
operator's explicit approval, in the session, for that one target; the full
conditions are invariant 1 in `AGENTS.md`, which is the canonical rule and is not
restated here.

If no approved target can verify a change, say so in the report and stop. Ask the
operator for approval to use a real controller rather than working around the gate.

## Verifying against the throwaway application

```
make uos/up      # create the VM, install, create the account, mint a key, adopt the fleet
make live/test   # run the live suite
make uos/status  # what is running, and whether the console answers
make uos/down    # stop it, keeping its disk
make uos/purge   # delete it and everything in it
```

The account and the integration key are created by `uos/up`, so a purge and an up
is a whole cycle with no human step. The key is written to
`tests/live/stack-uos/.env`, which is not committed. No secret has to exist in CI
for the live suite to run.

The two API families, what each covers, and how this reaches CI are in
[live-testing.md](live-testing.md). That page also says what must be re-checked
against each new Network application version.

This is the only gate that reaches the real application, and it is the one that
finds defects the others cannot: a wrong field name, a wrong base path, a
response shape assumed rather than read, a write aimed at a collection instead of
an object. Every one of those has been found here and by nothing else, because a
mock encodes the expectations of whoever wrote it and a code defect and a mock
defect look identical to each other.

It writes. The tests create, change and remove real objects, and a test that
creates one must remove it. See `.agents/rules/testing.md` for the isolation
discipline, which matters because the application serves one site that every test
shares.

## Making a change

1. State the scope in one sentence: unit of work, target, acceptance condition.
2. Work on a conventional branch in its own worktree, rebased on `main`.
3. Add a changelog fragment. Create `changelogs/fragments/` if it is missing, and
   add `<issue-or-pr-number>-<slug>.yml`. Nothing else may live in that
   directory: the `changelog` sanity test parses every file in it as YAML, so a
   README there fails the build.

   ```yaml
   ---
   minor_changes:
     - unifi_network - add the dhcp_dns option, a list that expands to the four
       resolver slots (https://github.com/abn/ansible-unifi-network/pull/1).
   ```

   Valid sections are `release_summary`, `major_changes`, `minor_changes`,
   `breaking_changes`, `deprecated_features`, `removed_features`,
   `security_fixes`, `bugfixes` and `known_issues`.

   **Do not write a fragment for a new module.** `antsibull` derives those from
   `version_added`, and the `changelog` sanity test fails if one is added.

4. Update `docs/` if behaviour changed, and record the change to the bundle in
   `docs/log.md`.
5. Run `make check/full`.
6. Get the change reviewed, then push.

Stage explicit paths. Never `git add -A`.

## Adding a module

The collection's own conventions are in `.agents/rules/ansible.md`. The short
version:

- Flat file under `plugins/modules/`, `AnsibleModule`, no third-party imports.
- Keep HTTP, retries, error mapping and canonicalisation in
  `plugins/module_utils/_unifi/`. A module contains none of it. That split is
  what makes the hard parts unit-testable without Ansible.
- `attributes:` for check mode and diff mode, never `notes:`.
- Proof of idempotency is a test that applies twice and asserts `changed == 0` on
  the second run. The per-object override surface makes that the interesting
  case, not the trivial one.

## Reporting a bug

Open an issue with the collection version, the `ansible-core` version, the
playbook task, and the module's failure message.
