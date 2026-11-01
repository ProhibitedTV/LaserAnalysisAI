"""Conservative, local comparison of explicitly unblinded session outcomes."""
from __future__ import annotations

import html
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifacts import sha256_json, utc_now_iso
from .capture_inference import sample_class, STATISTICS_VERSION
from .manifest import load_manifest, latest_run_dir, write_manifest, DEFAULT_DETECTORS
from .stats import current_statistics, evidence_ladder

COMPARISON_VERSION = "session-comparison-v1"
CRITERION = "same_primary_metric_above_control"
MAX_SESSIONS = 8
COMPARABILITY_FIELDS = ("camera", "exposure", "focus_mode", "compression_history", "projection_surface_type",
                        "projection_distance_meters", "laser_to_target_geometry_notes", "intermediate_material_notes",
                        "room_lighting_notes", "camera_fixed", "beam_path_fixed", "projected_region_not_saturated",
                        "wavelength_nm", "laser_pattern_type", "diffraction_optic_type")


def record_replication_plan(experiment_dir: Path, hypothesis_token: str, independent_acquisition: bool,
                            protocol: str | None = None, primary_metric: str | None = None) -> dict[str, Any]:
    """Record a local declaration before the first run, never retrofit prior results."""
    experiment_dir = Path(experiment_dir)
    manifest = load_manifest(experiment_dir)
    if manifest.get("outputs", {}).get("latest_run") or any((experiment_dir / "runs").glob("*/results.json")):
        raise ValueError("Record replication plans before the first analysis; saved outcomes cannot be retrofitted.")
    if manifest.get("replication_plan"):
        raise ValueError("This experiment already has a replication plan. Preserve it and use a new experiment for a different plan.")
    if not isinstance(hypothesis_token, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", hypothesis_token):
        raise ValueError("Use a short non-identifying hypothesis token: letters, digits, dots, underscores or hyphens.")
    plan = manifest.get("analysis_plan") or {}
    chosen_protocol = protocol or plan.get("protocol")
    chosen_metric = primary_metric or plan.get("primary_metric")
    if chosen_protocol not in {"anomaly", "diffraction", "speckle", "ocr"} or chosen_metric not in {
        "structure_score", "fft_peak_prominence", "speckle_contrast", "ocr_symbol_score"
    }:
        raise ValueError("Choose a supported protocol and primary metric before recording a replication plan.")
    declaration = {"version": COMPARISON_VERSION, "criterion": CRITERION,
                   "hypothesis_sha256": sha256_json({"hypothesis_token": hypothesis_token}),
                   "protocol": chosen_protocol, "primary_metric": chosen_metric,
                   "independent_original_acquisition_declared": independent_acquisition is True,
                   "recorded_at": utc_now_iso()}
    manifest["replication_plan"] = declaration
    write_manifest(experiment_dir, manifest)
    return declaration


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _known(value: Any) -> bool:
    return value is not None and str(value).strip().casefold() not in {"", "unknown", "none recorded", "unspecified"}


def _normalized(value: Any) -> str:
    return str(value).strip().casefold()


def _before_run(plan: dict[str, Any], run: dict[str, Any]) -> bool:
    try:
        planned = datetime.fromisoformat(plan["recorded_at"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        return planned.tzinfo is not None and started.tzinfo is not None and planned <= started
    except (KeyError, TypeError, ValueError):
        return False


def _supported_inference(aggregate: dict[str, Any]) -> bool:
    inference = aggregate.get("inference") or {}
    p_value, difference = aggregate.get("permutation_p_value"), aggregate.get("mean_difference")
    numeric = lambda value: type(value) in (int, float) and math.isfinite(value)
    if not (aggregate.get("statistics_version") == STATISTICS_VERSION and inference.get("version") == STATISTICS_VERSION
            and inference.get("method") == "paired_capture_sign_flip" and inference.get("status") == "tested"
            and type(inference.get("pair_count")) is int and inference["pair_count"] >= 5
            and numeric(p_value) and 0 <= p_value <= 1 and numeric(difference)
            and inference.get("p_value") == p_value and inference.get("mean_difference") == difference):
        return False
    return aggregate.get("evidence_ladder") == evidence_ladder(aggregate)


def compare_sessions(experiment_dirs: list[Path]) -> dict[str, Any]:
    """Read only public/unblinded results; never open source media or sealed maps."""
    if not 2 <= len(experiment_dirs) <= MAX_SESSIONS:
        raise ValueError(f"Choose between two and {MAX_SESSIONS} local experiments.")
    directories = [Path(directory).resolve() for directory in experiment_dirs]
    if len(set(directories)) != len(directories):
        raise ValueError("Choose distinct experiment directories; one experiment cannot replicate itself.")
    runs = []
    snapshots = []
    # Reject the complete selection before presenting any role-specific summary.
    for directory in directories:
        manifest = load_manifest(directory)
        if manifest.get("outputs", {}).get("review_state") == "blinded":
            raise ValueError("Every selected review must be explicitly unblinded before session comparison.")
        path = latest_run_dir(directory, manifest) / "results.json"
        if not path.resolve().is_relative_to(directory):
            raise ValueError("Run results must stay within their experiment directory.")
        payload = path.read_bytes()
        record = json.loads(payload)
        state = record.get("review_state")
        if not isinstance(state, dict) or state.get("unblinded") is not True:
            raise ValueError("Every selected run must have an explicit unblinded state; legacy unknown states need a new run.")
        snapshots.append(hashlib.sha256(payload).hexdigest())
        runs.append(current_statistics(record))
    return _compare_records(runs, snapshots)


def _compare_records(runs: list[dict[str, Any]], snapshots: list[str]) -> dict[str, Any]:
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    sessions = []
    empirical_by_session = []
    source_sets, frame_sets, lineage_sets = [], [], []
    identities = set()
    shared = False

    def check(key: str, status: str, message: str) -> None:
        checks.append({"key": key, "status": status, "message": message})
        if status != "matched":
            warnings.append(message)

    for index, run in enumerate(runs, 1):
        alias = f"S{index:02d}"
        identity = (run.get("experiment_id"), run.get("run_id"))
        if identity in identities:
            shared = True
        identities.add(identity)
        frames = {}
        for result in run.get("results", []):
            if sample_class(result) in {"empirical_laser", "declared_matched_control"}:
                frames.setdefault(result.get("sample_id"), result)
        empirical = list(frames.values())
        empirical_by_session.append(empirical)
        captures: dict[str, dict[str, Any]] = {}
        for result in empirical:
            captures.setdefault(result.get("capture_id"), result)
        sources = {result.get("capture_source_sha256") for result in empirical if _valid_hash(result.get("capture_source_sha256"))}
        hashes = {result.get("source_sha256") for result in empirical if _valid_hash(result.get("source_sha256"))}
        lineages = {(result.get("capture_metadata") or {}).get("acquisition_source_sha256") for result in empirical
                    if _valid_hash((result.get("capture_metadata") or {}).get("acquisition_source_sha256"))}
        if any(sources & old for old in source_sets) or any(hashes & old for old in frame_sets) or any(lineages & old for old in lineage_sets):
            shared = True
        # Also detect a declared original lineage reused as another session's direct source.
        if any(lineages & old for old in source_sets) or any(sources & old for old in lineage_sets):
            shared = True
        source_sets.append(sources)
        frame_sets.append(hashes)
        lineage_sets.append(lineages)
        provenance_known = bool(empirical) and all(_valid_hash(r.get("capture_source_sha256")) and _valid_hash(r.get("source_sha256")) for r in empirical)
        original_known = bool(captures) and all(
            _valid_hash((r.get("capture_metadata") or {}).get("acquisition_source_sha256")) and
            (r.get("capture_metadata") or {}).get("acquisition_source_sha256") == r.get("capture_source_sha256") for r in captures.values())
        if not provenance_known:
            check(f"{alias}_provenance", "unknown", f"{alias}: empirical source/frame hashes are incomplete; independent acquisition is not established.")
        if not original_known:
            check(f"{alias}_original_acquisition", "unknown", f"{alias}: original acquisition lineage is missing or indicates derived media; different files cannot establish independent replication.")
        aggregate = run.get("aggregate_statistics", {})
        inference = aggregate.get("inference", {})
        actual_counts = {"laser": sum(sample_class(record) == "empirical_laser" for record in captures.values()),
                         "matched_control": sum(sample_class(record) == "declared_matched_control" for record in captures.values())}
        supported = (_supported_inference(aggregate) and inference.get("empirical_capture_counts") == actual_counts
                     and actual_counts["laser"] == actual_counts["matched_control"] == inference.get("pair_count"))
        outcome = aggregate.get("evidence_ladder", "not tested") if supported else "not tested"
        if not supported:
            check(f"{alias}_inference", "unknown", f"{alias}: no supported independent capture-pair inference; this session remains descriptive.")
        quality = run.get("pre_run_quality") or {}
        if quality.get("status") != "consistent" or quality.get("requires_exploratory") is not False:
            check(f"{alias}_quality", "unknown", f"{alias}: Pair Quality was not assessed as consistent for this saved run.")
        configuration = run.get("analysis_configuration") or {}
        detector_ids = configuration.get("detectors") or []
        all_samples = {result.get("sample_id"): result for result in run.get("results", [])}
        all_captures = {result.get("capture_id"): result for result in all_samples.values() if result.get("capture_id")}
        class_counts: dict[str, int] = {}
        for result in all_samples.values():
            kind = sample_class(result)
            class_counts[kind] = class_counts.get(kind, 0) + 1
        metadata_status = {}
        for field in COMPARABILITY_FIELDS:
            values = [(record.get("capture_metadata") or {}).get(field) for record in empirical]
            metadata_status[field] = "unknown" if not values or not all(_known(value) for value in values) else "recorded" if len({_normalized(value) for value in values}) == 1 else "internally inconsistent"
        sessions.append({"session": alias, "outcome": outcome if outcome in {"no signal", "artifact", "anomaly", "above-control candidate", "not tested", "insufficient independent samples"} else "not tested",
                         "inference_status": "tested" if supported else "not tested",
                         "within_session_p_value": aggregate.get("permutation_p_value") if supported else None,
                         "independent_pair_count": inference.get("pair_count", 0), "empirical_capture_count": len(captures),
                         "laser_capture_count": sum(sample_class(r) == "empirical_laser" for r in captures.values()),
                         "matched_control_capture_count": sum(sample_class(r) == "declared_matched_control" for r in captures.values()),
                         "generated_frame_count": len({r.get("sample_id") for r in run.get("results", []) if sample_class(r) == "generated_null"}),
                         "frame_count": len(all_samples), "empirical_frame_count": len(empirical), "source_class_frame_counts": class_counts,
                         "mean_frame_persistence": aggregate.get("laser_mean_persistence"),
                         "protocol": run.get("protocol") if run.get("protocol") in {"anomaly", "diffraction", "speckle", "ocr"} else "unknown",
                         "primary_metric": aggregate.get("primary_metric") if aggregate.get("primary_metric") in {"structure_score", "fft_peak_prominence", "speckle_contrast", "ocr_symbol_score"} else "unknown",
                         "detectors": [value for value in detector_ids if value in DEFAULT_DETECTORS],
                         "preprocessing_profile": run.get("profile") if run.get("profile") in {"baseline", "wide"} else "custom or unknown",
                         "pair_quality": quality.get("status") if quality.get("status") in {"consistent", "mismatch", "unknown"} else "not assessed",
                         "metadata_status": metadata_status,
                         "captures": [{"capture": f"{alias}.C{number:02d}", "source_class": sample_class(result)}
                                      for number, result in enumerate(all_captures.values(), 1)]})

    provenance_available = all(source_sets) and all(frame_sets)
    check("shared_sources", "mismatch" if shared else "matched" if provenance_available else "unknown", "Source/run/frame or declared acquisition lineage is reused across sessions; this is not independent replication."
          if shared else "No identical available source/frame/lineage hashes were found. Missing lineage or re-encoded derivatives may remain undetected; different hashes cannot prove independence."
          if provenance_available else "Source/frame provenance is insufficient to rule out reuse; independent replication is not established.")
    for key, extractor in (
        ("protocol", lambda r: r.get("protocol")),
        ("primary_metric", lambda r: r.get("aggregate_statistics", {}).get("primary_metric")),
        ("statistics_method", lambda r: r.get("aggregate_statistics", {}).get("statistics_version")),
        ("detector_and_processing_settings", lambda r: r.get("analysis_configuration")),
    ):
        values = [extractor(run) for run in runs]
        known = all(bool(value) and _known(value) for value in values)
        if key == "detector_and_processing_settings":
            required = {"version", "detectors", "preprocessing_profile_sha256", "preprocessing_intensity",
                        "control_generation", "roi", "frame_sampling_mode", "ocr_engines"}
            known = all(isinstance(value, dict) and value.get("version") == "analysis-config-v1" and
                        required <= value.keys() and value.get("detectors") and
                        _valid_hash(value.get("preprocessing_profile_sha256")) for value in values)
        status = "unknown" if not known else "matched" if all(value == values[0] for value in values) else "mismatch"
        check(key, status, f"{key.replace('_', ' ').capitalize()}: " + ("compatible recorded settings." if status == "matched" else "missing or different settings; plans/metrics may have been selected differently and are not pooled."))
    all_frames = [frame for records in empirical_by_session for frame in records]
    for field in ("width", "height", "fps", "codec"):
        values = [(frame.get("media_metadata") or {}).get(field) for frame in all_frames]
        if field in {"fps", "codec"} and all_frames and all((frame.get("media_metadata") or {}).get("source_kind") == "image-set" for frame in all_frames):
            values = ["not applicable to image sets"] * len(all_frames)
        known = bool(values) and all(_known(value) for value in values)
        status = "unknown" if not known else "matched" if all(value == values[0] for value in values) else "mismatch"
        check("media_" + field, status, f"Media {field}: " + ("recorded settings agree." if status == "matched" else "missing or different recording settings; comparability is not established."))
    for field in COMPARABILITY_FIELDS:
        values = [(frame.get("capture_metadata") or {}).get(field) for frame in all_frames]
        known = bool(values) and all(_known(value) for value in values)
        status = "unknown" if not known else "matched" if all(_normalized(value) == _normalized(values[0]) for value in values) else "mismatch"
        if field in {"camera_fixed", "beam_path_fixed", "projected_region_not_saturated"} and any(value is False for value in values):
            status = "mismatch"
        check(field, status, f"{field.replace('_', ' ').capitalize()}: " + ("recorded declarations agree; not verified measurements." if status == "matched" else "missing or incompatible declarations; optical comparability is not established."))
    plans = [run.get("replication_plan") or {} for run in runs]
    plan_known = all(plan.get("version") == COMPARISON_VERSION and plan.get("criterion") == CRITERION and
                     _valid_hash(plan.get("hypothesis_sha256")) and _before_run(plan, run) and
                     plan.get("protocol") == run.get("protocol") and
                     plan.get("primary_metric") == run.get("aggregate_statistics", {}).get("primary_metric") for plan, run in zip(plans, runs))
    plan_matches = plan_known and len({plan["hypothesis_sha256"] for plan in plans}) == 1
    check("pre_run_hypothesis", "matched" if plan_matches else "unknown", "Matching local pre-run hypothesis commitments and fixed primary-metric criteria were recorded. Local timestamps are not external preregistration."
          if plan_matches else "Pre-run hypothesis commitments are missing, differ, or do not match these runs. Treat any repeated positive outcome as exploratory; selection/cherry-picking is not ruled out.")
    declared_independent = all(plan.get("independent_original_acquisition_declared") is True for plan in plans)
    check("independent_session_declaration", "matched" if declared_independent else "unknown", "Independent original acquisitions were explicitly declared; this is not proof."
          if declared_independent else "Independent original session acquisition was not explicitly declared for every session.")
    compatible = all(item["status"] == "matched" for item in checks)
    positive_count = sum(session["outcome"] == "above-control candidate" and session["inference_status"] == "tested" for session in sessions)
    tested_count = sum(session["inference_status"] == "tested" for session in sessions)
    null_count = sum(session["outcome"] == "no signal" and session["inference_status"] == "tested" for session in sessions)
    status = "shared_source_not_replication" if shared else "declared_replication_candidate" if compatible and positive_count == len(sessions) else "no_positive_replication" if compatible else "exploratory_comparison"
    message = {"shared_source_not_replication": "Shared acquisition provenance was found. These selections cannot establish independent replication.",
               "declared_replication_candidate": "Every compatible session exceeded its own matched controls for the locally predeclared primary criterion. This is a declared replication candidate, not verified independence or validated language.",
               "no_positive_replication": "Compatible sessions did not all exceed their own matched controls. No positive replication candidate is established.",
               "exploratory_comparison": "Compare the individual outcomes descriptively. Missing or incompatible design/provenance prevents an independent-session replication claim."}[status]
    return {"schema_version": 1, "comparison_version": COMPARISON_VERSION, "status": status, "message": message,
            "session_count": len(sessions), "tested_session_count": tested_count, "positive_session_count": positive_count,
            "null_session_count": null_count, "sessions": sessions, "compatibility": checks, "warnings": warnings,
            "replication_terms": {"frame_persistence": "Adjacent-frame mask overlap within one recording; may reflect a stable artifact.",
                                  "repeat_within_capture": "Repeated observations in one recording are not independent acquisition.",
                                  "across_capture_replication": "Distinct declared captures need source-lineage and design checks; filenames are not evidence of independence.",
                                  "independent_session_replication": "Separate original acquisitions with compatible predeclared hypotheses and controls; local declarations cannot prove independence."},
            "limitations": ["No combined score, p-value, effect size, FDR or pooled significance is computed.",
                            "The criterion concerns the same primary-metric outcome, not recurrence of a particular glyph, spatial feature or meaning.",
                            "Original acquisition hashes and independence are declarations. Re-encoded/nonoverlapping derivatives may escape byte checks; truthful lineage is essential.",
                            "Local pre-run commitments cannot establish external preregistration or rule out prior knowledge, selective reporting, repeated runs or omitted sessions.",
                            "Missing designs or empirical comparisons are not null findings. Frame persistence cannot promote evidence to replication.",
                            "This summary omits original IDs, paths, dates, raw media/hashes, free-text metadata, OCR text and private reports. Review before sharing."],
            "_snapshot_sha256": sha256_json(snapshots)}


def public_comparison(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def export_comparison(experiment_dirs: list[Path], output_path: Path, *, privacy_acknowledged: bool = False,
                      expected_snapshot: str | None = None) -> Path:
    if privacy_acknowledged is not True:
        raise ValueError("Review the pseudonymized session summary and acknowledge privacy before export.")
    summary = compare_sessions(experiment_dirs)
    if expected_snapshot is not None and summary["_snapshot_sha256"] != expected_snapshot:
        raise ValueError("A session changed since review. Compare and review it again before export.")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(public_comparison(summary), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def comparison_html(summary: dict[str, Any]) -> str:
    esc = lambda value: html.escape(str(value if value is not None else "n/a"))
    text = "<h2>Local session comparison</h2><p><strong>" + esc(summary["message"]) + "</strong></p>"
    text += "<p>Positive outcomes: " + esc(summary["positive_session_count"]) + "/" + esc(summary["session_count"]) + "; tested null outcomes: " + esc(summary["null_session_count"]) + ". No pooled significance is computed.</p>"
    text += "<table border='1' cellpadding='5'><tr><th>Session</th><th>Outcome</th><th>Declared pairs</th><th>Empirical captures</th><th>Frames / probes</th><th>Frame persistence</th><th>Protocol / metric</th></tr>"
    for session in summary["sessions"]:
        text += "<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (session["session"], session["outcome"], session["independent_pair_count"], session["empirical_capture_count"], session["frame_count"], session["mean_frame_persistence"], session["protocol"] + " / " + session["primary_metric"])) + "</tr>"
    text += "</table>"
    for session in summary["sessions"]:
        text += "<p>" + esc(session["session"]) + ": camera " + esc(session["metadata_status"]["camera"]) + "; geometry " + esc(session["metadata_status"]["laser_to_target_geometry_notes"]) + "; Pair Quality " + esc(session["pair_quality"]) + "; processing " + esc(session["preprocessing_profile"]) + "; detector settings recorded: " + str(len(session["detectors"])) + ".</p>"
    text += "<h3>Compatibility and limitations</h3><ul>"
    for check in sorted(summary["compatibility"], key=lambda value: {"mismatch": 0, "unknown": 1, "matched": 2}.get(value["status"], 1)):
        text += "<li><strong>" + esc(check["status"].capitalize()) + ":</strong> " + esc(check["message"]) + "</li>"
    text += "</ul><h3>What replication means here</h3><ul>" + "".join("<li><strong>" + esc(key.replace("_", " ")) + ":</strong> " + esc(value) + "</li>" for key, value in summary["replication_terms"].items()) + "</ul>"
    text += "<ul>" + "".join("<li>" + esc(value) + "</li>" for value in summary["limitations"]) + "</ul>"
    return text
