"""User preferences, stored as JSON the way ScriptRunner stores its config."""

import json
import logging
import platform
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def default_config_path() -> Path:
    home = Path.home()
    match platform.system():
        case "Windows":
            return home / "AppData/Roaming/PlanRunner/planrunner_config.json"
        case "Darwin":
            return home / "Library/Application Support/PlanRunner/planrunner_config.json"
        case _:
            return home / ".planrunner/planrunner_config.json"


class JsonConfigStore:
    """A ``ConfigStore`` backed by one JSON file. ``save`` merges into what is there."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> Mapping[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable config file %s", self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: Mapping[str, Any]) -> None:
        merged = {**self.load(), **data}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(merged, indent=2))
        except OSError:
            logger.warning("Could not save config file %s", self.path, exc_info=True)
