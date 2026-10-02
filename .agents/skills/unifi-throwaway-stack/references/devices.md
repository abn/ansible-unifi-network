# Test devices

The stack holds two devices, software emulators that speak the inform protocol,
so the `unifi_device` write path has something to write to and a
port-configuration write has a device that reports ports.

## The fleet

`tests/live/stack-uos/devices.json` declares both devices, and
`tests/live/stack-uos/uos.sh` runs `ghcr.io/jamesbraid/unifi-emu`, pinned by
digest, on the host with host networking. Each announces itself to the forwarded
inform port the way hardware does, and the official API adopts it with the
integration key. Adoption runs outbound from the device, so the controller never
reaches it: no LAN address, bridge or SSH is involved.

| MAC | Model | Why |
|---|---|---|
| `00:27:22:e0:00:01` | `U7PRO` | The access point the `unifi_device` write path targets |
| `00:27:22:e0:00:02` | `USM8P` | The switch, which reports eight ports so `port_overrides` exists |

The MACs are fixed because the controller adopts a device by its MAC and a later
run has to find the same one. The file is the only source of the identities; the
AP's MAC is also matched in `tests/live/settings.py` as `EMULATED_MAC`, so
changing it breaks the live suite, and the switch's is
`EMULATED_SWITCH_MAC`.

`make uos/device` starts the emulator and waits until the controller reports
every device connected. `make uos/up` calls it, so a fresh stack holds the fleet,
and `make uos/purge` removes the container with the VM. A `make uos/device` when
the container is already running the declared fleet is a no-op rather than a
second adoption.

A device that has been adopted holds an authkey, and a recreated emulator starts
without one, so the controller answers its inform with HTTP 400 instead of
re-adopting it. `make uos/device` therefore reuses a running emulator that matches
the declared fleet and refuses to replace one that does not, naming the reset:
changing the fleet, or restarting an emulator whose container is gone, is
`make uos/purge` and `make uos/up`.

## The switch's ports

The emulator's `USM8P` profile reports eight ports, and the controller turns them
into a populated `port_table` on the device's `stat/device` row. Writes to
`port_overrides` happen at `PUT /rest/device/{id}`, with the device's whole
document as read from `stat/device`, the same write the collection's own module
uses. The controller normalises an entry and fills fields in, so a written
`{"port_idx": 2, "name": "verify-port-override"}` reads back as:

```json
[
  {
    "port_idx": 2,
    "name": "verify-port-override",
    "native_networkconf_id": "<the site's Default network id>",
    "forward": "all"
  }
]
```

`port_overrides` is absent on a device nobody has configured. Setting it to an
empty list clears the entries, and the key then remains as an empty array. A
device's entry is restored by writing the original value, not by omitting the
key: a `PUT` merges rather than removing an unnamed field.

## What the live suite proves

`tests/live/test_module_device_live.py` writes to the emulated AP and asserts
that a task's option names reach the controller under the controller's own field
names: `led` arrives as `led_override` and `outdoor_mode` as
`outdoor_mode_override`. A second run of the same task reports `changed: false`.

The rest of the file is the refusal side, which is what a controller that does
not hold the named device gets. The suite asks for a MAC no device carries and
asserts that the module fails rather than creating one, that the message names
the MAC and says the module cannot create or adopt, that nothing changed, that
check mode refuses identically, and that no credential reaches the result.

## What is not proven

- **Real hardware.** The module refuses to adopt, so a real device being adopted
  and then managed is not exercised.
- **Removal.** The module does not offer forgetting a device, and no suite
  exercises one.
- **Port configuration.** The switch exists so a suite can write
  `port_overrides`, but no module or live case does yet.
- **Every field.** The suite writes `name`, `led` and `outdoor_mode`. The other
  options, `disabled`, `led_colour`, `led_brightness` and `management_network_id`,
  are specified and documented but have no live case.
