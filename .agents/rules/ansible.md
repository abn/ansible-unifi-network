# Ansible rules

Extends `AGENTS.md`. Applies to `plugins/`, `galaxy.yml`, `meta/` and the
ansible-test suites.

## Module authoring

- `AnsibleModule` from `ansible.module_utils.basic` is the only supported base for
  modules, and its signature is unchanged. There is no newer module class and no
  `@plugin` decorator; `AnsiblePlugin` and its Jinja2 subclasses are for
  non-module plugins only. Do not mix the two hierarchies.
- File layout inside a module, in this exact order: shebang, copyright plus the
  short GPL line, `DOCUMENTATION`, `EXAMPLES`, `RETURN`, then imports. The
  `import-placement` check requires imports directly below `RETURN`.
- Shebang is exactly `#!/usr/bin/python`, with no arguments, and the file must not
  be executable.
- The short licence line is required and must carry no year:
  `# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)`
- `short_description` must not end in a period. It is listed by `ansible-doc -l`
  with no surrounding context, so it has to stand alone.
- Check mode and diff support are declared in `attributes:`, never in `notes:`.
  `validate-modules` cross-checks `attributes.check_mode.support` against
  `supports_check_mode`, and requires `details:` for `partial`.
- Never pass `warnings=` or `deprecations=` to `exit_json` or `fail_json`. Both
  are deprecated for removal in 2.23; use `module.warn` and `module.deprecate`.
- Option removal uses `removed_in_version` (semver, must be `x.0.0`) together with
  the mandatory `removed_from_collection`, or `removed_at_date` in the future.
  `removed_in` is the `DOCUMENTATION` spelling; the argument spec uses
  `removed_in_version`.
- Deprecating a return value uses `deprecate_value` from
  `ansible.module_utils.datatag`, not a module-level warning.
- `state` must not offer `get`, `list`, `query` or `info`. Read-only behaviour
  belongs in a separate `<thing>_info` or `<thing>_facts` module.
- Module files are flat under `plugins/modules/`. Nesting breaks short FQCNs and
  fails `ansible-lint`.
- New options and new plugins declare `version_added` as `x.y.0`; it is the
  **collection** version, never an ansible-core version.

## The controller API: state the deployment, do not probe for it

A UniFi controller is reached two different ways depending on what is installed:
a UniFi OS console application is proxied under the console and authenticates
with a session cookie, while a classic self-hosted controller serves the API
directly. A module therefore takes the base URL and any deployment-specific
headers as options, and never sniffs for which one it is talking to. A probe is a
network call made before the credential has been checked, and a module that
guesses produces a login failure that says nothing about why.

The per-object override surface is a read-modify-write document, which is a
lost-update surface. Whatever the concurrency rule turns out to be, it has to be
decided before a module writes to it, and a design that guesses here will lose a
concurrent console edit silently.

## Secrets

- Any option whose name matches `pass|secret|token|key` and that is not obviously
  benign must set `no_log=True`. Options that merely *look* secret, such as
  `key_name` or `key_type`, must set `no_log=False` explicitly, or `no-log-needed`
  fails.
- `no_log` values are scrubbed from the result automatically. If a secret can end
  up in a **dict key**, call `sanitize_keys` as well.
- Never echo credentials in a failure message. In particular never include the
  request headers. Raise a module-local exception carrying an already-sanitised
  message and let `main()` convert it to `fail_json`.
- Return values differ by module kind. A resource module reports the controller's
  own re-read row, minus the secret fields named in `canon.SECRET_FIELDS` and
  removed by `reconcile.redact` at any depth. A `<thing>_info` module reports a
  whitelist projection instead, because it reads a collection rather than
  re-reading one object. A returned secret must be opt-in: `no_log` masks only the
  value a task supplied, so a stored secret the controller re-reads is removed by
  name rather than by projection.
- A controller session cookie is a secret. It lives in the client's memory for
  the run and goes in no return value, no diff, and no exception message.

## Private module_utils

`plugins/module_utils/_unifi/` is internal to this collection. The leading
underscore is the declaration: the kernel may be refactored in any release
without a major version bump. Every file under that path carries a comment saying
so. Promoting one of these files to public is a breaking change and requires a
rename plus a major release.

