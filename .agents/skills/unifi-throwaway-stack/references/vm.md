# Creating the host

UniFi OS Server is a host binary that installs a systemd service with `sudo`, and
Ubiquiti's FAQ says it is not available as a container. It has to live somewhere
with systemd, podman 4.9.3+ using pasta, and slirp4netns 1.2+. It goes in a
disposable VM, so the elevation lands somewhere that disappears with
`limactl delete` rather than on the operator's machine.

Known good: Lima 2.2.0, KVM present, Ubuntu 24.04 guest, installer 5.1.42,
`uosserver.service` active and enabled, console answering on loopback.

## The VM

`tests/live/stack-uos/lima.yaml`:

- Ubuntu 24.04, 4 CPU, 4GiB, 30GiB. Ubiquiti asks for 2GB and 10GB; the platform
  runs a database, a message broker, a web server and several services on top of
  the application.
- `podman` and `slirp4netns` provisioned, then `podman --version` asserted.
- **No host mounts.** A mount would put host paths inside an environment built to
  be thrown away.
- Only the console and the inform port are forwarded, both to `127.0.0.1`.

## The install

`tests/live/stack-uos/install.sh` runs **inside** the VM, never on the host:

1. Downloads the installer, pinned by version, URL and sha256.
2. Runs it. It asks `Proceed? (y/N)` and aborts when stdin is not a terminal,
   which is every scripted run, so the script answers that one prompt.
3. Installs and enables `uosserver.service`.

`make uos/up` does all of it and is idempotent: it creates the VM if absent,
starts it if stopped, installs only if `uosserver.service` is missing, waits for
the console, creates the account, mints the key and adopts the device.

## Ports

The installer serves the console on **11443 inside the guest**, not 443, which is
how it avoids needing a privileged port. Forwarding 443 there binds nothing and
answers nothing, and reads exactly like the VM being down. The template forwards
guest 11443 to host 11443 and guest 8080 to host 18080.

The console is bound to loopback only. It is not reachable from the network.

## Why not a container on the host

A container on the host can run the same image. It needs two workarounds the VM
does not:

1. `--systemd=always`, because the image runs systemd as PID 1 and exits 255
   without it.
2. A macvlan `eth0` alias, because rootless pasta names the container interface
   after the host's, `unifi-core` reads an empty MAC, and it crash-loops on
   `Error: Invalid MAC address:` while everything beneath it looks healthy.

If a VM is not possible, those two are what it takes, and `git log
tests/live/stack-uos` has the working command.

## Networking

Lima's QEMU networking on Linux is user-mode, so a device on the LAN cannot reach
the inform port, and bridged networking would need host privileges. The emulated
device needs neither: it runs on the host and informs outbound to the forwarded
port. See `references/devices.md`.

## Reference

Ubiquiti's requirements and install steps:
<https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi>

## The application version is context, not a gate

`tests/fixtures/unifi-integration-api.json` names a version, the console runs
whatever the installer shipped, and updates it from the Control Plane. The two
can disagree: the spec names 10.6.106 and the VM ships 10.6.101.

**That disagreement is not a failure and must not become one.** The official API
is versioned and grows: a capability added after the running version is simply
absent, and a module that meets its absence should say so and carry on rather
than refuse the whole run. Pinning the two together would mean a module that
works on an older console stops working the moment someone updates it, which is
the opposite of useful.

The rule, therefore:

- **Attempt the operation.** Do not consult a version table to decide whether a
  resource exists.
- **Read the answer.** A 404, `api.err.InvalidObject`, or a field the controller
  does not recognise is how absence actually arrives, and it names the thing that
  is missing.
- **Degrade, do not fail.** A capability the deployment lacks is a stated outcome,
  not an exception that aborts a play. Where a module cannot express that as
  `changed: false`, it fails with a message naming the version it met and the
  capability it wanted.

The version is still worth knowing, because a defect and a gap look the same in a
log and the version is what tells them apart:

```sh
curl -sk https://localhost:11443/proxy/network/integration/v1/info -H "X-API-KEY: $KEY"
# {"applicationVersion":"10.6.xxx"}
```

What is not acceptable is a hard version check standing in for a capability probe.
A check encodes an expectation of a release, and a fixture that describes one
controller while the tests run against another is how that expectation goes wrong.

## What this means for the modules

A module written against the official API should reach for the capability and
handle its absence, rather than gating on a version. The failure mode to avoid is
a first run against a console older than the one on the desk, which fails in a way
that reads like the collection being broken instead of the console being old.
