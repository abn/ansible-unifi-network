#!/usr/bin/env bash
# Lifecycle for the throwaway UniFi OS Server.
#
# Unofficial but standard install: UniFi OS Server is a host binary that installs
# a systemd service with sudo, which invariant 6 forbids on the operator's
# machine. So it is installed inside a disposable VM, where elevation lands
# somewhere that disappears with `limactl delete`.
#
# The VM is the environment the installer expects: a systemd host with podman and
# pasta. A container on the host can run the same image, but needs systemd inside
# it and a macvlan alias for `eth0`, because rootless pasta names the container
# interface after the host's and unifi-core crash-loops when it cannot read a MAC.
#
# Usage: uos.sh {up|device|down|purge|status|logs|shell}

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM="unifi-uos"
UI_PORT="${UOS_UI_PORT:-11443}"

# The host side of the inform forward the VM declares, and where the emulated
# device sends its inform. It must match the guestPort 8080 forward in lima.yaml.
INFORM_PORT="${UOS_INFORM_PORT:-18080}"

log() { printf '  %s\n' "$*" >&2; }

vm_status() {
    limactl list --format '{{.Status}}' "$VM" 2>/dev/null | head -1
}

running() {
    [ "$(vm_status)" = "Running" ]
}

exists() {
    limactl list --format '{{.Name}}' 2>/dev/null | grep -qx "$VM"
}

installed() {
    limactl shell "$VM" -- test -f /etc/systemd/system/uosserver.service 2>/dev/null
}

# The installer is interactive ("Proceed? (y/N)") and aborts when stdin is not a
# terminal, which is every scripted run. It also downloads 749MB, so this is the
# slow path and only runs once per VM.
install() {
    log "installing UniFi OS Server in the VM (downloads ~750MB)"
    limactl copy "$HERE/install.sh" "$VM:/tmp/install-uos.sh"
    limactl shell "$VM" -- sudo /tmp/install-uos.sh
}

reachable() {
    curl -sk -o /dev/null --max-time 5 "https://localhost:${UI_PORT}/" 2>/dev/null
}

wait_for_console() {
    log "waiting for the console"
    for _ in $(seq 1 60); do
        if reachable; then
            log "console is answering"
            return 0
        fi
        sleep 5
    done
    log "the console did not answer; check make uos/status and the VM log"
    return 1
}

# Software UniFi devices that speak the real inform protocol, so the controller
# adopts them the way it adopts hardware. Adoption runs outbound from the device,
# so the controller never has to reach it and no LAN address, bridge or SSH is
# involved: the emulator informs to the port this stack already forwards.
#
# The fleet is declared in devices.json: an AP so the device write path has
# something to write to, and a switch so a port-configuration write has a device
# that reports ports. The file is the only source of the identities; the AP's MAC
# is matched in tests/live/settings.py, so changing it breaks the live suite.
#
# Pinned by release tag and digest. The tag says which release this is and the
# digest says exactly which bytes, so a rebuilt tag is a visible change rather
# than a silent one.
EMU_IMAGE="ghcr.io/jamesbraid/unifi-emu:0.5.5@sha256:f57b072fa5af615ba4b572b8e61f0fb025103961d44c8004c9c53a3d3356f841"
EMU_NAME="unifi-emu"
EMU_SPEC="$HERE/devices.json"

# Prints the fleet's MACs, one per line, from devices.json.
emu_macs() {
    python3 -c 'import json,sys; print("\n".join(d["mac"] for d in json.load(open(sys.argv[1]))))' "$EMU_SPEC"
}

# A digest of the fleet file, recorded as a container label so a running
# emulator can be told apart from one built for a different fleet.
spec_digest() {
    cksum "$EMU_SPEC" | cut -d' ' -f1-2
}

emu_running() {
    [ "$(podman inspect --format '{{.State.Running}}' "$EMU_NAME" 2>/dev/null)" = "true" ]
}

# Whether the running container is the declared fleet. `podman container exists`
# is true for a stopped container, so a crashed emulator would otherwise be left
# down and every device would read as unadoptable.
emu_current() {
    emu_running \
        && [ "$(podman inspect --format '{{index .Config.Labels "unifi-emu.spec"}}' "$EMU_NAME")" = "$(spec_digest)" ]
}

