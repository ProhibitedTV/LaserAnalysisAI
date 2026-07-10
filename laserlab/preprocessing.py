"""Image preprocessing profiles for detector input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifacts import sha256_json


@dataclass(frozen=True)
class ProcessedImage:
    variant_name: str
    image: Any
    profile_hash: str
    profile: dict[str, Any]


def apply_profile_variants(image: Any, profile: dict[str, Any]) -> list[ProcessedImage]:
    variants = []
    for variant in profile.get("variants", []):
        processed = apply_steps(image, variant.get("steps", []))
        profile_record = {"profile": profile.get("name", "unknown"), "variant": variant}
        variants.append(
            ProcessedImage(
                variant_name=variant.get("name", "unnamed"),
                image=processed,
                profile_hash=sha256_json(profile_record),
                profile=profile_record,
            )
        )
    return variants


def apply_steps(image: Any, steps: list[str]) -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Preprocessing requires opencv-python.") from exc

    result = image
    for step in steps:
        if step == "grayscale":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
        elif step == "gaussian_blur":
            result = cv2.GaussianBlur(result, (5, 5), 0)
        elif step == "otsu_threshold":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            _, result = cv2.threshold(result, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif step.startswith("threshold_"):
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            threshold = int(step.rsplit("_", 1)[1])
            _, result = cv2.threshold(result, threshold, 255, cv2.THRESH_BINARY)
        elif step == "adaptive_threshold":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.adaptiveThreshold(
                result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
            )
        elif step.startswith("adaptive_threshold_"):
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            block_size = int(step.rsplit("_", 1)[1])
            if block_size % 2 == 0:
                block_size += 1
            result = cv2.adaptiveThreshold(
                result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, 5
            )
        elif step == "histogram_equalization":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.equalizeHist(result)
        elif step == "clahe":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            result = clahe.apply(result)
        elif step == "invert":
            result = cv2.bitwise_not(result)
        elif step == "sharpen":
            import numpy as np

            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            result = cv2.filter2D(result, -1, kernel)
        elif step == "canny_edges":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.Canny(result, 50, 150)
        elif step == "canny_low":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.Canny(result, 25, 100)
        elif step == "canny_high":
            if len(result.shape) == 3:
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            result = cv2.Canny(result, 100, 220)
        elif step == "morph_close_2":
            import numpy as np

            kernel = np.ones((2, 2), np.uint8)
            result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
        elif step == "morph_open_2":
            import numpy as np

            kernel = np.ones((2, 2), np.uint8)
            result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
        elif step == "morph_gradient_3":
            import numpy as np

            kernel = np.ones((3, 3), np.uint8)
            result = cv2.morphologyEx(result, cv2.MORPH_GRADIENT, kernel)
        elif step == "resize_2x":
            result = cv2.resize(result, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        else:
            raise ValueError(f"Unknown preprocessing step: {step}")
    return result
