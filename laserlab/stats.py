"""Aggregate statistics and evidence ladder."""

from __future__ import annotations

import random
from statistics import mean, pstdev
from typing import Any

from .scientific import benjamini_hochberg_q_values, mean_confidence_interval


def summarize_blinded_results(
    sample_results: list[dict[str, Any]],
    primary_metric: str = "structure_score",
) -> dict[str, Any]:
    sample_scores = _sample_scores(sample_results)
    positive_scores = [item["score"] for item in sample_scores if item["unblinded_label"] == "synthetic_positive"]
    review_scores = [item for item in sample_scores if item["unblinded_label"] != "synthetic_positive"]
    return {
        "sample_count": len(review_scores),
        "laser_count": None,
        "control_count": None,
        "synthetic_positive_count": len(positive_scores),
        "calibration_passed": bool(positive_scores and max(positive_scores) > 0.05),
        "primary_metric": primary_metric,
        "laser_mean_score": None,
        "control_mean_score": None,
        "synthetic_positive_mean_score": _mean(positive_scores),
        "laser_confidence_interval": {"mean": None, "low": None, "high": None, "count": 0},
        "control_confidence_interval": {"mean": None, "low": None, "high": None, "count": 0},
        "mean_difference": None,
        "cohen_d": None,
        "permutation_p_value": None,
        "fdr_method": "deferred_until_unblind",
        "candidate_q_values": {},
        "minimum_q_value": None,
        "laser_mean_persistence": None,
        "detector_family_statistics": {},
        "evidence_ladder": "blinded review",
        "null_result_language": (
            "Source roles are sealed. Review candidate structure without attribution, then explicitly unblind "
            "to compute matched-control statistics and the evidence ladder."
        ),
    }


def summarize_results(
    sample_results: list[dict[str, Any]],
    seed: int,
    permutations: int = 1000,
    primary_metric: str = "structure_score",
) -> dict[str, Any]:
    sample_scores = _sample_scores(sample_results)
    laser_scores = [item["score"] for item in sample_scores if _statistical_role(item["unblinded_label"]) == "laser"]
    control_scores = [item["score"] for item in sample_scores if _statistical_role(item["unblinded_label"]) == "control"]
    positive_scores = [item["score"] for item in sample_scores if item["unblinded_label"] == "synthetic_positive"]
    candidate_p_values = _candidate_p_values(sample_scores, control_scores)
    q_values = benjamini_hochberg_q_values([item["p_value"] for item in candidate_p_values])
    candidate_q_values = {
        item["sample_id"]: q_value for item, q_value in zip(candidate_p_values, q_values)
    }

    laser_mean = _mean(laser_scores)
    control_mean = _mean(control_scores)
    effect = cohen_d(laser_scores, control_scores)
    p_value = permutation_p_value(laser_scores, control_scores, seed=seed, permutations=permutations)
    persistence = _mean([item.get("persistence_score", 0.0) for item in sample_scores if _statistical_role(item["unblinded_label"]) == "laser"])

    stats = {
        "sample_count": len(sample_scores),
        "laser_count": len(laser_scores),
        "control_count": len(control_scores),
        "synthetic_positive_count": len(positive_scores),
        "calibration_passed": bool(positive_scores and max(positive_scores) > 0.05),
        "primary_metric": primary_metric,
        "laser_mean_score": laser_mean,
        "control_mean_score": control_mean,
        "synthetic_positive_mean_score": _mean(positive_scores),
        "laser_confidence_interval": mean_confidence_interval(laser_scores),
        "control_confidence_interval": mean_confidence_interval(control_scores),
        "mean_difference": None if laser_mean is None or control_mean is None else laser_mean - control_mean,
        "cohen_d": effect,
        "permutation_p_value": p_value,
        "fdr_method": "benjamini_hochberg",
        "candidate_q_values": candidate_q_values,
        "minimum_q_value": min(candidate_q_values.values()) if candidate_q_values else None,
        "laser_mean_persistence": persistence,
        "detector_family_statistics": _family_statistics(sample_results),
    }
    stats["evidence_ladder"] = evidence_ladder(stats)
    stats["null_result_language"] = null_result_language(stats)
    return stats


