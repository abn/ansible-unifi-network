#!/usr/bin/env python
"""A loopback stand-in for a UniFi controller, for the integration suite.

The live suite drives the real application with a stand-in for ``AnsibleModule``,
so it never exercises the framework itself. Nothing anywhere drives a module
through a real ``ansible-playbook``, which leaves the argument spec, the ``no_log``
masking, check mode and the diff callback unproven against anything but a
hand-written caller.

This answers the rest collections the integration playbook drives and nothing
else. It is not a model of the controller: it holds what it is told, in memory, for
the lifetime of one suite, and the assertions live in the playbook rather than
here.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path

COOKIE = "unifises"
SITE = "/api/s/default"

#: Both paths the connection fragment offers. Which one a deployment uses is its
#: own business, and the stub answering both is cheaper than the suite choosing.
LOGIN_PATHS = ("/api/login", "/api/auth/login")

_state: dict[str, list[dict[str, object]]] = {"networkconf": [], "firewallrule": []}
_counter = [0]
_writes: list[dict[str, object]] = []
_lock = threading.Lock()

#: The collections the stub holds. A module writes one of these, and the stub
#: treats them alike: it stores what it is told and the assertions live in the
#: playbook.
COLLECTIONS = ("networkconf", "firewallrule")


def _target(path: str) -> tuple[str, str] | None:
    """The collection and identifier a site path addresses, or ``None``.

    ``None`` means the path is not a rest collection beneath the site. An empty
    identifier means the collection itself, which is what a listing and a create
    address.
    """
    prefix = f"{SITE}/rest/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :].split("/", 1)
    collection = rest[0]
    identifier = rest[1] if len(rest) > 1 else ""
    if collection not in COLLECTIONS:
        return None
    return collection, identifier


def _envelope(data: object) -> bytes:
    return json.dumps({"meta": {"rc": "ok"}, "data": data}).encode()


def _identifier() -> str:
    _counter[0] += 1
    return f"stub{_counter[0]:024d}"


class Handler(BaseHTTPRequestHandler):
    """Answers the rest collections the playbook drives, holding them in memory."""

    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, *, set_cookie: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", f"{COOKIE}=stub-session; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(body)

    def _authenticated(self) -> bool:
        return COOKIE in self.headers.get("Cookie", "")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")

        if self.path in LOGIN_PATHS:
            self._send(200, _envelope([]), set_cookie=True)
            return

        if not self._authenticated():
            self._send(
                401, json.dumps({"meta": {"rc": "error", "msg": "api.err.LoginRequired"}}).encode()
            )
            return

        target = _target(self.path)
        if target is not None and not target[1]:
            collection = target[0]
            with _lock:
                record = {**payload, "_id": _identifier(), "site_id": "default"}
                _state[collection].append(record)
                _writes.append({"method": "POST", "record": record})
            self._send(200, _envelope([record]))
            return

        self._send(404, json.dumps({"meta": {"rc": "error", "msg": "api.err.NotFound"}}).encode())

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")

        target = _target(self.path)
        if target is None or not target[1]:
            self._send(
                404, json.dumps({"meta": {"rc": "error", "msg": "api.err.NotFound"}}).encode()
            )
            return

        collection, identifier = target
        with _lock:
            for index, record in enumerate(_state[collection]):
                if record["_id"] == identifier:
                    updated = {**record, **payload, "_id": identifier}
                    _state[collection][index] = updated
                    _writes.append({"method": "PUT", "record": updated})
                    self._send(200, _envelope([updated]))
                    return
        self._send(404, json.dumps({"meta": {"rc": "error", "msg": "api.err.NotFound"}}).encode())

    def do_DELETE(self) -> None:
        target = _target(self.path)
        if target is None or not target[1]:
            self._send(
                404, json.dumps({"meta": {"rc": "error", "msg": "api.err.NotFound"}}).encode()
            )
            return

        collection, identifier = target
        with _lock:
            remaining = [r for r in _state[collection] if r["_id"] != identifier]
            removed = len(_state[collection]) - len(remaining)
            _state[collection] = remaining
            if removed:
                _writes.append({"method": "DELETE", "id": identifier})
        self._send(200, _envelope([{"_id": identifier}]))

    def do_GET(self) -> None:
        if self.path == "/__writes":
            with _lock:
                self._send(200, _envelope(_writes))
            return
        if not self._authenticated():
            self._send(
                401, json.dumps({"meta": {"rc": "error", "msg": "api.err.LoginRequired"}}).encode()
            )
            return
        target = _target(self.path)
        if target is not None and not target[1]:
            with _lock:
                self._send(200, _envelope(list(_state[target[0]])))
            return
        self._send(404, json.dumps({"meta": {"rc": "error", "msg": "api.err.NotFound"}}).encode())


def main() -> None:
    """Bind an unused port, publish it, and serve until killed.

    The port is chosen by the kernel and written to a file, so two suites on one
    host cannot collide and the playbook does not have to guess.

    The listener speaks TLS because the modules build an ``https://`` URL whatever
    the transport underneath says, and ``validate_certs: false`` is what lets a
    self-signed certificate through. A certificate is generated per run rather
    than committed: a private key in a repository is a private key in a
    repository, and this one would expire anyway.
    """
    workdir, port_file = sys.argv[1], sys.argv[2]
    certificate = Path(workdir) / "stub.pem"
    _self_signed(certificate)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    with open(port_file, "w", encoding="utf-8") as handle:
        handle.write(str(server.server_address[1]))
    server.serve_forever()


def _self_signed(path: Path) -> None:
    """Write a throwaway certificate and key for loopback."""
    if path.exists():
        return
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(path),
            "-out",
            str(path),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )


if __name__ == "__main__":
    main()
