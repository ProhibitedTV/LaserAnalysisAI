from __future__ import annotations

import math
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from laserlab.psychophysics import (
    TrialRecord,
    analyze_trials,
    build_falsification_matrix,
    count_outcomes,
    load_trial_file,
    normalize_trial_record,
    normalize_trial_records,
    wilson_interval,
)


def _trials(hits: int, misses: int, false_alarms: int, correct_rejections: int):
    records = []
    outcomes = (
        [(True, True)] * hits
        + [(True, False)] * misses
        + [(False, True)] * false_alarms
        + [(False, False)] * correct_rejections
    )
    for index, (truth, response) in enumerate(outcomes):
        records.append(
            {
                "trial_id": f"trial-{index}",
                "stimulus_truth": truth,
                "response": "yes" if response else "no",
                "confidence": 0.8 if truth == response else 0.4,
            }
        )
    return records


class TrialNormalizationTests(unittest.TestCase):
    def test_loads_local_json_with_hash_and_without_path_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trials.json"
            path.write_text(json.dumps({"trials": _trials(2, 1, 1, 2)}), encoding="utf-8")
            payload = load_trial_file(path)
        self.assertEqual(payload["source"]["record_count"], 6)
        self.assertEqual(len(payload["source"]["sha256"]), 64)
        self.assertNotIn(str(path.parent), str(payload))
        self.assertEqual(payload["analysis"]["analysis_status"], "tested")

    def test_normalizes_aliases_binary_values_and_timestamps(self) -> None:
        trial = normalize_trial_record(
            {
                "trial_id": 17,
                "stimulus_truth": "signal",
                "response": "yes",
                "confidence": "0.75",
                "presented_at": "2026-01-02T03:04:05Z",
                "responded_at": datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc),
            }
        )
        self.assertEqual(
            trial,
            TrialRecord(
                stimulus_present=True,
                response_yes=True,
                confidence=0.75,
                trial_id="17",
                stimulus_timestamp="2026-01-02T03:04:05+00:00",
                response_timestamp="2026-01-02T03:04:06+00:00",
            ),
        )

    def test_accepts_noise_and_no_as_false(self) -> None:
        trial = normalize_trial_record(
            {"signal_present": "noise", "response_yes": "no", "confidence": 0}
        )
        self.assertFalse(trial.stimulus_present)
        self.assertFalse(trial.response_yes)

    def test_requires_truth_response_and_confidence(self) -> None:
        for record in (
            {"response": "yes", "confidence": 0.5},
            {"stimulus_truth": True, "confidence": 0.5},
            {"stimulus_truth": True, "response": "yes"},
        ):
            with self.subTest(record=record), self.assertRaises(ValueError):
                normalize_trial_record(record)

    def test_rejects_ambiguous_or_invalid_values(self) -> None:
        invalid_records = (
            {"stimulus_truth": "maybe", "response": "yes", "confidence": 0.5},
            {"stimulus_truth": True, "response": "sometimes", "confidence": 0.5},
            {"stimulus_truth": True, "response": True, "confidence": True},
            {"stimulus_truth": True, "response": True, "confidence": -0.01},
            {"stimulus_truth": True, "response": True, "confidence": 1.01},
            {"stimulus_truth": True, "response": True, "confidence": math.inf},
        )
        for record in invalid_records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                normalize_trial_record(record)

    def test_rejects_conflicting_aliases(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting"):
            normalize_trial_record(
                {
                    "stimulus_present": True,
                    "stimulus_truth": False,
                    "response": "yes",
                    "confidence": 0.5,
                }
            )

    def test_validates_timestamp_format_order_and_timezone_compatibility(self) -> None:
        invalid_pairs = (
            ("not-a-time", "2026-01-01T00:00:01Z"),
            ("2026-01-01T00:00:02Z", "2026-01-01T00:00:01Z"),
            ("2026-01-01T00:00:00", "2026-01-01T00:00:01Z"),
        )
        for presented, responded in invalid_pairs:
            with self.subTest(presented=presented), self.assertRaises(ValueError):
                normalize_trial_record(
                    {
                        "stimulus_truth": True,
                        "response": "yes",
                        "confidence": 0.5,
                        "stimulus_timestamp": presented,
                        "response_timestamp": responded,
                    }
                )

    def test_rejects_duplicate_ids_and_empty_inputs(self) -> None:
        duplicate = {
            "trial_id": "same",
            "stimulus_truth": True,
            "response": "yes",
            "confidence": 0.5,
        }
        with self.assertRaisesRegex(ValueError, "duplicate trial_id"):
            normalize_trial_records([duplicate, duplicate])
        with self.assertRaisesRegex(ValueError, "at least one trial"):
            normalize_trial_records([])


class OutcomeAndIntervalTests(unittest.TestCase):
    def test_counts_all_four_outcomes(self) -> None:
        counts = count_outcomes(_trials(4, 3, 2, 1))
        self.assertEqual(counts.hits, 4)
        self.assertEqual(counts.misses, 3)
        self.assertEqual(counts.false_alarms, 2)
        self.assertEqual(counts.correct_rejections, 1)
        self.assertEqual(counts.signal_trials, 7)
        self.assertEqual(counts.noise_trials, 3)
        self.assertEqual(counts.total_trials, 10)

    def test_wilson_interval_matches_known_half_proportion(self) -> None:
        interval = wilson_interval(5, 10)
        self.assertIsNotNone(interval)
        self.assertAlmostEqual(interval["estimate"], 0.5)
        self.assertAlmostEqual(interval["lower"], 0.236593, places=6)
        self.assertAlmostEqual(interval["upper"], 0.763407, places=6)
        self.assertEqual(interval["method"], "wilson_score")

    def test_wilson_handles_zero_trials_and_rejects_invalid_counts(self) -> None:
        self.assertIsNone(wilson_interval(0, 0))
        for successes, trials in ((-1, 1), (2, 1), (0, -1)):
            with self.subTest(successes=successes, trials=trials):
                with self.assertRaises(ValueError):
                    wilson_interval(successes, trials)
        with self.assertRaises(ValueError):
            wilson_interval(1, 2, confidence_level=1.0)


class SignalDetectionAnalysisTests(unittest.TestCase):
    def test_non_extreme_rates_use_raw_values(self) -> None:
        analysis = analyze_trials(_trials(8, 2, 2, 8))
        self.assertEqual(analysis["analysis_status"], "tested")
        self.assertEqual(analysis["evidence_domain"], "psychophysics")
        self.assertFalse(analysis["correction"]["applied_to_sdt"])
        self.assertAlmostEqual(analysis["rates"]["hit_rate"]["raw"], 0.8)
        self.assertAlmostEqual(
            analysis["rates"]["hit_rate"]["used_for_sdt"], 0.8
        )
        self.assertAlmostEqual(analysis["metrics"]["d_prime"], 1.683242, places=6)
        self.assertAlmostEqual(analysis["metrics"]["criterion"], 0.0, places=12)
        self.assertAlmostEqual(analysis["metrics"]["balanced_accuracy"], 0.8)
        self.assertAlmostEqual(analysis["metrics"]["accuracy"], 0.8)

    def test_extreme_rates_apply_log_linear_correction_and_remain_finite(self) -> None:
        analysis = analyze_trials(_trials(10, 0, 0, 10))
        self.assertTrue(analysis["correction"]["applied_to_sdt"])
        self.assertEqual(analysis["rates"]["hit_rate"]["raw"], 1.0)
        self.assertAlmostEqual(
            analysis["rates"]["hit_rate"]["used_for_sdt"], 10.5 / 11.0
        )
        self.assertAlmostEqual(
            analysis["rates"]["false_alarm_rate"]["used_for_sdt"], 0.5 / 11.0
        )
        self.assertTrue(math.isfinite(analysis["metrics"]["d_prime"]))
        self.assertAlmostEqual(analysis["metrics"]["criterion"], 0.0, places=12)
        self.assertTrue(any("log-linear" in item for item in analysis["warnings"]))

    def test_criterion_reflects_yes_response_bias(self) -> None:
        analysis = analyze_trials(_trials(9, 1, 6, 4))
        self.assertLess(analysis["metrics"]["criterion"], 0.0)

    def test_confidence_summary_separates_correct_and_incorrect_trials(self) -> None:
        analysis = analyze_trials(_trials(2, 1, 1, 2))
        self.assertAlmostEqual(analysis["confidence_summary"]["mean_correct"], 0.8)
        self.assertAlmostEqual(analysis["confidence_summary"]["mean_incorrect"], 0.4)
        self.assertAlmostEqual(analysis["confidence_summary"]["mean"], 4.0 / 6.0)

    def test_incomplete_design_does_not_manufacture_sdt_metrics(self) -> None:
        analysis = analyze_trials(_trials(3, 1, 0, 0))
        self.assertEqual(analysis["analysis_status"], "not_tested")
        self.assertIsNone(analysis["metrics"]["d_prime"])
        self.assertIsNone(analysis["metrics"]["criterion"])
        self.assertIsNone(analysis["metrics"]["balanced_accuracy"])
        self.assertIsNone(
            analysis["confidence_intervals"]["intervals"]["false_alarm_rate"]
        )
        self.assertTrue(analysis["warnings"])

    def test_accepts_one_pass_iterables(self) -> None:
        records = (record for record in _trials(2, 1, 1, 2))
        analysis = analyze_trials(records)
        self.assertEqual(analysis["counts"]["total_trials"], 6)


class FalsificationMatrixTests(unittest.TestCase):
    def test_matrix_always_includes_tested_and_not_tested_rows(self) -> None:
        analysis = analyze_trials(_trials(8, 2, 2, 8))
        matrix = build_falsification_matrix(psychophysics_analysis=analysis)
        by_id = {row["id"]: row for row in matrix["rows"]}

        self.assertEqual(by_id["participant_discrimination"]["status"], "tested")
        self.assertEqual(by_id["participant_response_bias"]["status"], "tested")
        self.assertEqual(by_id["detector_above_control"]["status"], "not_tested")
        self.assertEqual(by_id["cross_domain_correspondence"]["status"], "not_tested")
        self.assertEqual(by_id["independent_replication"]["status"], "not_tested")
        self.assertEqual(by_id["wall_coordinate_stability"]["status"], "not_tested")
        self.assertEqual(by_id["symbol_distribution_null"]["status"], "not_tested")

    def test_detector_evidence_remains_separate_and_requires_explicit_test_marker(self) -> None:
        analysis = analyze_trials(_trials(3, 1, 1, 3))
        unmarked = build_falsification_matrix(
            psychophysics_analysis=analysis,
            detector_evidence={"outcome": "above_control", "score": 99},
        )
        unmarked_row = next(
            row for row in unmarked["rows"] if row["id"] == "detector_above_control"
        )
        self.assertEqual(unmarked_row["status"], "not_tested")
        self.assertIsNone(unmarked_row["outcome"])

        marked = build_falsification_matrix(
            psychophysics_analysis=analysis,
            detector_evidence={"tested": True, "outcome": "null"},
        )
        detector_row = next(
            row for row in marked["rows"] if row["id"] == "detector_above_control"
        )
        psych_row = next(
            row for row in marked["rows"] if row["id"] == "participant_discrimination"
        )
        self.assertEqual(detector_row["evidence_domain"], "detector")
        self.assertEqual(detector_row["outcome"], "null")
        self.assertNotIn("score", psych_row["outcome"])
        self.assertEqual(
            next(
                row
                for row in marked["rows"]
                if row["id"] == "cross_domain_correspondence"
            )["status"],
            "not_tested",
        )

    def test_cross_domain_and_replication_rows_require_their_own_evidence(self) -> None:
        matrix = build_falsification_matrix(
            correspondence_evidence={"tested": True, "outcome": "no_association"},
            replication_evidence={"tested": True, "outcome": "not_replicated"},
        )
        by_id = {row["id"]: row for row in matrix["rows"]}
        self.assertEqual(by_id["participant_discrimination"]["status"], "not_tested")
        self.assertEqual(by_id["cross_domain_correspondence"]["status"], "tested")
        self.assertEqual(by_id["independent_replication"]["status"], "tested")
        self.assertIn("remain separate", matrix["separation_policy"])


if __name__ == "__main__":
    unittest.main()
