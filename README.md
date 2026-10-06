# Ansible collection: abn.unifi_network

Manage UniFi Network devices declaratively through the UniFi controller API.

Thirteen modules cover the controller's resources. Ten manage one: networks,
wireless networks, adopted devices, static DHCP reservations, port forwards,
classic firewall rules, firewall zones, firewall policies, switch port profiles
and single-port overrides. Three read back what the controller holds: networks,
devices, and clients with their active stations. The
[overview](docs/overview.md) says what each one manages and
which resources are not designed yet.

## Requirements

- `ansible-core` 2.19 or later.
- Python 3.12 or later on the host that runs a module. A module can use only the
  standard library and `ansible.module_utils`.
- No collection dependencies and no Python package dependencies, because a module
  has nowhere to install one.

## Install

From a release:

```sh
ansible-galaxy collection install abn.unifi_network
```

From the repository, to track `main`:

```sh
ansible-galaxy collection install git+https://github.com/abn/ansible-unifi-network.git
```

Either way the collection lands in `ansible_collections/abn/unifi_network` under
the first entry of `collections_path`, which is `~/.ansible/collections` unless
that has been changed.

## Using it

Each module carries its own documentation and examples. `ansible-doc
abn.unifi_network.unifi_network` lists the options, and the
[overview](docs/overview.md) names the other modules.

## Authentication

Every module accepts the shared connection options. A task authenticates with an
integration API key or with an administrator's username and password, against a
UniFi OS console or a self-hosted Network Application. The module documentation
states which combinations each deployment serves.

A UniFi OS console with an integration key is the shape this collection is
measured against. Every module speaks the legacy family, and a console accepts
the key on it:

```yaml
- name: Manage a network on a console
  abn.unifi_network.unifi_network:
    controller: "{{ unifi_controller }}"
    api_mount: console
    api_family: legacy
    site: default
    api_key: "{{ unifi_api_key }}"
    name: IoT
    purpose: corporate
    vlan: 20
    subnet: 10.0.20.1/24
```

A self-hosted Network Application takes the same task with the appliance mount
and the administrator's `username` and `password` in place of `api_key`.

A console rate-limits logins to about four in a window, and each task logs in
once, so a play against a console that uses `username` and `password` throttles
itself; the refusal reads as a wrong password rather than a rate limit. An
integration key is preferred because it does not log in.

No credential belongs in this repository, and none is. See the rule in the
[contributing guide](docs/contribution/README.md).

## Developing

```sh
make init        # toolchain, hooks, and the staged collection path
make check       # fast and hermetic: the gate that must pass before done
make check/full  # adds ansible-test sanity, units and integration
```

`make check` never starts a container and never reaches a controller. See
[AGENTS.md](AGENTS.md) for the invariants and the working procedure, and
[docs/contribution/README.md](docs/contribution/README.md) for the checks, the
changelog fragment format, and how to add a module.

## Licence

GPL-3.0-or-later, with `plugins/module_utils/**` under BSD-2-Clause. See
[LICENSE](LICENSE.md).
