#!/usr/bin/env bash
# A local replica of the NSLS-II "bsqs" queueserver deployment, for testing planrunner.
#
#   sim/queueserver/bsqs-local.sh up [builtin|hex|hextools]   # redis + RE Manager + httpserver
#   sim/queueserver/bsqs-local.sh down               # stop them
#   sim/queueserver/bsqs-local.sh status
#
# Same shape as the beamline VM: redis on 60590, RE Manager and httpserver talking over
# ZMQ ipc sockets, httpserver on localhost:60610 with the role's auth rules (anonymous =
# read only, the single-user API key = full control). Both services run from the
# profile's pixi `qs` environment, exactly as the systemd units do.
#
# Profiles:
#   builtin  the queueserver's own simulated profile (ophyd.sim det1, motor, ...): no IOCs
#   hex      hex-profile-collection's startup/ with HEX_SIM=1 against the simulated HEX
#            beamline (hex-ob/hex-simulated-beamline must be up: scripts/up_all.sh)
#   hextools hextools' own profile (hextools.profiles.collection) with HEXTOOLS_SIM=YES
#            against the simulated HEX beamline, from HEXTOOLS_REPO's `qs` environment
#
# Knobs: PROFILE_REPO (default ~/git_projects/hex-ob/hex-profile-collection),
#        HEXTOOLS_REPO (default ~/git_projects/hextools),
#        SIM_ENV (default ~/git_projects/hex-ob/hex-simulated-beamline/scripts/env.sh),
#        API_KEY (default planrunnerdev; alphanumeric, as the httpserver requires), REDIS_PORT (60590), HTTP_PORT (60610).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
RUN_DIR="${RUN_DIR:-$repo_root/.bsqs-local}"
# ZMQ ipc sockets need a path under 108 characters, which a deep checkout can exceed:
# keep them in a short directory, one per checkout.
SOCK_DIR="${SOCK_DIR:-${XDG_RUNTIME_DIR:-/tmp}/bsqs-$(printf %s "$RUN_DIR" | md5sum | cut -c1-8)}"
PROFILE_REPO="${PROFILE_REPO:-$HOME/git_projects/hex-ob/hex-profile-collection}"
SIM_ENV="${SIM_ENV:-$HOME/git_projects/hex-ob/hex-simulated-beamline/scripts/env.sh}"
API_KEY="${API_KEY:-planrunnerdev}"
REDIS_PORT="${REDIS_PORT:-60590}"
HTTP_PORT="${HTTP_PORT:-60610}"
HEXTOOLS_REPO="${HEXTOOLS_REPO:-$HOME/git_projects/hextools}"
QS=(pixi run --frozen --manifest-path "$PROFILE_REPO/pixi.toml" --environment qs)

say() { echo "[bsqs-local] $*"; }

render() {  # render TEMPLATE OUTPUT STARTUP_SOURCE PERMISSIONS
    sed -e "s|@RUN_DIR@|$RUN_DIR|g" -e "s|@SOCK_DIR@|$SOCK_DIR|g" -e "s|@REDIS_PORT@|$REDIS_PORT|g" \
        -e "s|@STARTUP_SOURCE@|$3|g" -e "s|@PERMISSIONS@|$4|g" "$1" > "$2"
}

start() {  # start NAME COMMAND... (background, logged, pid recorded)
    local name=$1; shift
    nohup "$@" > "$RUN_DIR/$name.log" 2>&1 &
    echo $! > "$RUN_DIR/$name.pid"
    say "$name started (pid $!, log $RUN_DIR/$name.log)"
}

running() { [ -f "$RUN_DIR/$1.pid" ] && kill -0 "$(cat "$RUN_DIR/$1.pid")" 2>/dev/null; }

