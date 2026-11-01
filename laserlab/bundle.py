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
from .stats import current_statistics
from .report import build_report, render_html_report


def export_review_bundle(
    experiment_dir: Path,
    output_path: Path,
    include_media: bool = False,
    privacy_acknowledged: bool = False,
) -> Path:
    """Create a shareable zip with reports, hashes, thumbnails, and optional media."""
    experiment_dir = Path(experiment_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(experiment_dir)
    run_dir = latest_run_dir(experiment_dir, manifest)
    results = current_statistics(load_json(run_dir / "results.json"))
    report = build_report(experiment_dir, run_dir, results, write_html=False)
    unblinded = is_unblinded(results)
    if include_media and not unblinded:
        raise ValueError("Source media cannot be exported until the review is explicitly unblinded.")
    if unblinded and _contains_sensitive_context(manifest) and not privacy_acknowledged:
        raise ValueError(
            "Review participant IDs, research plans, subjective context, community metadata, and sharing risk before export."
        )
    environment = {
        "laserlab_version": __version__,
        "statistics_version": results.get("aggregate_statistics", {}).get("statistics_version"),
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
        bundle.writestr("report.html", render_html_report(report))

        hashes: dict[str, str] = {}
        for candidate in report.get("top_candidates", [])[:20]:
            for key in ("review_image_path", "processed_path", "roi_overlay_path"):
                stored = candidate.get(key)
                if stored:
                    path = experiment_dir / stored
                    if path.exists():
                        folder = {
                            "review_image_path": "top_originals",
                            "processed_path": "top_candidates",
                            "roi_overlay_path": "top_overlays",
                        }[key]
                        archive_name = f"{folder}/{path.name}"
                        bundle.write(path, archive_name)
                        hashes[archive_name] = sha256_file(path)
            for roi in candidate.get("candidate_rois", [])[:3]:
                for key, folder in (
                    ("crop_path", "top_crops"),
                    ("processed_crop_path", "top_processed_crops"),
                    ("mask_path", "top_roi_masks"),
                ):
                    stored = roi.get(key)
                    if not stored:
                        continue
                    path = experiment_dir / stored
                    if path.exists():
                        archive_name = f"{folder}/{path.parent.name}_{path.name}"
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
            + ("PRACTICE DEMO: public sample clips are not a matched scientific experiment.\n\n"
               if results.get("experiment_purpose") == "demo" else "")
            + "This archive is local-first evidence packaging. It contains detector settings, "
            "hashes, report artifacts, top candidate images, and optional source media. "
            "It does not claim metaphysical origin; it records whether selected detections "
            "exceeded matched controls under the chosen protocol.\n\n"
            "Generated null probes are not empirical matched recordings. A run may be exploratory/not tested "
            "or have insufficient independent capture pairs. Candidate-level FDR is not estimated.\n\n"
            + (
                "Review state: unblinded. Source roles and provenance are included.\n"
                if unblinded
                else "Review state: blinded. Source roles, paths, provenance, and raw media remain sealed.\n"
            )
        )
        bundle.writestr("README.txt", readme)

    return output_path


def _contains_sensitive_context(manifest: dict[str, Any]) -> bool:
    study_context = manifest.get("study_context") or {}
    return bool(
        study_context.get("mode") not in (None, "footage_only")
        or manifest.get("subjective_reports")
        or (manifest.get("psychophysics_trials") or {}).get("records")
        or manifest.get("external_dataset_references")
        or (manifest.get("symbol_transcriptions") or {}).get("records")
        or manifest.get("replication_plan")
    )


def _write_json_member(bundle: zipfile.ZipFile, name: str, data: Any) -> None:
    import json

    bundle.writestr(name, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _sealed_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "experiment_id",
        "experiment_purpose",
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
    sealed["experiment_purpose"] = "demo" if manifest.get("experiment_purpose") == "demo" else "research"
    sealed["sources"] = []
    sealed["captures"] = []
    sealed["controls"] = []
    sealed["review_state"] = "blinded"
    outputs = dict(sealed.get("outputs", {}))
    outputs.pop("unblinded_at", None)
    outputs.pop("unblind_seal_sha256", None)
    sealed["outputs"] = outputs
    return sealed
