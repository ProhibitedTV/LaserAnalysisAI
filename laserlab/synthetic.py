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


def create_synthetic_grating(path: Path, size: tuple[int, int] = (320, 180), period: int = 16) -> Path:
    import cv2
    import numpy as np

    ensure_dir(path.parent)
    width, height = size
    x = np.arange(width)
    pattern = ((np.sin(2 * np.pi * x / max(2, period)) + 1.0) * 110 + 20).astype("uint8")
    image = np.tile(pattern, (height, 1))
    image = cv2.merge([image, image, image])
    cv2.imwrite(str(path), image)
    return path


def create_synthetic_speckle(path: Path, size: tuple[int, int] = (320, 180)) -> Path:
    import cv2
    import numpy as np

    ensure_dir(path.parent)
    width, height = size
    rng = np.random.default_rng(314)
    field = rng.rayleigh(scale=70, size=(height, width)).clip(0, 255).astype("uint8")
    image = cv2.merge([field, field, field])
    cv2.imwrite(str(path), image)
    return path


def create_synthetic_laser_like_control(path: Path, size: tuple[int, int] = (320, 180)) -> Path:
    import cv2
    import numpy as np

    ensure_dir(path.parent)
    width, height = size
    yy, xx = np.indices((height, width))
    center_x, center_y = width / 2, height / 2
    radius = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
    image = (35 + 160 * np.exp(-(radius**2) / (2 * (min(width, height) / 5) ** 2))).clip(0, 255).astype("uint8")
    image = cv2.merge([image // 4, image, image // 4])
    cv2.imwrite(str(path), image)
    return path


def create_shifted_copy(source: Path, destination: Path, shift_x: int = 7, shift_y: int = 4) -> Path:
    import cv2
    import numpy as np

    ensure_dir(destination.parent)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(source)
    matrix = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
    shifted = cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]))
    cv2.imwrite(str(destination), shifted)
    return destination
