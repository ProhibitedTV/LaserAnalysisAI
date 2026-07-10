"""Synthetic image helpers for tests and calibration runs."""

from __future__ import annotations

from pathlib import Path

from .artifacts import ensure_dir


def create_synthetic_positive(path: Path, text: str = "SIGNAL 314", size: tuple[int, int] = (320, 180)) -> Path:
    import cv2
    import numpy as np

    ensure_dir(path.parent)
    width, height = size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        image[:, x, 1] = int(40 + 80 * (x / max(1, width - 1)))
    cv2.putText(image, text, (18, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (230, 255, 230), 2, cv2.LINE_AA)
    cv2.imwrite(str(path), image)
    return path


def create_synthetic_negative(path: Path, size: tuple[int, int] = (320, 180)) -> Path:
    import cv2
    import numpy as np

    ensure_dir(path.parent)
    width, height = size
    rng = np.random.default_rng(42)
    base = rng.normal(loc=45, scale=8, size=(height, width, 3)).clip(0, 255).astype("uint8")
    cv2.GaussianBlur(base, (9, 9), 0, dst=base)
    cv2.imwrite(str(path), base)
    return path
