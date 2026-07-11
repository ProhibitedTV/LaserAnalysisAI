"""Source ingestion for image sets and videos."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .artifacts import (
    copy_with_hash,
    directory_fingerprint,
    ensure_dir,
    list_images,
    relative_to,
    sha256_file,
    utc_now_iso,
)
from .manifest import load_or_create_manifest, write_manifest
from .provenance import inspect_source, provenance_warnings
from .sampling import DuplicateTracker, frame_signature, resolve_sampling_plan, scene_change_score


CAPTURE_ROLES = {"laser", "control", "matched_control", "sensor_noise", "synthetic_positive", "synthetic_negative"}


def init_experiment(
    source: Path,
    kind: str,
    label: str,
    experiment_dir: Path,
    frame_interval: int | None = None,
    max_frames: int | None = None,
    capture_metadata: dict[str, Any] | None = None,
    sampling_profile: str = "baseline",
    sampling_mode: str | None = None,
    deduplicate: bool | None = None,
    scene_change_threshold: float | None = None,
) -> dict[str, Any]:
    if kind not in {"video", "image-set"}:
        raise ValueError("kind must be 'video' or 'image-set'")
    if label not in CAPTURE_ROLES:
        raise ValueError(f"label must be one of: {', '.join(sorted(CAPTURE_ROLES))}")
    sampling_plan = resolve_sampling_plan(
        profile=sampling_profile,
        mode=sampling_mode,
        frame_interval=frame_interval,
        max_frames=max_frames,
        deduplicate=deduplicate,
        scene_change_threshold=scene_change_threshold,
    )

    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    manifest = load_or_create_manifest(experiment_dir)
    if manifest.get("outputs", {}).get("review_state") == "blinded":
        raise ValueError("The latest review is still blinded. Explicitly unblind it before changing captures.")
    source_id = f"src-{uuid.uuid4().hex[:10]}"
    capture_id = f"cap-{uuid.uuid4().hex[:10]}"
    capture_dir = ensure_dir(experiment_dir / "frames" / capture_id)

    media_metadata = inspect_source(source, kind)
    metadata = dict(capture_metadata or {})
    warnings = provenance_warnings(metadata, media_metadata)

    if kind == "image-set":
        frame_records, source_hash, sampling_diagnostics = _ingest_image_set(
            source=source,
            experiment_dir=experiment_dir,
            capture_dir=capture_dir,
            capture_id=capture_id,
            sampling_plan=sampling_plan,
        )
    else:
        frame_records, source_hash, sampling_diagnostics = _ingest_video(
            source=source,
            experiment_dir=experiment_dir,
            capture_dir=capture_dir,
            capture_id=capture_id,
            sampling_plan=sampling_plan,
        )

    if not frame_records:
        raise ValueError(f"No frames were ingested from {source}")

    source_record = {
        "source_id": source_id,
        "path": str(source),
        "kind": kind,
        "label": label,
        "sha256": source_hash,
        "created_at": utc_now_iso(),
        "metadata": metadata,
        "media_metadata": media_metadata,
        "provenance_warnings": warnings,
    }
    capture_record = {
        "capture_id": capture_id,
        "source_id": source_id,
        "kind": kind,
        "label": label,
        "frames": frame_records,
        "created_at": utc_now_iso(),
        "metadata": metadata,
        "media_metadata": media_metadata,
        "provenance_warnings": warnings,
        "sampling": sampling_diagnostics,
    }

    manifest["sources"].append(source_record)
    manifest["captures"].append(capture_record)
    manifest["frame_sampling"].update(sampling_plan)
    manifest.setdefault("validation_warnings", []).append(
        {"capture_id": capture_id, "source_id": source_id, "warnings": warnings}
    )
    write_manifest(experiment_dir, manifest)
    return manifest


def _ingest_image_set(
    source: Path,
    experiment_dir: Path,
    capture_dir: Path,
    capture_id: str,
    sampling_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    import cv2
    import numpy as np

    images = list_images(source)
    source_hash = directory_fingerprint(images)
    records = []
    skipped_duplicates = []
    tracker = DuplicateTracker()
    previous_scene = None
    for source_index, image_path in enumerate(images):
        if sampling_plan["mode"] == "interval" and source_index % sampling_plan["frame_interval"] != 0:
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        if sampling_plan["mode"] == "scene_change":
            change = scene_change_score(previous_scene, image)
            if records and change < sampling_plan["scene_change_threshold"]:
                continue
            previous_scene = image
        signature = frame_signature(image)
        mean_intensity = float(np.mean(image))
        duplicate = tracker.match(signature, mean_intensity) if sampling_plan["deduplicate"] else None
        if duplicate:
            skipped_duplicates.append(
                {"source_index": source_index, "duplicate_of": duplicate.frame_id, "signature_distance": duplicate.distance, "mean_difference": round(duplicate.mean_difference, 6)}
            )
            continue
        index = len(records)
        suffix = image_path.suffix.lower() or ".png"
        destination = capture_dir / f"frame_{index:06d}{suffix}"
        frame_hash = copy_with_hash(image_path, destination)
        frame_id = f"{capture_id}-frame-{index:06d}"
        tracker.add(frame_id, signature, mean_intensity)
        records.append(
            {
                "frame_id": frame_id,
                "frame_index": source_index,
                "timestamp_ms": None,
                "path": relative_to(destination, experiment_dir),
                "source_sha256": frame_hash,
                "input_source_sha256": source_hash,
                "output_sha256": frame_hash,
                "frame_signature": signature,
                "mean_intensity": round(mean_intensity, 6),
                "extraction_settings": dict(sampling_plan),
                "synthetic": False,
            }
        )
        if sampling_plan["max_frames"] is not None and len(records) >= sampling_plan["max_frames"]:
            break
    return records, source_hash, _sampling_diagnostics(sampling_plan, len(images), records, skipped_duplicates)


def _ingest_video(
    source: Path,
    experiment_dir: Path,
    capture_dir: Path,
    capture_id: str,
    sampling_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Video ingestion requires opencv-python.") from exc

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError(f"Could not open video source: {source}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    source_hash = sha256_file(source)
    records: list[dict[str, Any]] = []
    frame_index = 0
    saved_index = 0
    decoded_frames = 0
    skipped_duplicates = []
    tracker = DuplicateTracker()
    previous_scene = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            decoded_frames += 1
            should_sample = sampling_plan["mode"] in {"all_frames", "capped_all_frames"}
            if sampling_plan["mode"] == "interval":
                should_sample = frame_index % sampling_plan["frame_interval"] == 0
            elif sampling_plan["mode"] == "scene_change":
                should_sample = scene_change_score(previous_scene, frame) >= sampling_plan["scene_change_threshold"]
            if should_sample:
                signature = frame_signature(frame)
                mean_intensity = float(np.mean(frame))
                duplicate = tracker.match(signature, mean_intensity) if sampling_plan["deduplicate"] else None
                if duplicate:
                    skipped_duplicates.append(
                        {"frame_index": frame_index, "duplicate_of": duplicate.frame_id, "signature_distance": duplicate.distance, "mean_difference": round(duplicate.mean_difference, 6)}
                    )
                    frame_index += 1
                    continue
                destination = capture_dir / f"frame_{saved_index:06d}.png"
                if not cv2.imwrite(str(destination), frame):
                    raise RuntimeError(f"Failed to write extracted frame: {destination}")
                timestamp_ms = None if fps <= 0 else int((frame_index / fps) * 1000)
                frame_id = f"{capture_id}-frame-{saved_index:06d}"
                output_hash = sha256_file(destination)
                tracker.add(frame_id, signature, mean_intensity)
                records.append(
                    {
                        "frame_id": frame_id,
                        "frame_index": frame_index,
                        "timestamp_ms": timestamp_ms,
                        "path": relative_to(destination, experiment_dir),
                        "source_sha256": output_hash,
                        "input_source_sha256": source_hash,
                        "output_sha256": output_hash,
                        "frame_signature": signature,
                        "mean_intensity": round(mean_intensity, 6),
                        "extraction_settings": dict(sampling_plan),
                        "synthetic": False,
                    }
                )
                previous_scene = frame
                saved_index += 1
                if sampling_plan["max_frames"] is not None and saved_index >= sampling_plan["max_frames"]:
                    break
            frame_index += 1
    finally:
        cap.release()

    return records, source_hash, _sampling_diagnostics(sampling_plan, decoded_frames, records, skipped_duplicates)


def _sampling_diagnostics(
    plan: dict[str, Any],
    available_frames: int,
    records: list[dict[str, Any]],
    skipped_duplicates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "settings": dict(plan),
        "available_frames": available_frames,
        "selected_frames": len(records),
        "duplicate_frames_skipped": len(skipped_duplicates),
        "duplicates": skipped_duplicates[:1000],
    }
