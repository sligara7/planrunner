"""Stop the simulated detectors from filling the disk.

Watches the sim data directory (default /tmp/hex-sim-data). Once it grows past the
cap (default 20 GB, env HEX_SIM_DATA_CAP_GB), turns off file writing on every
detector that writes files (Kinetix and Phantom HDF plugins, PandA HDF capture).
It keeps turning it off while the directory stays over the cap, so a scan started
afterwards fails loudly instead of writing. Clear space with `pixi run sim-prune`.

    python data_watchdog.py              # run until killed (sim/sim.sh up starts it)
    python data_watchdog.py --check      # exit 1 if over the cap, else 0

A real Phantom fills gigabytes of camera RAM in seconds. The simulated one keeps
no pixels, but a cine download writes ~1.3 MB zero-frames at ~130 MB/s and a
full cine is ~16 GB, so a plan that keeps downloading can fill a disk in hours.
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "iocs" / "panda"))
from localguard import assert_local_epics  # noqa: E402

assert_local_epics()  # before importing epics: never reach a real beamline

from epics import caput  # noqa: E402

DATA_DIR = Path(os.environ.get("HEX_SIM_DATA_DIR", "/tmp/hex-sim-data"))
CAP_GB = float(os.environ.get("HEX_SIM_DATA_CAP_GB", "20"))
PERIOD_S = 5.0

# (PV, value that stops file writing)
STOP_WRITING = [
    ("XF:27ID1-BI{Kinetix-Det:1}HDF1:Capture", 0),
    ("XF:27ID1-BI{Kinetix-Det:1}HDF1:EnableCallbacks", 0),
    ("XF:27ID1-ES{Phantom-Det:1}HDF1:Capture", 0),
    ("XF:27ID1-ES{Phantom-Det:1}HDF1:EnableCallbacks", 0),
    ("XF:27ID1-ES{PANDA:1}:DATA:Capture", 0),
]


def usage_bytes(root: Path) -> int:
    """Disk space used under ``root`` (allocated blocks, like ``du``)."""
    total = 0
    for dirpath, _, filenames in os.walk(root, onerror=lambda _: None):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_blocks * 512
            except OSError:
                pass  # removed while walking
    return total


def log(message: str) -> None:
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + message, flush=True)


def stop_writing() -> None:
    for pv, value in STOP_WRITING:
        caput(pv, value, wait=False, timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report and exit")
    args = parser.parse_args()
    cap = int(CAP_GB * 1e9)

    if args.check:
        used = usage_bytes(DATA_DIR)
        print(f"sim data: {used / 1e9:.1f} GB of {CAP_GB:g} GB cap at {DATA_DIR}")
        return 1 if used >= cap else 0

    log(f"watching {DATA_DIR}: cap {CAP_GB:g} GB (HEX_SIM_DATA_CAP_GB)")
    over = False
    while True:
        used = usage_bytes(DATA_DIR)
        if used >= cap:
            if not over:
                log(f"OVER CAP: {used / 1e9:.1f} GB >= {CAP_GB:g} GB. Detector file writing "
                    "is OFF until space is cleared: pixi run sim-prune")
            stop_writing()  # every pass: a new scan would re-enable it
            over = True
        elif over:
            log(f"back under cap ({used / 1e9:.1f} GB); detectors may write again")
            over = False
        time.sleep(PERIOD_S)


if __name__ == "__main__":
    sys.exit(main())
