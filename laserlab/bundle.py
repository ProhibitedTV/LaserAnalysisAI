"""Local-first community review bundle export."""

from __future__ import annotations

import platform
import sys
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import load_json, sha256_file, write_json
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
    environment = {
        "laserlab_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "include_media": include_media,
        "experiment_id": manifest.get("experiment_id"),
        "run_id": report.get("run_id"),
    }

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        _write_json_member(bundle, "manifest.json", manifest)
        _write_json_member(bundle, "report.json", report)
        _write_json_member(bundle, "results.json", results)
        _write_json_member(bundle, "environment.json", environment)
        bundle.write(run_dir / "report.html", "report.html")

        hashes: dict[str, str] = {}
        for candidate in report.get("top_candidates", [])[:20]:
            for key in ("processed_path",):
                stored = candidate.get(key)
                if stored:
                    path = experiment_dir / stored
                    if path.exists():
                        archive_name = f"top_candidates/{path.name}"
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

        if include_media:
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
            "exceeded matched controls under the chosen protocol.\n"
        )
        bundle.writestr("README.txt", readme)

    return output_path


def _write_json_member(bundle: zipfile.ZipFile, name: str, data: Any) -> None:
    import json

    bundle.writestr(name, json.dumps(data, indent=2, sort_keys=True) + "\n")