def _sample_scores(sample_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for result in sample_results:
        sample_id = result["sample_id"]
        record = grouped.setdefault(
            sample_id,
            {
                "sample_id": sample_id,
                "blind_id": result["blind_id"],
                "unblinded_label": result["unblinded_label"],
                "scores": [],
                "persistence_scores": [],
            },
        )
        record["scores"].append(float(result.get("primary_metric_score", result.get("structure_score", 0.0))))
        record["persistence_scores"].append(float(result.get("persistence_score", 0.0)))

    scores = []
    for record in grouped.values():
        scores.append(
            {
                "sample_id": record["sample_id"],
                "blind_id": record["blind_id"],
                "unblinded_label": record["unblinded_label"],
                "score": mean(record["scores"]) if record["scores"] else 0.0,
                "persistence_score": mean(record["persistence_scores"]) if record["persistence_scores"] else 0.0,
            }
        )
    return scores


def _mean(values: list[float]) -> float | None:
    return round(float(mean(values)), 6) if values else None


def cohen_d(group_a: list[float], group_b: list[float]) -> float | None:
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    std_a = pstdev(group_a)
    std_b = pstdev(group_b)
    pooled = ((std_a**2 + std_b**2) / 2) ** 0.5
    if pooled == 0:
        return 0.0
    return round(float((mean(group_a) - mean(group_b)) / pooled), 6)


def permutation_p_value(
    group_a: list[float],
    group_b: list[float],
    seed: int,
    permutations: int = 1000,
) -> float | None:
    if not group_a or not group_b:
        return None
    observed = mean(group_a) - mean(group_b)
    combined = group_a + group_b
    rng = random.Random(seed)
    count = 0
    for _ in range(permutations):
        shuffled = combined[:]
        rng.shuffle(shuffled)
        candidate_a = shuffled[: len(group_a)]
        candidate_b = shuffled[len(group_a) :]
        if mean(candidate_a) - mean(candidate_b) >= observed:
            count += 1
    return round(float((count + 1) / (permutations + 1)), 6)


def _candidate_p_values(sample_scores: list[dict[str, Any]], control_scores: list[float]) -> list[dict[str, Any]]:
    if not control_scores:
        return [{"sample_id": item["sample_id"], "p_value": 1.0} for item in sample_scores]
    records = []
    for item in sample_scores:
        greater_equal = sum(1 for control in control_scores if control >= item["score"])
        p_value = (greater_equal + 1) / (len(control_scores) + 1)
        records.append({"sample_id": item["sample_id"], "p_value": round(float(p_value), 6)})
    return records


def _family_statistics(sample_results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {"symbol": [], "diffraction": [], "speckle": [], "texture": []}
    for result in sample_results:
        if _statistical_role(result.get("unblinded_label")) != "laser":
            continue
        for family, value in result.get("detector_family_scores", {}).items():
            grouped.setdefault(family, []).append(float(value))
    return {family: mean_confidence_interval(values) for family, values in grouped.items()}


def _statistical_role(label: str | None) -> str:
    if label == "laser":
        return "laser"
    if label in {"control", "matched_control", "sensor_noise", "synthetic_negative"}:
        return "control"
    return "calibration" if label == "synthetic_positive" else "other"


def evidence_ladder(stats: dict[str, Any]) -> str:
    if not stats.get("laser_count") or not stats.get("control_count"):
        return "no signal"
    difference = stats.get("mean_difference") or 0.0
    p_value = stats.get("permutation_p_value")
    effect = stats.get("cohen_d")
    persistence = stats.get("laser_mean_persistence") or 0.0

    if difference <= 0.02:
        return "no signal"
    if p_value is None or effect is None:
        return "anomaly"
    if p_value <= 0.05 and effect >= 0.5 and persistence >= 0.15:
        return "repeatable candidate"
    if p_value <= 0.05 and effect >= 0.5:
        return "above-control candidate"
    if difference > 0.05:
        return "anomaly"
    return "artifact"


def null_result_language(stats: dict[str, Any]) -> str:
    ladder = stats.get("evidence_ladder")
    if ladder in {"above-control candidate", "repeatable candidate"}:
        return (
            "This run found structure scores above matched controls. Treat this as a candidate "
            "finding until it repeats across new blinded captures."
        )
    if ladder == "anomaly":
        return (
            "This run found elevated structure scores, but the evidence did not clear the "
            "configured blinded control threshold."
        )
    return (
        "This run did not find structured detections above matched controls. That does not "
        "prove absence of signal; it means this capture and detector set did not beat the null."
    )
