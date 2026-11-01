"""Measurement availability is separate from a measured low or empty result."""
from __future__ import annotations

from typing import Any

METRIC_VALIDITY_VERSION = "primary-metric-v1"


def assess_metric_result(result: dict[str, Any], primary_metric: str) -> dict[str, Any]:
    if primary_metric != "ocr_symbol_score":
        return {"version": METRIC_VALIDITY_VERSION, "status": "not_required", "reason_codes": []}
    reasons = set()
    attempts = result.get("ocr_attempts")
    if not isinstance(attempts, list) or not attempts:
        reasons.add("missing_attempts")
    else:
        for attempt in attempts:
            if not isinstance(attempt, dict) or type(attempt.get("available")) is not bool:
                reasons.add("missing_attempt_state")
            elif attempt.get("available") is not True:
                reasons.add("unavailable")
            elif "failure_reason" not in attempt or "text" not in attempt:
                reasons.add("missing_attempt_state")
            elif attempt["failure_reason"] is not None:
                reasons.add("failed")
            elif not isinstance(attempt["text"], str):
                reasons.add("null_output")
    summary = result.get("ocr")
    if not isinstance(summary, dict) or summary.get("available") is not True or not isinstance(summary.get("text"), str):
        reasons.add("missing_usable_summary")
    return {"version": METRIC_VALIDITY_VERSION, "status": "unscored" if reasons else "measured",
            "reason_codes": sorted(reasons)}


def assess_metric_frames(frames: list[dict[str, Any]], primary_metric: str) -> dict[str, Any]:
    if primary_metric != "ocr_symbol_score":
        return {"version": METRIC_VALIDITY_VERSION, "status": "not_required"}
    from .capture_inference import sample_class
    empirical = [frame for frame in frames if sample_class(frame) in {"empirical_laser", "declared_matched_control"}]
    unscored = [frame for frame in empirical if not frame["primary_metric_available"]]
    return {"version": METRIC_VALIDITY_VERSION, "status": "incomplete" if unscored else "complete" if empirical else "not_assessed",
            "scope": "empirical laser/matched sample observations; not independent n",
            "sample_observations": len(empirical), "unscored_sample_observations": len(unscored),
            "reason_codes": sorted({reason for frame in unscored for reason in frame["primary_metric_unscored_reasons"]})}
