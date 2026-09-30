#!/usr/bin/env bash
# The simulated HEX beamline + its queueserver, from nothing, on this machine.
#
#   sim/sim.sh up       # fetch, build, start everything (first run: ~30-60 min of builds)
#   sim/sim.sh down     # stop everything this script started
#   sim/sim.sh status
#
# `up` does, in order (every step is skipped when already done):
#   1. checks the prerequisites (Linux x86-64, Docker with compose v2, pixi, git, curl, openssl)
#   2. fetches the HEX profile collection at a pinned commit into .sim/hex-profile-collection
#      and installs its pixi `terminal` and `qs` environments (exactly as locked)
#   3. builds the sim's local Docker images (sim/hex/images/build.sh)
#   4. starts the simulated beamline (sim/hex/scripts/up_all.sh): services, PandA, Kinetix,
#      Phantom, motor IOC, encoder bridge, shutters/metadata IOC
#   5. starts the queueserver the way the beamline VM runs it (sim/queueserver), booting the
#      HEX profile against the sim
# Then run planrunner against it with:  pixi run sim-planrunner
#
# Everything binds to 127.0.0.1. Sim data goes to /tmp/hex-sim-data, capped at
# HEX_SIM_DATA_CAP_GB (default 20): past it, a watchdog turns detector file writing off.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
state="$repo/.sim"

# The profile the RE worker boots: HEX's profile collection with the HEX_SIM switch
# (NSLS2/hex-profile-collection + commit "HXM-1288: enable local simulated-beamline boot").
PROFILE_URL="${HEX_PROFILE_URL:-https://github.com/sligara7/hex-profile-collection.git}"
PROFILE_COMMIT="${HEX_PROFILE_COMMIT:-d8dfe732b3a1c1f1971e20babaa9fc2e90e06fde}"
PROFILE_DIR="$state/hex-profile-collection"

# Never let `pixi run` re-solve the pinned profile's lock file.
export PIXI_FROZEN=true

say() { echo "[sim] $*"; }
die() { echo "[sim] ERROR: $*" >&2; exit 1; }

preflight() {
    [ "$(uname -s)" = Linux ] || die "Linux is required (the sim uses Docker host networking)."
    [ "$(uname -m)" = x86_64 ] || die "x86-64 is required (the IOC images are built for it)."
    for tool in docker git curl openssl pixi ss pgrep; do
        command -v "$tool" >/dev/null || die "'$tool' is not installed."
    done
    docker compose version >/dev/null 2>&1 || die "Docker compose v2 ('docker compose') is required."
    docker info >/dev/null 2>&1 || die "cannot talk to Docker (is the daemon running, and are you in the docker group?)"
}

fetch_profile() {
    if [ ! -d "$PROFILE_DIR/.git" ]; then
        say "fetching the HEX profile collection..."
        mkdir -p "$state"
        git clone --quiet "$PROFILE_URL" "$PROFILE_DIR"
    fi
    if [ "$(git -C "$PROFILE_DIR" rev-parse HEAD)" != "$PROFILE_COMMIT" ]; then
        git -C "$PROFILE_DIR" fetch --quiet origin "$PROFILE_COMMIT" 2>/dev/null \
            || git -C "$PROFILE_DIR" fetch --quiet origin
        git -C "$PROFILE_DIR" -c advice.detachedHead=false checkout --quiet "$PROFILE_COMMIT"
    fi
    say "profile at ${PROFILE_COMMIT:0:7}; installing its environments (first time: several minutes)..."
    pixi install --frozen --manifest-path "$PROFILE_DIR/pixi.toml" -e terminal
    pixi install --frozen --manifest-path "$PROFILE_DIR/pixi.toml" -e qs
}

watchdog_script="$repo/sim/hex/scripts/data_watchdog.py"
toolpy="$repo/.pixi/envs/simtools/bin/python"

check_disk() {
    # Refuse to start while the sim data is over its cap (see data_watchdog.py).
    if [ -x "$toolpy" ] && ! "$toolpy" "$watchdog_script" --check; then
        die "simulated detector data is over its cap. Clear it with: pixi run sim-prune
       (or raise the cap: HEX_SIM_DATA_CAP_GB=<GB> pixi run sim-up)"
    fi
}