up() {
    local profile=${1:-builtin} startup_dir="" startup_source permissions
    mkdir -p "$RUN_DIR" "$SOCK_DIR"
    case $profile in
        builtin)
            # A private copy, so the worker's plan-list rewrite never touches site-packages.
            local pkg
            pkg=$("${QS[@]}" python -c \
                "import bluesky_queueserver, pathlib; print(pathlib.Path(bluesky_queueserver.__file__).parent)")
            rm -rf "$RUN_DIR/startup"
            cp -r "$pkg/profile_collection_sim" "$RUN_DIR/startup"
            startup_dir="$RUN_DIR/startup"
            ;;
        hex)
            [ -f "$SIM_ENV" ] || { say "missing $SIM_ENV"; exit 1; }
            # shellcheck disable=SC1090
            source "$SIM_ENV"
            export HEX_SIM=1 MPLBACKEND=Agg
            startup_dir="$PROFILE_REPO/startup"
            ;;
        hextools)
            [ -f "$SIM_ENV" ] || { say "missing $SIM_ENV"; exit 1; }
            [ -f "$HEXTOOLS_REPO/pixi.toml" ] || { say "no hextools checkout at $HEXTOOLS_REPO"; exit 1; }
            # shellcheck disable=SC1090
            source "$SIM_ENV"
            export HEXTOOLS_SIM=YES MPLBACKEND=Agg
            QS=(pixi run --frozen --manifest-path "$HEXTOOLS_REPO/pixi.toml" --environment qs)
            startup_source="startup_module: \"hextools.profiles.collection\""
            permissions="$here/hextools/user_group_permissions.yaml"
            # No list shipped: the worker writes it when the environment first opens.
            printf 'existing_plans: {}\nexisting_devices: {}\n' > "$RUN_DIR/existing_plans_and_devices.yaml"
            ;;
        *) say "unknown profile '$profile' (builtin|hex|hextools)"; exit 1 ;;
    esac
    if [ -n "$startup_dir" ]; then
        startup_source="startup_dir: \"$startup_dir\""
        permissions="$startup_dir"
        # The worker rewrites this file when the environment opens; keep that out of the repo.
        cp "$startup_dir/existing_plans_and_devices.yaml" "$RUN_DIR/existing_plans_and_devices.yaml"
    fi
    render "$here/queueserver-config.yml.in" "$RUN_DIR/queueserver-config.yml" "$startup_source" "$permissions"
    render "$here/httpserver-config.yml.in" "$RUN_DIR/httpserver-config.yml" "$startup_source" "$permissions"
    echo "$profile" > "$RUN_DIR/profile"

    running redis || start redis redis-server --port "$REDIS_PORT" --bind 127.0.0.1 \
        --save "" --appendonly no --dir "$RUN_DIR"
    sleep 1
    running manager || start manager "${QS[@]}" start-re-manager \
        --config "$RUN_DIR/queueserver-config.yml"
    running httpserver || QSERVER_HTTP_SERVER_CONFIG="$RUN_DIR/httpserver-config.yml" \
        QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY="$API_KEY" \
        start httpserver "${QS[@]}" uvicorn --host localhost --port "$HTTP_PORT" \
        bluesky_httpserver.server:app

    for _ in $(seq 60); do
        curl -sf "http://localhost:$HTTP_PORT/api/status" >/dev/null && break
        sleep 1
    done
    curl -sf "http://localhost:$HTTP_PORT/api/status" >/dev/null \
        || { say "httpserver did not answer; see $RUN_DIR/*.log"; exit 1; }
    say "UP ($profile profile). Try:"
    say "  pixi run planrunner --server http://localhost:$HTTP_PORT --api-key $API_KEY --connect"
    say "  pixi run planrunner --server http://localhost:$HTTP_PORT --connect   # read only"
}

down() {
    for name in httpserver manager redis; do
        if running "$name"; then
            local pid
            pid=$(cat "$RUN_DIR/$name.pid")
            kill "$pid"
            # Wait for it to exit, so an `up` straight after can bind the same ports.
            for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
            say "$name stopped"
        fi
        rm -f "$RUN_DIR/$name.pid"
    done
}

status() {
    for name in redis manager httpserver; do
        if running "$name"; then say "$name: running"; else say "$name: stopped"; fi
    done
    curl -s "http://localhost:$HTTP_PORT/api/status" || true
    echo
}

case ${1:-} in
    up) up "${2:-builtin}" ;;
    down) down ;;
    status) status ;;
    *) sed -n '2,8p' "$0"; exit 1 ;;
esac