## Target-side constraints

Modules execute on the target host under AnsiballZ:

- Standard library and `ansible.module_utils` only. No third-party imports. If a
  dependency is unavoidable, guard it with `try`/`except ImportError` and report
  it through `missing_required_lib`.
- HTTP goes through `ansible.module_utils.urls`. The `replace-urlopen` and
  `use-module-utils-urls` sanity tests enforce this.
- `print`, `sys.exit`, `subprocess` and `os.system` are banned in modules. Use
  `module.log`, `module.exit_json` and `module.run_command`.
- Modules target **Python 3.12 and later**. The floor is declared, not derived from
  an ansible-core floor, so builtin generics and PEP 604 unions are usable at
  runtime and not only inside annotations. The interpreter in `.python-version`
  governs tooling and happens to agree, which is not the reason it does.
- The 2.19 porting guide made `exit_json` reject non-string dict keys outright.
  Coerce keys explicitly.

## No live controller, no real credential

No module, test or fixture may contact a real UniFi controller by default. This is
not a gate with an acknowledgement variable. Invariant 1 in `AGENTS.md` is the
canonical rule: the only way past it is the operator's explicit approval, in the
session, for one named target, and only when no virtual target can answer the
question.

A credential present in the environment is deliberately **not** authorisation. A
key left in a shell profile, or a session cached by a browser against the local
console, must never be enough for an agent to write to a network.

Tests that need HTTP use a loopback stub, as the sibling collection does. It binds
an ephemeral port on `127.0.0.1` and reaches nothing else.

Two rules are absolute rather than conditional. No agent installs or invokes the
`unifi` CLI, and no agent touches a browser session, a local credential store, or
a controller's own on-disk configuration. A developer machine that has a console
open needs no credential at all for a "quick check", which is precisely why the
quick check is the dangerous one.

A controller's local user database is not a test credential. Those users exist
only on the controller, and the collection does not manage them anyway, so no test
creates one.

An agent does not create a credential of any kind without explicit approval.
Where the operator can supply one scoped to a test, that is preferred: there is
then nothing for the agent to authorise and nothing extra for a human to clean up.

If a change cannot be verified by any approved target, say so in the report and
stop. Ask the operator for approval to use a real controller rather than working
around the gate.

## Licensing split

Per REUSE, declared in `LICENSE.md` and resolved through `LICENSES/`:

- `plugins/modules/**` and everything else: `GPL-3.0-or-later`.
- `plugins/module_utils/**`: `BSD-2-Clause`, so that module authors under
  GPL-incompatible licences can still reuse them. This mirrors ansible-core, which
  relicenses its own `module_utils` for the same reason.

## Sanity tests

`make check/full` runs them; CI runs them across every supported ansible-core
branch. The ones that actually bite:

- `validate-modules`: documentation versus argument-spec agreement,
  `no-log-needed`, `attributes-check-mode`, `import-placement`, GPL header.
- `pylint` with the collection config: banned imports and functions, deprecation
  correctness.
- `import`: only the standard library is visible to a module.
- `changelog`: needs at least one user-affecting fragment. Do **not** write a
  fragment for a new module; antsibull derives those from `version_added`. The
  test parses **every** file in `changelogs/fragments/` as YAML, so nothing else
  may live there, not even a README.
- `yamllint`, driven by `.yamllint`.
- `empty-init` requires `__init__.py` in every plugin subdirectory, and requires
  each one to be **completely empty**, zero bytes. This directly conflicts with
  the REUSE convention of an SPDX header in every file, and ansible-test wins:
  the `__init__.py` files carry no header. The licensing of those files is stated
  in `LICENSE.md` instead.
- `ansible-doc`, which parses module documentation on every supported Python.

### Ignore files

`tests/sanity/ignore-<core>.txt` is treated as a smell. Each line is a known
defect with a comment justifying it. Ignoring an error that does not occur is
itself an error, so a stale entry fails the run, which is the intended pressure to
delete it. Never ignore `doc-choices-do-not-match-spec`, `doc-missing-type`,
`no-log-needed`, or the other errors on the must-not-ignore list.

Keep it empty.
