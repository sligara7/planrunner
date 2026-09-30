#!/usr/bin/env python3
"""Init for the sim pandablocks-ioc (autosave-equivalents), per queueserver profile.

On the real beamline these IOC-level settings persist; a recreated sim
container starts bare. Apply after any panda-ioc restart (the panda-side
block design is separate — ``hex_tomo_design.py`` over the control port).

The settings are the HDF dataset names of captured fields, and the two profiles
the sim can boot want different ones:

* ``hex`` (hex-profile-collection, the beamline today): ``CALC2:OUT:DATASET =
  "Angle"``, which the pyepics scripts read back via ``losa.load_hdf(panda.hdf,
  "Angle")``. CALC1 gets its default name back, in case hextools left "Angle" on it.
* ``hextools``: hextools' fly scan names CALC1's dataset "Angle" itself, and the
  PandA's HDF writer refuses two datasets with one name ("Unable to create dataset
  (name already exists)"), so CALC2 is renamed ``legacy_angle``. Which side changes
  on the beamline is still open; this only lets the sim run hextools meanwhile.

Names are always written non-empty: an empty string put to these PVs is ignored.

Run (env with `pyepics`): python iocs/panda/init_panda_ioc.py [--profile hex|hextools]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from localguard import assert_local_epics  # noqa: E402

assert_local_epics(default_ca="127.0.0.1:5095")

from epics import caget, caput  # noqa: E402

P = "XF:27ID1-ES{PANDA:1}:"

SETTINGS = {
    "hex": [
        ("CALC1:OUT:DATASET", "CALC1.OUT.Value"),  # the IOC's own default name
        ("CALC2:OUT:DATASET", "Angle"),
    ],
    "hextools": [
        ("CALC2:OUT:DATASET", "legacy_angle"),
    ],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Init the sim pandablocks-ioc.")
    parser.add_argument("--profile", choices=sorted(SETTINGS), default="hex")
    args = parser.parse_args(argv)

    failures = 0
    for pv, value in SETTINGS[args.profile]:
        ok = caput(P + pv, value, wait=True, timeout=5)
        got = caget(P + pv, as_string=True, timeout=5, use_monitor=False)
        print("%-22s = %-18r -> readback %r" % (pv, value, got))
        if ok is None or got != value:
            failures += 1
    if failures:
        print("FAILED to apply %d setting(s)" % failures, file=sys.stderr)
        return 1
    print(f"panda-ioc initialized for the {args.profile} profile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
