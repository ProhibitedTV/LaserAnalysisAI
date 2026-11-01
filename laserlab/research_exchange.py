"""Reviewed, media-free local results exchange; no provider submission contract."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import sha256_json
from .capture_inference import STATISTICS_VERSION, sample_class
from .capture_protocol import LASER_PATTERN_TYPES, SURFACE_TYPES
from .manifest import DEFAULT_DETECTORS, latest_run_dir
from .stats import EVIDENCE_THRESHOLDS, current_statistics, evidence_ladder

EXCHANGE_VERSION = "laserlab-research-exchange-v1"
METRICS = {"structure_score", "fft_peak_prominence", "speckle_contrast", "ocr_symbol_score"}
PROTOCOLS = {"anomaly", "diffraction", "speckle", "ocr"}


def _number(value: Any, minimum: float | None = None) -> float | int | None:
    return value if type(value) in (int, float) and math.isfinite(value) and (minimum is None or value >= minimum) else None


def _enum(value: Any, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _hash(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) else None


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _recorded(value: Any) -> str:
    return ("unknown" if value is None or str(value).strip().casefold() in {"", "unknown", "none recorded", "unspecified"}
            else "recorded_but_omitted")


def _sampling(value: Any) -> dict[str, Any]:
    data = _obj(value)
    return {"mode": _enum(data.get("mode"), {"interval", "scene_change", "all_frames", "capped_all_frames"}),
            "frame_interval": _number(data.get("frame_interval"), 1),
            "max_frames": _number(data.get("max_frames"), 1),
            "deduplicate": data.get("deduplicate") if type(data.get("deduplicate")) is bool else None,
            "scene_change_threshold": _number(data.get("scene_change_threshold"), 0)}


def _capture(record: dict, alias: str, include_hashes: bool) -> dict[str, Any]:
    metadata, media = _obj(record.get("capture_metadata")), _obj(record.get("media_metadata"))
    setup = {"camera_details": _recorded(metadata.get("camera")),
             "exposure_details": _recorded(metadata.get("exposure")),
             "geometry_notes": _recorded(metadata.get("laser_to_target_geometry_notes")),
             "focus_mode": _enum(metadata.get("focus_mode"), {"manual", "auto", "fixed"}),
             "projection_surface_type": _enum(metadata.get("projection_surface_type"), SURFACE_TYPES),
             "laser_pattern_type": _enum(metadata.get("laser_pattern_type"), LASER_PATTERN_TYPES)}
    for key in ("projection_distance_meters", "wavelength_nm", "rated_power_mw", "measured_power_mw"):
        setup[key] = _number(metadata.get(key), 0)
    for key in ("camera_fixed", "beam_path_fixed", "projected_region_not_saturated"):
        setup[key] = metadata.get(key) if type(metadata.get(key)) is bool else None
    result = {"capture": alias, "source_class": sample_class(record), "reported_setup": setup,
              "media_dimensions": {key: _number(media.get(key), 0) for key in ("width", "height", "fps")},
              "sampling": _sampling(record.get("extraction_settings"))}
    if include_hashes:
        result["recorded_source_hashes"] = {"capture_sha256": _hash(record.get("capture_source_sha256")),
                                             "acquisition_sha256": _hash(metadata.get("acquisition_source_sha256"))}
    return result


def prepare_exchange(experiment_dir: Path, *, include_source_hashes: bool = False,
                     reference: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read saved explicit-unblind artifacts; return an allow-listed review draft.

    Never read media, source files, sealed maps, OCR text or participant reports.
    The internal snapshot and reference choices are not part of the document.
    """
    experiment_dir = Path(experiment_dir).resolve()
    manifest_bytes = (experiment_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("outputs", {}).get("review_state") == "blinded":
        raise ValueError("Explicitly unblind the review before preparing a results exchange.")
    results_path = (latest_run_dir(experiment_dir, manifest) / "results.json").resolve()
    if not results_path.is_relative_to(experiment_dir):
        raise ValueError("Run results must stay within the selected experiment.")
    result_bytes = results_path.read_bytes()
    saved = json.loads(result_bytes)
    if _obj(saved.get("review_state")).get("unblinded") is not True:
        raise ValueError("An explicit unblinded saved run is required for a results exchange.")
    if type(include_source_hashes) is not bool:
        raise ValueError("Choose explicitly whether recorded source hashes are included.")
    # Only IDs from references linked to this experiment can be selected. No
    # provider content, titles, author information or optical metadata is copied.
    choices = []
    for item in manifest.get("external_dataset_references", []):
        item = _obj(item)
        if (item.get("source") == "veilbreak" and item.get("record_type") in {"protocol", "experiment"}
                and type(item.get("record_id")) is int and item["record_id"] > 0):
            choice = {"source": "veilbreak", "record_type": item["record_type"], "record_id": item["record_id"]}
            if choice not in choices:
                choices.append(choice)
    if reference is not None:
        if (not isinstance(reference, dict) or type(reference.get("record_id")) is not int
                or reference not in choices):
            raise ValueError("Select a Veilbreak reference already linked to this local experiment.")
        reference = dict(choices[choices.index(reference)])
    run = current_statistics(saved)
    aggregate = _obj(run.get("aggregate_statistics"))
    inference = _obj(aggregate.get("inference"))
    configuration = _obj(run.get("analysis_configuration"))
    demo = run.get("experiment_purpose") == "demo" or manifest.get("experiment_purpose") == "demo"
    status = _enum(inference.get("status"), {"tested", "insufficient_independent_samples", "not_tested"})
    supported = aggregate.get("statistics_version") == STATISTICS_VERSION
    status = status if supported and not demo else "not_tested"
    tested = status == "tested"
    outcome = evidence_ladder(aggregate) if supported and not demo else "not tested"
    quality = _obj(run.get("pre_run_quality"))
    quality_status = _enum(quality.get("status"), {"consistent", "mismatch", "unknown"}) or "not_assessed"
    captures, seen = [], set()
    for index, result in enumerate(run.get("results", [])):
        identity = (result.get("capture_id") or result.get("sample_id") or index, sample_class(result))
        if identity not in seen:
            seen.add(identity)
            captures.append(_capture(result, f"C{len(captures) + 1:03d}", include_source_hashes))
    roi = _obj(configuration.get("roi"))
    version = run.get("laserlab_version")
    warnings = ["This is a local draft exchange format, not a Veilbreak submission schema or permission to publish.",
                "No upload occurs. Review consent, source rights and attribution before sharing.",
                "Omitting names does not guarantee anonymity; settings and outcomes may still disclose context.",
                "This media-free summary does not by itself reproduce the complete analysis.",
                "Reported setup and lineage are declarations; they do not establish optical validity or independence.",
                "One recorded pair is descriptive. Extra frames are not independent repeats; candidate FDR is not estimated.",
                "OCR fragments do not establish language or meaning. No OCR text or human interpretation is included."]
    if demo:
        warnings.append("Practice demo: public fixtures are not a matched scientific experiment.")
    elif any(capture["source_class"] == "demonstration_fixture" for capture in captures):
        warnings.append("Demonstration/calibration fixtures are not empirical matched controls.")
    if quality_status != "consistent":
        warnings.append("Pair Quality is missing or unresolved; no new quality pass is invented for this export.")
    if include_source_hashes:
        warnings.append("Recorded source hashes can link recordings across exports. They are not freshly verified against media files.")
    if reference is not None:
        warnings.append("The selected provider ID is context only. Verify its canonical URL, author credit and license before redistribution.")
    document = {
        "schema_version": EXCHANGE_VERSION, "exporter": {"name": "LaserLab", "version": __version__},
        "analysis_software_version": version if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version) else None,
        "experiment_purpose": "practice_demo" if demo else "research" if run.get("experiment_purpose") == "research" else "unspecified",
        "review": {"explicitly_unblinded": True, "review_marked_complete": _obj(run.get("review_session")).get("complete") is True},
        "community_references": [dict(reference)] if reference is not None else [],
        "method": {"statistics_version": STATISTICS_VERSION,
                   "protocol": _enum(run.get("protocol"), PROTOCOLS),
                   "primary_metric": _enum(aggregate.get("primary_metric"), METRICS),
                   "preprocessing_profile": _enum(run.get("profile"), {"baseline", "wide"}),
                   "detectors": sorted({value for value in (configuration.get("detectors") or []) if isinstance(value, str)} & set(DEFAULT_DETECTORS)),
                   "preprocessing_intensity": _enum(configuration.get("preprocessing_intensity"), {"standard", "wide"}),
                   "control_generation": _enum(configuration.get("control_generation"), {"none", "standard"}),
                   "roi": {key: _number(roi.get(key), 0) for key in ("x", "y", "width", "height")},
                   "frame_sampling_mode": _enum(configuration.get("frame_sampling_mode"), {"interval", "scene_change", "all_frames", "capped_all_frames"}),
                   "evidence_thresholds": dict(EVIDENCE_THRESHOLDS)},
        "findings": {"evidence_level": outcome, "inference_status": status or "not_tested",
                     "declared_independent_pair_count": _number(inference.get("pair_count"), 0),
                     "laser_mean_score": _number(aggregate.get("laser_mean_score")),
                     "control_mean_score": _number(aggregate.get("control_mean_score")),
                     "score_summary_unit": "equal_weight_capture_medians" if tested else "descriptive_frames_only",
                     "mean_difference": _number(aggregate.get("mean_difference")),
                     "permutation_p_value": _number(aggregate.get("permutation_p_value"), 0) if tested else None,
                     "candidate_fdr": None},
        "quality": {"status": quality_status, "exploratory": quality.get("requires_exploratory") is True},
        "captures": captures,
        "privacy": {"source_hashes_included": include_source_hashes, "media_included": False,
                    "personal_identifiers_included": False, "free_text_included": False},
        "limitations": warnings,
    }
    snapshot = sha256_json({"manifest": hashlib.sha256(manifest_bytes).hexdigest(),
                            "results": hashlib.sha256(result_bytes).hexdigest(),
                            "document": document})
    return {"document": document, "_snapshot_sha256": snapshot, "_reference_choices": choices}


def export_exchange(experiment_dir: Path, output_path: Path, *, expected_snapshot: str,
                    privacy_acknowledged: bool = False, include_source_hashes: bool = False,
                    reference: dict[str, Any] | None = None) -> Path:
    if privacy_acknowledged is not True:
        raise ValueError("Review the exact exchange preview and acknowledge consent/privacy before saving.")
    if _hash(expected_snapshot) is None:
        raise ValueError("Prepare and review an exchange preview before saving.")
    preview = prepare_exchange(experiment_dir, include_source_hashes=include_source_hashes, reference=reference)
    if preview["_snapshot_sha256"] != expected_snapshot:
        raise ValueError("The experiment or export options changed. Prepare and review a fresh preview.")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(preview["document"], handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return output_path
