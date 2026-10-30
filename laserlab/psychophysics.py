"""Dependency-free psychophysics helpers for conservative yes/no SDT analysis.

This module deliberately treats participant responses and automated detector
output as separate evidence domains.  It quantifies a pre-declared yes/no task;
it does not infer the origin or meaning of a stimulus.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from statistics import NormalDist, fmean
from typing import Any, Iterable, Mapping, Optional


SCHEMA_VERSION = "1.0"
DEFAULT_CONFIDENCE_LEVEL = 0.95


@dataclass(frozen=True)
class TrialRecord:
    """Canonical record for one pre-declared yes/no discrimination trial."""

    stimulus_present: bool
    response_yes: bool
    confidence: float
    trial_id: Optional[str] = None
    stimulus_timestamp: Optional[str] = None
    response_timestamp: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SDTCounts:
    hits: int
    misses: int
    false_alarms: int
    correct_rejections: int

    @property
    def signal_trials(self) -> int:
        return self.hits + self.misses

    @property
    def noise_trials(self) -> int:
        return self.false_alarms + self.correct_rejections

    @property
    def total_trials(self) -> int:
        return self.signal_trials + self.noise_trials

    @property
    def correct_trials(self) -> int:
        return self.hits + self.correct_rejections

    def to_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "false_alarms": self.false_alarms,
            "correct_rejections": self.correct_rejections,
            "signal_trials": self.signal_trials,
            "noise_trials": self.noise_trials,
            "total_trials": self.total_trials,
            "correct_trials": self.correct_trials,
        }


_MISSING = object()
_TRUTH_KEYS = ("stimulus_present", "stimulus_truth", "signal_present")
_RESPONSE_KEYS = ("response_yes", "response")


def _first_value(record: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    found = [(key, record[key]) for key in keys if key in record]
    if not found:
        return _MISSING
    first_key, first_value = found[0]
    for key, value in found[1:]:
        if value != first_value:
            raise ValueError(f"conflicting values for {first_key!r} and {key!r}")
    return first_value


def _normalize_binary(value: Any, *, field: str, kind: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if kind == "truth":
            true_values = {"1", "true", "present", "signal", "signal_present"}
            false_values = {"0", "false", "absent", "noise", "signal_absent"}
        else:
            true_values = {"1", "true", "yes", "present", "signal"}
            false_values = {"0", "false", "no", "absent", "noise"}
        if normalized in true_values:
            return True
        if normalized in false_values:
            return False
    raise ValueError(f"{field} must be an unambiguous binary {kind} value")


def _normalize_confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("confidence must be numeric, not boolean")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be finite and between 0.0 and 1.0")
    return confidence


def _parse_timestamp(value: Any, *, field: str) -> tuple[Optional[str], Optional[datetime]]:
    if value is None or value == "":
        return None, None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None, None
        if candidate.endswith(("Z", "z")):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    else:
        raise ValueError(f"{field} must be an ISO 8601 string or datetime")
    return parsed.isoformat(), parsed


def normalize_trial_record(record: Mapping[str, Any] | TrialRecord) -> TrialRecord:
    """Validate and normalize a mapping into a canonical :class:`TrialRecord`.

    Confidence uses a documented 0.0 to 1.0 scale.  Timestamps are optional,
    but when both are supplied they must use compatible timezone conventions
    and the response cannot precede stimulus presentation.
    """

    if isinstance(record, TrialRecord):
        record = record.to_dict()
    if not isinstance(record, Mapping):
        raise TypeError("trial record must be a mapping or TrialRecord")

    truth = _first_value(record, _TRUTH_KEYS)
    response = _first_value(record, _RESPONSE_KEYS)
    if truth is _MISSING:
        raise ValueError("trial record requires stimulus_present or stimulus_truth")
    if response is _MISSING:
        raise ValueError("trial record requires response_yes or response")
    if "confidence" not in record:
        raise ValueError("trial record requires confidence")

    trial_id_value = record.get("trial_id")
    trial_id = None if trial_id_value is None else str(trial_id_value).strip()
    if trial_id == "":
        raise ValueError("trial_id cannot be empty")

    stimulus_value = record.get("stimulus_timestamp", record.get("presented_at"))
    response_value = record.get("response_timestamp", record.get("responded_at"))
    stimulus_timestamp, stimulus_dt = _parse_timestamp(
        stimulus_value, field="stimulus_timestamp"
    )
    response_timestamp, response_dt = _parse_timestamp(
        response_value, field="response_timestamp"
    )
    if stimulus_dt is not None and response_dt is not None:
        stimulus_aware = stimulus_dt.utcoffset() is not None
        response_aware = response_dt.utcoffset() is not None
        if stimulus_aware != response_aware:
            raise ValueError("stimulus and response timestamps must use compatible timezones")
        if response_dt < stimulus_dt:
            raise ValueError("response_timestamp cannot precede stimulus_timestamp")

    return TrialRecord(
        stimulus_present=_normalize_binary(truth, field="stimulus truth", kind="truth"),
        response_yes=_normalize_binary(response, field="response", kind="response"),
        confidence=_normalize_confidence(record["confidence"]),
        trial_id=trial_id,
        stimulus_timestamp=stimulus_timestamp,
        response_timestamp=response_timestamp,
    )


def normalize_trial_records(
    records: Iterable[Mapping[str, Any] | TrialRecord],
) -> list[TrialRecord]:
    """Normalize trial records and reject duplicate non-null trial IDs."""

    normalized: list[TrialRecord] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        try:
            trial = normalize_trial_record(record)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid trial at index {index}: {exc}") from exc
        if trial.trial_id is not None:
            if trial.trial_id in seen_ids:
                raise ValueError(f"duplicate trial_id at index {index}: {trial.trial_id!r}")
            seen_ids.add(trial.trial_id)
        normalized.append(trial)
    if not normalized:
        raise ValueError("at least one trial is required")
    return normalized


def load_trial_file(path: str | Path) -> dict[str, Any]:
    """Load pre-declared yes/no trials from a local JSON or CSV file."""

    raw_path = str(path)
    if "://" in raw_path:
        raise ValueError("Trial import is local-only; provide a JSON or CSV file.")
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_bytes = source_path.read_bytes()
    suffix = source_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(source_bytes.decode("utf-8-sig"))
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, Mapping):
            records = next(
                (
                    payload[key]
                    for key in ("trials", "records", "data")
                    if isinstance(payload.get(key), list)
                ),
                None,
            )
            if records is None:
                records = [payload]
        else:
            raise ValueError("Trial JSON must be an object or list of objects.")
    elif suffix == ".csv":
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle))
    else:
        raise ValueError("Trial import requires a local .json or .csv file.")

    normalized = normalize_trial_records(records)
    analysis = analyze_trials(normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_domain": "psychophysics",
        "source": {
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "record_count": len(normalized),
            "local_path_included": False,
            "network_accessed": False,
        },
        "records": [trial.to_dict() for trial in normalized],
        "analysis": analysis,
        "interpretation_limit": analysis["interpretation_limit"],
    }


def count_outcomes(records: Iterable[Mapping[str, Any] | TrialRecord]) -> SDTCounts:
    """Count hit, miss, false-alarm, and correct-rejection outcomes."""

    trials = normalize_trial_records(records)
    hits = sum(trial.stimulus_present and trial.response_yes for trial in trials)
    misses = sum(trial.stimulus_present and not trial.response_yes for trial in trials)
    false_alarms = sum(not trial.stimulus_present and trial.response_yes for trial in trials)
    correct_rejections = sum(
        not trial.stimulus_present and not trial.response_yes for trial in trials
    )
    return SDTCounts(hits, misses, false_alarms, correct_rejections)


def wilson_interval(
    successes: int,
    trials: int,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> Optional[dict[str, Any]]:
    """Return a two-sided Wilson score interval for a binomial proportion."""

    if isinstance(successes, bool) or isinstance(trials, bool):
        raise ValueError("successes and trials must be integers")
    if not isinstance(successes, int) or not isinstance(trials, int):
        raise ValueError("successes and trials must be integers")
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("require 0 <= successes <= trials")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if trials == 0:
        return None

    estimate = successes / trials
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (estimate + z_squared / (2.0 * trials)) / denominator
    margin = (
        z
        * ((estimate * (1.0 - estimate) / trials + z_squared / (4.0 * trials * trials)) ** 0.5)
        / denominator
    )
    return {
        "method": "wilson_score",
        "confidence_level": confidence_level,
        "successes": successes,
        "trials": trials,
        "estimate": estimate,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def _rate_record(successes: int, trials: int) -> dict[str, Optional[float]]:
    if trials == 0:
        return {"raw": None, "log_linear": None, "used_for_sdt": None}
    raw = successes / trials
    corrected = (successes + 0.5) / (trials + 1.0)
    return {"raw": raw, "log_linear": corrected, "used_for_sdt": raw}


def _confidence_summary(trials: list[TrialRecord]) -> dict[str, Optional[float]]:
    correct = [
        trial.confidence
        for trial in trials
        if trial.stimulus_present == trial.response_yes
    ]
    incorrect = [
        trial.confidence
        for trial in trials
        if trial.stimulus_present != trial.response_yes
    ]
    return {
        "mean": fmean(trial.confidence for trial in trials),
        "mean_correct": fmean(correct) if correct else None,
        "mean_incorrect": fmean(incorrect) if incorrect else None,
    }


def analyze_trials(
    records: Iterable[Mapping[str, Any] | TrialRecord],
    *,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Analyze a yes/no experiment using conservative Signal Detection Theory.

    Raw rates remain visible.  If either the hit rate or false-alarm rate is 0
    or 1, d-prime and criterion use the log-linear correction
    ``(count + 0.5) / (n + 1)`` for both rates.  Incomplete designs return
    counts and available intervals, but do not manufacture SDT metrics.
    """

    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    trials = normalize_trial_records(records)
    counts = SDTCounts(
        hits=sum(trial.stimulus_present and trial.response_yes for trial in trials),
        misses=sum(trial.stimulus_present and not trial.response_yes for trial in trials),
        false_alarms=sum(
            not trial.stimulus_present and trial.response_yes for trial in trials
        ),
        correct_rejections=sum(
            not trial.stimulus_present and not trial.response_yes for trial in trials
        ),
    )

    hit_rate = _rate_record(counts.hits, counts.signal_trials)
    false_alarm_rate = _rate_record(counts.false_alarms, counts.noise_trials)
    miss_rate = _rate_record(counts.misses, counts.signal_trials)
    correct_rejection_rate = _rate_record(counts.correct_rejections, counts.noise_trials)
    design_complete = counts.signal_trials > 0 and counts.noise_trials > 0
    extreme_rate = design_complete and (
        hit_rate["raw"] in (0.0, 1.0) or false_alarm_rate["raw"] in (0.0, 1.0)
    )
    if extreme_rate:
        hit_rate["used_for_sdt"] = hit_rate["log_linear"]
        false_alarm_rate["used_for_sdt"] = false_alarm_rate["log_linear"]

    d_prime: Optional[float] = None
    criterion: Optional[float] = None
    balanced_accuracy: Optional[float] = None
    if design_complete:
        z_hit = NormalDist().inv_cdf(float(hit_rate["used_for_sdt"]))
        z_false_alarm = NormalDist().inv_cdf(float(false_alarm_rate["used_for_sdt"]))
        d_prime = z_hit - z_false_alarm
        criterion = -0.5 * (z_hit + z_false_alarm)
        balanced_accuracy = 0.5 * (
            float(hit_rate["raw"]) + float(correct_rejection_rate["raw"])
        )

    intervals = {
        "hit_rate": wilson_interval(counts.hits, counts.signal_trials, confidence_level),
        "miss_rate": wilson_interval(counts.misses, counts.signal_trials, confidence_level),
        "false_alarm_rate": wilson_interval(
            counts.false_alarms, counts.noise_trials, confidence_level
        ),
        "correct_rejection_rate": wilson_interval(
            counts.correct_rejections, counts.noise_trials, confidence_level
        ),
        "accuracy": wilson_interval(
            counts.correct_trials, counts.total_trials, confidence_level
        ),
    }
    warnings: list[str] = []
    if not design_complete:
        warnings.append(
            "Both signal-present and signal-absent trials are required for d-prime, "
            "criterion, and balanced accuracy."
        )
    if extreme_rate:
        warnings.append(
            "An extreme hit or false-alarm rate required log-linear correction for SDT metrics."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_domain": "psychophysics",
        "analysis_status": "tested" if design_complete else "not_tested",
        "counts": counts.to_dict(),
        "rates": {
            "hit_rate": hit_rate,
            "miss_rate": miss_rate,
            "false_alarm_rate": false_alarm_rate,
            "correct_rejection_rate": correct_rejection_rate,
        },
        "correction": {
            "method": "log_linear_(count+0.5)/(n+1)",
            "applied_to_sdt": extreme_rate,
        },
        "metrics": {
            "d_prime": d_prime,
            "criterion": criterion,
            "balanced_accuracy": balanced_accuracy,
            "accuracy": counts.correct_trials / counts.total_trials,
        },
        "confidence_intervals": {
            "method": "wilson_score",
            "confidence_level": confidence_level,
            "intervals": intervals,
        },
        "confidence_summary": _confidence_summary(trials),
        "warnings": warnings,
        "interpretation_limit": (
            "This analysis measures yes/no discrimination and response bias only; "
            "it is not detector evidence and does not establish stimulus origin or meaning."
        ),
    }


