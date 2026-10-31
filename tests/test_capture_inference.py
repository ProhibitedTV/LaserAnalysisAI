from __future__ import annotations

import copy
import hashlib
import random
import unittest

from laserlab.capture_inference import MINIMUM_PAIRS
from laserlab.stats import current_statistics, summarize_blinded_results, summarize_results


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def frame(pair: int, role: str, score: float, number: int = 0) -> dict:
    return {
        "sample_id": f"{pair}-{role}-{number}", "blind_id": f"B{pair}-{role}-{number}",
        "capture_id": f"capture-{pair}-{role}", "unblinded_label": role,
        "capture_source_sha256": digest(f"source-{pair}-{role}"),
        "source_sha256": digest(f"frame-{pair}-{role}-{number}"),
        "capture_metadata": {"footage_class": "primary_wall_projection", "independent_pair_id": f"pair-{pair}",
                             "pair_exchangeability_acknowledged": True},
        "preprocessing_variant": "raw", "primary_metric_score": score, "inference_metric_score": score,
        "structure_score": score, "persistence_score": 0,
    }


def pairs(count: int = MINIMUM_PAIRS, *, null: bool = False) -> list[dict]:
    return [frame(pair, role, (.2 + pair * .01) if null or role == "matched_control" else .8 + pair * .01)
            for pair in range(count) for role in ("laser", "matched_control")]


