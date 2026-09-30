# bsqs-local: the HEX queueserver deployment, on your machine

A local replica of what the NSLS-II `bsqs` Ansible role deploys to `xf27id1-hex-qs1`. It
runs the same pieces:

- Redis on 60590
- RE Manager and httpserver talking over ZMQ ipc sockets
- httpserver on 60610, with the role's auth rules: anonymous callers get `read:status` and
  `read:console` only, and the single-user API key gets full control

Both services run from the profile's pixi `qs` environment, as the systemd units do. The
two `*.yml.in` files mirror the role's templates.

```bash
sim/queueserver/bsqs-local.sh up builtin   # queueserver's simulated profile, no IOCs
pixi run live-test                             # drive the real GUI against it
pixi run planrunner --server http://localhost:60610 --api-key planrunnerdev --connect
sim/queueserver/bsqs-local.sh down
```

`up hex` runs hex-profile-collection's `startup/` with `HEX_SIM=1` instead. The simulated
HEX beamline must be up first (`hex-ob/hex-simulated-beamline/scripts/up_all.sh`).

`up hextools` runs hextools' own profile (`hextools.profiles.collection`, loaded with
`startup_module`) with `HEXTOOLS_SIM=YES`, from the `qs` environment of the checkout at
`HEXTOOLS_REPO` (default `~/git_projects/hextools`). In that mode the profile uses the
sim's Redis, tiled and data directory, connects devices for real, and refuses to start if
EPICS could reach anything but loopback. Its permissions file is
`hextools/user_group_permissions.yaml` (the HEX profile's, unchanged). From the top:
`SIM_PROFILE=hextools HEXTOOLS_REPO=<checkout> pixi run sim-up`.

`up hex` and `up hextools` also set the PandA's dataset names each profile's plans expect
(`sim/hex/iocs/panda/init_panda_ioc.py --profile`). hextools names CALC1's output "Angle",
which the HEX design already gives CALC2, and the PandA's HDF writer refuses two datasets
with one name. So for hextools CALC2 becomes `legacy_angle`, and `up hex` puts it back.
Which side should change on the beamline is still open.

Everything the services write goes to `.bsqs-local/` (gitignored), including the plan
list the worker rewrites when the environment opens. Nothing in the profile repo is
modified.

**Differences from the VM:**
- It runs whatever queueserver version the profile clone's lock file holds.
- It serves plain HTTP on localhost, with no nginx or TLS in front.
