"""Blinded run orchestration."""

from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, relative_to, resolve_experiment_path, sha256_file, utc_now_iso, write_json
from .controls import generate_matched_controls
from .detectors import DetectorContext, run_detectors
from .manifest import load_manifest, upgrade_manifest, write_manifest
from .preprocessing import apply_profile_variants
from .protocols import get_protocol_preset
from .report import build_report
from .scientific import metric_score, phase_registration_metrics
from .stats import summarize_results
from .synthetic import create_synthetic_positive


def run_experiment(
    experiment_dir: Path,
    profile_name: str = "baseline",
    blind_seed: int = 1,
    protocol: str | None = None,
    roi: dict[str, int] | None = None,
    primary_metric: str | None = None,
    preprocessing_intensity: str | None = None,
    control_generation: str | None = None,
) -> dict[str, Any]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Running experiments requires opencv-python.") from exc

    manifest = upgrade_manifest(load_manifest(experiment_dir))
    plan = manifest.setdefault("analysis_plan", {})
    preset = get_protocol_preset(protocol or plan.get("protocol") or manifest.get("protocol"))
    protocol_id = preset["id"]
    if profile_name == "auto":
        profile_name = preset["profile"]
    primary_metric = primary_metric or plan.get("primary_metric") or preset["primary_metric"]
    roi = roi if roi is not None else plan.get("roi")
    preprocessing_intensity = preprocessing_intensity or plan.get("preprocessing_intensity", "standard")
    control_generation = control_generation or plan.get("control_generation", "standard")
    profile = manifest.get("preprocessing_profiles", {}).get(profile_name)
    if not profile:
        raise ValueError(f"Unknown preprocessing profile: {profile_name}")

    run_id = f"run-{utc_now_iso().replace(':', '').replace('-', '').replace('Z', '')}-{uuid.uuid4().hex[:8]}"
    run_dir = ensure_dir(experiment_dir / "runs" / run_id)
    manifest["blind_seed"] = blind_seed
    manifest["protocol"] = protocol_id
    plan.update(
        {
            "protocol": protocol_id,
            "roi": roi,
            "primary_metric": primary_metric,
            "preprocessing_intensity": preprocessing_intensity,
            "control_generation": control_generation,
        }
    )

    samples = _build_samples(experiment_dir, run_dir, manifest, control_generation=control_generation)
    blinded_samples = _blind_samples(samples, blind_seed)

    processed_dir = ensure_dir(run_dir / "processed")
    results: list[dict[str, Any]] = []
    masks_for_persistence: dict[tuple[str, str], list[tuple[int, str, Any]]] = {}
    previous_images: dict[tuple[str, str], Any] = {}

    for sample in blinded_samples:
        image_path = resolve_experiment_path(experiment_dir, sample["path"])
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Could not read sample image: {image_path}")
        image = _apply_roi(image, roi)

        for processed in apply_profile_variants(image, profile):
            processed_path = processed_dir / f"{sample['blind_id']}_{processed.variant_name}.png"
            cv2.imwrite(str(processed_path), processed.image)
            group_key = (sample.get("capture_id") or sample.get("parent_capture_id") or sample["sample_id"], processed.variant_name)
            registration = {"shift_x": 0.0, "shift_y": 0.0, "shift_magnitude": 0.0, "response": 0.0}
            if group_key in previous_images:
                registration = phase_registration_metrics(previous_images[group_key], processed.image)
            previous_images[group_key] = processed.image

            detector_result = run_detectors(
                processed.image,
                DetectorContext(
                    experiment_dir=experiment_dir,
                    run_dir=run_dir,
                    blind_id=sample["blind_id"],
                    variant_name=processed.variant_name,
                    original_image=image,
                ),
            )

            result_record = {
                "run_id": run_id,
                "sample_id": sample["sample_id"],
                "blind_id": sample["blind_id"],
                "blinded_label": sample["blinded_label"],
                "unblinded_label": sample["unblinded_label"],
                "capture_id": sample.get("capture_id"),
                "parent_capture_id": sample.get("parent_capture_id"),
                "frame_id": sample.get("frame_id"),
                "parent_frame_id": sample.get("parent_frame_id"),
                "control_type": sample.get("control_type"),
                "frame_index": sample.get("frame_index"),
                "timestamp_ms": sample.get("timestamp_ms"),
                "source_path": sample["path"],
                "source_sha256": sample["source_sha256"],
                "processed_path": relative_to(processed_path, experiment_dir),
                "processed_sha256": sha256_file(processed_path),
                "preprocessing_profile": profile_name,
                "preprocessing_variant": processed.variant_name,
                "preprocessing_hash": processed.profile_hash,
                "protocol": protocol_id,
                "primary_metric": primary_metric,
                "ocr": detector_result["ocr"],
                "connected_components": detector_result["connected_components"],
                "entropy_texture": detector_result["entropy_texture"],
                "edge_line_density": detector_result["edge_line_density"],
                "fft_spectrum": detector_result["fft_spectrum"],
                "speckle_contrast": detector_result["speckle_contrast"],
                "texture_features": detector_result["texture_features"],
                "frame_registration": registration,
                "detector_family_scores": detector_result["detector_family_scores"],
                "candidate_rois": detector_result["candidate_rois"],
                "structure_score": detector_result["structure_score"],
                "primary_metric_score": 0.0,
                "q_value": None,
                "persistence_score": 0.0,
            }
            result_record["primary_metric_score"] = round(float(metric_score(result_record, primary_metric)), 6)
            results.append(result_record)
            masks_for_persistence.setdefault(group_key, []).append(
                (int(sample.get("frame_index") or 0), result_record["sample_id"], processed.image)
            )

    _apply_persistence_scores(results, masks_for_persistence)
    aggregate = summarize_results(results, seed=blind_seed, primary_metric=primary_metric)
    for result in results:
        result["q_value"] = aggregate.get("candidate_q_values", {}).get(result["sample_id"])
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "experiment_id": manifest["experiment_id"],
        "profile": profile_name,
        "protocol": protocol_id,
        "analysis_plan": plan,
        "blind_seed": blind_seed,
        "samples": blinded_samples,
        "results": results,
        "aggregate_statistics": aggregate,
    }

    write_json(run_dir / "results.json", run_record)
    report = build_report(experiment_dir, run_dir, run_record)
    write_json(run_dir / "report.json", report)
    manifest["outputs"]["latest_run"] = relative_to(run_dir, experiment_dir)
    manifest["outputs"]["latest_results"] = relative_to(run_dir / "results.json", experiment_dir)
    manifest["outputs"]["latest_report_json"] = relative_to(run_dir / "report.json", experiment_dir)
    manifest["outputs"]["latest_report_html"] = relative_to(run_dir / "report.html", experiment_dir)
    write_manifest(experiment_dir, manifest)
    return run_record


