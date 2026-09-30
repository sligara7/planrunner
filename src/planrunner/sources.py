"""Find a plan's source code on this machine, for the read-only source viewer.

The queueserver does not serve plan source, so the viewer reads local checkouts:
the profile collection (plans reported with module ``__main__`` are defined in its
``startup/*.py`` files) and packages such as hextools, found under the configured
source roots or, for installed packages like bluesky, through the import system.

What is shown is the LOCAL copy. It can differ from what the server runs, which
is why the viewer always names the file it read.
"""

import ast
import importlib.util
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlanSource:
    path: Path
    first_line: int
    text: str


class SourceFinder:
    def __init__(self, roots: Sequence[Path] = ()) -> None:
        self.roots = [Path(r).expanduser() for r in roots]

    def find(self, name: str, module: str | None) -> PlanSource | None:
        if not module or module == "__main__":
            return self._last_definition(name, self._profile_files())
        return self._last_definition(name, self._module_files(module))

    # --- Where to look ------------------------------------------------------------

    def _profile_files(self) -> Iterator[Path]:
        """Startup files in load order: a later definition replaces an earlier one."""
        for root in self.roots:
            startup = root / "startup" if (root / "startup").is_dir() else root
            yield from sorted(startup.glob("*.py"))

    def _module_files(self, module: str) -> Iterator[Path]:
        relative = Path(*module.split("."))
        for root in self.roots:
            for base in (root, root / "src"):
                for candidate in (base / f"{relative}.py", base / relative / "__init__.py"):
                    if candidate.is_file():
                        yield candidate
        if (installed := self._installed_file(module)) is not None:
            yield installed

    @staticmethod
    def _installed_file(module: str) -> Path | None:
        """Locate an installed module without importing it (only its top package is found)."""
        top, *rest = module.split(".")
        try:
            spec = importlib.util.find_spec(top)
        except (ImportError, ValueError):
            return None
        if spec is None or not spec.origin:
            return None
        package_dir = Path(spec.origin).parent
        if not rest:
            return Path(spec.origin)
        candidate = package_dir.joinpath(*rest[:-1], f"{rest[-1]}.py")
        return candidate if candidate.is_file() else None

    # --- Reading ------------------------------------------------------------------

    @staticmethod
    def _last_definition(name: str, files: Iterator[Path]) -> PlanSource | None:
        found: PlanSource | None = None
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                    end = node.end_lineno or node.lineno
                    lines = text.splitlines()[start - 1 : end]
                    found = PlanSource(path, start, "\n".join(lines))
        return found
