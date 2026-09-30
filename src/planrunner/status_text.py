"""Turn RE Manager status and queue items into what the GUI shows.

Pure functions: which buttons are usable in the current state, the rows of the
status strip, and one-line summaries of queue and history items.
"""

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from planrunner.permissions import Permissions
from planrunner.protocols import JSON


class Tone(StrEnum):
    """How a status value should be coloured."""

    NORMAL = "normal"
    GOOD = "good"
    BUSY = "busy"
    WARN = "warn"
    BAD = "bad"


@dataclass(frozen=True, slots=True)
class StatusField:
    label: str
    value: str
    tone: Tone = Tone.NORMAL


@dataclass(frozen=True, slots=True)
class Controls:
    """Which queue and RunEngine commands make sense right now."""

    start: bool = False
    stop_after_current: bool = False
    cancel_stop: bool = False
    pause: bool = False
    resume: bool = False
    stop_run: bool = False
    stop: bool = False
    """'Stop run': pause now if running, then stop."""
    abort: bool = False
    halt: bool = False
    run_now: bool = False
    open_environment: bool = False
    close_environment: bool = False
    edit_queue: bool = False
    set_loop: bool = False


def controls_for(status: JSON | None, allowed: Permissions | None = None) -> Controls:
    """The commands to enable in this state, for a user with these permissions.

    ``status`` is ``None`` when not connected; ``allowed`` defaults to everything.
    """
    if not status:
        return Controls()
    allowed = allowed or Permissions.full()
    state = status.get("manager_state", "")
    env = bool(status.get("worker_environment_exists"))
    running = state in ("executing_queue", "executing_task")
    paused = state == "paused"
    stop_pending = bool(status.get("queue_stop_pending"))
    idle = state == "idle"
    queue, plan, manager = allowed.control_queue, allowed.control_plan, allowed.control_manager
    return Controls(
        start=queue and idle and env and status.get("items_in_queue", 0) > 0,
        stop_after_current=queue and state == "executing_queue" and not stop_pending,
        cancel_stop=queue and state == "executing_queue" and stop_pending,
        pause=plan and running and not status.get("pause_pending"),
        resume=plan and paused,
        stop_run=plan and paused,
        stop=plan and (running or paused),
        abort=plan and paused,
        halt=plan and paused,
        run_now=allowed.execute and idle and env,
        open_environment=manager and idle and not env,
        close_environment=manager and idle and env,
        edit_queue=allowed.edit_queue,
        set_loop=queue,
    )


def status_fields(status: JSON | None, reachable: bool = True) -> list[StatusField]:
    """The status strip, left to right."""
    if status is None:
        return [StatusField("Server", "not connected", Tone.WARN)]
    if not reachable:
        return [StatusField("Server", "unreachable", Tone.BAD)]

    state = status.get("manager_state", "?")
    manager_tone = (
        Tone.GOOD if state == "idle"
        else Tone.WARN if state == "paused"
        else Tone.BUSY
    )
    env = status.get("worker_environment_exists")
    re_state = status.get("re_state") or "-"
    queue_size = status.get("items_in_queue", 0)
    mode = status.get("plan_queue_mode") or {}

    fields = [
        StatusField("Manager", state.replace("_", " "), manager_tone),
        StatusField("Environment", "open" if env else "closed", Tone.GOOD if env else Tone.WARN),
        StatusField("RunEngine", re_state, Tone.WARN if re_state == "paused" else Tone.NORMAL),
        StatusField("Queue", f"{queue_size} item{'' if queue_size == 1 else 's'}"),
        StatusField("History", str(status.get("items_in_history", 0))),
    ]
    if mode.get("loop"):
        fields.append(StatusField("Loop", "on", Tone.BUSY))
    if status.get("queue_stop_pending"):
        fields.append(StatusField("Stop", "after current plan", Tone.WARN))
    if status.get("pause_pending"):
        fields.append(StatusField("Pause", "pending", Tone.WARN))
    lock = status.get("lock") or {}
    if locked := [name for name in ("environment", "queue") if lock.get(name)]:
        fields.append(StatusField("Locked", " + ".join(locked), Tone.BAD))
    return fields


# ------------------------------------------------------------------------------
#                       Items
# ------------------------------------------------------------------------------


def parameters_text(item: JSON, limit: int = 120) -> str:
    """``item``'s arguments as a call signature, e.g. ``['det1'], num=3``."""
    parts = [_short_repr(a) for a in item.get("args", ())]
    parts += [f"{k}={_short_repr(v)}" for k, v in item.get("kwargs", {}).items()]
    text = ", ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def item_title(item: JSON) -> str:
    kind = item.get("item_type", "plan")
    name = item.get("name", "?")
    return name if kind == "plan" else f"[{kind}] {name}"


def item_details(item: JSON) -> str:
    """Multi-line description of an item for the details pane."""
    lines = [item_title(item)]
    lines += [f"  arg {i}: {a!r}" for i, a in enumerate(item.get("args", ()))]
    lines += [f"  {k} = {v!r}" for k, v in item.get("kwargs", {}).items()]
    if user := item.get("user"):
        lines.append(f"Added by: {user}")
    if result := item.get("result"):
        lines.append(f"Result: {result_text(result)}")
        if scan_ids := result.get("scan_ids"):
            lines.append(f"Scan IDs: {', '.join(map(str, scan_ids))}")
        if msg := result.get("msg"):
            lines.append(f"Message: {msg}")
        if tb := result.get("traceback"):
            lines += ["", tb]
    return "\n".join(lines)


def result_text(result: JSON) -> str:
    status = result.get("exit_status", "?")
    start, stop = result.get("time_start"), result.get("time_stop")
    if start and stop:
        return f"{status} ({_duration(stop - start)})"
    return str(status)


def time_text(timestamp: float | None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp)) if timestamp else ""


def _duration(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _short_repr(value: Any) -> str:
    return value if isinstance(value, str) and value.isidentifier() else repr(value)
