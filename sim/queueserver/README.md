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

Everything the services write goes to `.bsqs-local/` (gitignored), including the plan
list the worker rewrites when the environment opens. Nothing in the profile repo is
modified.

**Differences from the VM:**
- It runs whatever queueserver version the profile clone's lock file holds.
- It serves plain HTTP on localhost, with no nginx or TLS in front.