class IndependentCaptureInferenceTests(unittest.TestCase):
    def summarize(self, records: list[dict], **kwargs) -> dict:
        return summarize_results(records, seed=31, **kwargs)

    def test_five_declared_pairs_use_exact_whole_pair_permutations(self):
        summary = self.summarize(pairs())
        self.assertEqual(summary["inference"]["status"], "tested")
        self.assertEqual(summary["inference"]["pair_count"], 5)
        self.assertEqual(summary["inference"]["permutations"], 32)
        self.assertEqual(summary["permutation_p_value"], 1 / 32)
        self.assertEqual(summary["evidence_ladder"], "above-control candidate")
        self.assertEqual(summary["candidate_q_values"], {})
        self.assertIsNone(summary["minimum_q_value"])
        self.assertIsNone(summary["cohen_d"])
        self.assertEqual(summary["laser_confidence_interval"]["count"], 5)
        self.assertEqual(summary["laser_confidence_interval"]["unit"], "empirical capture")

    def test_generated_nulls_cannot_replace_recorded_controls(self):
        records = [frame(0, "laser", .9)]
        for i in range(300):
            records.append({**frame(i, "control", .01), "synthetic": True, "parent_capture_id": "capture-0-laser"})
        summary = self.summarize(records)
        self.assertEqual(summary["control_count"], 0)
        self.assertEqual(summary["control_diagnostics"]["generated_null"]["frame_count"], 300)
        self.assertEqual(summary["evidence_ladder"], "not tested")
        self.assertIsNone(summary["permutation_p_value"])
        self.assertIn("Exploratory", summary["null_result_language"])

    def test_mixed_sign_exact_case_matches_independent_scipy_reference(self):
        # scipy.stats.permutation_test(permutation_type='samples',
        # alternative='greater', n_resamples=inf), SciPy 1.15.3.
        laser, control = [.9, .7, .8, .6, .7], [.1, .6, .3, .7, .5]
        records = [frame(i, role, values[i]) for i in range(5)
                   for role, values in (("laser", laser), ("matched_control", control))]
        summary = self.summarize(records)
        self.assertEqual(summary["permutation_p_value"], .09375)
        self.assertNotEqual(summary["evidence_ladder"], "above-control candidate")

    def test_legacy_generated_provenance_is_still_excluded_without_flag(self):
        sample = frame(0, "matched_control", .01)
        sample["control_type"] = "rotated"
        self.assertEqual(self.summarize([frame(0, "laser", .9), sample])["control_count"], 0)

    def test_other_controls_sensor_noise_and_synthetic_negatives_are_distinct(self):
        for role, category in (("control", "other_empirical_control"), ("sensor_noise", "sensor_noise"),
                               ("synthetic_negative", "synthetic_negative")):
            with self.subTest(role=role):
                summary = self.summarize([frame(0, "laser", .8), frame(0, role, .01)])
                self.assertEqual(summary["control_count"], 0)
                self.assertEqual(summary["control_diagnostics"][category]["frame_count"], 1)
                self.assertEqual(summary["evidence_ladder"], "not tested")

    def test_one_pair_cannot_become_replicates_by_adding_frames(self):
        records = [frame(0, role, score, i) for role, score in (("laser", .9), ("matched_control", .1)) for i in range(250)]
        summary = self.summarize(records)
        self.assertEqual(summary["inference"]["pair_count"], 1)
        self.assertEqual(summary["evidence_ladder"], "insufficient independent samples")
        for field in ("permutation_p_value", "cohen_d", "minimum_q_value"):
            self.assertIsNone(summary[field])
        self.assertIsNone(summary["laser_confidence_interval"]["low"])

    def test_duplicated_frames_and_preprocessing_do_not_change_inference(self):
        records = pairs()
        expected = self.summarize(records)
        duplicates = copy.deepcopy(records)
        for i in range(100):
            for sample in records:
                duplicates.append({**sample, "sample_id": sample["sample_id"] + f"copy-{i}",
                                   "primary_metric_score": .99, "persistence_score": 1})
                duplicates.append(dict(sample))
        actual = self.summarize(duplicates)
        self.assertEqual(actual["inference"], expected["inference"])
        self.assertEqual(actual["permutation_p_value"], expected["permutation_p_value"])
        self.assertNotEqual(actual["evidence_ladder"], "repeatable candidate")

    def test_frame_imbalance_does_not_weight_pairs_as_replicates(self):
        records = pairs()
        expected = self.summarize(records)
        records.extend(frame(0, "laser", .8, i) for i in range(1, 70))
        self.assertEqual(self.summarize(records)["inference"], expected["inference"])

    def test_null_and_correlated_frame_benchmark_do_not_promote(self):
        records = pairs(null=True)
        summary = self.summarize(records * 80)
        self.assertEqual(summary["permutation_p_value"], 1)
        self.assertEqual(summary["evidence_ladder"], "no signal")

    def test_copied_sources_or_shared_frames_prevent_independence(self):
        for field, status in (("capture_source_sha256", "shared_source"), ("source_sha256", "shared_frames")):
            with self.subTest(field=field):
                records = pairs()
                records[2][field] = records[0][field]
                self.assertEqual(self.summarize(records)["inference"]["status"], status)

    def test_missing_declarations_hashes_and_legacy_scores_withhold_inference(self):
        for mutation, status in (
            (lambda r: r["capture_metadata"].pop("independent_pair_id"), "unverified_design"),
            (lambda r: r["capture_metadata"].update(pair_exchangeability_acknowledged=False), "unverified_design"),
            (lambda r: r.pop("capture_source_sha256"), "unverified_provenance"),
            (lambda r: r.pop("inference_metric_score"), "unverified_provenance"),
        ):
            records = pairs()
            mutation(records[0])
            self.assertEqual(self.summarize(records)["inference"]["status"], status)

    def test_incomplete_or_ambiguous_pairs_are_not_pooled(self):
        records = pairs()
        self.assertEqual(self.summarize(records[:-1])["inference"]["status"], "incomplete_pairs")
        extra = frame(9, "laser", .9)
        extra["capture_metadata"]["independent_pair_id"] = "pair-0"
        self.assertEqual(self.summarize(records + [extra])["inference"]["status"], "invalid_pairs")

    def test_positives_only_calibrate_and_demo_fixtures_are_not_empirical(self):
        records = pairs()
        before = self.summarize(records)
        after = self.summarize(records + [frame(i, "synthetic_positive", 1) for i in range(20)])
        self.assertTrue(after["calibration_passed"])
        self.assertEqual(after["inference"], before["inference"])
        for record in records:
            record["capture_metadata"]["footage_class"] = "demo_fixture"
        self.assertEqual(self.summarize(records)["evidence_ladder"], "not tested")

    def test_large_design_has_seeded_nonzero_monte_carlo_p_value(self):
        records = pairs(17)
        first = self.summarize(records, permutations=1000)
        self.assertEqual(first, self.summarize(records, permutations=1000))
        self.assertGreater(first["permutation_p_value"], 0)
        self.assertEqual(first["inference"]["permutation_mode"], "monte_carlo_plus_one")

    def test_blinded_summary_never_discloses_design_ids_roles_or_hashes(self):
        import json
        serialized = json.dumps(summarize_blinded_results(pairs()))
        self.assertNotIn("pair-0", serialized)
        self.assertNotIn("capture-0", serialized)
        self.assertNotIn(digest("source-0-laser"), serialized)
        summary = summarize_blinded_results(pairs())
        self.assertIsNone(summary["laser_count"])
        self.assertEqual(summary["control_diagnostics"], {"sealed": True})

    def test_legacy_statistics_are_replaced_in_memory_without_mutating_record(self):
        legacy = {"results": pairs(1), "blind_seed": 1, "review_state": {"unblinded": True},
                  "aggregate_statistics": {"evidence_ladder": "repeatable candidate", "permutation_p_value": .001}}
        original = copy.deepcopy(legacy)
        updated = current_statistics(legacy)
        self.assertEqual(legacy, original)
        self.assertEqual(updated["aggregate_statistics"]["evidence_ladder"], "insufficient independent samples")
        self.assertIn("superseded", updated["statistics_migration"])

    def test_nonfinite_scores_and_conflicting_variants_fail_closed(self):
        record = frame(0, "laser", float("nan"))
        with self.assertRaises(ValueError):
            self.summarize([record])
        record = frame(0, "laser", .9)
        with self.assertRaises(ValueError):
            self.summarize([record, {**record, "primary_metric_score": .1}])

    def test_reported_motion_or_saturation_is_not_a_suitable_comparison(self):
        records = pairs()
        records[0]["capture_metadata"]["projected_region_not_saturated"] = False
        self.assertEqual(self.summarize(records)["inference"]["status"], "reported_quality_failure")

    def test_correlated_null_simulations_are_invariant_to_frame_count(self):
        rng = random.Random(1027)
        false_positives = 0
        for trial in range(40):
            records = []
            for pair in range(6):
                shared = .5 + rng.uniform(-.1, .1)
                difference = rng.uniform(-.08, .08)
                records.extend((frame(pair, "laser", shared + difference / 2),
                                frame(pair, "matched_control", shared - difference / 2)))
            before = self.summarize(records)
            repeated = [dict(record, sample_id=record["sample_id"] + f"-{i}") for record in records for i in range(80)]
            after = self.summarize(repeated)
            self.assertEqual(after["inference"], before["inference"])
            false_positives += before["evidence_ladder"] == "above-control candidate"
        # A deterministic regression bound for this known-null score simulation,
        # not a claim about the detector's optical false-positive rate.
        self.assertLessEqual(false_positives, 4)