start_emu() {
    podman rm -f "$EMU_NAME" >/dev/null 2>&1 || true
    # Host networking so the emulator reaches the inform port on loopback. It
    # only makes outbound requests, so nothing is published by this. The fleet is
    # passed by value rather than mounted: a rootless container with SELinux
    # enforcing cannot read a host file without relabelling it.
    podman run -d --network=host --name "$EMU_NAME" \
        --label "unifi-emu.spec=$(spec_digest)" \
        -e "SIM_DEVICES=$(cat "$EMU_SPEC")" \
        "$EMU_IMAGE" \
        -inform "http://localhost:${INFORM_PORT}/inform" >/dev/null
    log "started $EMU_NAME with the declared fleet"
}

# The emulator's own healthcheck turns healthy once every device is informing,
# which is the point at which an adoption request will be understood.
wait_for_emu_healthy() {
    for _ in $(seq 1 40); do
        [ "$(podman inspect --format '{{.State.Health.Status}}' "$EMU_NAME" 2>/dev/null)" = "healthy" ] \
            && return 0
        sleep 2
    done
    return 1
}

# Prints the MACs among the arguments the controller does not report connected,
# one per line. Empty output means every named device is adopted and up.
pending_macs() {
    key="$1"; shift
    curl -sk "https://localhost:${UI_PORT}/proxy/network/api/s/default/stat/device" \
        -H "X-API-KEY: $key" 2>/dev/null \
        | python3 -c '
import json, sys
states = {row.get("mac"): row.get("state") for row in json.load(sys.stdin).get("data", [])}
print("\n".join(mac for mac in sys.argv[1:] if states.get(mac) != 1))
' "$@"
}

cmd_device() {
    running || { log "the VM is not running"; return 1; }
    key="$(key_from_env)"
    [ -n "$key" ] || { log "no integration key; run uos/up first"; return 1; }

    site=""
    for _ in $(seq 1 40); do
        site=$(curl -sk "https://localhost:${UI_PORT}/proxy/network/integration/v1/sites" \
            -H "X-API-KEY: $key" 2>/dev/null \
            | python3 -c 'import json,sys;d=json.load(sys.stdin)["data"];print(d[0]["id"] if d else "")' 2>/dev/null)
        [ -n "$site" ] && break
        sleep 3
    done
    [ -n "$site" ] || { log "no site came back from the console"; return 1; }

    macs=()
    while IFS= read -r mac; do macs+=("$mac"); done < <(emu_macs)
    [ "${#macs[@]}" -gt 0 ] || { log "no devices declared in $EMU_SPEC"; return 1; }

    if emu_current; then
        log "$EMU_NAME already running the declared fleet"
    elif podman container exists "$EMU_NAME" 2>/dev/null; then
        # A stopped emulator, or one built for another fleet, cannot be replaced
        # in place: the controller holds each device by MAC, and a recreated
        # emulator has lost the authkey adoption assigned it, so the controller
        # answers its inform with HTTP 400 until the record is gone. That is a
        # reset, not a device step.
        log "the emulator exists but is not the running declared fleet; reset with"
        log "  make uos/purge && make uos/up"
        return 1
    else
        start_emu
    fi

    wait_for_emu_healthy \
        || { log "the emulator did not report its fleet informing"; return 1; }

    # Adopting is per device and a MAC already adopted makes this a no-op, so a
    # second run adopts nothing new rather than duplicating a device.
    log "adopting ${#macs[@]} emulated devices"
    for mac in "${macs[@]}"; do
        curl -sk -o /dev/null -X POST \
            "https://localhost:${UI_PORT}/proxy/network/integration/v1/sites/${site}/devices" \
            -H "X-API-KEY: $key" -H 'Content-Type: application/json' \
            -d "{\"macAddress\":\"$mac\",\"ignoreDeviceLimit\":false}"
    done

    # Adoption completes outbound, so this polls the listing rather than a job.
    for _ in $(seq 1 40); do
        if [ -z "$(pending_macs "$key" "${macs[@]}")" ]; then
            log "the fleet is adopted and connected"
            return 0
        fi
        sleep 3
    done
    log "the fleet did not reach the adopted state; read a device log with"
    log "  podman logs $EMU_NAME"
    log "if the controller still holds a device from an earlier emulator, reset with"
    log "  make uos/purge && make uos/up"
    return 1
}

