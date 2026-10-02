# SPDX-License-Identifier: BSD-2-Clause
"""The connection options, as documentation.

Declared once here and repeated in every module's ``ARGUMENT_SPEC``, because
``validate-modules`` cross-checks a module's effective spec against its
documentation. A spec assembled from a shared constant would leave the
documentation describing options the checker never sees, which is a cross-check
that silently stops checking.

The prose states what a choice means rather than restating the type, and never
repeats a default, because the cross-check reads the ``default`` key and not the
sentence beside it.
"""

from __future__ import annotations


class ModuleDocFragment:
    #: The controller, how it is reached, and how to authenticate to it.
    DOCUMENTATION = r"""
options:
  controller:
    description:
      - The controller to manage.
      - A bare host or host and port is taken as an HTTPS address, because the
        application serves TLS and a scheme that was assumed wrong produces a
        refusal that names nothing useful.
    type: str
    required: true
  api_mount:
    description:
      - Where the application is mounted.
      - Choose C(appliance) for a self-hosted Network Application, which serves
        its API at the root of the given controller. Choose C(console) for a
        UniFi OS console, which proxies the application beneath the OS at
        C(/proxy/network).
      - One cue tells them apart. A UniFi OS console has an OS settings area and
        serves the application beneath C(/proxy/network), while a self-hosted
        Network Application has no OS settings area and serves it at the root.
      - This is not a preference. The two addresses different paths, and a path
        the deployment does not serve answers 404.
    type: str
    required: true
    choices: [appliance, console]
  api_family:
    description:
      - Which API to speak.
      - The legacy family is the application's own API. The UniFi Network user
        interface calls it for everything it does, port forwards, DHCP
        reservations, port profiles and per-port overrides among them, and no
        part of that interface calls the official family at all. It is not the
        older of two paths being replaced; it is the one the product runs on.
      - Every shipped module speaks the legacy family. None speaks the official
        family yet, so naming C(official) is refused with a clear message rather
        than reaching an endpoint no module addresses.
      - The official family is an additional surface for external integrations.
        It is versioned, it takes an API key, and it covers a subset. It cannot
        write a port forward, a DHCP reservation, a port profile, a per-port
        override, or any layer 3 switching.
      - Which family covers what is a measurement of one version of one
        deployment, and UniFi moves between versions. Re-check it against each
        new release rather than treating the split as fixed; see
        C(docs/contribution/live-testing.md).
      - A self-hosted appliance serves the legacy family only. An official key
        cannot be created on one, so a combination the deployment cannot serve is
        refused here rather than arriving as a permission failure on a network.
      - A UniFi OS console serves both. Its legacy paths are reached through the
        same console proxy prefix as the official ones, and a local integration
        key is accepted on them, so C(api_key) with C(api_family=legacy) is a
        valid combination there rather than a contradiction.
      - Choosing the official family is not required to use a key. The family
        picks the endpoints, and the credential is a separate choice.
    type: str
    required: true
    choices: [official, legacy]
  site:
    description:
      - The site's internal name, as the legacy family addresses it.
      - Required by the legacy family and unused by the official family, which
        addresses sites by a UUID.
    type: str
  login_path:
    description:
      - Where the deployment accepts a login, left unset to use the one the
        chosen O(api_mount) implies.
      - Set it only when a deployment has moved its login, since a wrong path
        draws a 404 that names nothing useful.
    type: str
    choices: ["/api/login", "/api/auth/login"]
  api_key:
    description:
      - An integration API key, sent in a header and with nothing to exchange.
      - A console accepts one on both families, so a key does not imply
        C(api_family=official).
      - Preferred over O(username) and O(password) because it does not log in. A
        console rate-limits logins to about four in a window and each task logs
        in once, so a play that logs in can throttle itself, and the refusal
        reads as a wrong password rather than a rate limit.
      - Mutually exclusive with O(username) and O(password).
    type: str
  username:
    description:
      - An administrator's name on the legacy family.
      - Logging in is rate-limited on a console to about four in a window, and a
        play logs in once per task, so a play against a console can throttle
        itself; the refusal reads as a wrong password rather than a rate limit.
        O(api_key) is preferred because it does not log in.
      - Requires O(password).
    type: str
  password:
    description:
      - That administrator's password.
      - Logging in is rate-limited on a console to about four in a window, and a
        play logs in once per task, so a play against a console can throttle
        itself; the refusal reads as a wrong password rather than a rate limit.
        O(api_key) is preferred because it does not log in.
      - Requires O(username).
    type: str
  ca_path:
    description:
      - Path to a certificate authority bundle, for a controller presenting a
        certificate this host does not already trust.
      - A self-signed certificate is the usual case, and a bundle naming its
        issuer is the preferred answer because it keeps verification on and
        checks the certificate the appliance actually presents.
    type: path
  validate_certs:
    description:
      - Whether to verify the controller's certificate.
      - Keep verification on by naming the appliance's issuing certificate in
        O(ca_path) when it presents a self-signed one.
      - Setting this to C(false) is a supported fallback for an appliance that
        ships a default self-signed certificate and cannot be given a bundle. It
        accepts an unverified certificate for the whole run.
    type: bool
    default: true
  timeout:
    description:
      - How long to wait for one request, in seconds.
    type: int
    default: 30
attributes:
  check_mode:
    description:
      - Whether the module can run without writing, and what it reports instead.
    support: full
    details:
      - Nothing is written, and the change that would be made is reported as a
        diff.
  diff_mode:
    description:
      - Whether the module reports what it changed, and in what shape.
    support: full
    details:
      - The module returns a top-level C(diff) return value with C(before) and
        C(after). Both are the whole document, as the controller held it before
        the run and as it holds it after, not a reduced set of the fields this
        run changed; the names of the changed fields are reported separately in
        C(changed_fields). The callback that renders a changed task reads
        C(diff.before) and C(diff.after).
"""
