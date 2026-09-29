"""The threading core: dispatcher, event bus, server client and feeds."""

import threading

from fakes import FakeQueueServer, RecordingBus

from planrunner.client import ConnectionSettings, NotConnectedError, ServerClient
from planrunner.dispatch import ImmediateDispatcher, QueueDispatcher
from planrunner.events import (
    AllowedChanged,
    ConsoleText,
    EventBus,
    HistoryUpdated,
    QueueUpdated,
    ServerReachable,
    ServerUnreachable,
    StatusUpdated,
)
from planrunner.feeds import ConsoleFeed, PollingStatusFeed


def test_bus_delivers_by_type_through_dispatcher():
    dispatcher = QueueDispatcher()
    bus = EventBus(dispatcher)
    seen: list[object] = []
    unsubscribe = bus.subscribe(ConsoleText, seen.append)

    bus.publish(ConsoleText("a"))
    bus.publish(StatusUpdated({}))
    assert seen == []  # nothing runs until the UI thread drains
    dispatcher.drain()
    assert seen == [ConsoleText("a")]

    unsubscribe()
    bus.publish(ConsoleText("b"))
    dispatcher.drain()
    assert seen == [ConsoleText("a")]


def test_dispatcher_survives_a_failing_callback():
    dispatcher = QueueDispatcher()
    ran = []

    def fail() -> None:
        raise RuntimeError("boom")

    dispatcher.post(fail)
    dispatcher.post(lambda: ran.append(1))
    assert dispatcher.drain() == 2
    assert ran == [1]


class _Waiter:
    """Collects outcomes posted from the client's worker thread."""

    def __init__(self) -> None:
        self.dispatcher = QueueDispatcher()
        self.outcomes: list = []

    def done(self, outcome) -> None:
        self.outcomes.append(outcome)

    def wait(self, count: int, timeout: float = 2.0) -> None:
        event = threading.Event()
        for _ in range(int(timeout / 0.01)):
            self.dispatcher.drain()
            if len(self.outcomes) >= count:
                return
            event.wait(0.01)
        raise AssertionError(f"got {len(self.outcomes)} outcomes, wanted {count}")


def test_client_runs_calls_after_connecting():
    server = FakeQueueServer()
    waiter = _Waiter()
    client = ServerClient(waiter.dispatcher, api_factory=lambda settings: server)
    try:
        client.run(lambda api: api.queue_start(), waiter.done)
        client.connect(ConnectionSettings(uri="http://x"), waiter.done)
        client.run(lambda api: api.queue_start(), waiter.done)
        waiter.wait(3)
    finally:
        client.shutdown()

    not_connected, connected, started = waiter.outcomes
    assert isinstance(not_connected.error, NotConnectedError)
    assert connected.ok and connected.value is server
    assert started.ok
    assert server.called("queue_start")
    assert server.closed  # shutdown closes the connection


def test_client_reports_failed_connection_and_closes_it():
    server = FakeQueueServer(fail_with=ConnectionError("refused"))
    waiter = _Waiter()
    client = ServerClient(waiter.dispatcher, api_factory=lambda settings: server)
    try:
        client.connect(ConnectionSettings(uri="http://x"), waiter.done)
        waiter.wait(1)
    finally:
        client.shutdown()
    assert isinstance(waiter.outcomes[0].error, ConnectionError)
    assert server.closed


def test_status_feed_fetches_only_what_changed():
    server = FakeQueueServer(
        status_reply={"plan_queue_uid": "q1", "plan_history_uid": "h1",
                      "plans_allowed_uid": "p1", "devices_allowed_uid": "d1"},
        queue_reply={"items": [{"name": "count"}], "running_item": {}},
    )
    bus = RecordingBus()
    feed = PollingStatusFeed(bus)

    feed.poll_once(server)
    feed.poll_once(server)

    assert len(bus.of_type(StatusUpdated)) == 2
    assert len(bus.of_type(QueueUpdated)) == 1
    assert bus.of_type(QueueUpdated)[0] == QueueUpdated(None, ({"name": "count"},))
    assert len(bus.of_type(HistoryUpdated)) == 1
    assert len(bus.of_type(AllowedChanged)) == 1
    assert len(bus.of_type(ServerReachable)) == 1

    server.status_reply["plan_queue_uid"] = "q2"
    feed.poll_once(server)
    assert len(bus.of_type(QueueUpdated)) == 2


def test_status_feed_reports_reachability_transitions_once():
    server = FakeQueueServer(fail_with=ConnectionError("down"))
    bus = RecordingBus()
    feed = PollingStatusFeed(bus)
    feed.poll_once(server)
    feed.poll_once(server)
    assert bus.of_type(ServerUnreachable) == [ServerUnreachable("down")]

    server.fail_with = None
    feed.poll_once(server)
    assert len(bus.of_type(ServerReachable)) == 1


def test_status_feed_is_read_only():
    server = FakeQueueServer(status_reply={"plan_queue_uid": "q"})
    feed = PollingStatusFeed(RecordingBus())
    feed.poll_once(server)
    assert {name for name, _, _ in server.calls} <= {
        "status", "queue_get", "history_get", "plans_allowed", "devices_allowed"
    }


def test_console_feed_publishes_messages():
    server = FakeQueueServer()
    server.monitor.messages = [{"time": 1.0, "msg": "hello\n"}]
    bus = RecordingBus()
    feed = ConsoleFeed(bus)
    feed.read_once(server)
    feed.read_once(server)  # nothing left: a timeout, not an event
    assert bus.of_type(ConsoleText) == [ConsoleText("hello\n")]


def test_console_feed_start_stop_toggles_monitor():
    server = FakeQueueServer()
    feed = ConsoleFeed(EventBus(ImmediateDispatcher()), wait=0.01)
    feed.start(server)
    assert server.monitor.enabled
    feed.stop()
    assert not server.monitor.enabled
