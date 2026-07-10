"""Community-facing protocol presets for LaserLab."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROTOCOL_PRESETS: dict[str, dict[str, Any]] = {
    "diffraction": {
        "id": "diffraction",
        "name": "Diffraction / interference",
        "profile": "wide",
        "primary_metric": "fft_peak_prominence",
        "detector_family": "diffraction",
        "description": "Looks for repeatable spatial-frequency structure such as fringes, peaks, and rings.",
        "quality_checks": ["laser_capture", "control_capture", "frame_count", "saturation", "calibration"],
        "science": [
            "2D FFT spectrum",
            "fringe spacing proxy",
            "peak/ring stability",
        ],
    },
    "speckle": {
        "id": "speckle",
        "name": "Laser speckle / scatter",
        "profile": "wide",
        "primary_metric": "speckle_contrast",
        "detector_family": "speckle",
        "description": "Measures spatial and frame-to-frame speckle contrast against matched controls.",
        "quality_checks": ["laser_capture", "control_capture", "frame_count", "saturation", "stability"],
        "science": [
            "spatial speckle contrast",
            "local variance map",
            "temporal contrast proxy",
        ],
    },
    "ocr": {
        "id": "ocr",
        "name": "OCR / symbol recovery",
        "profile": "baseline",
        "primary_metric": "ocr_symbol_score",
        "detector_family": "symbol",
        "description": "Keeps OCR as a detector while requiring synthetic-positive calibration and controls.",
        "quality_checks": ["laser_capture", "control_capture", "ocr_available", "calibration"],
        "science": [
            "OCR confidence",
            "connected components",
            "synthetic known-text calibration",
        ],
    },
    "anomaly": {
        "id": "anomaly",
        "name": "General anomaly scan",
        "profile": "wide",
        "primary_metric": "structure_score",
        "detector_family": "anomaly",
        "description": "Broad texture, edge, OCR, and persistence scan with stricter false-positive language.",
        "quality_checks": ["laser_capture", "control_capture", "frame_count", "fdr"],
        "science": [
            "texture features",
            "edge/line density",
            "frame persistence",
            "FDR correction",
        ],
    },
}


def list_protocol_presets() -> list[dict[str, Any]]:
    """Return protocol presets sorted for UI display."""
    return [deepcopy(PROTOCOL_PRESETS[key]) for key in ("diffraction", "speckle", "ocr", "anomaly")]


def get_protocol_preset(protocol_id: str | None) -> dict[str, Any]:
    """Return a protocol preset, defaulting to the general anomaly scan."""
    key = protocol_id or "anomaly"
    if key not in PROTOCOL_PRESETS:
        raise ValueError(f"Unknown protocol preset: {protocol_id}")
    return deepcopy(PROTOCOL_PRESETS[key])


def describe_protocol(protocol_id: str) -> str:
    preset = get_protocol_preset(protocol_id)
    science = ", ".join(preset["science"])
    return f"{preset['name']}: {preset['description']} Science options: {science}."
