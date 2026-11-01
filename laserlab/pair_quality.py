"""Bounded, local setup diagnostics; these do not validate an optical experiment."""
from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from typing import Any

from .capture_inference import sample_class

PAIR_QUALITY_VERSION = "pair-quality-v1"
MAX_SAMPLE_FRAMES = 3
MAX_SAMPLE_EDGE = 256


def inspect_pair(experiment_dir: Path, manifest: dict[str, Any], laser_capture_id: str,
                 control_capture_id: str) -> dict[str, Any]:
    """Inspect already-imported frames without changing the manifest or reading videos."""
    if manifest.get("outputs", {}).get("review_state") == "blinded":
        raise ValueError("Pair Quality is unavailable during sealed review. Explicitly unblind first.")
    if not laser_capture_id or not control_capture_id or laser_capture_id == control_capture_id:
        raise ValueError("Select two distinct imported captures for Pair Quality.")
    captures = manifest.get("captures", [])
    selected = []
    for capture_id in (laser_capture_id, control_capture_id):
        matches = [capture for capture in captures if capture.get("capture_id") == capture_id]
        if len(matches) != 1:
            raise ValueError("Each selected capture must exist exactly once in this experiment.")
        selected.append(matches[0])
    laser, control = selected
    checks: list[dict[str, Any]] = []

    def add(key: str, label: str, status: str, left: Any, right: Any, message: str,
            approximate: bool = False) -> None:
        check = {"key": key, "label": label, "status": status, "laser": left,
                 "control": right, "message": message}
        if approximate:
            check["approximate"] = True
        checks.append(check)

    classes = [_capture_class(capture) for capture in selected]
    eligible = classes == ["empirical_laser", "declared_matched_control"]
    add("source_type", "Recorded comparison roles", "matched" if eligible else "mismatch",
        classes[0], classes[1],
        "Declared empirical laser and matched-control recordings; labels do not prove comparability."
        if eligible else "Select an empirical laser recording and a declared matched control. Generated probes, fixtures, unrelated controls and sensor noise do not establish this comparison.")
    sources = {source.get("source_id"): source for source in manifest.get("sources", [])}
    source_hashes = [sources.get(capture.get("source_id"), {}).get("sha256") for capture in selected]
    valid_sources = all(_valid_hash(value) for value in source_hashes)
    same_source = valid_sources and source_hashes[0] == source_hashes[1]
    add("source_provenance", "Source provenance", "mismatch" if same_source else "matched" if valid_sources else "unknown",
        "hash recorded" if _valid_hash(source_hashes[0]) else "missing hash",
        "hash recorded" if _valid_hash(source_hashes[1]) else "missing hash",
        "The captures reuse identical source bytes; copies are not independent recordings." if same_source else
        "Different source hashes do not prove independent acquisition." if valid_sources else
        "Source hashes are missing; provenance cannot be compared.")
    hashes = [{frame.get("source_sha256") for frame in capture.get("frames", [])
               if _valid_hash(frame.get("source_sha256"))} for capture in selected]
    all_frames_hashed = all(capture.get("frames") and all(_valid_hash(frame.get("source_sha256"))
                            for frame in capture["frames"]) for capture in selected)
    shared_frames = bool(hashes[0] & hashes[1])
    add("shared_frames", "Copied frame check", "mismatch" if shared_frames else "matched" if all_frames_hashed else "unknown",
        "frame hashes recorded" if hashes[0] else "missing hashes",
        "frame hashes recorded" if hashes[1] else "missing hashes",
        "The captures share identical imported frame bytes; do not treat them as independent repeats."
        if shared_frames else "No identical imported frame hashes were found; re-encoded derivatives may remain undetected."
        if all_frames_hashed else "Some imported frame hashes are missing; copied frames cannot be ruled out.")

    media = [capture.get("media_metadata") or {} for capture in selected]
    kinds = [capture.get("kind") or info.get("source_kind") for capture, info in zip(selected, media)]
    add("media_kind", "Media type", "matched" if kinds[0] == kinds[1] and kinds[0] in {"video", "image-set"} else "mismatch"
        if all(kinds) else "unknown", kinds[0] or "unknown", kinds[1] or "unknown",
        "Compare the original recording types; image sets do not establish a video frame rate.")
    resolutions = [(_positive(info.get("width")), _positive(info.get("height"))) for info in media]
    _compare(add, "resolution", "Resolution", resolutions[0] if all(resolutions[0]) else None,
             resolutions[1] if all(resolutions[1]) else None,
             "Different resolutions can change visible detail; use comparable original recordings.")
    images_only = kinds == ["image-set", "image-set"]
    for key, label in (("fps", "Frame rate"), ("duration_ms", "Duration"), ("frame_count", "Source frame count")):
        if images_only and key in {"fps", "duration_ms"}:
            add(key, label, "matched", "not applicable", "not applicable", "Image sets have no declared video timing.")
            continue
        values = [_positive(info.get("image_count" if images_only and key == "frame_count" else key)) for info in media]
        tolerance = .01 if key == "fps" else .05
        _compare(add, key, label, *values,
                 "Source counts/duration describe coverage, not independent replication. Unequal capture sampling is not itself proof of invalid inference."
                 if key != "fps" else "Different frame rates change temporal sampling; check the recording settings.", tolerance=tolerance)
        if key in {"duration_ms", "frame_count"} and all(value is not None for value in values):
            checks[-1]["descriptive"] = True
    codecs = [info.get("formats") if images_only else info.get("codec") for info in media]
    _compare(add, "codec", "Codec / image format", *codecs,
             "Different encoding can introduce different artifacts. Matching codec names do not prove equal compression.", text=True)

    metadata = [capture.get("metadata") or {} for capture in selected]
    pair_ids = [item.get("independent_pair_id") for item in metadata]
    declared_ids = all(isinstance(value, str) and value.strip() for value in pair_ids)
    acknowledged = all(item.get("pair_exchangeability_acknowledged") is True for item in metadata)
    add("independent_design", "Independent pair declaration",
        "mismatch" if declared_ids and pair_ids[0] != pair_ids[1] else "matched" if declared_ids and acknowledged else "unknown",
        *["declared" if isinstance(value, str) and value.strip() else "unknown" for value in pair_ids],
        "Use the same predeclared non-identifying pair ID and justify within-pair exchangeability. These declarations cannot establish independence; five independent pairs are required for inference.")
    text_fields = (("camera", "Camera / device"), ("exposure", "Exposure settings"),
                   ("focus_mode", "Focus settings"), ("compression_history", "Compression history"),
                   ("projection_surface_type", "Projection surface"),
                   ("laser_to_target_geometry_notes", "Optical geometry"),
                   ("intermediate_material_notes", "Intermediate material"),
                   ("room_lighting_notes", "Room lighting"))
    for key, label in text_fields:
        _compare(add, key, label, metadata[0].get(key), metadata[1].get(key),
                 f"Record comparable {label.lower()} for both captures. Different wording requires manual review; matching declarations are not measurements.", text=True)
        automatic_modes = {"auto", "automatic", "continuous auto", "autofocus", "auto focus", "auto exposure", "continuous autofocus"}
        if key in {"exposure", "focus_mode"} and any(
            isinstance(item.get(key), str) and item[key].strip().casefold() in automatic_modes for item in metadata
        ):
            checks[-1].update(status="unknown", message="Automatic exposure or focus mode does not verify equal capture settings. Actual comparable settings were not established.")
    _compare(add, "projection_distance_meters", "Projection distance", *[_positive(item.get("projection_distance_meters")) for item in metadata],
             "Check the recorded geometry; missing distances remain unknown.", tolerance=.01)
    for key, label in (("camera_fixed", "Fixed camera"), ("beam_path_fixed", "Fixed optical geometry"),
                       ("non_reflective_surface", "Non-reflective target"),
                       ("projected_region_not_saturated", "Reported unclipped projection")):
        values = [item.get(key) for item in metadata]
        status = "mismatch" if any(value is False for value in values) else "matched" if all(value is True for value in values) else "unknown"
        add(key, label, status, *["yes" if value is True else "no" if value is False else "unknown" for value in values],
            "A reported problem requires review; unknown is not confirmation that conditions were matched.")

    observations = {side: _observe_frames(Path(experiment_dir), capture) for side, capture in zip(("laser", "control"), selected)}
    for key, label in (("sample_readability", "Imported preview frames"), ("clipping", "Approximate channel clipping"),
                       ("motion", "Approximate frame motion")):
        left, right = observations["laser"], observations["control"]
        if key == "sample_readability":
            status = "matched" if all(item["sampled_frame_count"] == item["attempted_frame_count"] and item["sampled_frame_count"] > 0 for item in (left, right)) else "unknown"
            values = [f"{item['sampled_frame_count']}/{item['attempted_frame_count']} readable" for item in (left, right)]
            message = "Only first/middle/last imported frames are inspected. Missing or out-of-folder paths are never followed."
        elif key == "clipping":
            fractions = [item["clipped_channel_fraction"] for item in (left, right)]
            status = "mismatch" if any(value is not None and value >= .02 for value in fractions) else "matched" if all(value is not None for value in fractions) else "unknown"
            values = fractions
            message = "Approximate fraction of preview pixels with any channel >=250/255. This is a clipping warning, not a calibrated sensor measurement; small clipped regions can be missed."
        else:
            values = [item["motion"]["status"] for item in (left, right)]
            status = "mismatch" if "motion_warning" in values else "matched" if values == ["no_large_shift_detected", "no_large_shift_detected"] else "unknown"
            message = "Approximate phase correlation within each capture, only when texture and confidence are sufficient. Stable image shifts do not establish fixed camera geometry."
        add(key, label, status, *values, message, approximate=key != "sample_readability")
    histograms = [observations[side]["brightness_histogram"] for side in ("laser", "control")]
    add("brightness", "Approximate brightness distribution", "unknown", *histograms,
        "Brightness is descriptive: laser and control intensities need not be identical. Similar histograms do not verify exposure or optical matching.", approximate=True)
    # Different brightness and unequal coverage are descriptive, not violations of capture-level inference.
    decision_checks = [check for check in checks if check["key"] != "brightness" and not check.get("descriptive")]
    status = "mismatch" if any(check["status"] == "mismatch" for check in decision_checks) else "unknown" if any(check["status"] == "unknown" for check in decision_checks) else "consistent"
    summary = {"mismatch": "Comparison problems found. Review the listed differences; proceed only as exploratory until resolved.",
               "unknown": "Some comparison details are unknown. Review what is missing; this check cannot establish a fair comparison.",
               "consistent": "Recorded details and bounded previews are consistent. This does not validate matching, independence or experimental evidence."}[status]
    return {"version": PAIR_QUALITY_VERSION, "laser_capture_id": laser_capture_id,
            "control_capture_id": control_capture_id, "status": status, "summary": summary, "checks": checks,
            "observations": observations,
            "warnings": [check["message"] for check in decision_checks if check["status"] != "matched"],
            "limitations": ["Setup diagnostics only; no detector scores, source roles or capture metadata are changed.",
                            "At most three already-imported frames per capture are decoded and resized to a maximum 256-pixel edge; no source video is opened.",
                            "Imported frames may omit motion or clipping elsewhere in the original recording. Heuristics can be wrong.",
                            "Matching declarations and different hashes do not prove independent acquisition or within-pair exchangeability.",
                            "These observations do not replace the independent-pair inference requirements."]}


