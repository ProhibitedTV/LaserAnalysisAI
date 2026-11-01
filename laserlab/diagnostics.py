"""Privacy-preserving diagnostics and support logging for LaserLab."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from . import __version__
from .runtime import resource_path


DIAGNOSTIC_SCHEMA = "laserlab.diagnostics"
DIAGNOSTIC_SCHEMA_VERSION = 1
PATH_REDACTION_VERSION = "filesystem-paths-v2"
SUPPORT_LOG_BYTES = 256 * 1024
_LOGGER_NAME = "laserlab"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "numpy": ("numpy",),
    "opencv": (
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
    ),
    "PyQt5": ("PyQt5",),
    "pytesseract": ("pytesseract",),
}


def get_state_dir() -> Path:
    """Return the platform-appropriate per-user LaserLab state directory."""

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "LaserLab"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LaserLab"
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "laserlab"


def get_log_path() -> Path:
    """Return the default rotating application log path without creating it."""

    return get_state_dir() / "logs" / "laserlab.log"


class _RedactingFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        return _redact_text(super().format(record))


def configure_logging(
    log_path: str | os.PathLike[str] | None = None,
    *,
    level: int = logging.INFO,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
    install_hook: bool = True,
) -> logging.Logger:
    """Configure LaserLab's rotating, path-redacting application log."""

    path = Path(log_path) if log_path is not None else get_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    resolved = str(path.resolve())
    managed_handler: RotatingFileHandler | None = None
    for handler in list(logger.handlers):
        if not getattr(handler, "_laserlab_managed", False):
            continue
        if getattr(handler, "baseFilename", None) == resolved:
            managed_handler = handler
        else:
            logger.removeHandler(handler)
            handler.close()

    if managed_handler is None:
        managed_handler = RotatingFileHandler(
            path,
            maxBytes=max(1, int(max_bytes)),
            backupCount=max(0, int(backup_count)),
            encoding="utf-8",
        )
        managed_handler._laserlab_managed = True  # type: ignore[attr-defined]
        logger.addHandler(managed_handler)

    managed_handler.setLevel(level)
    managed_handler.setFormatter(
        _RedactingFormatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    )
    if install_hook:
        install_exception_hook(logger)
    return logger


def install_exception_hook(logger: logging.Logger | None = None) -> Callable[..., Any]:
    """Log uncaught exceptions and retain the behavior of the previous hook."""

    logger = logger or logging.getLogger(_LOGGER_NAME)
    current = sys.excepthook
    if getattr(current, "_laserlab_exception_hook", False):
        return current

    previous = current

    def laserlab_exception_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if not issubclass(exc_type, KeyboardInterrupt):
                logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, traceback))
        finally:
            previous(exc_type, exc_value, traceback)

    laserlab_exception_hook._laserlab_exception_hook = True  # type: ignore[attr-defined]
    laserlab_exception_hook._laserlab_previous_hook = previous  # type: ignore[attr-defined]
    sys.excepthook = laserlab_exception_hook
    return laserlab_exception_hook


