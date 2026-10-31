"""Declared independent matched-pair inference, separate from frame diagnostics."""
from __future__ import annotations

import random
from collections import defaultdict
from itertools import product
from statistics import mean, median, stdev
from typing import Any

STATISTICS_VERSION = "paired-capture-v2"
MINIMUM_PAIRS = 5


def source_class_label(record: dict[str, Any]) -> str:
    """Human-readable provenance for explicitly unblinded candidates only."""
    kind = record.get("source_class") or sample_class(record)
    label = {
        "empirical_laser": "Empirical laser (declared)",
        "declared_matched_control": "Empirical matched control (declared)",
        "other_empirical_control": "Other empirical control",
        "sensor_noise": "Sensor-noise recording",
        "generated_null": "Generated null probe",
        "synthetic_positive": "Synthetic positive calibration",
        "synthetic_negative": "Synthetic negative calibration",
        "demonstration_fixture": "Demo/calibration fixture",
    }.get(kind, "Unverified origin")
    if kind == "generated_null" and record.get("control_type"):
        return label + " / " + str(record["control_type"])
    return label + " / " + str(record.get("unblinded_label") or "unknown role")


def sample_class(record: dict[str, Any]) -> str:
    label = record.get("unblinded_label")
    if label == "synthetic_positive":
        return "synthetic_positive"
    if label == "synthetic_negative":
        return "synthetic_negative"
    if record.get("synthetic") or record.get("control_type") or record.get("parent_capture_id"):
        return "generated_null"
    metadata = record.get("capture_metadata") or {}
    if metadata.get("fixture_id") or metadata.get("footage_class") in {"calibration_fixture", "regression_fixture", "demo_fixture"}:
        return "demonstration_fixture"
    if not record.get("capture_id") or metadata.get("footage_class") != "primary_wall_projection":
        return "unverified_origin"
    return {"laser": "empirical_laser", "matched_control": "declared_matched_control",
            "control": "other_empirical_control", "sensor_noise": "sensor_noise"}.get(label, "unverified_origin")