def assess_experiment(experiment_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Assess every declared pair without inventing pairings or acquisition facts."""
    if manifest.get("outputs", {}).get("review_state") == "blinded":
        raise ValueError("Pair Quality is unavailable during sealed review. Explicitly unblind first.")
    relevant = [capture for capture in manifest.get("captures", [])
                if capture.get("label") in {"laser", "matched_control"}]
    checks = []
    pairs = []
    groups: dict[str, list[dict[str, Any]]] = {}
    unassigned = []
    for capture in relevant:
        pair_id = (capture.get("metadata") or {}).get("independent_pair_id")
        if isinstance(pair_id, str) and pair_id.strip():
            groups.setdefault(pair_id.strip(), []).append(capture)
        else:
            unassigned.append(capture)
    # The one obvious legacy comparison is useful descriptively, with design unknown.
    if not groups and len(unassigned) == 2 and {item.get("label") for item in unassigned} == {"laser", "matched_control"}:
        groups[""] = unassigned
        unassigned = []
    if unassigned:
        checks.append({"key": "unassigned_captures", "label": "Capture pairing", "status": "unknown",
                       "laser": sum(item.get("label") == "laser" for item in unassigned),
                       "control": sum(item.get("label") == "matched_control" for item in unassigned),
                       "message": "Some recordings have no declared pair mapping. Select pair IDs before claiming a complete matched design; no mappings were invented."})
    for captures in groups.values():
        lasers = [item for item in captures if item.get("label") == "laser"]
        controls = [item for item in captures if item.get("label") == "matched_control"]
        if len(lasers) != 1 or len(controls) != 1:
            checks.append({"key": "ambiguous_pair", "label": "Declared pair mapping", "status": "unknown",
                           "laser": len(lasers), "control": len(controls),
                           "message": "Each declared pair must have exactly one laser and one matched control. Incomplete or ambiguous groups are not silently pooled."})
            continue
        try:
            pairs.append(inspect_pair(experiment_dir, manifest, lasers[0].get("capture_id"), controls[0].get("capture_id")))
        except ValueError:
            checks.append({"key": "invalid_capture_ids", "label": "Capture identity", "status": "unknown",
                           "laser": "invalid", "control": "invalid", "message": "Capture IDs are missing or ambiguous; re-import or repair the experiment before comparison."})
    if not relevant or not groups:
        checks.append({"key": "missing_comparison", "label": "Recorded matched comparison", "status": "unknown",
                       "laser": sum(item.get("label") == "laser" for item in relevant),
                       "control": sum(item.get("label") == "matched_control" for item in relevant),
                       "message": "No complete empirical laser / declared matched-control pair is available. Generated probes, fixtures and unrelated controls do not supply a matched experiment."})
    # Detect duplicate media across different declared pairs as well as within a pair.
    source_map = {item.get("source_id"): item for item in manifest.get("sources", [])}
    sources_seen = set()
    frames_seen = set()
    copied = False
    for capture in relevant:
        source_hash = source_map.get(capture.get("source_id"), {}).get("sha256")
        frame_hashes = {frame.get("source_sha256") for frame in capture.get("frames", [])
                        if _valid_hash(frame.get("source_sha256"))}
        if (_valid_hash(source_hash) and source_hash in sources_seen) or frames_seen & frame_hashes:
            copied = True
        if _valid_hash(source_hash):
            sources_seen.add(source_hash)
        frames_seen.update(frame_hashes)
    if copied:
        checks.append({"key": "shared_experiment_sources", "label": "Independent acquisition provenance", "status": "mismatch",
                       "laser": "shared source or frame bytes", "control": "shared source or frame bytes",
                       "message": "Recordings in this experiment share identical source or frame bytes, including across declared pairs. Copies do not establish independent repeats."})
    statuses = [item["status"] for item in checks] + [item["status"] for item in pairs]
    status = "mismatch" if "mismatch" in statuses else "unknown" if "unknown" in statuses or not pairs else "consistent"
    return {"version": PAIR_QUALITY_VERSION, "status": status,
            "summary": {"mismatch": "Comparison problems found across the selected experiment. Resolve differences or proceed as exploratory.",
                        "unknown": "The experiment has missing or ambiguous comparison details. Proceed as exploratory until the design and conditions are established.",
                        "consistent": "All declared pair details and bounded previews are consistent. This is not validation of matching, independence or experimental evidence."}[status],
            "pairs": pairs, "checks": checks, "requires_exploratory": status != "consistent",
            "limitations": ["Pair mappings are declarations, not inferred or verified acquisitions.",
                            "All laser and declared matched-control captures must be assigned unambiguously. Other controls and generated diagnostics cannot substitute.",
                            "At most three imported frames are inspected per capture; work scales with imported capture pairs, not video duration.",
                            "Different hashes cannot prove independence. Re-encoded derivatives may escape duplicate checks.",
                            "Pair Quality does not establish significance, statistical power or independent-session replication."]}


def _capture_class(capture: dict[str, Any]) -> str:
    return sample_class({"capture_id": capture.get("capture_id"), "unblinded_label": capture.get("label"),
                         "capture_metadata": capture.get("metadata") or {}, "synthetic": capture.get("synthetic", False),
                         "control_type": capture.get("control_type"), "parent_capture_id": capture.get("parent_capture_id")})


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _known(value: Any) -> bool:
    return value is not None and str(value).strip().casefold() not in {"", "unknown", "not recorded", "not known", "unspecified", "n/a", "[]"}


def _compare(add: Any, key: str, label: str, left: Any, right: Any, message: str,
             *, tolerance: float = 0, text: bool = False) -> None:
    if not _known(left) or not _known(right):
        status = "unknown"
    elif text:
        status = "matched" if str(left).strip().casefold() == str(right).strip().casefold() else "mismatch"
    elif tolerance:
        status = "matched" if abs(left - right) <= max(abs(left), abs(right)) * tolerance else "mismatch"
    else:
        status = "matched" if left == right else "mismatch"
    # Free-text declarations may include names, locations or other private context.
    display = ["recorded" if _known(value) else "unknown" for value in (left, right)] if text else [left, right]
    add(key, label, status, *display, message)


def _observe_frames(experiment_dir: Path, capture: dict[str, Any]) -> dict[str, Any]:
    import cv2
    import numpy as np

    frames = capture.get("frames") or []
    indices = sorted({0, len(frames) // 2, len(frames) - 1}) if frames else []
    images = []
    clipped = []
    root = experiment_dir.resolve()
    for index in indices[:MAX_SAMPLE_FRAMES]:
        stored = frames[index].get("path")
        if not isinstance(stored, str) or not stored:
            continue
        try:
            path = (root / stored).resolve()
            path.relative_to(root)
        except (OSError, ValueError, RuntimeError):
            continue
        # Never accept the original source: only the experiment's imported frames tree.
        try:
            path.relative_to((root / "frames").resolve())
        except (OSError, ValueError, RuntimeError):
            continue
        if not path.is_file():
            continue
        try:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        except (cv2.error, OSError):
            continue
        if image is None or not image.size:
            continue
        # Measure original imported channels before resizing can average clipped pixels away.
        clipped.append(float(np.mean(np.any(image >= 250, axis=2))))
        height, width = image.shape[:2]
        scale = min(1.0, MAX_SAMPLE_EDGE / max(height, width))
        image = cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
        images.append(image)
    histograms = []
    gray_images = []
    for image in images:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_images.append(gray.astype(np.float32))
        histogram, _ = np.histogram(gray, bins=8, range=(0, 256))
        histograms.append(histogram / gray.size)
    motion = {"status": "unknown", "reliable_comparisons": 0, "maximum_shift_fraction": None}
    shifts = []
    for reference, moving in zip(gray_images, gray_images[1:]):
        if reference.shape != moving.shape or min(reference.shape) < 16:
            continue
        if min(float(reference.std()), float(moving.std())) < 3:
            continue
        try:
            window = cv2.createHanningWindow((reference.shape[1], reference.shape[0]), cv2.CV_32F)
            # OpenCV applies the window in-place; protect the middle frame reused
            # as the reference in the next adjacent comparison.
            (dx, dy), response = cv2.phaseCorrelate(reference.copy(), moving.copy(), window)
        except cv2.error:
            continue
        if not all(math.isfinite(value) for value in (dx, dy, response)) or response < .3:
            continue
        shifts.append(math.hypot(dx, dy) / min(reference.shape))
    if shifts and len(shifts) == len(gray_images) - 1:
        maximum = max(shifts)
        motion = {"status": "motion_warning" if maximum > .02 else "no_large_shift_detected",
                  "reliable_comparisons": len(shifts), "maximum_shift_fraction": round(maximum, 6)}
    return {"capture_id": capture.get("capture_id"), "attempted_frame_count": len(indices),
            "sampled_frame_count": len(images), "max_dimension": MAX_SAMPLE_EDGE,
            "clipped_channel_fraction": round(mean(clipped), 6) if clipped else None,
            "brightness_histogram": [round(float(value), 6) for value in np.mean(histograms, axis=0)] if histograms else None,
            "motion": motion}