def _build_samples(
    experiment_dir: Path,
    run_dir: Path,
    manifest: dict[str, Any],
    control_generation: str = "standard",
) -> list[dict[str, Any]]:
    import cv2

    samples = []
    generated_controls = []
    for capture in manifest.get("captures", []):
        for frame in capture.get("frames", []):
            samples.append(
                {
                    "sample_id": frame["frame_id"],
                    "capture_id": capture["capture_id"],
                    "frame_id": frame["frame_id"],
                    "path": frame["path"],
                    "source_sha256": frame["source_sha256"],
                    "frame_index": frame.get("frame_index"),
                    "timestamp_ms": frame.get("timestamp_ms"),
                    "unblinded_label": capture["label"],
                    "synthetic": False,
                }
            )

            if capture["label"] == "laser" and control_generation != "none":
                image_path = resolve_experiment_path(experiment_dir, frame["path"])
                image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                if image is None:
                    raise FileNotFoundError(f"Could not read frame for control generation: {image_path}")
                generated_controls.extend(
                    generate_matched_controls(experiment_dir, run_dir, capture, frame, image, level=control_generation)
                )

    samples.extend(generated_controls)
    samples.append(_synthetic_positive_sample(experiment_dir, run_dir))
    manifest["controls"] = _dedupe_controls(manifest.get("controls", []) + generated_controls)
    return samples


def _synthetic_positive_sample(experiment_dir: Path, run_dir: Path) -> dict[str, Any]:
    path = create_synthetic_positive(run_dir / "synthetic_positive" / "known_text.png", text="SIGNAL 314")
    return {
        "sample_id": "synthetic-positive-known-text",
        "path": relative_to(path, experiment_dir),
        "source_sha256": sha256_file(path),
        "frame_index": 0,
        "timestamp_ms": None,
        "unblinded_label": "synthetic_positive",
        "synthetic": True,
        "known_text": "SIGNAL 314",
    }


def _dedupe_controls(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for control in controls:
        key = control["sample_id"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(control)
    return unique


def _blind_samples(samples: list[dict[str, Any]], blind_seed: int) -> list[dict[str, Any]]:
    rng = random.Random(blind_seed)
    shuffled = [sample.copy() for sample in samples]
    rng.shuffle(shuffled)
    for index, sample in enumerate(shuffled):
        sample["blind_id"] = f"B{index + 1:06d}"
        sample["blinded_label"] = sample["blind_id"]
    return shuffled


def _apply_persistence_scores(results: list[dict[str, Any]], grouped_masks: dict[tuple[str, str], list[tuple[int, str, Any]]]) -> None:
    import cv2
    import numpy as np

    persistence_by_sample_variant: dict[tuple[str, str], float] = {}
    for (_group, variant), records in grouped_masks.items():
        ordered = sorted(records, key=lambda item: item[0])
        previous_mask = None
        previous_sample = None
        for _frame_index, sample_id, image in ordered:
            gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            mask = mask > 0
            if previous_mask is None:
                score = 0.0
            else:
                if previous_mask.shape != mask.shape:
                    previous_mask = cv2.resize(
                        previous_mask.astype("uint8"), (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST
                    ) > 0
                intersection = np.logical_and(previous_mask, mask).sum()
                union = np.logical_or(previous_mask, mask).sum()
                score = float(intersection / union) if union else 0.0
                persistence_by_sample_variant[(previous_sample, variant)] = max(
                    persistence_by_sample_variant.get((previous_sample, variant), 0.0), score
                )
            persistence_by_sample_variant[(sample_id, variant)] = max(
                persistence_by_sample_variant.get((sample_id, variant), 0.0), score
            )
            previous_mask = mask
            previous_sample = sample_id

    for result in results:
        key = (result["sample_id"], result["preprocessing_variant"])
        result["persistence_score"] = round(float(persistence_by_sample_variant.get(key, 0.0)), 6)


def _apply_roi(image: Any, roi: dict[str, int] | None) -> Any:
    if not roi:
        return image
    height, width = image.shape[:2]
    x = max(0, int(roi.get("x", 0)))
    y = max(0, int(roi.get("y", 0)))
    w = max(1, int(roi.get("width", width - x)))
    h = max(1, int(roi.get("height", height - y)))
    x1 = min(width, x + w)
    y1 = min(height, y + h)
    if x >= x1 or y >= y1:
        return image
    return image[y:y1, x:x1]
