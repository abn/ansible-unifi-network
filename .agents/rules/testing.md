# Testing rules

Extends `AGENTS.md`. Applies to `tests/` at every level.

The unit suite is fast and hermetic and it is not sufficient. A mock encodes the
expectations of whoever wrote it, so a passing unit suite proves the collection
agrees with its own tests and nothing more. A change to the kernel is verified
against the throwaway application, and a change verified only against a mock is
unverified however green the unit suite is.

## Levels

| Suite | Reaches | Proves |
|---|---|---|
| `tests/unit/**` | nothing; the transport is substituted | logic, canonical comparison, error mapping |
| `tests/integration/targets/**` | a loopback stub | that a real `ansible-playbook` and a real callback agree, which is the only level that enforces an argument spec |
| `tests/live/**` | the throwaway application | that the controller agrees |

A unit test asserting behaviour belongs at the unit level, not duplicated live.
The live suite earns its cost by asserting what only the controller can answer,
and each of its cases is a question that had no other source.

## Against shared state

The live suite runs against one controller with one site. That makes isolation a
test's own responsibility, and getting it wrong produces a failure that points at
the code rather than at the leftover.

**Every test takes a distinct identifier that nothing else in the suite uses.** A
VLAN number, a port index, a name. Sharing one is how a test passes alone and
fails in a run, which reads as a defect in what is being tested.

**Clean up before and after, not only after.** A run that fails part-way leaves
objects holding their identifiers, and the next run then fails on a collision
that has nothing to do with the change under test. Cleanup before the test makes
the suite repeatable after any failure, including one that killed the process.

**Name what a test owns.** Objects a test creates carry a recognisable prefix, and
removal matches on that prefix. Cleanup that matches on a hard-coded identifier
misses an object created by a run that failed before it recorded one.

**Assert on the state the test depends on.** After a failure, read the
controller's actual state before changing the code. A `VlanUsed` or
`InvalidPayload` refusal names the symptom, and both of those in this suite have
been a leftover from an earlier run rather than a fault in the change.

## Writing the case

Name the test for the behaviour and the condition, not the function:
`test_a_second_run_reports_no_change`, not `test_apply_2`.

A test that has to be read twice to know which phase it is in is too long. Arrange,
act, assert, with a blank line between.

Prefer a case that fails for one reason. Three assertions in one test report one
of them and hide the other two.

When a live test fails, the question is whether the code or the expectation is
wrong, and the answer is not always the code. A mock expectation carried into a
live test is a finding about the mock.

## What must never happen here

No test reaches a real controller by default. A test that would, does not run; it
is refused before the request is made, and the refusal is the assertion. A
committed test stays hermetic. An operator-approved real controller is for a
verification run an agent asks for, not for the suite. See invariant 1.
