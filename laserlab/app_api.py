"""GUI-safe facade over the LaserLab engine."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

from .artifacts import load_json
from .bundle import export_review_bundle as _export_review_bundle
from .ingest import init_experiment
from .manifest import latest_run_dir, load_manifest, load_or_create_manifest, write_manifest
from .pipeline import run_experiment, unblind_latest_run as _unblind_latest_run
from .protocols import describe_protocol, list_protocol_presets as _list_protocol_presets
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
    frame_interval: int | None = None,
    max_frames: int | None = None,
    capture_metadata: dict[str, Any] | None = None,
    sampling_profile: str = "baseline",
    sampling_mode: str | None = None,
    deduplicate: bool = True,
    scene_change_threshold: float | None = None,
) -> dict[str, Any]:
    """Ingest a video or image set into an experiment."""
    return init_experiment(
        source=Path(source),
        kind=kind,
        label=label,
        experiment_dir=Path(experiment_dir),
        frame_interval=1 if all_frames else frame_interval,
        max_frames=max_frames,
        capture_metadata=capture_metadata,
        sampling_profile=sampling_profile,
        sampling_mode=("capped_all_frames" if max_frames is not None else "all_frames") if all_frames else sampling_mode,
        deduplicate=deduplicate,
        scene_change_threshold=scene_change_threshold,
    )


def run_analysis(
    experiment_dir: Path,
    profile: str = "baseline",
    blind_seed: int = 1,
    protocol: str | None = None,
    roi: dict[str, int] | None = None,
    primary_metric: str | None = None,
    preprocessing_intensity: str | None = None,
    control_generation: str | None = None,
) -> dict[str, Any]:
    """Run the blinded analysis pipeline and return the run record."""
    return run_experiment(
        Path(experiment_dir),
        profile_name=profile,
        blind_seed=blind_seed,
        protocol=protocol,
        roi=roi,
        primary_metric=primary_metric,
        preprocessing_intensity=preprocessing_intensity,
        control_generation=control_generation,
    )


def list_protocol_presets() -> list[dict[str, Any]]:
    return _list_protocol_presets()


def describe_protocol_preset(protocol_id: str) -> str:
    return describe_protocol(protocol_id)


def update_analysis_plan(
    experiment_dir: Path,
    protocol: str,
    primary_metric: str,
    preprocessing_intensity: str,
    control_generation: str,
    frame_sampling_mode: str = "interval",
    roi: dict[str, int] | None = None,
) -> dict[str, Any]:
    manifest = load_or_create_manifest(Path(experiment_dir))
    if manifest.get("outputs", {}).get("review_state") == "blinded":
        raise ValueError("The latest review is still blinded. Explicitly unblind it before changing the plan.")
    manifest["protocol"] = protocol
    manifest.setdefault("analysis_plan", {}).update(
        {
            "protocol": protocol,
            "primary_metric": primary_metric,
            "preprocessing_intensity": preprocessing_intensity,
            "control_generation": control_generation,
            "frame_sampling_mode": frame_sampling_mode,
            "roi": roi,
        }
    )
    write_manifest(Path(experiment_dir), manifest)
    return manifest


def estimate_run(
    experiment_dir: Path,
    profile: str = "baseline",
    protocol: str | None = None,
    control_generation: str | None = None,
) -> dict[str, Any]:
    manifest = load_or_create_manifest(Path(experiment_dir))
    profile_record = manifest.get("preprocessing_profiles", {}).get(profile, {})
    variants = len(profile_record.get("variants", [])) or 1
    source_frames = sum(len(capture.get("frames", [])) for capture in manifest.get("captures", []))
    control_generation = control_generation or manifest.get("analysis_plan", {}).get("control_generation", "standard")
    controls_per_laser = {"none": 0, "standard": 3, "strict": 5}.get(control_generation, 3)
    generated_controls = sum(
        len(capture.get("frames", [])) * controls_per_laser
        for capture in manifest.get("captures", [])
        if capture.get("label") == "laser"
    )
    synthetic = 1
    sample_count = source_frames + generated_controls + synthetic
    detector_records = sample_count * variants
    return {
        "protocol": protocol or manifest.get("protocol", "anomaly"),
        "profile": profile,
        "control_generation": control_generation,
        "sample_count": sample_count,
        "preprocessing_variants": variants,
        "detector_records": detector_records,
        "runtime_label": "short" if detector_records < 250 else "medium" if detector_records < 2000 else "long",
    }


def preview_source_frames(source: Path, kind: str, output_dir: Path | None = None, max_frames: int = 4) -> list[Path]:
    """Extract lightweight preview images for a source without ingesting it."""
    import cv2

    source = Path(source)
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="laserlab-preview-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    previews: list[Path] = []
    if kind == "image-set":
        from .artifacts import list_images

        for index, image_path in enumerate(list_images(source)[:max_frames]):
            destination = output_dir / f"preview_{index:02d}{image_path.suffix.lower() or '.png'}"
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is not None:
                cv2.imwrite(str(destination), image)
                previews.append(destination)
        return previews

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError(f"Could not open source for preview: {source}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, total // max(1, max_frames)) if total else 1
    frame_index = 0
    try:
        while len(previews) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % step == 0:
                destination = output_dir / f"preview_{len(previews):02d}.png"
                cv2.imwrite(str(destination), frame)
                previews.append(destination)
            frame_index += 1
    finally:
        cap.release()
    return previews


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


def unblind_latest_run(experiment_dir: Path) -> dict[str, Any]:
    """Explicitly reveal source roles and compute control statistics for the latest run."""
    _unblind_latest_run(Path(experiment_dir))
    return load_latest_report(Path(experiment_dir))


def save_review_annotation(
    experiment_dir: Path,
    blind_id: str,
    note: str = "",
    flags: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a source-safe annotation against a blinded candidate ID."""
    from .review import save_annotation

    return save_annotation(Path(experiment_dir), blind_id=blind_id, note=note, flags=flags)


