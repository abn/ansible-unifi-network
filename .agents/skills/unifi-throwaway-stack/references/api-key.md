# Generating the integration API key

Verified end to end against the VM in `references/vm.md`.

The console has no scriptable key endpoint on the legacy Network Server, and on
that platform the UI route does not exist either. UniFi OS Server has one, and it
takes the console username and password rather than a browser session, so a
script can do the whole thing.

## The script

The minter is a project asset at `tests/live/stack-uos/mint-key.py`, and
`uos.sh` runs it during `make uos/up`. The script is documented here because the
calls it makes are the part worth understanding.

```sh
UOS_URL=https://localhost:11443 \
UOS_USERNAME=admin \
UOS_CONSOLE_PASSWORD=... \
python3 tests/live/stack-uos/mint-key.py
```

It prints the key and nothing else, so it pipes cleanly:

```sh
KEY=$(UOS_CONSOLE_PASSWORD=... python3 tests/live/stack-uos/mint-key.py) || exit 1
```

## The three calls it makes

**1. Log in.** The console account is `admin`, whatever the server is named.

```
POST /api/auth/login
{"username": "admin", "password": "...", "token": "", "rememberMe": false}
-> 200, and a TOKEN cookie
```

The response also carries `X-Csrf-Token` on a header. The body is a user object
with `unique_id`, which the key path needs.

**2. Read the CSRF token.**

```
GET /api/users/self  ->  X-Csrf-Token: <uuid>
```

The token arrives on a response header and not in the body, and every write
needs it in an `X-CSRF-Token` request header. A write without it is
`403 {"error":{"code":403,"message":"Forbidden"}}`, which reads like a permission
problem and is not one.

**3. Create the key.**

```
POST /proxy/users/api/v2/user/{unique_id}/keys
X-CSRF-Token: <uuid>
{"name": "verify-stack"}
-> 200 {"code":1,"codeS":"SUCCESS","data":{"full_api_key":"...","id":"...","name":"..."}}
```

The path looks like one segment too many and is correct. The users service is
proxied at `/proxy/users/` and its own API prefix is `/api`, so the key route is
`/proxy/users/api/v2/user/{uid}/keys`. Dropping either one answers
`{"code":404,...,"error":"you entered no-man zone"}`, which is the users service
telling you it is the users service and the path is wrong.

List with `GET` on the same path. Delete at
`DELETE /proxy/users/api/v2/keys/{id}`, which is under `/proxy/users/api/v2/keys`
rather than under the user, and also needs the CSRF header.

## Using the key

The Integration API is behind the Network application's proxy, not at the console
root. `/integration/...` serves the portal UI and answers 200 with HTML, which is
easy to mistake for success.

```sh
curl -sk "$UOS_URL/proxy/network/integration/v1/sites" \
  -H "X-API-KEY: $KEY"
```

```
{"offset":0,"limit":25,"count":1,"totalCount":1,
 "data":[{"id":"88f7af54-...","internalReference":"default","name":"Default"}]}
```

`GET /proxy/network/integration/v1/info` answers
`{"applicationVersion":"10.6.101"}` and is the cheapest way to prove a key works.

Note the site id: the official API addresses sites by **UUID**, where the legacy
API uses the slug `default`. A module moving from one to the other changes the
identifier it is given.

## Rules

- The key belongs in `tests/live/stack-uos/.env`, which is not committed. It is a
  credential, it is shown once by the console, and it must not appear in a test,
  an example, a docstring, a comment or a changelog.
- A key minted for a run should be deleted after it, the same way a run removes
  the objects it creates. `DELETE /proxy/users/api/v2/keys/{id}`.
- The console password is the one set in `references/account.md`. It is a
  throwaway for a loopback VM and nothing else.

## What the official API covers

The official API carries resources the legacy engine does not:

```
POST   /proxy/network/integration/v1/sites/{siteId}/networks
POST   /proxy/network/integration/v1/sites/{siteId}/wifi/broadcasts
DELETE /proxy/network/integration/v1/sites/{siteId}/firewall/zones/{zoneId}
```

That last one is the operation the legacy v2 engine was measured refusing. The
spec for this exact version is `beezly/unifi-apis` `unifi-network/10.6.106.json`,
and an equivalent is already vendored at `tests/fixtures/unifi-integration-api.json`.
