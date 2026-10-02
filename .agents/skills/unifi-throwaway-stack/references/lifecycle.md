# Lifecycle

One VM, one console, one site. This repository starts it, and a lane never does.

## Targets

```
make uos/up       # create, install, create the account, mint the key, adopt the fleet
make uos/device   # start or restart the emulated fleet and adopt it
make uos/down     # stop, keep the data
make uos/purge    # stop and delete the data
make uos/status   # vm, uosserver, whether the console answers
make uos/logs     # follow the log
make live/test    # the live suite, against this console
```

`make uos/up` creates the VM if absent, installs UniFi OS Server if the service
is missing, waits for the console, creates the account, mints the key and adopts
the emulated fleet. It has no step that needs a person. `make uos/status` prints
the three things worth knowing: the VM, `uosserver`, and whether the console
answers.

## Reset

A reset is `purge` then `up`. Nothing is preserved, which is the point: a suite
that cannot start from nothing is not a suite, and a controller carrying the last
run's leftovers is how a test passes for the wrong reason.

`purge` deletes the VM, so the console account and any integration key go with it.
`up` recreates all of it: the VM, the install, the account, the key and the
emulated fleet. There is no step that needs a human, which is what makes the reset
get used.

A reset is also the remedy when the emulator container is gone or was built for a
different fleet: a device that has been adopted holds an authkey, and a recreated
emulator starts without one, so the controller answers its inform with HTTP 400
rather than re-adopting it. `make uos/device` reuses a running emulator that
matches the declared fleet and refuses to replace one that does not, naming
`make uos/purge` and `make uos/up` as the way to change it.

Cold start is slow. The image boots systemd and then a database, a message
broker, a web server and several Go services before the application answers.
Budget minutes, not seconds, and read the log rather than assuming a failure.

## Ports

| Host (loopback) | Guest | What |
|---|---|---|
| 11443 | 11443 | the console and the application web UI |
| 18080 | 8080 | HTTP inform and redirect |

Both forwards are declared in `tests/live/stack-uos/lima.yaml`, and each binds
`127.0.0.1` on the host. Host 8080 is deliberately not used: it is commonly taken
already, and only the guest side matters to discovery. Nothing is published off
loopback.

## Diagnosing, in order

Each layer fails in a way that reads like the layer below it, so work outward.

1. **Is the VM up?**
   `make uos/status`, or `limactl list`.

2. **Is the service up?**
   `limactl shell unifi-uos sudo systemctl status uosserver`
   Expect `active (enabled)`. `inactive` after a stop is normal; `failed` is not.

3. **What else is failing?**
   `limactl shell unifi-uos sudo systemctl --failed`
   Expect empty. mongodb, postgresql, rabbitmq and nginx come up before the
   application.

4. **Does the console answer?**
   `curl -sk -o /dev/null -w '%{http_code}' https://localhost:11443/`
   `200` whether or not setup is done. A console that answers but whose setup
   times out means the account service is not ready yet, and `setup.py` waits for
   it rather than the URL.

5. **Does the forward relay?**
   `curl -sk -o /dev/null -w '%{http_code}' https://localhost:11443/`
   A connection that opens and then answers nothing means Lima's port forward has
   stopped relaying, which is separate from the VM being down. Lima forwards over
   SSH, and the tunnel can die while the VM stays healthy: the guest answers 200
   to itself and the host gets a stalled socket.

   **The remedy is a restart.** `limactl stop -f unifi-uos` then `make uos/up`.
   A stop may hang while the tunnel is broken, which is why it is forced.

6. **Does the log say why?**
   `make uos/logs`, which follows `uosserver` inside the VM.

6. **Is the site there?**
   `make live/test` prints skips rather than failures when the stack is absent,
   because "could not run" and "ran and failed" are different states.

## What the stack must never do

- Publish a port that is not bound to loopback.
- Reach a controller the operator administers. The loopback check exists so a
  misdirected run stops before a credential is sent rather than after.
- Read the host's own UniFi configuration.
- Hold a credential for anything except itself.
