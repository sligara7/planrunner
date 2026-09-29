#!/usr/bin/env bash
# Build the simulated HEX beamline's local Docker images from pinned public sources.
#
#   sim/hex/images/build.sh             # build whichever images are missing
#   sim/hex/images/build.sh --rebuild [panda|kinetix|phantom ...]   # build again (default: all)
#
#   hexsim-panda-sim:local     PandABlocks-server + the FPGA block-sim engine (Dockerfile)
#   hexsim-kinetix-ioc:local   real ADSimDetector IOC under the HEX Kinetix prefix
#   hexsim-phantom-ioc:local   real ADPhantom IOC (talks to sim_camera.py)
#
# The two IOC images are built the facility way: NSLS2's nsls2.ioc_deploy runs its
# adsimdetector / adphantom role inside an EPICS AlmaLinux 8 container (compiling
# ADCore, the driver and their dependencies), and the result is committed as an image.
# First build: roughly 15 minutes and ~12 GB of images.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sim="$(cd "$here/.." && pwd)"
repo="$(cd "$sim/../.." && pwd)"
work="$repo/.sim"

IOC_DEPLOY_URL="https://github.com/NSLS2/nsls2.ioc_deploy.git"
IOC_DEPLOY_COMMIT="99f6726446623a3e365071541f27b4006a2fa321"   # NSLS2 main, 2026-08-04
DEPLOY_CONTAINER="nsls2_ioc_deploy_el8"   # the name nsls2.ioc_deploy gives its container
PHANTOM_TEMPLATE="/epics/modules/adphantom_afefafc/db/phantomCamera.template"

say() { echo "[images] $*" >&2; }
have() { docker image inspect "$1" >/dev/null 2>&1; }

rebuild=()
if [ "${1:-}" = "--rebuild" ]; then
    shift
    rebuild=("$@")
    [ $# -eq 0 ] && rebuild=(panda kinetix phantom)
fi
wanted() {  # wanted NAME IMAGE: build when asked to rebuild it, or when it is missing
    [[ " ${rebuild[*]} " == *" $1 "* ]] || ! have "$2"
}

fetch_ioc_deploy() {
    local dir="$work/nsls2.ioc_deploy"
    if [ ! -d "$dir/.git" ]; then
        say "fetching nsls2.ioc_deploy..."
        mkdir -p "$work"
        git clone --quiet "$IOC_DEPLOY_URL" "$dir"
    fi
    git -C "$dir" -c advice.detachedHead=false checkout --quiet "$IOC_DEPLOY_COMMIT"
    echo "$dir"
}

# deploy_ioc IMAGE CONFIG [AFTER]: run the role in a fresh container, optionally
# adjust the container with AFTER, then commit it as IMAGE.
deploy_ioc() {
    local image=$1 config=$2 after=${3:-}
    local ioc_deploy
    ioc_deploy=$(fetch_ioc_deploy)
    docker rm -f "$DEPLOY_CONTAINER" >/dev/null 2>&1 || true
    say "building $image (role deploy + compile; several minutes)..."
    (cd "$ioc_deploy" && PIXI_FROZEN=true pixi run deployment --container -c "$config")
    [ -n "$after" ] && "$after"
    docker commit "$DEPLOY_CONTAINER" "$image" >/dev/null
    docker rm -f "$DEPLOY_CONTAINER" >/dev/null
    say "  $image built"
}

add_phantom_records() {
    # Give the IOC the PVs the HEX-deployed ADPhantom has beyond the public source.
    # As root: the role installs the template owned by the build user.
    docker exec -i -u 0 "$DEPLOY_CONTAINER" sh -c "cat >> $PHANTOM_TEMPLATE" \
        < "$sim/iocs/phantom/acquire_time_ms.template"
}

trap 'docker rm -f "$DEPLOY_CONTAINER" >/dev/null 2>&1 || true' EXIT

if wanted panda hexsim-panda-sim:local; then
    say "building hexsim-panda-sim:local..."
    docker compose -f "$sim/compose/docker-compose.panda.yml" build panda-sim
fi
if wanted kinetix hexsim-kinetix-ioc:local; then
    deploy_ioc hexsim-kinetix-ioc:local "$sim/iocs/kinetix/hexsim-kinetix1.yml"
fi
if wanted phantom hexsim-phantom-ioc:local; then
    deploy_ioc hexsim-phantom-ioc:local "$sim/iocs/phantom/hexsim-phantom1.yml" add_phantom_records
    count=$(docker run --rm --entrypoint grep hexsim-phantom-ioc:local -c AcquireTimeMs \
        "$PHANTOM_TEMPLATE" || true)
    [ "$count" = 3 ] || { say "ERROR: phantom template has $count AcquireTimeMs records, expected 3"; exit 1; }
fi
say "images ready."
