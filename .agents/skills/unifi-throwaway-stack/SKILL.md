---
name: unifi-throwaway-stack
description: Stand up, drive and tear down the throwaway UniFi controller this collection is verified against, including the console account, the integration API key and test devices. Use when running make live/*, when the stack is broken or absent, when a live run needs an API key, or when a change to the stack itself is being made.
---

# The throwaway UniFi stack

This collection is verified against a controller the repository starts itself.
Nothing here reaches a controller an operator administers, and nothing outside
loopback is ever contacted. That rule is invariant 1 in `AGENTS.md` and this skill
does not relax it.

## Which platform

There are two things called a "UniFi controller" and only one of them can be
verified against.

| | Legacy UniFi Network Server | UniFi OS Server |
|---|---|---|
| Integration API key | never | yes, by script |
| Official API | unreachable | served |
| Legacy API | served | served |

The stack is a UniFi OS Server, and a key exists only there. On the Network Server
the `settings/control-plane` route answers **Page Not Found**, its settings
sections stop at Policy Engine and System, and the application itself offers to
upgrade. A suite that needs the official API needs this platform.

**The two families are not old and new.** The legacy family is the application's
own API: the Network user interface calls `rest/portforward`, `rest/networkconf`
and the v2 engine for everything it does, and calls the official family not at
all. The official family is an additional, narrower surface for external
integrations. A collection that manages port forwards or DHCP reservations has to
speak legacy, and that is not a compromise.

That split is a measurement of one version of one deployment. Re-check it against
each new Network application version; `docs/contribution/live-testing.md` says
where it is asserted.

Legacy-only resources still exist and are still served: port forwards and DHCP
reservations have no official API path at all, so they are verified against the
same stack through the legacy family.

## What is not obvious

UniFi OS Server is a host binary that installs a systemd service with `sudo`, and
the vendor FAQ says it is not available as a container. It goes in a virtual
machine, and three things about doing that are not obvious:

1. **The install is interactive.** It asks `Proceed? (y/N)` and aborts when stdin
   is not a terminal, so every scripted run stops there unless the prompt is
   answered.
2. **It serves the console on 11443 inside the machine, not 443.** A port forward
   aimed at 443 binds nothing and answers nothing, which reads exactly like the VM
   being down.
3. **The console answers on `/` minutes before the service that creates an account
   is ready.** A reset that tries once and gives up works on the second run, which
   is the worst kind of works.

Details are in `references/vm.md`.

## Workflow

The lifecycle is wired: `make uos/*` runs `tests/live/stack-uos/uos.sh`, which
creates or starts the VM, installs UniFi OS Server if it is missing, waits for the
console, creates the console account, mints the integration key the suite
authenticates with, and starts the emulated fleet the controller adopts.

```
make uos/up           # start the console and leave it ready to test against
make uos/status       # vm, uosserver, whether the console answers
make uos/device       # start or restart the emulated fleet and adopt it
make uos/down         # stop, keep the data
make uos/purge        # stop and delete the data
make live/test        # the live suite, against this console
```

Each step is a reference below.

| Step | Reference | Verified |
|---|---|---|
| Create and install the host, a VM | `references/vm.md` | yes |
| Set the throwaway console account | `references/account.md` | yes, scripted via the setup API |
| Generate the integration API key | `references/api-key.md` | yes, `tests/live/stack-uos/mint-key.py` works |
| Lifecycle: up, down, purge, reset, diagnose | `references/lifecycle.md` | yes |
| Test devices on the stack | `references/devices.md` | yes, `make uos/device` adopts the fleet |

## Rules this stack exists to keep

- **Loopback only.** Every published port binds `127.0.0.1`. The database
  publishes nothing. An address that is not loopback is refused before a
  credential is sent.
- **A credential for this stack is not a credential.** The console password and
  the integration key belong in `tests/live/stack-uos/.env`, which is not committed.
  No hostname, address, password, key or certificate belonging to anything else
  may be written into a test, an example, a docstring, a comment or a changelog.
- **The stack is the coordinator's.** Lanes do not create, reset or purge it, and
  do not run podman or docker. One controller, one site.
- **A test that creates an object removes it.** Where the controller will not
  allow removal, the reference says so and the test asserts the state it can.

## When it is broken

Start at `references/lifecycle.md`, which has the diagnostic order: VM state, then
systemd inside it, then whether the console answers, then the application log.
Each layer fails in a way that reads like the layer below it.
