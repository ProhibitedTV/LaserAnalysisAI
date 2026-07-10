"""Aggregate statistics and evidence ladder."""

from __future__ import annotations

import random
from statistics import mean, pstdev
from typing import Any


def summarize_results(sample_results: list[dict[str, Any]], seed: int, permutations: int = 1000) -> dict[str, Any]:
    sample_scores = _sample_scores(sample_results)
    laser_scores = [item["score"] for item in sample_scores if item["unblinded_label"] == "laser"]
    control_scores = [item["score"] for item in sample_scores if item["unblinded_label"] == "control"]
    positive_scores = [item["score"] for item in sample_scores if item["unblinded_label"] == "synthetic_positive"]

    laser_mean = _mean(laser_scores)
    control_mean = _mean(control_scores)
    effect = cohen_d(laser_scores, control_scores)
    p_value = permutation_p_value(laser_scores, control_scores, seed=seed, permutations=permutations)
    persistence = _mean([item.get("persistence_score", 0.0) for item in sample_scores if item["unblinded_label"] == "laser"])

    stats = {
        "sample_count": len(sample_scores),
        "laser_count": len(laser_scores),
        "control_count": len(control_scores),
        "synthetic_positive_count": len(positive_scores),
        "laser_mean_score": laser_mean,
        "control_mean_score": control_mean,
        "synthetic_positive_mean_score": _mean(positive_scores),
        "mean_difference": None if laser_mean is None or control_mean is None else laser_mean - control_mean,
        "cohen_d": effect,
        "permutation_p_value": p_value,
        "laser_mean_persistence": persistence,
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
        record["scores"].append(float(result.get("structure_score", 0.0)))
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
