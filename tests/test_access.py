"""Permissions from scopes, API key discovery, and lock display."""

import os

from planrunner.credentials import EnvironmentKey, FoundKey, KeyFinder, QsClientKeyFile
from planrunner.permissions import Permissions
from planrunner.status_text import StatusField, Tone, controls_for, status_fields

PAUSED = {"manager_state": "paused", "worker_environment_exists": True, "items_in_queue": 2}
IDLE = {"manager_state": "idle", "worker_environment_exists": True, "items_in_queue": 2}


def test_anonymous_scopes_are_read_only():
    allowed = Permissions.from_scopes(["read:status", "read:queue", "read:console"])
    assert allowed.read_only
    assert controls_for(IDLE, allowed) == controls_for(None)


def test_single_user_scopes_allow_control():
    allowed = Permissions.from_scopes([
        "write:queue:edit", "write:queue:control", "write:plan:control",
        "write:manager:control", "write:execute",
    ])
    assert not allowed.read_only
    assert controls_for(PAUSED, allowed).abort
    assert controls_for(IDLE, allowed).start


def test_each_control_follows_its_own_scope():
    allowed = Permissions.from_scopes(["write:queue:edit"])
    controls = controls_for(PAUSED, allowed)
    assert controls.edit_queue
    assert not (controls.resume or controls.abort or controls.set_loop)


def test_key_file_named_after_server_host_wins(tmp_path):
    (tmp_path / "xf27id1-hex-qs1.nsls2.bnl.gov").write_text("file-key\n")
    finder = KeyFinder([
        QsClientKeyFile(tmp_path),
        EnvironmentKey({"QSERVER_HTTP_SERVER_API_KEY": "env-key"}),
    ])
    found = finder.find("https://xf27id1-hex-qs1.nsls2.bnl.gov:443")
    assert found == FoundKey("file-key", str(tmp_path / "xf27id1-hex-qs1.nsls2.bnl.gov"))
    assert finder.find("http://localhost:60610") == FoundKey(
        "env-key", "$QSERVER_HTTP_SERVER_API_KEY"
    )


def test_typed_key_overrides_and_missing_key_is_none(tmp_path):
    finder = KeyFinder([QsClientKeyFile(tmp_path), EnvironmentKey({})])
    assert finder.find("http://localhost:60610") is None
    assert finder.find("http://localhost:60610", typed=" k ") == FoundKey("k", "typed in")


def test_unreadable_key_file_is_skipped(tmp_path):
    key_file = tmp_path / "host"
    key_file.write_text("secret")
    key_file.chmod(0)
    try:
        found = QsClientKeyFile(tmp_path).find("http://host:60610")
    finally:
        key_file.chmod(0o600)
    assert found is None or os.geteuid() == 0  # root can read anything


def test_locks_show_in_status_strip():
    fields = status_fields({**IDLE, "lock": {"environment": True, "queue": True}})
    assert StatusField("Locked", "environment + queue", Tone.BAD) in fields
    assert not any(f.label == "Locked" for f in status_fields(IDLE))
