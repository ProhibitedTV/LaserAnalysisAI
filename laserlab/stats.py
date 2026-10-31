"""Source-separated diagnostics and independent capture-pair inference."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean, pstdev
from typing import Any

from .capture_inference import STATISTICS_VERSION, paired_capture_inference, sample_class


def summarize_blinded_results(sample_results: list[dict[str, Any]], primary_metric: str = "structure_score") -> dict[str, Any]:
    scores = _sample_scores(sample_results)
    positives = [r["score"] for r in scores if r.get("unblinded_label") == "synthetic_positive"]
    return {
        "statistics_version": STATISTICS_VERSION,
        "sample_count": len(scores) - len(positives), "laser_count": None, "control_count": None,
        "synthetic_positive_count": len(positives), "calibration_passed": bool(positives and max(positives) > .05),
        "primary_metric": primary_metric, "laser_mean_score": None, "control_mean_score": None,
        "synthetic_positive_mean_score": _mean(positives),
        "laser_confidence_interval": _descriptive([]), "control_confidence_interval": _descriptive([]),
        "mean_difference": None, "cohen_d": None, "permutation_p_value": None,
        "candidate_q_values": {}, "minimum_q_value": None, "fdr_method": "not_estimated_related_candidates",
        "laser_mean_persistence": None, "detector_family_statistics": {}, "control_diagnostics": {"sealed": True},
        "inference": {"status": "sealed", "message": "Source roles and independent-unit counts remain sealed. Repeated frames are descriptive observations, not independent experiments."},
        "evidence_ladder": "blinded review",
        "null_result_language": "Source roles are sealed. Inspect candidates before explicitly unblinding. Suitable empirical controls and independent capture repeats are required for inference; candidate-level FDR is not estimated.",
    }


def summarize_results(sample_results: list[dict[str, Any]], seed: int, permutations: int = 10000,
                      primary_metric: str = "structure_score") -> dict[str, Any]:
    frames = _sample_scores(sample_results)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        groups[sample_class(frame)].append(frame)
    laser, controls = groups["empirical_laser"], groups["declared_matched_control"]
    positives = [r["score"] for r in groups["synthetic_positive"]]
    inference = paired_capture_inference(frames, seed, permutations)
    tested = inference["status"] == "tested"
    laser_mean = inference.get("laser_mean") if tested else _mean([r["score"] for r in laser])
    control_mean = inference.get("control_mean") if tested else _mean([r["score"] for r in controls])
    stats = {
        "statistics_version": STATISTICS_VERSION, "sample_count": len(frames),
        "laser_count": len(laser), "control_count": len(controls),
        "synthetic_positive_count": len(positives), "calibration_passed": bool(positives and max(positives) > .05),
        "primary_metric": primary_metric, "laser_mean_score": laser_mean, "control_mean_score": control_mean,
        "score_summary_unit": "equal-weight capture medians" if tested else "descriptive frames only; not independent n",
        "synthetic_positive_mean_score": _mean(positives),
        "laser_confidence_interval": _descriptive([r["score"] for r in laser]),
        "control_confidence_interval": _descriptive([r["score"] for r in controls]),
        "mean_difference": inference.get("mean_difference") if tested else (None if laser_mean is None or control_mean is None else laser_mean - control_mean),
        "cohen_d": inference.get("cohen_dz"), "effect_size_method": "paired Cohen dz; not a frame-level effect",
        "permutation_p_value": inference.get("p_value"), "inference": inference,
        "candidate_q_values": {}, "minimum_q_value": None, "fdr_method": "not_estimated_related_candidates",
        "laser_mean_persistence": _mean([r.get("persistence_score", 0) for r in laser]),
        "detector_family_statistics": _family_statistics(sample_results),
        "control_diagnostics": {
            kind: {"frame_count": len(records), "capture_count": len({r.get("capture_id") for r in records if r.get("capture_id")}),
                   "mean_score": _mean([r["score"] for r in records]), "used_for_inference": tested and kind == "declared_matched_control"}
            for kind, records in groups.items()
        },
    }
    stats["evidence_ladder"] = evidence_ladder(stats)
    stats["null_result_language"] = null_result_language(stats)
    if tested:
        for key, point in (("laser_confidence_interval", laser_mean), ("control_confidence_interval", control_mean)):
            stats[key] = {"mean": point, "low": None, "high": None, "count": inference["pair_count"],
                          "unit": "empirical capture", "method": "no_confidence_interval_estimated"}
    return stats


def current_statistics(run_record: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate legacy unblinded records in memory; never rewrite source results."""
    if run_record.get("aggregate_statistics", {}).get("statistics_version") == STATISTICS_VERSION:
        return run_record
    updated = dict(run_record)
    if not run_record.get("review_state", {"unblinded": True}).get("unblinded"):
        updated["aggregate_statistics"] = summarize_blinded_results(
            run_record.get("results", []), run_record.get("aggregate_statistics", {}).get("primary_metric", "structure_score")
        )
        for key in ("synthetic_positive_count", "calibration_passed", "synthetic_positive_mean_score"):
            if key in run_record.get("aggregate_statistics", {}):
                updated["aggregate_statistics"][key] = run_record["aggregate_statistics"][key]
        return updated
    updated["aggregate_statistics"] = summarize_results(
        run_record.get("results", []), int(run_record.get("blind_seed", 1)),
        primary_metric=run_record.get("aggregate_statistics", {}).get("primary_metric", "structure_score"),
    )
    updated["results"] = [{**result, "q_value": None, "source_class": sample_class(result)} for result in run_record.get("results", [])]
    updated["samples"] = [{**sample, "source_class": sample_class(sample)} for sample in run_record.get("samples", [])]
    updated["statistics_migration"] = "Legacy frame-level significance and candidate FDR are superseded. Original results and source media remain unchanged; re-run to record independent-unit provenance."
    return updated


