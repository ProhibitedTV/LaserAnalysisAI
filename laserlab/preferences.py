"""Small, privacy-limited local preferences for LaserLab.

This module stores navigation conveniences and an explicit public-cache choice. Experiment
contents and analysis metadata belong in experiment records, not in per-user
application preferences.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_RECENT_EXPERIMENTS = 5
_PREFERENCES_FILENAME = "preferences.json"


def preferences_path() -> Path:
    """Return the default cross-platform per-user preferences file path."""

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "LaserLab" / _PREFERENCES_FILENAME


def load_preferences(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load normalized preferences, returning defaults for unusable files.

    Missing recent experiment directories are removed during normalization.
    The optional ``path`` is a preferences file path intended for callers that
    need an isolated location, including tests.
    """

    target = _target_path(path)
    try:
        with target.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return _default_preferences()

    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
        return _default_preferences()
    return _normalize_preferences(raw)


def save_preferences(
    data: Mapping[str, Any],
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Atomically persist an allow-listed preferences record.

    Unknown keys and non-string directory values are discarded. The returned
    dictionary is the exact normalized record written to disk.
    """

    if not isinstance(data, Mapping):
        raise TypeError("Preferences data must be a mapping.")

    target = _target_path(path)
    normalized = _normalize_preferences(data)
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(normalized, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return normalized


def remember_experiment(
    experiment_dir: str | os.PathLike[str],
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Move an existing experiment directory to the front of recents."""

    experiment = _directory_string(experiment_dir)
    if experiment is None:
        raise ValueError("Experiment directory must be a non-empty path.")

    data = load_preferences(path)
    recent = [
        entry
        for entry in data["recent_experiments"]
        if _path_key(entry) != _path_key(experiment)
    ]
    data["recent_experiments"] = [experiment, *recent][:MAX_RECENT_EXPERIMENTS]
    return save_preferences(data, path)


def set_last_source_directory(
    source_dir: str | os.PathLike[str],
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Store the most recently used source directory."""

    source = _directory_string(source_dir)
    if source is None:
        raise ValueError("Source directory must be a non-empty path.")

    data = load_preferences(path)
    data["last_source_directory"] = source
    return save_preferences(data, path)


def set_veilbreak_cache_enabled(enabled: bool, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Persist only an explicit boolean choice; never enable on a truthy string."""
    if type(enabled) is not bool:
        raise ValueError("The public catalog cache choice must be an explicit boolean.")
    data = load_preferences(path)
    data["veilbreak_cache_enabled"] = enabled
    return save_preferences(data, path)


def _target_path(path: str | os.PathLike[str] | None) -> Path:
    return Path(path).expanduser() if path is not None else preferences_path()


def _default_preferences() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "recent_experiments": [],
        "last_source_directory": None,
        "veilbreak_cache_enabled": False,
    }


def _normalize_preferences(data: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _default_preferences()
    recent = data.get("recent_experiments")
    if isinstance(recent, list):
        seen: set[str] = set()
        for value in recent:
            directory = _directory_string(value)
            if directory is None or not Path(directory).is_dir():
                continue
            key = _path_key(directory)
            if key in seen:
                continue
            seen.add(key)
            normalized["recent_experiments"].append(directory)
            if len(normalized["recent_experiments"]) == MAX_RECENT_EXPERIMENTS:
                break

    normalized["last_source_directory"] = _directory_string(data.get("last_source_directory"))
    normalized["veilbreak_cache_enabled"] = data.get("veilbreak_cache_enabled") is True
    return normalized


def _directory_string(value: Any) -> str | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    try:
        text = os.fspath(value).strip()
    except (TypeError, ValueError):
        return None
    if not text:
        return None
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return None


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))
