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


def init_experiment(
    source: Path,
    kind: str,
    label: str,
    experiment_dir: Path,
    frame_interval: int = 5,
    max_frames: int | None = None,
) -> dict[str, Any]:
    if kind not in {"video", "image-set"}:
        raise ValueError("kind must be 'video' or 'image-set'")
    if label not in {"laser", "control"}:
        raise ValueError("label must be 'laser' or 'control'")
    if frame_interval < 1:
        raise ValueError("frame_interval must be >= 1")
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be >= 1 when provided")

    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    manifest = load_or_create_manifest(experiment_dir)
    source_id = f"src-{uuid.uuid4().hex[:10]}"
    capture_id = f"cap-{uuid.uuid4().hex[:10]}"
    capture_dir = ensure_dir(experiment_dir / "frames" / capture_id)

    if kind == "image-set":
        frame_records, source_hash = _ingest_image_set(
            source=source,
            experiment_dir=experiment_dir,
            capture_dir=capture_dir,
            capture_id=capture_id,
            max_frames=max_frames,
        )
    else:
        frame_records, source_hash = _ingest_video(
            source=source,
            experiment_dir=experiment_dir,
            capture_dir=capture_dir,
            capture_id=capture_id,
            frame_interval=frame_interval,
            max_frames=max_frames,
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
    }
    capture_record = {
        "capture_id": capture_id,
        "source_id": source_id,
        "kind": kind,
        "label": label,
        "frames": frame_records,
        "created_at": utc_now_iso(),
    }

    manifest["sources"].append(source_record)
    manifest["captures"].append(capture_record)
    manifest["frame_sampling"]["frame_interval"] = frame_interval
    manifest["frame_sampling"]["max_frames"] = max_frames
    write_manifest(experiment_dir, manifest)
    return manifest


def _ingest_image_set(
    source: Path,
    experiment_dir: Path,
    capture_dir: Path,
    capture_id: str,
    max_frames: int | None,
) -> tuple[list[dict[str, Any]], str]:
    images = list_images(source)
    if max_frames is not None:
        images = images[:max_frames]
    source_hash = directory_fingerprint(images)
    records = []
    for index, image_path in enumerate(images):
        suffix = image_path.suffix.lower() or ".png"
        destination = capture_dir / f"frame_{index:06d}{suffix}"
        frame_hash = copy_with_hash(image_path, destination)
        records.append(
            {
                "frame_id": f"{capture_id}-frame-{index:06d}",
                "frame_index": index,
                "timestamp_ms": None,
                "path": relative_to(destination, experiment_dir),
                "source_sha256": frame_hash,
                "synthetic": False,
            }
        )
    return records, source_hash


def _ingest_video(
    source: Path,
    experiment_dir: Path,
    capture_dir: Path,
    capture_id: str,
    frame_interval: int,
    max_frames: int | None,
) -> tuple[list[dict[str, Any]], str]:
    try:
        import cv2
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
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % frame_interval == 0:
                destination = capture_dir / f"frame_{saved_index:06d}.png"
                if not cv2.imwrite(str(destination), frame):
                    raise RuntimeError(f"Failed to write extracted frame: {destination}")
                timestamp_ms = None if fps <= 0 else int((frame_index / fps) * 1000)
                records.append(
                    {
                        "frame_id": f"{capture_id}-frame-{saved_index:06d}",
                        "frame_index": frame_index,
                        "timestamp_ms": timestamp_ms,
                        "path": relative_to(destination, experiment_dir),
                        "source_sha256": sha256_file(destination),
                        "synthetic": False,
                    }
                )
                saved_index += 1
                if max_frames is not None and saved_index >= max_frames:
                    break
            frame_index += 1
    finally:
        cap.release()

    return records, source_hash