key_from_env() {
    [ -f "$HERE/.env" ] && sed -n 's/^UOS_API_KEY=//p' "$HERE/.env" | head -1
}

cmd_up() {
    if ! exists; then
        log "creating the VM"
        limactl start --name="$VM" --tty=false "$HERE/lima.yaml"
    elif ! running; then
        log "starting the VM"
        limactl start "$VM"
    else
        log "the VM is already running"
    fi

    installed || install

    # The service is enabled, but a VM that was stopped mid-install can come back
    # with it inactive, and starting it is cheap and idempotent.
    limactl shell "$VM" -- sudo systemctl start uosserver.service >/dev/null 2>&1 || true

    wait_for_console

    # The console account is created here rather than by hand. A reset that needs
    # a human in a browser is a reset that gets skipped, and `purge` deletes the
    # account along with the VM.
    log "creating the console account"
    UOS_URL="https://localhost:${UI_PORT}" \
    UOS_CONSOLE_PASSWORD="${UOS_CONSOLE_PASSWORD:-throwaway-not-a-secret}" \
        python3 "$HERE/setup.py" || return 1

    # A console rate-limits logins to about four in a window, and the collection
    # logs in once per task, so the suite authenticates with a key instead. It is
    # minted here so `up` leaves the stack ready to run against rather than ready
    # to be prepared.
    log "minting an integration key"
    key=$(UOS_URL="https://localhost:${UI_PORT}" \
          UOS_CONSOLE_PASSWORD="${UOS_CONSOLE_PASSWORD:-throwaway-not-a-secret}" \
          python3 "$HERE/mint-key.py") || return 1
    printf 'UOS_API_KEY=%s\n' "$key" > "$HERE/.env"
    chmod 600 "$HERE/.env"

    # The device tests need devices that report ports, and there is no other way
    # to get them.
    cmd_device

    log ""
    log "console:  https://localhost:${UI_PORT}/"
    log "key:      written to $HERE/.env, which is not committed"
    log "next:     make live/test"
}

cmd_down() {
    if ! running; then
        log "the VM is not running"
        return 0
    fi
    # A failed stop is reported as a failed stop. Collapsing it into "not
    # running" hides the case that matters: a VM that is up but whose port
    # forwards have stopped relaying, which is when a stop is most likely to
    # hang and is exactly what a reader needs to be told.
    limactl stop "$VM" >/dev/null || { log "the VM did not stop"; return 1; }
    log "stopped the VM"
}

# Deleting the VM is the purge: the account, the key and every object a run
# created live in its disk image. There is no volume to keep and nothing on the
# host to clean up.
cmd_purge() {
    if ! exists; then
        log "no VM"
    else
        limactl delete -f "$VM" >/dev/null || { log "the VM could not be deleted"; return 1; }
        log "deleted the VM and everything in it"
    fi
    # The key dies with the VM, so leaving it behind would hand the suite a
    # credential for a machine that no longer exists, and the failure reads like a
    # bad key rather than a stale one.
    rm -f "$HERE/.env"
    podman rm -f "$EMU_NAME" >/dev/null 2>&1 || true
}

cmd_status() {
    if ! exists; then
        log "no VM"
        return 0
    fi
    printf '  vm:          %s\n' "$(vm_status)"
    if running; then
        printf '  uosserver:   %s (%s)\n' \
            "$(limactl shell "$VM" -- systemctl is-active uosserver.service 2>/dev/null | head -1 || echo unknown)" \
            "$(limactl shell "$VM" -- systemctl is-enabled uosserver.service 2>/dev/null | head -1 || echo unknown)"
        if reachable; then
            printf '  console:     https://localhost:%s/ answers\n' "$UI_PORT"
        else
            printf '  console:     not answering on https://localhost:%s/\n' "$UI_PORT"
        fi
    fi
}

cmd_logs() {
    limactl shell "$VM" -- sudo journalctl -fu uosserver.service
}

case "${1:-}" in
    up) cmd_up ;;
    device) cmd_device ;;
    down) cmd_down ;;
    purge) cmd_purge ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    shell) limactl shell "$VM" ;;
    *) log "usage: uos.sh {up|device|down|purge|status|logs|shell}"; exit 2 ;;
esac
