"""Optics and statistics helpers for protocol-driven analysis."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any


def to_gray_float(image: Any) -> Any:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return gray.astype(np.float32)


def fft_spectrum_metrics(image: Any) -> dict[str, Any]:
    """Measure spatial-frequency peaks useful for diffraction/fringe fixtures."""
    import numpy as np

    gray = to_gray_float(image)
    gray = gray - float(gray.mean())
    height, width = gray.shape[:2]
    if height < 4 or width < 4:
        return {"peak_prominence": 0.0, "peak_radius": 0.0, "peak_angle_degrees": 0.0, "ring_energy_ratio": 0.0}

    window = np.outer(np.hanning(height), np.hanning(width))
    spectrum = np.fft.fftshift(np.fft.fft2(gray * window))
    magnitude = np.log1p(np.abs(spectrum))
    cy, cx = height // 2, width // 2
    yy, xx = np.indices(magnitude.shape)
    radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    mask = radius > max(3, min(height, width) * 0.04)
    if not np.any(mask):
        return {"peak_prominence": 0.0, "peak_radius": 0.0, "peak_angle_degrees": 0.0, "ring_energy_ratio": 0.0}

    masked = magnitude.copy()
    masked[~mask] = 0
    peak_y, peak_x = np.unravel_index(int(np.argmax(masked)), masked.shape)
    background = magnitude[mask]
    bg_mean = float(background.mean()) if background.size else 0.0
    bg_std = float(background.std()) if background.size else 0.0
    peak_value = float(magnitude[peak_y, peak_x])
    prominence = (peak_value - bg_mean) / (bg_std + 1e-6)

    peak_radius = float(radius[peak_y, peak_x])
    ring_width = max(2.0, min(height, width) * 0.015)
    ring_mask = np.abs(radius - peak_radius) <= ring_width
    ring_energy = float(magnitude[ring_mask].sum())
    total_energy = float(magnitude[mask].sum()) or 1.0
    angle = math.degrees(math.atan2(peak_y - cy, peak_x - cx))
    normalized_radius = peak_radius / max(1.0, min(height, width) / 2.0)
    return {
        "peak_prominence": round(float(max(0.0, prominence)), 6),
        "peak_radius": round(normalized_radius, 6),
        "peak_angle_degrees": round(float(angle), 3),
        "ring_energy_ratio": round(float(ring_energy / total_energy), 6),
    }


def speckle_contrast_metrics(image: Any, window_size: int = 7) -> dict[str, Any]:
    """Compute spatial speckle contrast K = std / mean over local windows."""
    import cv2
    import numpy as np

    gray = to_gray_float(image)
    kernel = (max(3, window_size), max(3, window_size))
    mean_img = cv2.blur(gray, kernel)
    mean_sq = cv2.blur(gray * gray, kernel)
    variance = np.maximum(0.0, mean_sq - mean_img * mean_img)
    contrast_map = np.sqrt(variance) / (mean_img + 1e-6)
    saturated_fraction = float(np.count_nonzero(gray >= 250) / max(1, gray.size))
    return {
        "spatial_contrast_mean": round(float(np.mean(contrast_map)), 6),
        "spatial_contrast_std": round(float(np.std(contrast_map)), 6),
        "local_variance_mean": round(float(np.mean(variance)), 6),
        "saturated_fraction": round(saturated_fraction, 6),
    }


def glcm_texture_metrics(image: Any, levels: int = 16) -> dict[str, Any]:
    """Small Haralick-style texture summary without adding scikit-image."""
    import numpy as np

    gray = to_gray_float(image)
    if gray.max() > gray.min():
        quantized = ((gray - gray.min()) / (gray.max() - gray.min()) * (levels - 1)).astype("uint8")
    else:
        quantized = np.zeros_like(gray, dtype="uint8")

    matrix = np.zeros((levels, levels), dtype=np.float64)
    pairs = [
        (quantized[:, :-1], quantized[:, 1:]),
        (quantized[:-1, :], quantized[1:, :]),
    ]
    for left, right in pairs:
        for a, b in zip(left.ravel(), right.ravel()):
            matrix[int(a), int(b)] += 1
            matrix[int(b), int(a)] += 1
    total = matrix.sum()
    if total <= 0:
        return {"contrast": 0.0, "homogeneity": 0.0, "energy": 0.0, "entropy": 0.0}
    p = matrix / total
    i, j = np.indices(p.shape)
    contrast = float(((i - j) ** 2 * p).sum())
    homogeneity = float((p / (1.0 + np.abs(i - j))).sum())
    energy = float(np.sqrt((p * p).sum()))
    entropy = -float((p[p > 0] * np.log2(p[p > 0])).sum())
    return {
        "contrast": round(contrast, 6),
        "homogeneity": round(homogeneity, 6),
        "energy": round(energy, 6),
        "entropy": round(entropy, 6),
    }


def phase_registration_metrics(reference: Any, moving: Any) -> dict[str, Any]:
    """Estimate frame shift and registration confidence by phase correlation."""
    import cv2
    import numpy as np

    ref = to_gray_float(reference)
    mov = to_gray_float(moving)
    if ref.shape != mov.shape:
        mov = cv2.resize(mov, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_AREA)
    try:
        (shift_x, shift_y), response = cv2.phaseCorrelate(ref, mov)
    except cv2.error:
        shift_x, shift_y, response = 0.0, 0.0, 0.0
    return {
        "shift_x": round(float(shift_x), 6),
        "shift_y": round(float(shift_y), 6),
        "shift_magnitude": round(float(math.hypot(shift_x, shift_y)), 6),
        "response": round(float(response), 6),
    }


def benjamini_hochberg_q_values(p_values: list[float]) -> list[float]:
    """Return q-values in original order using the BH step-up procedure."""
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(max(0.0, min(1.0, float(p))) for p in p_values), key=lambda item: item[1])
    q_values = [1.0] * m
    running = 1.0
    for rank, (original_index, p_value) in reversed(list(enumerate(indexed, start=1))):
        running = min(running, p_value * m / rank)
        q_values[original_index] = round(float(min(1.0, running)), 6)
    return q_values


def mean_confidence_interval(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": None, "low": None, "high": None}
    avg = float(mean(values))
    if len(values) == 1:
        low = high = avg
    else:
        margin = 1.96 * (pstdev(values) / math.sqrt(len(values)))
        low = avg - margin
        high = avg + margin
    return {"mean": round(avg, 6), "low": round(low, 6), "high": round(high, 6)}


def metric_score(result: dict[str, Any], metric_name: str) -> float:
    if metric_name == "fft_peak_prominence":
        return min(1.0, float(result.get("fft_spectrum", {}).get("peak_prominence", 0.0)) / 8.0)
    if metric_name == "speckle_contrast":
        return min(1.0, float(result.get("speckle_contrast", {}).get("spatial_contrast_mean", 0.0)) * 2.0)
    if metric_name == "ocr_symbol_score":
        ocr = result.get("ocr", {})
        words = float(ocr.get("word_count", len(ocr.get("boxes", []))) or 0)
        conf = max(0.0, float(ocr.get("confidence", 0.0) or 0.0)) / 100.0
        return min(1.0, (words / 8.0) * 0.6 + conf * 0.4) if ocr.get("available") else 0.0
    return float(result.get("structure_score", 0.0) or 0.0)
