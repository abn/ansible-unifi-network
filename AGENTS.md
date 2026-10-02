# AGENTS.md

The committed entrypoint for humans and agents working on this repository. Short
by design: invariants, not essays.

## Project

`abn.unifi_network` is an Ansible collection that manages UniFi Network devices
declaratively through the UniFi controller API.

Modules exist under `plugins/modules/`. The resources they cover, the ones that
are not designed, and the shape of the controller API are in
[docs/overview.md](docs/overview.md). The internal research behind the design
belongs in `.agents/brain/docs/`, which is git-ignored and absent on a fresh
clone.

The repository root **is** the collection root, so what is committed here is what
ships to Galaxy (minus `build_ignore` in `galaxy.yml`).

## Invariants

These are not negotiable without an explicit decision recorded in
`docs/log.md`.

1. **No real controller unless the operator approves the specific use.** This is
   the hardest rule in the repository, and it has no acknowledgement variable:
   the only way past it is a human saying yes, in the session, for the target in
   front of it. By default nothing in this collection contacts a UniFi controller
   the operator administers, and no agent uses a credential that reaches one.

   The default authorised target is the throwaway console in
   `tests/live/stack-uos/`, which this repository starts itself in a virtual
   machine on loopback, from a digest-pinned installer. Authorisation for it says
   nothing about any other target.

   **The one exception: an operator-provided controller, when nothing virtual can
   stand in for it.** An agent may work against a real controller the operator
   administers only when every one of these holds. If any does not, it stops and
   says which.

   - The throwaway stack cannot satisfy the requirement. The agent states the
     specific capability that is missing, such as a device class the emulator
     cannot emulate against the controller, and does not reach for a real
     controller while a virtual one would answer the question.
   - The operator provides the controller and the credential and asks for the
     work. The credential is passed by environment only, is never committed, and
     is scoped to a test rather than reused from anything in production.
   - The agent asks the operator for explicit approval, in the session, before
     its first contact with that controller, and does not proceed without it.
     Approval is per session and per target: it does not carry into the next
     session, and approval of one controller does not cover another.
   - Before contact the agent states what it will read and what it will write,
     and confines itself to that. It does not explore the network behind the
     controller, and it does not treat one approval as a general licence.

   The rest of the rule is unchanged:
   - No hostname, IP address, port, API key, password or certificate belonging to
     a real controller is committed, including in a test, an example, a
     docstring, a comment or a changelog fragment. Write
     `https://<unifi-controller-host>` and `unifi_password: "{{ unifi_password }}"`.
   - The stack runs in a virtual machine that forwards only the console and the
     inform port, and forwards both to loopback. Nothing it runs publishes an
     address the network can reach, and the live suite addresses it as
     `localhost` and nothing else.
   - Nothing reads the host's own UniFi configuration, and no agent installs or
     invokes the `unifi` CLI. A developer machine may have a console bookmarked,
     a stored session, or a key in a shell profile, and "just checking the API
     shape" is exactly the shortcut that turns a read into a write.
   - No agent creates a credential on a real system without explicit approval: no
     API key, no local user, no trust credential. Where the operator can supply a
     credential scoped to the test, that is preferred over an agent minting one.
   - A change the approved targets cannot verify says so and stops. It does not
     work around the gate.

   Verification runs at three levels, and the first two never touch a network:

   1. `tests/unit/**` substitutes the transport. A mock encodes the expectations
      of whoever wrote it, so a passing unit suite proves the collection agrees
      with its own tests and nothing more.
   2. `tests/integration/targets/**` drives a loopback stub through a real
      `ansible-playbook`.
   3. `make live/test` reaches the throwaway application. This is the only level
      that can catch a wrong field name, a wrong base path, a response shape
      assumed rather than read, or a write aimed at the wrong object, and every
      one of those has been found by it and by nothing else. Run it after
      changing the kernel; a change verified only against a mock is unverified.

   Writes against the stack are expected and are removed afterwards. A test that
   creates an object must also remove it, and see
   [the testing rule](.agents/rules/testing.md) for the isolation discipline that
   a shared controller requires.
2. **Idempotency is the product.** A second run of the same playbook must report
   `changed: 0`. The per-object override surface makes this the interesting
   case rather than the trivial one, and a module that cannot achieve it is not
   ready.
3. **Fail closed on concurrency.** The controller's per-object overrides are a
   read-modify-write document, which is a lost-update surface. The concurrency
   behaviour is not designed yet; when it is, the sibling collection's policy
   file is the model, and it fails closed rather than proceeding.
4. **No third-party Python in `plugins/`.** Modules run on the target host with
   only the standard library and `ansible.module_utils`. Use
   `ansible.module_utils.urls`; never `requests`, `urllib.request` directly, or a
   generated client.
5. **Two linters, two jurisdictions.** `ansible-test sanity` owns module layout
   and correctness under `plugins/`; `ruff` and `ty` own `plugins/` and `tests/`,
   and `ruff` additionally owns import order everywhere, which `sanity` does not
   check. `ty` reads `plugins/` because nothing in `module_utils` is reachable
   from `tests` by import. Auto-fixes and formatting
   always apply, including to code that has already been reviewed. Do not add a
   hand-written hook for anything the existing tooling can already do.
6. **No sudo** unless a human explicitly asks for elevation.
7. **No reaching outside the worktree, for reads or writes.** An agent works in
   its own worktree and reads only what that change needs. Credential files, vault
   files, other repositories' secrets and other repositories' internals are out
   of scope for reads as well as writes. `ansible-tailscale-admin` is a sibling to
   read for conventions, never to write to.
8. **Zero AI slop.** No em dashes or en dashes anywhere, no marketing prose, no
   filler. Full rules in `.agents/rules/comments.md`.