def _external_row(
    row_id: str,
    question: str,
    domain: str,
    evidence: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    explicitly_tested = evidence is not None and evidence.get("tested") is True
    return {
        "id": row_id,
        "question": question,
        "evidence_domain": domain,
        "status": "tested" if explicitly_tested else "not_tested",
        "outcome": evidence.get("outcome") if explicitly_tested else None,
    }


def build_falsification_matrix(
    *,
    psychophysics_analysis: Optional[Mapping[str, Any]] = None,
    detector_evidence: Optional[Mapping[str, Any]] = None,
    correspondence_evidence: Optional[Mapping[str, Any]] = None,
    replication_evidence: Optional[Mapping[str, Any]] = None,
    confound_evidence: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Build an explicit tested/not-tested falsification matrix.

    Detector, correspondence, and replication rows require an explicit
    ``{"tested": True}`` marker.  No detector score is folded into d-prime or
    any other psychophysics metric, and no cross-domain conclusion is inferred
    merely because both domains have data.
    """

    psych_tested = (
        psychophysics_analysis is not None
        and psychophysics_analysis.get("evidence_domain") == "psychophysics"
        and psychophysics_analysis.get("analysis_status") == "tested"
    )
    metrics: Mapping[str, Any] = {}
    if psych_tested:
        candidate = psychophysics_analysis.get("metrics", {})
        if isinstance(candidate, Mapping):
            metrics = candidate

    confounds = confound_evidence or {}
    rows = [
        {
            "id": "participant_discrimination",
            "question": "Did yes/no responses discriminate signal-present from signal-absent trials?",
            "evidence_domain": "psychophysics",
            "status": "tested" if psych_tested else "not_tested",
            "outcome": (
                {
                    "d_prime": metrics.get("d_prime"),
                    "balanced_accuracy": metrics.get("balanced_accuracy"),
                }
                if psych_tested
                else None
            ),
        },
        {
            "id": "participant_response_bias",
            "question": "Was yes/no response bias quantified?",
            "evidence_domain": "psychophysics",
            "status": "tested" if psych_tested else "not_tested",
            "outcome": {"criterion": metrics.get("criterion")} if psych_tested else None,
        },
        _external_row(
            "detector_above_control",
            "Did an automated detector exceed its matched-control distribution?",
            "detector",
            detector_evidence,
        ),
        _external_row(
            "cross_domain_correspondence",
            "Was correspondence between blinded human responses and detector output tested?",
            "cross_domain",
            correspondence_evidence,
        ),
        _external_row(
            "independent_replication",
            "Was the result repeated in an independent, pre-declared dataset?",
            "replication",
            replication_evidence,
        ),
    ]
    rows.extend(
        _external_row(row_id, question, domain, confounds.get(row_id))
        for row_id, question, domain in (
            (
                "wall_coordinate_stability",
                "Was candidate stability tested against gaze or wall coordinates?",
                "visual_stability",
            ),
            (
                "motion_parallax",
                "Was motion parallax tested across controlled camera or observer positions?",
                "spatial_context",
            ),
            (
                "focus_accommodation",
                "Were wall and foreground focus conditions compared?",
                "subjective_context",
            ),
            (
                "binocular_consistency",
                "Were left-eye, right-eye, or alternating-eye reports compared?",
                "subjective_context",
            ),
            (
                "polarization_entoptic_control",
                "Were polarization or head-tilt conditions compared?",
                "optical_control",
            ),
            (
                "carrier_grid_interaction",
                "Was a visible grid, grating, mesh, or occluder interaction tested?",
                "physical_control",
            ),
            (
                "wavelength_surface_control",
                "Were wavelength or surface changes tested under otherwise matched conditions?",
                "capture_control",
            ),
            (
                "symbol_distribution_null",
                "Were transcription distributions compared with a declared null model?",
                "transcription_context",
            ),
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
        "separation_policy": (
            "Psychophysics and detector evidence remain separate. Cross-domain "
            "correspondence requires its own explicit test."
        ),
    }


__all__ = [
    "DEFAULT_CONFIDENCE_LEVEL",
    "SCHEMA_VERSION",
    "SDTCounts",
    "TrialRecord",
    "analyze_trials",
    "build_falsification_matrix",
    "count_outcomes",
    "load_trial_file",
    "normalize_trial_record",
    "normalize_trial_records",
    "wilson_interval",
]