start_armed_gate() {
    # The simulated Kinetix free-runs the moment it is armed, unlike a real one on an
    # external trigger, so an ophyd-async fly scan (which arms during prepare) fails its
    # kickoff check ("Kickoff requested N:M, but detector was only prepared up to K").
    # This bridge holds the camera until the PandA pulse train fires. On by default here
    # (planrunner runs ophyd-async plans); HEX_SIM_ARMED_GATE=0 turns it off, e.g. for the
    # pyepics oracle, which must run without it.
    [ "${HEX_SIM_ARMED_GATE:-1}" = 0 ] && return
    if ! pgrep -f "$repo/sim/hex/iocs/panda/armed_gate_bridge.py" >/dev/null; then
        # shellcheck disable=SC1091
        (source "$repo/sim/hex/scripts/env.sh" \
            && nohup "$toolpy" -u "$repo/sim/hex/iocs/panda/armed_gate_bridge.py" \
                > /tmp/hex-armed-gate-bridge.log 2>&1 &)
        say "camera armed-gate bridge started (log /tmp/hex-armed-gate-bridge.log)"
    fi
}

start_watchdog() {
    if ! pgrep -f "$watchdog_script" >/dev/null; then
        # shellcheck disable=SC1091
        (source "$repo/sim/hex/scripts/env.sh" \
            && nohup "$toolpy" -u "$watchdog_script" > /tmp/hex-data-watchdog.log 2>&1 &)
        say "data watchdog started (cap ${HEX_SIM_DATA_CAP_GB:-20} GB, log /tmp/hex-data-watchdog.log)"
    fi
}

up() {
    preflight
    check_disk
    fetch_profile
    say "planrunner's simtools environment..."
    pixi install --manifest-path "$repo/pixi.toml" -e simtools
    "$repo/sim/hex/images/build.sh"
    HEX_PROFILE_MANIFEST="$PROFILE_DIR/pixi.toml" "$repo/sim/hex/scripts/up_all.sh"
    start_watchdog
    start_armed_gate
    PROFILE_REPO="$PROFILE_DIR" SIM_ENV="$repo/sim/hex/scripts/env.sh" \
        "$repo/sim/queueserver/bsqs-local.sh" up hex
    cat <<EOF

[sim] The simulated HEX beamline and its queueserver are up.
[sim]   pixi run sim-planrunner      # planrunner with the dev API key (full control)
[sim]   pixi run planrunner --server http://localhost:60610 --connect   # read only
[sim] In planrunner: open the environment, pick a plan, add it to the queue, start.
[sim] Stop everything: sim/sim.sh down
EOF
}

# The host processes up_all.sh starts, matched by their path inside THIS checkout
# (so a second copy of the sim elsewhere on the machine is left alone).
host_processes=(
    "$repo/sim/hex/iocs/phantom/sim_camera.py"
    "$repo/sim/hex/iocs/motor/motor_ioc.py"
    "$repo/sim/hex/iocs/panda/motor_encoder_bridge.py"
    "$repo/sim/hex/iocs/panda/ttl_trigger_bridge.py"
    "$repo/sim/hex/iocs/sim_ioc.py"
    "$repo/sim/hex/scripts/data_watchdog.py"
    "$repo/sim/hex/iocs/panda/armed_gate_bridge.py"
)

down() {
    "$repo/sim/queueserver/bsqs-local.sh" down || true
    for pattern in "${host_processes[@]}"; do
        pkill -f "$pattern" 2>/dev/null && say "stopped $(basename "$pattern")" || true
    done
    for file in docker-compose.phantom.yml docker-compose.kinetix.yml docker-compose.panda.yml; do
        COMPOSE_IGNORE_ORPHANS=1 docker compose -f "$repo/sim/hex/compose/$file" down 2>/dev/null || true
    done
    "$repo/sim/hex/scripts/down.sh"
    say "all stopped. Sim data remains in /tmp/hex-sim-data (sim/hex/scripts/prune_sim_data.sh)."
}

status() {
    say "containers:"
    docker ps --filter name=hexsim- --format '  {{.Names}}\t{{.Status}}' || true
    say "host processes:"
    for pattern in "${host_processes[@]}"; do
        if pgrep -f "$pattern" >/dev/null; then
            echo "  $(basename "$pattern"): running"
        else
            echo "  $(basename "$pattern"): stopped"
        fi
    done
    "$repo/sim/queueserver/bsqs-local.sh" status
}

case ${1:-} in
    up) up ;;
    down) down ;;
    status) status ;;
    *) sed -n '2,6p' "$0"; exit 1 ;;
esac
