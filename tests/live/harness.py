# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a module in-process, shared by the live suites.

The live suites drive a module through a stand-in for ``AnsibleModule`` with a
synthesised argument payload, so the argument spec, the check mode handling and
the reporting are exercised without a playbook. One copy, because a change to how
a module is invoked has to land in one place rather than five.
"""

from __future__ import annotations

import json
from typing import Any

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

#: The result of the run, since the module constructs its own module object.
PUBLISHED: list[dict[str, Any]] = []


class ModuleUnderTest:
    """A stand-in for ``AnsibleModule`` that runs the module unmodified.

    The argument payload is validated against the module's own spec, which makes
    the spec part of what is under test rather than a formality checked elsewhere.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.argument_spec = kwargs.get("argument_spec", {})
        payload = _payload()
        # Check mode arrives as its own key beside the module's arguments, and
        # reading it from anywhere else would report a change the run never made.
        self.check_mode = bool(payload.get("_ansible_check_mode", False))
        # The constraints are not derivable from the spec, and a module states
        # them on the same call that carries the spec, so they are read from
        # there rather than restated by every test.
        self.params = _validated(
            self.argument_spec,
            payload,
            required_if=kwargs.get("required_if"),
            required_together=kwargs.get("required_together"),
            mutually_exclusive=kwargs.get("mutually_exclusive"),
        )

    def exit_json(self, **kwargs: Any) -> None:
        PUBLISHED.append(kwargs)
        # The framework leaves the process here. A stand-in that only recorded the
        # result would let the code after the call run and fall through.
        raise SystemExit(0)

    def fail_json(self, **kwargs: Any) -> None:
        PUBLISHED.append({**kwargs, "failed": True})

    def warn(self, warning: str) -> None:
        PUBLISHED[-1].setdefault("warnings", []).append(warning)


def call(module: Any, task: dict[str, Any]) -> dict[str, Any]:
    """Run one module once and return what it would report to a task.

    The module binds ``AnsibleModule`` into its own namespace at import, so the
    stand-in replaces that name there rather than the one in ``basic``, which the
    module never looks at. Patching the latter would leave the real class in place
    and the run would exit without the result being recorded.
    """
    PUBLISHED.clear()
    namespace: dict[str, Any] = vars(module)
    original = namespace["AnsibleModule"]
    namespace["AnsibleModule"] = ModuleUnderTest
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": task}))
    basic._ANSIBLE_PROFILE = "legacy"
    try:
        module.main()
    except SystemExit:
        # The framework exits on a failure, and the result is already recorded.
        pass
    finally:
        namespace["AnsibleModule"] = original
    assert PUBLISHED, "the module reported nothing"
    return PUBLISHED[-1]


def _payload() -> dict[str, Any]:
    """The argument payload the stand-in is constructed from."""
    raw = basic._ANSIBLE_ARGS
    assert raw is not None, "no module arguments were set"
    return dict(json.loads(raw)["ANSIBLE_MODULE_ARGS"])


def _validated(
    spec: dict[str, Any],
    args: dict[str, Any],
    *,
    required_if: list[Any] | None = None,
    required_together: list[Any] | None = None,
    mutually_exclusive: list[Any] | None = None,
) -> dict[str, Any]:
    """Validate a task's payload against the module's spec, raising on a mismatch.

    Two points differ from the framework's own validation. An argument the spec
    does not declare is refused here rather than reaching the module, so a live
    test that passes an undeclared or misspelled option fails here instead of
    silently dropping it. And an alias and its canonical option named together is
    refused here, where the framework warns and lets the alias win: this is
    stricter, and no test relies on the framework behaviour.

    The required, required_if and required_together terms are read from key
    presence, as the framework's own checks count it, so an explicit ``null``
    satisfies a term rather than counting as absent.
    """
    # The framework adds keys of its own beside the module's arguments, such as
    # the check mode flag, and the spec never declares those.
    supplied = {name: value for name, value in args.items() if not name.startswith("_ansible_")}
    _resolve_aliases(spec, supplied)
    unknown = set(supplied) - set(spec)
    if unknown:
        raise ValueError(f"unsupported parameters: {', '.join(sorted(unknown))}")
    _refuse_mutually_exclusive(mutually_exclusive, supplied)

    resolved: dict[str, Any] = {}
    for name, definition in spec.items():
        if name in supplied and supplied[name] is not None:
            value = supplied[name]
            if definition.get("type") == "int":
                value = int(value)
            elif definition.get("type") == "bool":
                value = str(value).lower() in ("true", "yes", "1")
            if "choices" in definition and value not in definition["choices"]:
                raise ValueError(f"{name} must be one of {definition['choices']}")
            resolved[name] = value
        elif "default" in definition:
            resolved[name] = definition["default"]

    # A non-None default is set before the framework checks the required terms,
    # so it counts as present even when the task did not state it.
    present = set(supplied)
    present.update(
        name for name, definition in spec.items() if definition.get("default") is not None
    )

    _refuse_missing_required(spec, present)
    _refuse_required_if(required_if, resolved, present)
    _refuse_required_together(required_together, present)
    return resolved


def _resolve_aliases(spec: dict[str, Any], supplied: dict[str, Any]) -> None:
    """Replace an alias in place with the option it names."""
    for name, definition in spec.items():
        for alias in definition.get("aliases", []):
            if alias not in supplied:
                continue
            if name in supplied:
                raise ValueError(f"{name} and its alias {alias} were both given")
            supplied[name] = supplied.pop(alias)


def _refuse_mutually_exclusive(pairs: list[Any] | None, supplied: dict[str, Any]) -> None:
    for pair in pairs or []:
        present = [name for name in pair if name in supplied]
        if len(present) > 1:
            raise ValueError(f"parameters are mutually exclusive: {', '.join(present)}")


def _refuse_missing_required(spec: dict[str, Any], present: set[str]) -> None:
    missing = [
        name
        for name, definition in spec.items()
        if definition.get("required") and name not in present
    ]
    if missing:
        raise ValueError(f"missing required arguments: {', '.join(sorted(missing))}")


def _refuse_required_if(
    requirements: list[Any] | None, resolved: dict[str, Any], present: set[str]
) -> None:
    for requirement in requirements or []:
        if len(requirement) == 4:
            name, value, needed, one_of = requirement
        else:
            name, value, needed = requirement
            one_of = False
        if resolved.get(name) != value:
            continue
        if one_of:
            if not any(field in present for field in needed):
                raise ValueError(f"{name} is {value} but one of {', '.join(needed)} is required")
            continue
        missing = [field for field in needed if field not in present]
        if missing:
            raise ValueError(f"{name} is {value} but {', '.join(missing)} is required")


def _refuse_required_together(groups: list[Any] | None, present: set[str]) -> None:
    for group in groups or []:
        stated = [name for name in group if name in present]
        if not stated or len(stated) == len(group):
            continue
        missing = [name for name in group if name not in present]
        raise ValueError(f"parameters are required together: {', '.join(group)}; missing {missing}")
