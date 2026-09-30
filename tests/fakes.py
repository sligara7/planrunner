"""Test doubles that satisfy planrunner's protocols."""

import time
from dataclasses import dataclass, field
from typing import Any

from planrunner.protocols import JSON


@dataclass
class FakeConsoleMonitor:
    messages: list[JSON] = field(default_factory=list)
    enabled: bool = False

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def next_msg(self, timeout: float | None = None) -> JSON:
        if not self.messages:
            if timeout:
                time.sleep(timeout)
            raise TimeoutError("no message")
        return self.messages.pop(0)


@dataclass
class FakeQueueServer:
    """Records every call; returns canned replies. Satisfies ``QueueServerAPI``."""

    status_reply: JSON = field(default_factory=dict)
    queue_reply: JSON = field(default_factory=lambda: {"items": [], "running_item": {}})
    history_reply: JSON = field(default_factory=lambda: {"items": []})
    plans: JSON = field(default_factory=dict)
    devices: JSON = field(default_factory=dict)
    scopes: list[str] | None = None
    """None: the server grants everything (as a test default)."""
    fail_with: Exception | None = None
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)
    monitor: FakeConsoleMonitor = field(default_factory=FakeConsoleMonitor)
    closed: bool = False
    task_reply: JSON = field(default_factory=lambda: {
        "success": True, "msg": "", "return_value": "done"})
    """The ``result`` of every function_execute task."""
    _uids: int = 0

    @property
    def console_monitor(self) -> FakeConsoleMonitor:
        return self.monitor

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.fail_with is not None:
            raise self.fail_with

    def called(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for n, a, k in self.calls if n == name]

    def status(self, *, reload: bool = False) -> JSON:
        self._record("status")
        return dict(self.status_reply)

    def api_scopes(self) -> JSON:
        self._record("api_scopes")
        if self.scopes is None:
            # What the bsqs-configured httpserver grants the single-user API key.
            return {"roles": ["unauthenticated_single_user"], "scopes": [
                "read:status", "read:queue", "read:history", "read:resources", "read:console",
                "write:queue:edit", "write:queue:control", "write:plan:control",
                "write:manager:control", "write:execute"]}
        return {"roles": ["unauthenticated_public"], "scopes": self.scopes}

    def plans_allowed(self, *, reload: bool = False) -> JSON:
        self._record("plans_allowed")
        return {"plans_allowed": self.plans}

    def devices_allowed(self, *, reload: bool = False) -> JSON:
        self._record("devices_allowed")
        return {"devices_allowed": self.devices}

    def queue_get(self, *, reload: bool = False) -> JSON:
        self._record("queue_get")
        return self.queue_reply

    def history_get(self, *, reload: bool = False) -> JSON:
        self._record("history_get")
        return self.history_reply

    def item_add_batch(self, items, *, pos=None) -> JSON:
        self._record("item_add_batch", items, pos=pos)
        added = []
        for item in items:
            self._uids += 1
            added.append({**item, "item_uid": f"uid-{self._uids}"})
        return {"success": True, "items": added}

    def item_update(self, item, *, replace=None) -> JSON:
        self._record("item_update", item, replace=replace)
        return {"success": True}

    def item_move(self, *, uid=None, pos_dest=None) -> JSON:
        self._record("item_move", uid=uid, pos_dest=pos_dest)
        return {"success": True}

    def item_remove(self, *, uid=None) -> JSON:
        self._record("item_remove", uid=uid)
        return {"success": True}

    def item_execute(self, item) -> JSON:
        self._record("item_execute", item)
        return {"success": True}

    def queue_start(self) -> JSON:
        self._record("queue_start")
        return {"success": True}

    def queue_stop(self) -> JSON:
        self._record("queue_stop")
        return {"success": True}

    def queue_stop_cancel(self) -> JSON:
        self._record("queue_stop_cancel")
        return {"success": True}

    def queue_clear(self) -> JSON:
        self._record("queue_clear")
        return {"success": True}

    def queue_mode_set(self, **kwargs: Any) -> JSON:
        self._record("queue_mode_set", **kwargs)
        return {"success": True}

    def re_pause(self, option=None) -> JSON:
        self._record("re_pause", option)
        return {"success": True}

    def re_resume(self) -> JSON:
        self._record("re_resume")
        return {"success": True}

    def re_stop(self) -> JSON:
        self._record("re_stop")
        return {"success": True}

    def re_abort(self) -> JSON:
        self._record("re_abort")
        return {"success": True}

    def re_halt(self) -> JSON:
        self._record("re_halt")
        return {"success": True}

    def environment_open(self) -> JSON:
        self._record("environment_open")
        return {"success": True}

    def environment_close(self) -> JSON:
        self._record("environment_close")
        return {"success": True}

    def function_execute(self, item: JSON, *, run_in_background: bool = False) -> JSON:
        self._record("function_execute", item, run_in_background=run_in_background)
        return {"success": True, "task_uid": "task-1"}

    def wait_for_completed_task(self, task_uid: str, *, timeout: float = 60) -> Any:
        self._record("wait_for_completed_task", task_uid)
        return {task_uid: "completed"}

    def task_result(self, task_uid: str) -> JSON:
        self._record("task_result", task_uid)
        return {"success": True, "result": {"task_uid": task_uid, **self.task_reply}}

    def close(self) -> None:
        self.closed = True


@dataclass
class RecordingBus:
    """An ``EventPublisher`` that just keeps what was published."""

    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)

    def of_type[E](self, event_type: type[E]) -> list[E]:
        return [e for e in self.events if isinstance(e, event_type)]
