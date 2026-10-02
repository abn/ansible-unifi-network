---
type: Guide
title: Live testing
description: The throwaway stack the live suite runs against, what must be re-checked on each new
  Network application version, and how it reaches CI.
status: draft
tags:
  - contributing
  - testing
  - workflow
---

# Live testing, and how it reaches CI

The suite under `tests/live/` is the only level that reaches a real application.
`AGENTS.md` invariant 1 says what it may reach and
`.agents/rules/testing.md` says how to write against it. This page says what the
stack is, what it costs, and how it gets into CI.

## The stack

`tests/live/stack-uos/` starts a UniFi OS Server in a disposable Lima VM, all on
loopback:

```
make uos/up       create the VM, install, create the account, mint a key, adopt the fleet
make uos/status   the VM, the service, whether the console answers
make uos/down     stop it, keeping its disk
make uos/purge    delete it and everything in it
make live/test    the suite
```

`uos/up` has no step that needs a person, which is what makes `purge` then `up` a
reset anyone will use. The console password and the integration key are both
generated locally and written to `tests/live/stack-uos/.env`, which is not
committed. **No secret has to exist in CI for the live suite to run.**

A software fleet (`ghcr.io/jamesbraid/unifi-emu`, pinned by digest) informs to
the forwarded inform port, and the official API adopts each device with the key.
The fleet is an access point and a switch, so both the device write path and a
port-configuration write have hardware to write to. Adoption runs outbound from
each device, so nothing needs a LAN address and no bridging is involved.

## The two API families are a measurement, not a law

The legacy family is the application's own API: the UniFi Network user interface
calls `rest/portforward`, `rest/networkconf`, `rest/wlanconf` and the v2 engine
for everything it does, and calls the official family not at all. The official
family is an additional surface for external integrations and covers a subset.

That split was measured against one version of one deployment. UniFi moves, and a
release can add an official endpoint, retire a legacy one, or change a field. So:

**Re-check this split against each new Network application version, and record
what changed.** The `api_family` description in
`plugins/doc_fragments/_connection.py` is what a user reads, and the vendored
specs under `tests/fixtures/` are asserted against the field tables by the field
unit tests.

The cheap re-check is to diff the vendored specs against a newer release and run
the unit suite: field tables are asserted against the fixtures, so a changed
field fails there before it reaches a controller. The expensive one is the live
suite, which is where a changed behaviour shows up.

## CI: what a runner has to provide

The stack is heavier than anything this repository ran in CI before, and three
constraints decide the design.

1. **`/dev/kvm` is absent on GitHub-hosted runners.** Lima needs it for
   acceptable speed. Without it QEMU falls back to software emulation and booting
   UniFi OS Server is impractical. A hosted runner can run the containers this
   repository uses for `ansible-test`, and it cannot run this stack.
2. **It is heavy.** The installer is about 750MB, the VM image about 600MB, and
   the application pulls more inside. A cold start is minutes; the suite is
   seconds.
3. **It is not hermetic.** It contacts the internet for images and the vendor
   download, which is why it must never be part of `make check`.

## The tiers

| Tier | Runner | Trigger | What it proves |
|---|---|---|---|
| 0 | hosted | every PR | `make check`, and `ansible-test` sanity, units and integration. Already in `.github/workflows/ansible-test.yml`. |
| 1 | hosted | every PR | The vendored specs and the field tables agree. No controller, no network. |
| 2 | with `/dev/kvm` | nightly, and manual | The live suite against the real application. |

Tier 1 is not yet written and is the cheapest thing to add: it is `make test`
plus a diff of the fixtures, and it catches a wrong field name without a
controller, which is most of what tier 2 finds.

Tier 2 needs a runner with `/dev/kvm`. GitHub does not offer one on hosted
runners, so it is either a self-hosted runner or a cloud VM with nested
virtualisation. It should not run on every PR: the download alone would dominate
CI minutes, and a failing live suite on an unrelated pull request trains people to
ignore it.

## Making tier 2 practical

- **Cache the VM image.** `~/.lima/_cache` is keyed by the image digest, so a
  cache keyed on the digest is stable until the image changes.
- **Cache the installer.** `install.sh` keeps it at `/tmp/uos-install/installer`
  and verifies its sha256, so a cache keyed on the pinned version and hash is
  safe.
- **One stack per runner.** The suite assumes one controller and one site, and
  the emulator binds fixed MACs.
- **Diagnose on failure.** `make uos/status`, `limactl shell unifi-uos sudo
  journalctl -u uosserver`, and `podman logs unifi-emu` between them explain
  almost every failure this stack has produced so far.
- **Always `make uos/purge` afterwards**, including on failure, so a runner does
  not accumulate VMs.

## What this costs, and the alternative

A cold tier 2 job is several minutes of download and install for a few seconds of
test. If that proves annoying, a container on the host can run the same image: it
runs on a hosted runner with `--privileged`, boots faster, and needs the `eth0`
alias workaround the VM does not. The working command is in the git history of
`tests/live/stack-uos/`. The trade is a workaround in exchange for a runner
requirement, and it is worth revisiting only if the KVM runner is hard to get.