def _sample_scores(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for result in results:
        record = grouped.setdefault(result["sample_id"], {**result, "variants": {}})
        provenance_keys = ("unblinded_label", "capture_id", "parent_capture_id", "control_type", "synthetic",
                           "source_sha256", "capture_source_sha256", "capture_metadata")
        if any(record.get(key) != result.get(key) for key in provenance_keys):
            raise ValueError("Conflicting provenance for one sample ID")
        value = float(result.get("primary_metric_score", result.get("structure_score", 0)))
        inference_value = result.get("inference_metric_score")
        if not math.isfinite(value) or (inference_value is not None and not math.isfinite(float(inference_value))):
            raise ValueError("Statistical scores must be finite")
        variant = result.get("preprocessing_variant", "legacy")
        entry = (value, None if inference_value is None else float(inference_value), float(result.get("persistence_score", 0)))
        if not math.isfinite(entry[2]):
            raise ValueError("Persistence scores must be finite")
        if variant in record["variants"] and record["variants"][variant] != entry:
            raise ValueError("Conflicting duplicate preprocessing variant")
        record["variants"][variant] = entry
    frames = []
    for record in grouped.values():
        variants = list(record.pop("variants").values())
        frames.append({**record, "score": mean(v[0] for v in variants),
                       "inference_score": None if any(v[1] is None for v in variants) else mean(v[1] for v in variants),
                       "persistence_score": mean(v[2] for v in variants)})
    return frames


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 6) if values else None


def _descriptive(values: list[float]) -> dict[str, Any]:
    return {"mean": _mean(values), "low": None, "high": None, "count": len(values),
            "unit": "descriptive observations; not independent n", "method": "descriptive_only_no_confidence_interval"}


def _family_statistics(results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for result in results:
        if sample_class(result) == "empirical_laser":
            for family, value in result.get("detector_family_scores", {}).items():
                groups[family].append(float(value))
    return {family: _descriptive(values) for family, values in groups.items()}


def evidence_ladder(stats: dict[str, Any]) -> str:
    inference = stats.get("inference", {})
    if inference.get("status") == "insufficient_independent_samples":
        return "insufficient independent samples"
    if inference.get("status") != "tested":
        return "not tested"
    difference = stats.get("mean_difference") or 0
    if difference <= .02:
        return "no signal"
    if stats["permutation_p_value"] <= .05:
        return "above-control candidate"
    return "anomaly" if difference > .05 else "artifact"


def null_result_language(stats: dict[str, Any]) -> str:
    inference = stats.get("inference", {})
    if inference.get("status") != "tested":
        return inference.get("message", "Not tested against independent empirical matched captures.")
    if stats.get("evidence_ladder") == "above-control candidate":
        return "Capture-pair scores exceeded the declared empirical matched controls under the stated exchangeability assumptions. This is a bounded candidate, not validated language or independent replication."
    return "This capture-pair comparison did not clear the selected threshold. It does not prove absence of a signal. Frame persistence is descriptive, not independent replication."


def cohen_d(group_a: list[float], group_b: list[float]) -> float | None:
    """Legacy low-level helper for independent inputs; unused for run inference."""
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    pooled = ((pstdev(group_a) ** 2 + pstdev(group_b) ** 2) / 2) ** .5
    return round((mean(group_a) - mean(group_b)) / pooled, 6) if pooled else 0.0


def permutation_p_value(group_a: list[float], group_b: list[float], seed: int, permutations: int = 1000) -> float | None:
    """Legacy independent-sample utility; run inference never shuffles frames."""
    if not group_a or not group_b:
        return None
    rng, exceed = random.Random(seed), 0
    observed = mean(group_a) - mean(group_b)
    for _ in range(permutations):
        combined = group_a + group_b
        rng.shuffle(combined)
        exceed += mean(combined[:len(group_a)]) - mean(combined[len(group_a):]) >= observed
    return round((exceed + 1) / (permutations + 1), 6)