def paired_capture_inference(frames: list[dict[str, Any]], seed: int, resamples: int) -> dict[str, Any]:
    """Flip whole declared pairs, using one equally weighted median per capture."""
    inference: dict[str, Any] = {
        "method": "paired_capture_sign_flip", "version": STATISTICS_VERSION,
        "unit": "independent matched capture pair", "minimum_pairs": MINIMUM_PAIRS,
        "capture_aggregation": "median of unique-frame means over unique preprocessing variants; excludes persistence",
        "alternative": "greater", "seed": seed, "pair_count": 0,
        "empirical_capture_counts": {"laser": 0, "matched_control": 0},
        "status": "not_tested", "p_value": None, "cohen_dz": None,
        "confidence_interval_method": "not estimated",
        "limitations": [
            "Independence and within-pair exchangeability are user declarations; hashes cannot prove them.",
            "Candidate-level FDR and confidence intervals are not estimated for related frames/variants.",
            "Repeated runs, protocol selection and cross-session replication are not corrected or established.",
            "Optical comparability remains reported metadata; automatic pair-quality measurements are separate.",
        ],
    }

    def stop(status: str, message: str) -> dict[str, Any]:
        inference.update(status=status, message=message)
        return inference

    captures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        if sample_class(frame) in {"empirical_laser", "declared_matched_control"}:
            captures[frame["capture_id"]].append(frame)
    for records in captures.values():
        role = "laser" if sample_class(records[0]) == "empirical_laser" else "matched_control"
        inference["empirical_capture_counts"][role] += 1
    counts = inference["empirical_capture_counts"]
    if not counts["laser"] or not counts["matched_control"]:
        return stop("not_tested", "Exploratory: no empirical laser / declared matched-capture comparison. Generated nulls, fixtures, other controls and sensor noise do not establish a matched experiment.")
    pairs: dict[str, dict[str, float]] = defaultdict(dict)
    seen_sources: set[str] = set()
    seen_frames: set[str] = set()
    for records in captures.values():
        first = records[0]
        metadata = first.get("capture_metadata") or {}
        if any(metadata.get(field) is False for field in ("camera_fixed", "beam_path_fixed", "projected_region_not_saturated")):
            return stop("reported_quality_failure", "Not tested: a capture reports camera/beam motion or saturation. Review the optical comparison before claiming matched evidence.")
        pair_id = str(metadata.get("independent_pair_id") or "").strip()
        if not pair_id or metadata.get("pair_exchangeability_acknowledged") is not True:
            return stop("unverified_design", "Not tested: declare independent matched pair IDs and justify within-pair exchangeability before analysis. Collect independently acquired controlled repeats; frames are not independent experiments.")
        source = first.get("capture_source_sha256")
        if not _valid_hash(source) or any(r.get("capture_source_sha256") != source for r in records):
            return stop("unverified_provenance", "Not tested: capture-level source hashes are missing or inconsistent. Re-run the current analysis; legacy frame counts cannot establish independent captures.")
        if source in seen_sources:
            return stop("shared_source", "Not tested: captures reuse identical source bytes. Copied or resampled recordings are not independent repeats.")
        seen_sources.add(source)
        unique: dict[str, set[float]] = defaultdict(set)
        for frame in records:
            frame_hash = frame.get("source_sha256")
            if not _valid_hash(frame_hash) or frame.get("inference_score") is None:
                return stop("unverified_provenance", "Not tested: independent-unit scores or frame hashes are missing. Re-run the current analysis without changing detector settings.")
            unique[frame_hash].add(frame["inference_score"])
        if seen_frames.intersection(unique):
            return stop("shared_frames", "Not tested: captures share identical frame bytes. Independent acquisition cannot be inferred from different filenames or capture IDs.")
        seen_frames.update(unique)
        role = "laser" if sample_class(first) == "empirical_laser" else "matched_control"
        if role in pairs[pair_id]:
            return stop("invalid_pairs", "Not tested: each independent pair must contain exactly one laser capture and one declared matched control. Unequal or ambiguous capture sets are not pooled.")
        pairs[pair_id][role] = median(mean(sorted(scores)) for scores in unique.values())
    if any(set(pair) != {"laser", "matched_control"} for pair in pairs.values()):
        return stop("incomplete_pairs", "Not tested: independent pairs are incomplete. Add their matched captures; unmatched captures are not silently discarded.")
    inference["pair_count"] = len(pairs)
    if len(pairs) < MINIMUM_PAIRS:
        return stop("insufficient_independent_samples", "Insufficient independent samples: collect at least five independently acquired, exchangeable matched capture pairs. Extra frames or preprocessing variants do not increase this number.")
    ordered = [pairs[key] for key in sorted(pairs)]
    differences = [pair["laser"] - pair["matched_control"] for pair in ordered]
    observed = mean(differences)
    tolerance = max(1.0, abs(observed)) * 1e-12
    if len(differences) <= 16:
        total = 2 ** len(differences)
        exceed = sum(mean(d * sign for d, sign in zip(differences, signs)) >= observed - tolerance
                     for signs in product((-1, 1), repeat=len(differences)))
        p_value = exceed / total
        inference.update(permutation_mode="exact", permutations=total)
    else:
        total = max(1, int(resamples))
        rng = random.Random(seed)
        exceed = sum(mean(d * rng.choice((-1, 1)) for d in differences) >= observed - tolerance for _ in range(total))
        p_value = (exceed + 1) / (total + 1)
        inference.update(permutation_mode="monte_carlo_plus_one", permutations=total)
    spread = stdev(differences)
    inference.update(
        status="tested", message="Compared declared independent matched pairs; frame persistence remains descriptive, not independent replication.",
        laser_mean=mean(pair["laser"] for pair in ordered), control_mean=mean(pair["matched_control"] for pair in ordered),
        mean_difference=observed, p_value=p_value, cohen_dz=(observed / spread if spread > tolerance else None),
        effect_size_method="paired Cohen dz; undefined when pair differences have zero variance",
    )
    return inference


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
