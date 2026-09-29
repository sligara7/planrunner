"""Finding the API key where the NSLS-II ``bsqs`` Ansible role deploys it.

On an operator workstation the role writes the queueserver's single-user API key
to ``/etc/qs_client/<queueserver hostname>`` and exports it as
``$QSERVER_HTTP_SERVER_API_KEY``. The per-host file is checked first: a
workstation served by two queueservers gets two exports of the same variable,
and only the file says which key belongs to which server.
"""

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

API_KEY_ENV = "QSERVER_HTTP_SERVER_API_KEY"
QS_CLIENT_DIR = Path("/etc/qs_client")


@dataclass(frozen=True, slots=True)
class FoundKey:
    key: str
    origin: str
    """Where it came from, for the connection bar, e.g. ``/etc/qs_client/host``."""


class KeySource(Protocol):
    def find(self, server_uri: str) -> FoundKey | None: ...


class QsClientKeyFile:
    """``<directory>/<hostname of the server>``, as written by the bsqs client tasks."""

    def __init__(self, directory: Path = QS_CLIENT_DIR) -> None:
        self._directory = directory

    def find(self, server_uri: str) -> FoundKey | None:
        host = urlsplit(server_uri if "://" in server_uri else f"//{server_uri}").hostname
        if not host:
            return None
        path = self._directory / host
        try:
            key = path.read_text().strip()
        except FileNotFoundError:
            return None
        except OSError as ex:  # e.g. present but readable only by the operator account
            logger.info("Cannot read %s: %s", path, ex)
            return None
        return FoundKey(key, str(path)) if key else None


class EnvironmentKey:
    def __init__(self, environ: Mapping[str, str] = os.environ, name: str = API_KEY_ENV) -> None:
        self._environ = environ
        self._name = name

    def find(self, server_uri: str) -> FoundKey | None:
        key = self._environ.get(self._name, "").strip()
        return FoundKey(key, f"${self._name}") if key else None


class KeyFinder:
    """Tries each source in order; a key the user typed always wins."""

    def __init__(self, sources: Sequence[KeySource]) -> None:
        self._sources = sources

    def find(self, server_uri: str, typed: str = "") -> FoundKey | None:
        if typed.strip():
            return FoundKey(typed.strip(), "typed in")
        for source in self._sources:
            if found := source.find(server_uri):
                return found
        return None


def default_key_finder() -> KeyFinder:
    return KeyFinder([QsClientKeyFile(), EnvironmentKey()])
