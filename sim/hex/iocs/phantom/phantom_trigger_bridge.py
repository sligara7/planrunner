#!/usr/bin/env python3
"""Send the simulated Phantom its event trigger when the PandA's pulse train starts.

An armed Phantom records into its cine until an EVENT trigger, then records its
post-trigger frames and can be downloaded. In a fly scan (ExtSyncType = FSYNC,
one frame per PandA pulse) that trigger is the start of the PandA's train; the sim
has no cable for it, so this bridge closes the gap in software, like
``panda/armed_gate_bridge.py`` does for the Kinetix: when the cumulative pulse
tally (``COUNTER3:OUT``, wired to PULSE1.OUT) increments while the camera is armed
and waiting for a trigger, it writes ``cam1:SendSoftwareTrigger`` once.

Left alone on purpose: a camera in FREE-RUN, where the trigger is an operator's
decision (planrunner's Trigger button, or ``SendSoftwareTrigger`` by hand).

Only the LOCAL sim is written; never point this at a real beamline.
"""

import argparse
import fcntl
import os
import signal
import sys
import time

DEFAULT_CAM_PREFIX = "XF:27ID1-ES{Phantom-Det:1}cam1:"
DEFAULT_COUNTER_PV = "XF:27ID1-ES{PANDA:1}:COUNTER3:OUT"
WAITING_FOR_TRIGGER = 1 << 2  # State_RBV bit 2 (PhantomIO.waiting_for_trigger)
LOCK = "/tmp/hex-phantom-trigger-bridge.lock"


def run(args):
    # Beamline guard before importing epics (it reads the environment at import).
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "panda"))
    from localguard import assert_local_epics

    assert_local_epics(default_ca="127.0.0.1:5064 127.0.0.1:5095 127.0.0.1:5105")

    lock = open(LOCK, "w")  # noqa: SIM115 - held for the life of the process
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"ERROR: another phantom_trigger_bridge holds {LOCK}", file=sys.stderr)
        return 1

    from epics import PV

    # Callbacks only decide; the main loop writes. pyepics does not reliably send a
    # put made from inside a monitor callback (the first version's trigger never
    # reached the IOC).
    state = {"tally": None, "waiting": False, "fsync": False, "sent": False,
             "fire": None}

    def on_tally(value=None, **_kw):
        if value is None:
            return
        tally, previous = int(value), state["tally"]
        state["tally"] = tally
        if previous is None or tally <= previous:
            return  # first reading, or the reset at PCAP arm
        if state["waiting"] and state["fsync"] and not state["sent"]:
            state["sent"] = True
            state["fire"] = f"pulse train started (tally {previous} -> {tally})"

    def on_state(value=None, **_kw):
        if value is None:
            return
        waiting = bool(int(value) & WAITING_FOR_TRIGGER)
        if waiting and not state["waiting"]:
            state["sent"] = False  # a new arm: one trigger per arm
        state["waiting"] = waiting

    def on_sync(char_value=None, **_kw):
        if char_value:
            state["fsync"] = char_value == "FSYNC"

    trigger = PV(args.cam_prefix + "SendSoftwareTrigger")
    pvs = [
        trigger,
        PV(args.cam_prefix + "State_RBV", callback=on_state, auto_monitor=True),
        PV(args.cam_prefix + "ExtSyncType_RBV", callback=on_sync, auto_monitor=True,
           form="ctrl"),
        PV(args.counter_pv, callback=on_tally, auto_monitor=True),
    ]
    for pv in pvs:
        if not pv.wait_for_connection(timeout=args.connect_timeout):
            print(f"ERROR: could not connect to {pv.pvname}", file=sys.stderr)
            return 1
    on_sync(char_value=pvs[2].get(as_string=True))

    print(f"phantom_trigger_bridge up: {args.counter_pv} -> "
          f"{args.cam_prefix}SendSoftwareTrigger (FSYNC only)", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            time.sleep(0.01)
            if (reason := state["fire"]) is not None:
                state["fire"] = None
                trigger.put(1, wait=True, timeout=5)
                print(f"TRIGGER: {reason}", flush=True)
    except KeyboardInterrupt:
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="PandA pulse train -> Phantom event trigger.")
    parser.add_argument("--cam-prefix", default=DEFAULT_CAM_PREFIX)
    parser.add_argument("--counter-pv", default=DEFAULT_COUNTER_PV)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
