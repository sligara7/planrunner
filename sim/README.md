# Simulated HEX beamline: try planrunner without a beamline

Everything needed to run planrunner against a realistic HEX setup on your own machine:

- **the simulated HEX (27-ID) beamline** (`hex/`): real EPICS IOCs for the Kinetix and
  Phantom cameras, a cycle-accurate simulated PandA, a motor IOC with real motion, and the
  shutter/metadata PVs, plus the Redis/Mongo/Kafka/Tiled services a HEX session expects
- **the queueserver, deployed the way the beamline VM runs it** (`queueserver/`): the same
  configuration the NSLS-II `bsqs` Ansible role writes, booting the real HEX profile
  collection against the sim

Nothing here reaches a real beamline. Every server binds to 127.0.0.1, and simulated data
goes to `/tmp/hex-sim-data` under a fake data session (`pass-000000`).

## Quick start

You need **Linux x86-64**, **Docker** with compose v2 (your user in the `docker` group),
**pixi**, **git**, **curl** and **openssl**. Allow ~15 GB of disk for images.

```bash
pixi run sim-up            # first run: ~20-30 min (builds IOC images, installs the profile)
pixi run sim-planrunner    # planrunner, connected with the dev API key
pixi run sim-down          # stop everything
```

`sim-up` is idempotent: run it again to start whatever is not running. Later runs take
under a minute. `pixi run sim-status` shows what is up.

In planrunner: **Environment → Open** (the RE worker boots the HEX profile, ~30 s), pick
a plan, fill in the form, **Add to queue**, **Start**. Watch the console and the History
tab. Without the API key (`pixi run planrunner --server http://localhost:60610 --connect`)
you get the read-only view an operator without the key would see.

## What `sim-up` does

1. Fetches the HEX profile collection at a pinned commit into `.sim/` and installs its
   pixi environments exactly as locked.
2. Builds three local Docker images from pinned public sources (`hex/images/build.sh`):
   the PandA simulator, and the Kinetix and Phantom IOCs, which are compiled by NSLS2's
   `nsls2.ioc_deploy` roles the same way beamline IOCs are.
3. Starts the beamline (`hex/scripts/up_all.sh`).
4. Starts Redis, RE Manager and bluesky-httpserver (`queueserver/bsqs-local.sh up hex`),
   with the API key `planrunnerdev`.

**Disk use.** The simulated cameras write real HDF5 files of zero-valued frames to
`/tmp/hex-sim-data`. Recording on the simulated Phantom writes nothing; downloading a
cine does, at about 130 MB/s, and a full cine is about 16 GB. A watchdog caps the
directory at **20 GB**. Past the cap it turns detector file writing off, so scans fail
loudly instead of filling the disk. Clear space with `pixi run sim-prune`, or change the
cap with `HEX_SIM_DATA_CAP_GB=<GB> pixi run sim-up`.

Logs: `.bsqs-local/*.log` (queueserver), `/tmp/hex-*.log` (sim host processes),
`docker logs hexsim-<name>` (containers).

## Where this came from

`hex/` is a copy of `hex-simulated-beamline` from
[sligara7/hex-ob](https://github.com/sligara7/hex-ob) at commit `c30c925`, which remains
its canonical home. The copy was made portable for this repo. Anyone refreshing it
from hex-ob should carry these changes over:

- paths default to this checkout, and the helper scripts run in planrunner's `simtools`
  pixi environment instead of a pip venv
- `iocs/panda/Dockerfile.simserver` pins PandABlocks-FPGA to `916fb9a6` (upstream `main`
  removed the block-simulation engine on 2026-09-24)
- `iocs/kinetix/init_kinetix.py` sets `HDF1:LazyOpen=1`, so the first capture after the IOC
  boots does not fail
- the motor IOC binds Channel Access to 127.0.0.1 only
- new: `images/build.sh`, and `iocs/phantom/acquire_time_ms.template` (the three PVs the
  HEX-deployed ADPhantom IOC has beyond the public source)

The sim's own documentation (`hex/README.md`, `hex/PROGRESS.md`) is kept as it was,
including paths from its original location.

**Known limit:** the PandA simulator's control port (8888) listens on all interfaces,
because PandABlocks-server has no bind option. Use a host firewall if that matters on
your network.
