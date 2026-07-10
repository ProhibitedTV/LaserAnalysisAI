"""Matched control generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, relative_to, sha256_file


def generate_matched_controls(
    experiment_dir: Path,
    run_dir: Path,
    capture: dict[str, Any],
    frame: dict[str, Any],
    image: Any,
    level: str = "standard",
) -> list[dict[str, Any]]:
    import cv2
    import numpy as np

    controls_dir = ensure_dir(run_dir / "generated_controls" / frame["frame_id"])
    records = []

    gray_mean = int(np.mean(image))
    dark = np.full_like(image, gray_mean)
    records.append(_write_control(experiment_dir, controls_dir, "blank_mean", dark, capture, frame))

    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    records.append(_write_control(experiment_dir, controls_dir, "rotated", rotated, capture, frame))

    shuffled = _block_shuffle(image, block_size=32)
    records.append(_write_control(experiment_dir, controls_dir, "block_shuffle", shuffled, capture, frame))

    if level == "strict":
        noise = np.random.default_rng(20260710).normal(loc=np.mean(image), scale=np.std(image), size=image.shape)
        records.append(_write_control(experiment_dir, controls_dir, "noise_matched", noise.clip(0, 255).astype("uint8"), capture, frame))
        inverted = cv2.bitwise_not(image)
        records.append(_write_control(experiment_dir, controls_dir, "intensity_inverted", inverted, capture, frame))

    return records


def _write_control(
    experiment_dir: Path,
    controls_dir: Path,
    control_type: str,
    image: Any,
    capture: dict[str, Any],
    frame: dict[str, Any],
) -> dict[str, Any]:
    import cv2

    path = controls_dir / f"{control_type}.png"
    cv2.imwrite(str(path), image)
    return {
        "sample_id": f"ctrl-{frame['frame_id']}-{control_type}",
        "parent_capture_id": capture["capture_id"],
        "parent_frame_id": frame["frame_id"],
        "control_type": control_type,
        "path": relative_to(path, experiment_dir),
        "source_sha256": sha256_file(path),
        "frame_index": frame.get("frame_index"),
        "timestamp_ms": frame.get("timestamp_ms"),
        "unblinded_label": "control",
        "synthetic": True,
    }


def _block_shuffle(image: Any, block_size: int) -> Any:
    import numpy as np

    height, width = image.shape[:2]
    shuffled = image.copy()
    blocks = []
    for y in range(0, height, block_size):
        for x in range(0, width, block_size):
            blocks.append((y, x, image[y : min(y + block_size, height), x : min(x + block_size, width)].copy()))

    rng = np.random.default_rng(12345)
    shuffled_blocks = [block for _, _, block in blocks]
    rng.shuffle(shuffled_blocks)

    for (y, x, _), block in zip(blocks, shuffled_blocks):
        bh, bw = block.shape[:2]
        target = shuffled[y : min(y + bh, height), x : min(x + bw, width)]
        shuffled[y : y + target.shape[0], x : x + target.shape[1]] = block[: target.shape[0], : target.shape[1]]
    return shuffled
