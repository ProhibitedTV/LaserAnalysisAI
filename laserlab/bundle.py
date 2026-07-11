"""Local-first community review bundle export."""

from __future__ import annotations

import platform
import sys
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import load_json, sha256_file, write_json
from .blinding import is_unblinded
from .manifest import latest_run_dir, load_manifest


def export_review_bundle(experiment_dir: Path, output_path: Path, include_media: bool = False) -> Path:
    """Create a shareable zip with reports, hashes, thumbnails, and optional media."""
    experiment_dir = Path(experiment_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(experiment_dir)
    run_dir = latest_run_dir(experiment_dir, manifest)
    report = load_json(run_dir / "report.json")
    results = load_json(run_dir / "results.json")
    unblinded = is_unblinded(results)
    if include_media and not unblinded:
        raise ValueError("Source media cannot be exported until the review is explicitly unblinded.")
    environment = {
        "laserlab_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "include_media": include_media,
        "experiment_id": manifest.get("experiment_id"),
        "run_id": report.get("run_id"),
    }

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        _write_json_member(bundle, "manifest.json", manifest if unblinded else _sealed_manifest(manifest))
        _write_json_member(bundle, "report.json", report)
        _write_json_member(bundle, "results.json", results)
        _write_json_member(bundle, "environment.json", environment)
        bundle.write(run_dir / "report.html", "report.html")

        hashes: dict[str, str] = {}
        for candidate in report.get("top_candidates", [])[:20]:
            for key in ("review_image_path", "processed_path"):
                stored = candidate.get(key)
                if stored:
                    path = experiment_dir / stored
                    if path.exists():
                        folder = "top_originals" if key == "review_image_path" else "top_candidates"
                        archive_name = f"{folder}/{path.name}"
                        bundle.write(path, archive_name)
                        hashes[archive_name] = sha256_file(path)
            for roi in candidate.get("candidate_rois", [])[:3]:
                crop = roi.get("crop_path")
                if crop:
                    path = experiment_dir / crop
                    if path.exists():
                        archive_name = f"top_crops/{path.parent.name}_{path.name}"
                        bundle.write(path, archive_name)
                        hashes[archive_name] = sha256_file(path)

        if include_media and unblinded:
            for source in manifest.get("sources", []):
                source_path = Path(source.get("path", ""))
                if source_path.exists() and source_path.is_file():
                    archive_name = f"media/{source_path.name}"
                    bundle.write(source_path, archive_name)
                    hashes[archive_name] = sha256_file(source_path)

        _write_json_member(bundle, "hashes.json", hashes)
        readme = (
            "LaserLab community review bundle\n\n"
            "This archive is local-first evidence packaging. It contains detector settings, "
            "hashes, report artifacts, top candidate images, and optional source media. "
            "It does not claim metaphysical origin; it records whether selected detections "
            "exceeded matched controls under the chosen protocol.\n\n"
            + (
                "Review state: unblinded. Source roles and provenance are included.\n"
                if unblinded
                else "Review state: blinded. Source roles, paths, provenance, and raw media remain sealed.\n"
            )
        )
        bundle.writestr("README.txt", readme)

    return output_path


def _write_json_member(bundle: zipfile.ZipFile, name: str, data: Any) -> None:
    import json

    bundle.writestr(name, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _sealed_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "experiment_id",
        "created_at",
        "frame_sampling",
        "preprocessing_profiles",
        "detectors",
        "blind_seed",
        "protocol",
        "analysis_plan",
        "outputs",
    }
    sealed = {key: value for key, value in manifest.items() if key in allowed}
    sealed["sources"] = []
    sealed["captures"] = []
    sealed["controls"] = []
    sealed["review_state"] = "blinded"
    outputs = dict(sealed.get("outputs", {}))
    outputs.pop("unblinded_at", None)
    outputs.pop("unblind_seal_sha256", None)
    sealed["outputs"] = outputs
    return sealed
