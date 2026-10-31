"""Runtime path resolution for source checkouts and packaged applications."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_RESOURCE_ROOT_ENV = "LASERLAB_RESOURCE_ROOT"
_EXPERIMENTS_DIR_ENV = "LASERLAB_EXPERIMENTS_DIR"


def resource_path(*parts: str | os.PathLike[str]) -> Path:
    """Resolve a bundled resource without relying on the working directory.

    Existing candidates are checked in this order: an explicit environment
    override, PyInstaller's extraction directory, the frozen executable's
    directory, and the repository root. If none exists, the candidate under
    the first applicable root is returned as a deterministic fallback.
    """

    roots = _resource_roots()
    candidates = [root.joinpath(*parts) for root in roots]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def default_experiments_dir() -> Path:
    """Return the default experiment directory without creating it."""

    override = _environment_path(_EXPERIMENTS_DIR_ENV)
    if override is not None:
        return override
    if _is_frozen():
        return Path.home() / "Documents" / "LaserLab" / "experiments"
    return _repository_root() / "experiments"


def _resource_roots() -> list[Path]:
    roots: list[Path] = []

    override = _environment_path(_RESOURCE_ROOT_ENV)
    if override is not None:
        roots.append(override)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass).expanduser().resolve())

    if _is_frozen():
        roots.append(Path(sys.executable).resolve().parent)

    roots.append(_repository_root())

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique_roots.append(root)
    return unique_roots


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _repository_root() -> Path:
    return Path(__file__).resolve().parent.parent