def collect_diagnostics(experiment_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Collect a JSON-safe support record without reading experiment contents."""

    record: dict[str, Any] = {
        "schema": DIAGNOSTIC_SCHEMA,
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "timestamp_utc": _utc_now(),
        "laserlab_version": __version__,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "entrypoint": _entrypoint_kind(),
            "platform": platform.platform(),
            "machine": platform.machine() or "unknown",
        },
        "dependencies": {name: _dependency_record(distributions) for name, distributions in _DEPENDENCIES.items()},
        "ocr": {
            "optional": True,
            "required_for_core_analysis": False,
            "tesseract": _tesseract_record(),
        },
        "fixtures": _fixture_record(),
        "experiment": _experiment_record(experiment_dir),
        "privacy": {
            "paths_redacted": True,
            "path_redaction_version": PATH_REDACTION_VERSION,
            "manifest_read": False,
            "source_media_included": False,
        },
    }
    redacted = _redact_value(record)
    json.dumps(redacted, allow_nan=False)
    return redacted


def export_support_bundle(
    output_path: str | os.PathLike[str],
    experiment_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Write a deterministic, media-free support ZIP."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = collect_diagnostics(experiment_dir)
    diagnostic_bytes = (
        json.dumps(diagnostics, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")

    members: list[tuple[str, bytes]] = [("diagnostics.json", diagnostic_bytes)]
    log_path = get_log_path()
    try:
        if log_path.is_file():
            recent_log = _read_recent_log(log_path)
            if recent_log:
                members.append(("laserlab.log", _redact_text(recent_log).encode("utf-8")))
    except OSError:
        pass

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, content in sorted(members):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            bundle.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return destination


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _entrypoint_kind() -> str:
    if not bool(getattr(sys, "frozen", False)):
        return "source"
    executable_name = Path(sys.executable).stem.lower()
    return "cli" if executable_name.endswith("cli") else "gui"


def _dependency_record(distributions: tuple[str, ...]) -> dict[str, Any]:
    for distribution in distributions:
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
        except Exception as exc:  # pragma: no cover - package metadata backends vary
            return {"available": False, "version": None, "status": "probe_failed", "failure": type(exc).__name__}
        return {"available": True, "version": str(version), "status": "available"}
    return {"available": False, "version": None, "status": "unavailable"}


def _tesseract_record() -> dict[str, Any]:
    executable = shutil.which("tesseract")
    if not executable:
        return {"available": False, "version": None, "status": "unavailable", "failure": "executable not found"}
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "version": None, "status": "probe_failed", "failure": "version probe timed out"}
    except Exception as exc:
        return {"available": False, "version": None, "status": "probe_failed", "failure": type(exc).__name__}

    output = (result.stdout or result.stderr or "").strip().splitlines()
    if result.returncode != 0:
        return {
            "available": False,
            "version": None,
            "status": "probe_failed",
            "failure": f"version probe exited with code {result.returncode}",
        }
    version = output[0].strip() if output else "unknown"
    return {"available": True, "version": version, "status": "available", "failure": None}


def _fixture_record() -> dict[str, Any]:
    try:
        from .fixtures import FIXTURE_CATALOG, validate_fixture_catalog

        media_dir = _fixture_media_dir()
        redistributable = [item for item in FIXTURE_CATALOG if item.get("redistributable")]
        present_count = sum(
            1 for item in redistributable if item.get("filename") and (media_dir / str(item["filename"])).is_file()
        )
        errors = validate_fixture_catalog(media_dir, require_bundled_files=True)
        return {
            "catalog_count": len(FIXTURE_CATALOG),
            "redistributable_count": len(redistributable),
            "bundled_file_count": present_count,
            "bundled_manifest_present": (media_dir / "fixture_manifest.json").is_file(),
            "catalog_valid": not errors,
            "validation_error_count": len(errors),
            "validation_errors": errors,
        }
    except Exception as exc:
        return {
            "catalog_count": 0,
            "redistributable_count": 0,
            "bundled_file_count": 0,
            "bundled_manifest_present": False,
            "catalog_valid": False,
            "validation_error_count": 1,
            "validation_errors": [f"fixture validation failed: {type(exc).__name__}"],
        }


def _fixture_media_dir() -> Path:
    return resource_path("sample_media")


def _experiment_record(experiment_dir: str | os.PathLike[str] | None) -> dict[str, Any]:
    if experiment_dir is None:
        return {"provided": False, "exists": False, "manifest_present": False}
    try:
        path = Path(experiment_dir).expanduser()
        return {
            "provided": True,
            "exists": path.exists(),
            "manifest_present": (path / "manifest.json").is_file() if path.is_dir() else False,
        }
    except (OSError, TypeError, ValueError):
        return {"provided": True, "exists": False, "manifest_present": False, "status": "probe_failed"}


def _read_recent_log(path: Path, limit: int = SUPPORT_LOG_BYTES) -> str:
    with path.open("rb") as handle:
        size = path.stat().st_size
        if size > limit:
            handle.seek(size - limit)
            handle.readline()
        return handle.read(limit).decode("utf-8", errors="replace")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {_redact_text(str(key)): _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _redact_text(value: str) -> str:
    # Preserve useful root categories, but never retain private descendants.
    roots = _redaction_roots()

    def path_label(path: str) -> str:
        marker = re.match(r"<(HOME|TEMP|INSTALL|PATH)>", path)
        if marker:
            return marker.group()
        normalized = path.replace("\\", "/").casefold()
        for root, replacement in roots:
            root = root.replace("\\", "/").rstrip("/").casefold()
            if normalized == root or normalized.startswith(root + "/"):
                return replacement
        return "<PATH>"

    # Respect escaped quotes in Python exception repr and JSON log strings.
    # Also sanitize older masked roots without retaining their descendants.
    start = r"(?:[A-Za-z]:[\\/]|\\\\|/|<(?:HOME|TEMP|INSTALL|PATH)>)"
    redacted = re.sub(
        rf"(?P<quote>[\"'])(?P<path>{start}(?:\\[^\r\n]|(?!(?P=quote))[^\r\n])*)(?P=quote)",
        lambda match: match["quote"] + path_label(match["path"]) + match["quote"],
        str(value),
    )
    # Unquoted paths have no reliable end boundary: spaces, apostrophes and '='
    # can all occur in names. Consume the rest of that line rather than guess;
    # error classes and context on surrounding lines remain available.
    tail = r"[^\r\n]*"
    redacted = re.sub(
        rf"(?i)(?<![A-Za-z0-9:/])(?:[A-Z]:[\\/]|\\\\|/|<(?:HOME|TEMP|INSTALL)>[\\/]|<PATH>[ \\/]){tail}",
        lambda match: path_label(match.group()), redacted,
    )
    return redacted


def _redaction_roots() -> list[tuple[str, str]]:
    candidates: list[tuple[Path, str]] = []
    try:
        candidates.append((Path(__file__).resolve().parents[1], "<INSTALL>"))
    except OSError:
        pass
    for raw, replacement in (
        (getattr(sys, "_MEIPASS", None), "<INSTALL>"),
        (getattr(sys, "prefix", None), "<INSTALL>"),
        (getattr(sys, "base_prefix", None), "<INSTALL>"),
        (Path(sys.executable).parent if sys.executable else None, "<INSTALL>"),
        (tempfile.gettempdir(), "<TEMP>"),
        (Path.home(), "<HOME>"),
    ):
        if raw:
            candidates.append((Path(raw), replacement))

    unique: dict[str, str] = {}
    for path, replacement in candidates:
        raw_text = str(path.expanduser())
        try:
            resolved_text = str(path.expanduser().resolve())
        except (OSError, RuntimeError):
            resolved_text = raw_text
        for text in (raw_text, resolved_text):
            if len(text) > 2:
                unique[text] = replacement
    return sorted(unique.items(), key=lambda item: len(item[0]), reverse=True)


__all__ = [
    "collect_diagnostics",
    "configure_logging",
    "export_support_bundle",
    "get_log_path",
    "get_state_dir",
    "install_exception_hook",
]
