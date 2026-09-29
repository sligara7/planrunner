# PlanRunner

A [ScriptRunner](https://github.com/algotom/scriptrunner)-style GUI for building, scheduling and
running **Bluesky plans** on a **bluesky-queueserver**, through **bluesky-httpserver**. Built for
the HEX beamline (NSLS-II) as a friendlier replacement for the bluesky-widgets `queue-monitor`:
richer status, and a typed form for every plan so building the queue takes far less typing.

The GUI is only a client. Plans, devices and the RunEngine live in the queueserver's RE worker,
and the GUI never touches the queue or the RunEngine unless you click something. Closing it,
crashing it or losing the network cannot disturb a running scan.

## Run it

```bash
pixi run planrunner --server http://localhost:60610 --api-key <key> --connect
```

`--server` defaults to `$QSERVER_HTTP_SERVER_URI` or the last server you used; `--api-key`
defaults to `$QSERVER_HTTP_SERVER_API_KEY`.

## Deploy on a beamline workstation

planrunner runs from a clone of this repository with its own pixi environment:

```bash
git clone <this repo> ~/planrunner && cd ~/planrunner
pixi install
pixi run hex          # HEX: --server https://xf27id1-hex-qs1.nsls2.bnl.gov:443 --connect
```

**API key.** The NSLS-II `bsqs` Ansible role already deploys the queueserver's API key to
the workstations it lists as clients. planrunner looks for it, in order:

1. `/etc/qs_client/<queueserver hostname>`, which is readable only by the beamline operator account
2. `$QSERVER_HTTP_SERVER_API_KEY`, which the role exports from `/etc/profile.d/`
3. a key typed into the connection bar (a typed key always wins)

The key is never written to planrunner's settings file. Without a key, planrunner connects
**read only**: status, queue, history and console all work, and every control that would
change something is greyed out. That makes it usable as a monitor anywhere.

## The window

Same layout as ScriptRunner, with the server in place of the script folder:

| ScriptRunner | PlanRunner |
|---|---|
| Base folder bar | **Connection bar**: server, API key, connect; open/close the RE environment |
| — | **Status strip**: manager state, environment, RunEngine, queue size, loop/stop/pause flags |
| Available scripts | **Available plans** (`plans_allowed`), with a filter box |
| Script parameters (from argparse) | **Plan parameters** (from the plan's signature): typed fields, device pickers, defaults, ranges, help text |
| Run now / Add to schedule | **Run now** (`item_execute`) / **Add to queue**, with Repeat and Position |
| Scheduler table + task details | **Queue** tab (move, edit, duplicate, delete) and **History** tab (results, errors, queue again) |
| Run / Pause / Resume / Stop | Queue **Start / Stop after current**, RunEngine **Pause / Resume / Stop / Abort / Halt**, **Loop queue** |
| Console + save to log | Console streams the RE worker's output; save to a log file |

### How parameters become fields

The form is built from what `plans_allowed` says about each parameter:

- `int` / `float` / `str` / `bool` annotations give number, text and checkbox fields, checked
  against `min`/`max`.
- Bluesky protocol annotations (`Readable`, `Movable`, `Flyable`, …) and
  `@parameter_annotation_decorator` device/plan/enum lists give drop-downs, or multi-selects for
  `list[...]`.
- Anything else is a Python literal field. When a parameter has no annotation at all, the field
  suggests device names.

**Heads-up for plan authors:** the queueserver drops annotations it cannot rebuild from
`typing`/`bluesky` names. A parameter typed with a concrete ophyd-async class, such as
`list[KinetixDetector]`, reaches the GUI untyped. Annotate device parameters with
`bluesky.protocols` types (`list[Readable]`, `Movable`) to get proper pickers and server-side
validation.

## Code map

Composition, dependency injection and `typing.Protocol` seams throughout. No class subclasses
another to share behaviour. `app.py` is the only place objects are built and wired.

```
src/planrunner/
  app.py            composition root: builds and wires everything
  main.py           command line
  protocols.py      the seams: QueueServerAPI, CallRunner, Feed, Dispatcher, Dialogs, ...
  events.py         event dataclasses + EventBus (delivers on the UI thread)
  dispatch.py       QueueDispatcher (drained by the Tk loop), ImmediateDispatcher (tests)
  client.py         ServerClient: runs API calls on one worker thread
  feeds.py          PollingStatusFeed, ConsoleFeed: read-only background feeds
  plan_params.py    plan description -> form fields -> queue item   (pure)
  type_strings.py   reads queueserver annotation strings            (pure)
  status_text.py    status strip, enabled buttons, item summaries   (pure)
  config.py         JSON preferences file
  controllers/      behaviour, written against view protocols (no tkinter)
  ui/               Tk views: each composes widgets and forwards clicks to its controller
```

Status arrives by polling today. When the HEX httpserver reaches 0.0.14, a websocket feed can
replace `PollingStatusFeed` behind the same `Feed` protocol, with nothing else changing.

## Develop

```bash
pixi run test        # pytest (includes a GUI smoke test when a display is available)
pixi run lint        # ruff
pixi run typecheck   # mypy
```

Layout, styling and the scheduler concept are adapted from ScriptRunner by Nghia Vo
(Apache-2.0).