def complete_review(experiment_dir: Path) -> dict[str, Any]:
    """Mark candidate inspection complete without revealing source roles."""
    from .review import complete_review as _complete_review

    return _complete_review(Path(experiment_dir))


def export_candidates_csv(experiment_dir: Path, output_path: Path) -> Path:
    """Export the latest report's top candidates to CSV."""
    report = load_latest_report(Path(experiment_dir))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    unblinded = bool(report.get("review_state", {}).get("unblinded", True))
    fields = [
        "rank",
        "blind_id",
        "sample_id",
        "primary_metric",
        "primary_metric_score",
        "structure_score",
        "persistence_score",
        "preprocessing_variant",
        "ocr_confidence",
        "ocr_text",
        "review_flags",
        "review_note",
        "q_value",
        "detector_family_scores",
        "processed_path",
    ]
    if unblinded:
        fields[3:3] = ["unblinded_label", "source_path", "frame_index", "control_type"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, item in enumerate(report.get("top_candidates", []), 1):
            record = {
                    "rank": rank,
                    "blind_id": item.get("blind_id", ""),
                    "sample_id": item.get("sample_id", ""),
                    "primary_metric": item.get("primary_metric", ""),
                    "primary_metric_score": item.get("primary_metric_score", ""),
                    "structure_score": item.get("structure_score", ""),
                    "persistence_score": item.get("persistence_score", ""),
                    "preprocessing_variant": item.get("preprocessing_variant", ""),
                    "ocr_confidence": item.get("ocr_confidence", ""),
                    "ocr_text": item.get("ocr_text", ""),
                    "review_flags": ",".join(item.get("review_annotation", {}).get("flags", [])),
                    "review_note": item.get("review_annotation", {}).get("note", ""),
                    "q_value": item.get("q_value", ""),
                    "detector_family_scores": item.get("detector_family_scores", ""),
                    "processed_path": item.get("processed_path", ""),
                }
            if unblinded:
                record.update(
                    {
                        "unblinded_label": item.get("unblinded_label", ""),
                        "source_path": item.get("source_path", ""),
                        "frame_index": item.get("frame_index", ""),
                        "control_type": item.get("control_type", ""),
                    }
                )
            writer.writerow(record)
    return output_path


def export_review_bundle(experiment_dir: Path, output_path: Path, include_media: bool = False) -> Path:
    path = _export_review_bundle(Path(experiment_dir), Path(output_path), include_media=include_media)
    manifest = load_manifest(Path(experiment_dir))
    manifest.setdefault("community_export", {})["last_bundle"] = str(path)
    manifest["community_export"]["include_media"] = include_media
    write_manifest(Path(experiment_dir), manifest)
    return path
