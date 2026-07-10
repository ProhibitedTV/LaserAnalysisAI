"""Experiment manifest creation and persistence."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, load_json, utc_now_iso, write_json

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"

BASELINE_PROFILE = {
    "name": "baseline",
    "description": "Multi-pass OCR and structure analysis for laser/control comparison.",
    "variants": [
        {"name": "grayscale", "steps": ["grayscale"]},
        {"name": "otsu", "steps": ["grayscale", "gaussian_blur", "otsu_threshold"]},
        {"name": "adaptive", "steps": ["grayscale", "adaptive_threshold"]},
        {"name": "equalized", "steps": ["grayscale", "histogram_equalization", "otsu_threshold"]},
        {"name": "edges", "steps": ["grayscale", "gaussian_blur", "canny_edges"]},
    ],
}

WIDE_PROFILE = {
    "name": "wide",
    "description": "Exploratory sweep across contrast, threshold, edge, morphology, and scale variants.",
    "variants": [
        {"name": "grayscale", "steps": ["grayscale"]},
        {"name": "clahe", "steps": ["grayscale", "clahe"]},
        {"name": "sharpen_otsu", "steps": ["grayscale", "sharpen", "otsu_threshold"]},
        {"name": "invert_otsu", "steps": ["grayscale", "invert", "otsu_threshold"]},
        {"name": "threshold_64", "steps": ["grayscale", "threshold_64"]},
        {"name": "threshold_96", "steps": ["grayscale", "threshold_96"]},
        {"name": "threshold_128", "steps": ["grayscale", "threshold_128"]},
        {"name": "threshold_160", "steps": ["grayscale", "threshold_160"]},
        {"name": "threshold_192", "steps": ["grayscale", "threshold_192"]},
        {"name": "adaptive_15", "steps": ["grayscale", "adaptive_threshold_15"]},
        {"name": "adaptive_31", "steps": ["grayscale", "adaptive_threshold_31"]},
        {"name": "adaptive_51", "steps": ["grayscale", "adaptive_threshold_51"]},
        {"name": "edges_low", "steps": ["grayscale", "gaussian_blur", "canny_low"]},
        {"name": "edges_standard", "steps": ["grayscale", "gaussian_blur", "canny_edges"]},
        {"name": "edges_high", "steps": ["grayscale", "gaussian_blur", "canny_high"]},
        {"name": "morph_close", "steps": ["grayscale", "otsu_threshold", "morph_close_2"]},
        {"name": "morph_open", "steps": ["grayscale", "otsu_threshold", "morph_open_2"]},
        {"name": "morph_gradient", "steps": ["grayscale", "morph_gradient_3"]},
        {"name": "resize_2x_otsu", "steps": ["grayscale", "resize_2x", "otsu_threshold"]},
    ],
}

DEFAULT_DETECTORS = [
    "ocr",
    "connected_components",
    "entropy_texture",
    "edge_line_density",
    "frame_persistence",
]


def manifest_path(experiment_dir: Path) -> Path:
    return experiment_dir / MANIFEST_NAME


def new_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": f"exp-{uuid.uuid4().hex[:12]}",
        "created_at": utc_now_iso(),
        "sources": [],
        "captures": [],
        "controls": [],
        "frame_sampling": {
            "frame_interval": 5,
            "max_frames": None,
            "image_extensions": [".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"],
        },
        "preprocessing_profiles": {"baseline": BASELINE_PROFILE, "wide": WIDE_PROFILE},
        "detectors": DEFAULT_DETECTORS,
        "blind_seed": None,
        "outputs": {},
    }


def load_manifest(experiment_dir: Path) -> dict[str, Any]:
    path = manifest_path(experiment_dir)
    if not path.exists():
        raise FileNotFoundError(f"Experiment manifest not found: {path}")
    manifest = load_json(path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported manifest schema {manifest.get('schema_version')}; expected {SCHEMA_VERSION}"
        )
    return manifest


def load_or_create_manifest(experiment_dir: Path) -> dict[str, Any]:
    ensure_dir(experiment_dir)
    path = manifest_path(experiment_dir)
    if path.exists():
        return load_manifest(experiment_dir)
    manifest = new_manifest()
    write_manifest(experiment_dir, manifest)
    return manifest


def write_manifest(experiment_dir: Path, manifest: dict[str, Any]) -> None:
    ensure_dir(experiment_dir)
    write_json(manifest_path(experiment_dir), manifest)


def latest_run_dir(experiment_dir: Path, manifest: dict[str, Any]) -> Path:
    latest = manifest.get("outputs", {}).get("latest_run")
    if not latest:
        raise FileNotFoundError("No run output exists yet. Run laserlab first.")
    return experiment_dir / latest
