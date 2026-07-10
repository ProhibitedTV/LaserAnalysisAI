"""GUI-safe facade over the LaserLab engine."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .artifacts import load_json
from .ingest import init_experiment
from .manifest import latest_run_dir, load_manifest, load_or_create_manifest, write_manifest
from .pipeline import run_experiment
from .report import build_report


def create_experiment(experiment_dir: Path) -> dict[str, Any]:
    """Create or open an experiment manifest."""
    manifest = load_or_create_manifest(Path(experiment_dir))
    write_manifest(Path(experiment_dir), manifest)
    return manifest


def add_capture(
    experiment_dir: Path,
    source: Path,
    kind: str,
    label: str,
    all_frames: bool = False,
    frame_interval: int = 5,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Ingest a video or image set into an experiment."""
    return init_experiment(
        source=Path(source),
        kind=kind,
        label=label,
        experiment_dir=Path(experiment_dir),
        frame_interval=1 if all_frames else frame_interval,
        max_frames=max_frames,
    )


def run_analysis(experiment_dir: Path, profile: str = "baseline", blind_seed: int = 1) -> dict[str, Any]:
    """Run the blinded analysis pipeline and return the run record."""
    return run_experiment(Path(experiment_dir), profile_name=profile, blind_seed=blind_seed)


def load_latest_report(experiment_dir: Path) -> dict[str, Any]:
    """Load the latest run report and attach useful local artifact paths."""
    experiment_dir = Path(experiment_dir)
    manifest = load_manifest(experiment_dir)
    run_dir = latest_run_dir(experiment_dir, manifest)
    results_path = run_dir / "results.json"
    report_path = run_dir / "report.json"
    if not report_path.exists():
        run_record = load_json(results_path)
        report = build_report(experiment_dir, run_dir, run_record)
    else:
        report = load_json(report_path)
    report["local_paths"] = {
        "run_dir": str(run_dir),
        "results_json": str(results_path),
        "report_json": str(report_path),
        "report_html": str(run_dir / "report.html"),
    }
    return report


def export_candidates_csv(experiment_dir: Path, output_path: Path) -> Path:
    """Export the latest report's top candidates to CSV."""
    report = load_latest_report(Path(experiment_dir))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "blind_id",
        "sample_id",
        "unblinded_label",
        "structure_score",
        "persistence_score",
        "preprocessing_variant",
        "ocr_confidence",
        "ocr_text",
        "source_path",
        "frame_index",
        "control_type",
        "processed_path",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, item in enumerate(report.get("top_candidates", []), 1):
            writer.writerow(
                {
                    "rank": rank,
                    "blind_id": item.get("blind_id", ""),
                    "sample_id": item.get("sample_id", ""),
                    "unblinded_label": item.get("unblinded_label", ""),
                    "structure_score": item.get("structure_score", ""),
                    "persistence_score": item.get("persistence_score", ""),
                    "preprocessing_variant": item.get("preprocessing_variant", ""),
                    "ocr_confidence": item.get("ocr_confidence", ""),
                    "ocr_text": item.get("ocr_text", ""),
                    "source_path": item.get("source_path", ""),
                    "frame_index": item.get("frame_index", ""),
                    "control_type": item.get("control_type", ""),
                    "processed_path": item.get("processed_path", ""),
                }
            )
    return output_path
