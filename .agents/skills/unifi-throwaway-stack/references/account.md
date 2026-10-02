# Setting the throwaway console account

A fresh console has a first-run wizard. It is two API calls, and
`tests/live/stack-uos/setup.py` makes them, so `make uos/up` creates the account
itself and `purge` then `up` is a true reset.

A reset that needs a human in a browser is a reset that gets skipped.

## The two calls

**1. Start a setup session.**

```
POST /api/setup/start
{"sendTrace": true, "type": "webui"}
-> 200 {"setupId": "<uuid>"}
```

On a console that has already been set up this answers **401**, which is how the
wizard prevents a second run. The script treats that as success, so `up` is safe
to re-run.

**2. Create the console account.**

```
POST /api/setup
{"name": "verify-uos",
 "timezone": "Etc/UTC",
 "optimizeNetwork": false,
 "sendDiagnostics": false,
 "newAccount": true,
 "advancedSetup": {"mode": "dhcp"},
 "username": "admin",
 "password": "...",
 "country": 840,
 "setupId": "<uuid from step 1>",
 "raid": "raid5"}
-> 200 and the created user object
```

`country` is the wizard's numeric picker value, not ISO 3166-1: 840 is the United
States, which is what the picker sends when it is left alone.

`optimizeNetwork` and `sendDiagnostics` are both false on purpose. The first makes
the console change things it was not asked to change, and the second sends data
off the machine.

The username is `admin`. `mint-key.py` logs in with it.

## The variables

Read from the environment, defaulted for a throwaway:

| Variable | Default |
|---|---|
| `UOS_URL` | `https://localhost:11443` |
| `UOS_DEVICE_NAME` | `verify-uos` |
| `UOS_USERNAME` | `admin` |
| `UOS_CONSOLE_PASSWORD` | defaulted by `uos.sh` when unset |
| `UOS_TIMEZONE` | `Etc/UTC` |
| `UOS_COUNTRY` | `840` |

The password is a throwaway for a loopback VM and nothing else, so `uos.sh`
supplies a default when it is unset. The integration key is what `uos.sh` writes
to `tests/live/stack-uos/.env`, which is not committed; see
`references/api-key.md`.

## Where the wizard's steps live, for when the API changes

The wizard is at `/setup/device-name`, then `/setup/credentials`, then
`/setup/setting-up`. The calls it makes, in order, are:

```
GET  /api/backup/setup/has-legacy-net
GET  /api/system/previous-subnet
GET  /api/auth/denylist
GET  /api/system
POST /api/setup/start
POST /api/setup
```

If a future release changes the body, capture it the same way: drive the wizard
with playwright-cli, then read `requests` and `request-body <n>`. That is how the
contract above was obtained rather than guessed.

## Driving the wizard by hand, if it comes to that

The browser refuses the console's self-signed certificate by default. `open
--config` is the switch, and the config shape is nested under `browser`; a
top-level `contextOptions` is silently ignored:

```json
{
  "browser": {
    "contextOptions": { "ignoreHTTPSErrors": true },
    "launchOptions": { "args": ["--ignore-certificate-errors"] }
  }
}
```

Then: name the server, **Proceed Without a UI Account**, **Continue Anyway**, and
a console password. The validator reports one rule at a time and wants between 12
and 128 characters with at least one capital and at least one number.
