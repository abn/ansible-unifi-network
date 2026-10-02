#!/usr/bin/env bash
# Install UniFi OS Server inside the throwaway VM.
#
# Runs inside the VM, not on the host. The supported Linux install is a host
# binary that installs a systemd service with sudo, which invariant 6 forbids on
# the operator's machine; the VM exists so that elevation lands somewhere
# disposable. Never run this on the host.
#
# Usage, from the host:
#   limactl shell unifi-uos sudo /tmp/install-uos.sh
#
# Or let `uos.sh` copy and run it.

set -euo pipefail

# The release the pin names, and the only URL that is allowed to differ. Ubiquiti
# does not publish a stable "latest" link; the id in the path changes per release,
# so a bump is a deliberate edit here.
VERSION="5.1.42"
URL="https://fw-download.ubnt.com/data/unifi-os-server/5172-linux-x64-5.1.42-12e9e3cf-8f8b-4e54-928c-76b80a10c8a4.42-x64"

# Filled in after the first successful download, so a changed artifact fails
# loudly instead of installing quietly.
SHA256="${UOS_INSTALLER_SHA256:-f6111e9396a42c74016f5dde9b01fbef486a6fe69efe137935e6e38b7c22f94d}"

WORKDIR="/tmp/uos-install"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

if [ ! -f installer ]; then
    echo "downloading UniFi OS Server $VERSION"
    curl -fL --retry 3 -o installer "$URL"
    chmod +x installer
fi

actual="$(sha256sum installer | cut -d' ' -f1)"

if [ -z "$SHA256" ]; then
    # First run: report the hash so it can be pinned, rather than trusting a URL
    # that carries no checksum of its own.
    echo "installer sha256: $actual"
    echo "pin it by setting UOS_INSTALLER_SHA256, or editing SHA256 above"
elif [ "$actual" != "$SHA256" ]; then
    echo "installer checksum mismatch: expected $SHA256, got $actual" >&2
    exit 1
fi

# The installer is self-contained: it unpacks the OCI image Ubiquiti ships inside
# it and hands it to the machine's own podman, then installs uosserver.service.
#
# It asks "Proceed? (y/N)" and aborts when stdin is not a terminal, which is
# every scripted run. Answering the one prompt is not consent being bypassed: the
# consent is the operator choosing to run this inside a throwaway VM.
echo "installing"
printf 'y\n' | ./installer

echo "installed; the service is uosserver.service"
systemctl is-enabled uosserver.service 2>/dev/null || true
