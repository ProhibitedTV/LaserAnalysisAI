"""Blind-ID-only reviewer annotations for candidate inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import load_json, utc_now_iso, write_json
from .manifest import latest_run_dir, load_manifest
from .report import build_report


REVIEW_FLAGS = {"interesting", "artifact", "ocr_hit", "persistent", "exclude"}


def save_annotation(
    experiment_dir: Path,
    blind_id: str,
    note: str = "",
    flags: list[str] | None = None,
) -> dict[str, Any]:
    experiment_dir = Path(experiment_dir)
    run_dir, run_record = _load_run(experiment_dir)
    available = {item.get("blind_id") for item in run_record.get("results", [])}
    if blind_id not in available:
        raise ValueError(f"Unknown blind candidate: {blind_id}")
    normalized_flags = sorted({str(flag) for flag in (flags or [])})
    unknown = set(normalized_flags) - REVIEW_FLAGS
    if unknown:
        raise ValueError(f"Unknown review flags: {', '.join(sorted(unknown))}")
    annotations = run_record.setdefault("review_annotations", {})
    existing = annotations.get(blind_id, {})
    record = {
        "blind_id": blind_id,
        "note": note.strip(),
        "flags": normalized_flags,
        "created_at": existing.get("created_at") or utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    annotations[blind_id] = record
    _persist_run(experiment_dir, run_dir, run_record)
    return record


def complete_review(experiment_dir: Path) -> dict[str, Any]:
    experiment_dir = Path(experiment_dir)
    run_dir, run_record = _load_run(experiment_dir)
    session = run_record.setdefault("review_session", {})
    session.update({"complete": True, "completed_at": utc_now_iso()})
    _persist_run(experiment_dir, run_dir, run_record)
    return dict(session)


def _load_run(experiment_dir: Path) -> tuple[Path, dict[str, Any]]:
    manifest = load_manifest(experiment_dir)
    run_dir = latest_run_dir(experiment_dir, manifest)
    return run_dir, load_json(run_dir / "results.json")


def _persist_run(experiment_dir: Path, run_dir: Path, run_record: dict[str, Any]) -> None:
    write_json(run_dir / "results.json", run_record)
    report = build_report(experiment_dir, run_dir, run_record)
    write_json(run_dir / "report.json", report)