9. **Every comment earns its place.** A comment either explains a non-obvious
   constraint or says something the code cannot. It never narrates how the code
   came to be, never addresses the reader, never uses the first person, and never
   restates the code or an obvious convention. Before writing one, ask: if the
   line below it were deleted, would this leave the reader worse off? If not,
   delete it. A comment describing the past rather than the present is wrong, not
   merely verbose.
10. **Docs move with the change.** Behaviour changes update `docs/` and
    `docs/log.md`. Do not document intended behaviour as if it were implemented:
    where a design is undecided, say it is undecided.
11. **Automation over manual conformance.** If a rule can be a hook or a check
    target, it is a hook or a check target.
12. **Public-ready by default.** Nothing committed may contain hostnames, IPs,
    absolute home paths, tokens, or internal task identifiers. `.agents/brain/` is
    the only place for internal working material, and it is git-ignored.

## Working procedure

- **State the scope in one sentence before starting:** unit of work, target,
  acceptance condition. Anything not needed for that outcome is out of scope.
- **Stage explicit paths.** Never `git add -A`. The pre-commit hook runs the full
  gate over the staged index, so a partial commit would fail it.
- **Conventional Commits, summary-only.** Titles are at most 52 characters, in
  the imperative mood, with no type suffix noise. Add a body only when the *why*
  is not evident from the diff.
- **No AI attribution trailers.** Do not add `Co-Authored-By` or similar.
- **Clean history.** Fixup or amend into the owning commit rather than stacking
  noisy fix commits.
- **One worktree per scoped change** on a conventional branch (`feat/`,
  `fix/`, `docs/`, `chore/`, `refactor/`), hyphenated, rebased on the latest
  `main` before work starts. *Bootstrap is the exception: the repository was
  initialised directly on `main`.*
- **Review gate before push.** A subagent reviews the change as a skeptical
  maintainer, then the human holds the approve-to-push decision.

## Verification

A change is done only when the check target passes with real captured output.

```
make check          # fast, hermetic, no containers.
make check/full     # adds ansible-test sanity, units and integration in containers.
make uos/up         # start the console, mint a key, adopt the fleet
make live/test      # against the throwaway console
```

`make check` runs `make lint` first, which is `ruff`, then `ty`, then
`ansible-lint`. It then lints the changelog fragments, then runs
`antsibull-docs lint-collection-docs`, which parses each module's `DOCUMENTATION`,
`EXAMPLES` and `RETURN` as YAML and which nothing else in the fast path does.
Finally it runs all pre-commit hooks over every file, which is where
`okf validate docs/` runs. It must never need Docker or Podman.

`make live/test` is not part of `check` and is not hermetic, because it needs a
running console. It is the only gate that reaches the real application, and it is
the one that finds defects the other two cannot. See invariant 1 for what it
authorises and `.agents/rules/testing.md` for how to write against it.

The pre-commit hook does not call `make check`. It runs the pre-commit hooks
alone, because it fires on files already staged and `make check` is the superset
that CI runs.

When a pre-commit hook rewrites a file, `make check` reports failure on the run
that fixed it and passes on the next. Read the failure before re-running, so an
automatic fix is not mistaken for a defect.

Claims like "the tests pass" without output are not verification. If a gate cannot
run in the current environment, say so rather than implying it passed.

## Division of labour

| Concern | Owner |
|---|---|
| Module layout and `module_utils` correctness | `ansible-test sanity` |
| Import order, everywhere | `ruff` |
| Repo tooling and test code style | `ruff`, `ty` |
| Collection manifest, FQCN usage, YAML | `ansible-lint` |
| Docs bundle structure and frontmatter | `okf validate docs/` |
| Commit message form and editorial invariants | `pre-commit` |
| No literal controller endpoints or home paths | `pre-commit` |
| Galaxy artifact contents and size | `make build`, which asserts both |
| The ansible-core x Python matrix | CI, via `ansible-test-gh-action` |

Locally, one ansible-test version is used. The matrix belongs in CI, not in a
hand-rolled local runner.

`ansible-galaxy build` does not read `.gitignore`, so a development path missing
from `build_ignore` in `galaxy.yml` ships silently. `make build` therefore
verifies the artifact rather than trusting the list: it fails on any known
development path and on anything over the 20 MB Galaxy limit. When a tool is added
that writes into the tree, extend that assertion in the same change.

## Scratch area

`.agents/brain/` is git-ignored and holds transient working material: `inbox/` for
incoming material, `outbox/` for the internal progress log, `tasks/` for
breakdowns and risk registers, `assets/` for reusable material.

`ansible-test` needs a second, separate scratch area, and it deliberately does
**not** live in `.agents/brain/`. `ansible-test` enumerates content through git,
so a tree nested anywhere inside this repository, git-ignored or not, reports
`All targets skipped` and silently checks nothing. `make collection/link`
therefore stages the collection at
`$TMPDIR/ansible-unifi-network/ansible_collections/abn/unifi_network`, and the
`sanity`, `test` and `integration` targets depend on it.

## Project rules

Extended, never replacing, the above:

- `.agents/rules/ansible.md`: module conventions, the private `module_utils`
  package, the GPL/BSD licensing split, sanity-test expectations, and the
  no-real-controller rule as it applies to code.
- `.agents/rules/comments.md`: what a comment may say, and what it must never say.
- `.agents/rules/python.md`: interpreter, uv workflow, ruff and `ty` scope.
- `.agents/rules/testing.md`: the three verification levels, and the isolation
  discipline a shared controller requires.
- `.agents/rules/documentation.md`: OKF bundle rules, and the rule that an
  undecided design is documented as undecided.

## Further reading

- [Overview](docs/overview.md)
- [Contributing](docs/contribution/README.md)
