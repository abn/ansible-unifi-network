#!/usr/bin/env python3
"""Find newer upstream releases and move this repository's pins onto them.

Three things are pinned, and they drift on other people's schedules:

- the official Integration API description, vendored at
  ``tests/fixtures/unifi-integration-api.json``;
- the emulated device image, pinned by digest in ``tests/live/stack-uos/uos.sh``;
- the UniFi OS Server installer, pinned by version, URL and sha256 in
  ``tests/live/stack-uos/install.sh``.

Sources are ranked by how much they can be relied on. The first two answer with
JSON over a stable API. The third is a single-page application whose HTML carries
no download links, so it is attempted, reported when it fails, and never guessed
at: a wrong URL pinned as though it were right is worse than a stale one.

Reports what it found and, with ``--apply``, moves the pins. It never decides a
change is safe; the caller runs the gates before proposing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "tests" / "live" / "stack-uos" / "install.sh"
UOS = ROOT / "tests" / "live" / "stack-uos" / "uos.sh"
VENDORED_SPEC = ROOT / "tests" / "fixtures" / "unifi-integration-api.json"

SPEC_LISTING = "https://api.github.com/repos/beezly/unifi-apis/contents/unifi-network"
SPEC_RAW = "https://raw.githubusercontent.com/beezly/unifi-apis/main/unifi-network/{version}.json"
EMU_REPO = "jamesbraid/unifi-emu"
EMU_PACKAGE = "ghcr.io/jamesbraid/unifi-emu"
RELEASES = "https://ui.com/download/software/unifi-os-server"

TIMEOUT = 120

INSTALLER = re.compile(
    r"https://fw-download\.ubnt\.com/data/unifi-os-server/"
    r"[0-9a-f]+-linux-x64-(\d+\.\d+\.\d+)-[0-9a-f-]+\.[0-9a-z]+-x64"
)


def _get(url: str, *, headers: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "abn-unifi-network-pin-refresh", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(), dict(response.headers)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def spec_versions() -> list[str]:
    payload, _ = _get(SPEC_LISTING)
    return [
        entry["name"][: -len(".json")]
        for entry in json.loads(payload)
        if entry["name"].endswith(".json")
        and re.fullmatch(r"\d+\.\d+\.\d+", entry["name"][: -len(".json")])
    ]


def spec_current() -> str:
    return json.loads(VENDORED_SPEC.read_text())["info"]["version"]


def spec_apply(version: str) -> dict[str, list[str]]:
    before = json.loads(VENDORED_SPEC.read_text())
    payload, _ = _get(SPEC_RAW.format(version=version))
    after = json.loads(payload)
    VENDORED_SPEC.write_text(json.dumps(after, indent=2) + "\n")
    return {
        "paths_added": sorted(set(after["paths"]) - set(before["paths"])),
        "paths_removed": sorted(set(before["paths"]) - set(after["paths"])),
    }


def _ghcr_token() -> str:
    payload, _ = _get(
        "https://ghcr.io/token?scope=repository:" + EMU_REPO + ":pull&service=ghcr.io"
    )
    return json.loads(payload)["token"]


def _ghcr_tags(token: str) -> list[str]:
    payload, _ = _get(
        f"https://ghcr.io/v2/{EMU_REPO}/tags/list", headers={"Authorization": f"Bearer {token}"}
    )
    return json.loads(payload).get("tags", [])


def _ghcr_digest(token: str, tag: str) -> str:
    _, headers = _get(
        f"https://ghcr.io/v2/{EMU_REPO}/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json",
        },
    )
    for name, value in headers.items():
        if name.lower() == "docker-content-digest":
            return value.removeprefix("sha256:")
    raise SystemExit(f"GHCR answered without a content digest for {tag}")


def emu_current() -> tuple[str, str]:
    """The release tag and digest the stack pins."""
    match = re.search(r"unifi-emu:(\d+\.\d+\.\d+)@sha256:([0-9a-f]{64})", UOS.read_text())
    if not match:
        raise SystemExit("the emulator pin is not where this script expects it")
    return match.group(1), match.group(2)


def emu_latest() -> tuple[str, str]:
    """The newest released tag, resolved to the digest that tag currently names.

    A tag rather than ``latest``: the maintainer rebuilds ``latest`` freely, and
    a pin that moves with every rebuild produces a pull request nobody reads.
    """
    token = _ghcr_token()
    releases = [tag for tag in _ghcr_tags(token) if re.fullmatch(r"\d+\.\d+\.\d+", tag)]
    if not releases:
        raise SystemExit("the emulator image publishes no release tags")
    newest = max(releases, key=_version)
    return newest, _ghcr_digest(token, newest)


def emu_apply(version: str, digest: str) -> None:
    text = UOS.read_text()
    text, count = re.subn(
        r"unifi-emu:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}",
        f"unifi-emu:{version}@sha256:{digest}",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("the emulator pin is not where this script expects it")
    UOS.write_text(text)


def installer_current() -> str:
    return re.search(r'^VERSION="([^"]+)"', INSTALL.read_text(), re.M).group(1)


def installer_latest() -> str | None:
    """The newest Linux x64 installer, or ``None`` when the page cannot be read.

    The release page is a single-page application and its HTML carries no download
    links, so this returns nothing today. When the vendor renders it, or publishes
    a feed, this starts working without a change elsewhere.
    """
    try:
        payload, _ = _get(RELEASES)
    except urllib.error.URLError as error:
        print(f"the release page could not be read: {error}", file=sys.stderr)
        return None
    html = payload.decode("utf-8", "replace")
    versions = [m.group(1) for m in INSTALLER.finditer(html)]
    return max(versions, key=_version) if versions else None


def installer_apply(version: str, url: str) -> str:
    payload, _ = _get(url)
    digest = hashlib.sha256(payload).hexdigest()
    text = INSTALL.read_text()
    for pattern, value in (
        (r'^VERSION="[^"]+"', f'VERSION="{version}"'),
        (r'^URL="[^"]+"', f'URL="{url}"'),
        (
            r'^SHA256="\$\{UOS_INSTALLER_SHA256:-[0-9a-f]{64}\}"',
            f'SHA256="${{UOS_INSTALLER_SHA256:-{digest}}}"',
        ),
    ):
        text, count = re.subn(pattern, value, text, count=1, flags=re.M)
        if count != 1:
            raise SystemExit(f"could not rewrite {pattern!r}")
    INSTALL.write_text(text)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    summary: dict[str, object] = {"changed": False}

    have, want = spec_current(), max(spec_versions(), key=_version)
    if _version(want) > _version(have):
        summary["spec"] = {"from": have, "to": want}
        if args.apply:
            summary["spec"].update(spec_apply(want))
        summary["changed"] = True

    have, want = emu_current(), emu_latest()
    if want != have:
        summary["emulator"] = {"from": have[0], "to": want[0]}
        if args.apply:
            emu_apply(*want)
        summary["changed"] = True

    have, want = installer_current(), installer_latest()
    if want is None:
        summary["installer"] = {"from": have, "to": None, "detected": False}
    elif _version(want) > _version(have):
        summary["installer"] = {"from": have, "to": want, "detected": True}
        summary["changed"] = True
    else:
        summary["installer"] = {"from": have, "to": want, "detected": True}

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
