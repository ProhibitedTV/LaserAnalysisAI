"""Synthetic declared-pair plumbing, not evidence from actual empirical captures."""
from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from laserlab import app_api
from laserlab.artifacts import write_json
from laserlab.bundle import export_review_bundle
from laserlab.manifest import new_manifest, write_manifest
from laserlab.metric_validity import METRIC_VALIDITY_VERSION, assess_metric_result
from laserlab.ocr_adapters import (DeterministicStubAdapter, FailingStubAdapter, OCRPayload,
                                   OCRRequest, UnavailableStubAdapter, run_ocr_ensemble)
from laserlab.research_exchange import prepare_exchange
from laserlab.scientific import metric_score
from laserlab.stats import current_statistics, summarize_results, summarize_blinded_results

try:
    from test_capture_inference import pairs, frame
except ModuleNotFoundError:
    from tests.test_capture_inference import pairs, frame


def ocr_records(count=5, *, positive=False):
    records = pairs(count)
    for record in records:
        text = "AB" if positive and record["unblinded_label"] == "laser" else ""
        record.update(primary_metric="ocr_symbol_score", ocr={"available": True, "text": text,
                      "word_count": 1 if text else 0, "confidence": 90 if text else 0},
                      ocr_attempts=[{"available": True, "text": text, "failure_reason": None}],
                      blinded_label="sealed", processed_path="processed/fixture.png")
        score = metric_score(record, "ocr_symbol_score")
        record.update(primary_metric_score=score, inference_metric_score=score)
    return records


def unavailable(record):
    record["ocr"] = {"available": False, "text": "", "confidence": 0, "word_count": 0}
    record["ocr_attempts"] = [{"available": False, "text": None, "failure_reason": "PRIVATE engine path"}]
    record.update(primary_metric_score=0, inference_metric_score=0)


class MetricValidityTests(unittest.TestCase):
    def summarize(self, records):
        return summarize_results(records, 31, primary_metric="ocr_symbol_score")

    def test_unavailable_ocr_is_not_a_null_finding_or_a_measured_zero(self):
        records = ocr_records()
        for record in records:
            unavailable(record)
        aggregate = self.summarize(records)
        self.assertEqual(aggregate["evidence_ladder"], "not tested")
        self.assertEqual(aggregate["inference"]["status"], "primary_metric_unavailable")
        for field in ("permutation_p_value", "mean_difference", "laser_mean_score", "control_mean_score"):
            self.assertIsNone(aggregate[field])
        self.assertEqual(aggregate["primary_metric_validity"]["unscored_sample_observations"], 10)
        self.assertNotIn("PRIVATE", json.dumps(aggregate))

    def test_successful_empty_recognition_is_a_measured_zero_with_a_supported_null(self):
        aggregate = self.summarize(ocr_records())
        self.assertEqual(aggregate["primary_metric_validity"]["status"], "complete")
        self.assertEqual(aggregate["evidence_ladder"], "no signal")
        self.assertEqual(aggregate["permutation_p_value"], 1)
        self.assertEqual(aggregate["laser_mean_score"], 0)

    def test_successful_text_and_empty_controls_keep_the_existing_pair_test(self):
        aggregate = self.summarize(ocr_records(positive=True))
        self.assertEqual(aggregate["evidence_ladder"], "above-control candidate")
        self.assertEqual(aggregate["permutation_p_value"], 1 / 32)
        self.assertEqual(aggregate["inference"]["pair_count"], 5)
        self.assertIsNone(aggregate["minimum_q_value"])

    def test_failed_null_missing_and_nonboolean_attempts_are_unscored(self):
        for attempts in ([{"available": True, "text": "", "failure_reason": "PRIVATE failure"}],
                         [{"available": True, "text": None, "failure_reason": None}], [],
                         [{"available": True, "text": ""}],
                         [{"available": 1, "text": "", "failure_reason": None}]):
            with self.subTest(attempts=attempts):
                records = ocr_records()
                records[0]["ocr_attempts"] = attempts
                aggregate = self.summarize(records)
                self.assertEqual(aggregate["evidence_ladder"], "not tested")
                self.assertIsNone(aggregate["permutation_p_value"])
                self.assertNotIn("PRIVATE", json.dumps(aggregate))

    def test_one_failed_roi_or_variant_cannot_be_dropped_in_favor_of_success(self):
        records = ocr_records(positive=True)
        records[0]["ocr_attempts"].append({"available": True, "text": None, "failure_reason": "failure"})
        self.assertEqual(self.summarize(records)["evidence_ladder"], "not tested")
        records = ocr_records(positive=True)
        variant = copy.deepcopy(records[0])
        variant["preprocessing_variant"] = "blur"
        unavailable(variant)
        records.append(variant)
        aggregate = self.summarize(records)
        self.assertEqual(aggregate["evidence_ladder"], "not tested")
        self.assertEqual(aggregate["primary_metric_validity"]["sample_observations"], 10)
        self.assertEqual(aggregate["primary_metric_validity"]["unscored_sample_observations"], 1)

    def test_generated_probe_failure_does_not_block_complete_empirical_measurements(self):
        records = ocr_records(positive=True)
        probe = {**copy.deepcopy(records[0]), "sample_id": "probe", "capture_id": "probe",
                 "synthetic": True, "parent_capture_id": records[0]["capture_id"]}
        unavailable(probe)
        records.append(probe)
        aggregate = self.summarize(records)
        self.assertEqual(aggregate["evidence_ladder"], "above-control candidate")
        self.assertEqual(aggregate["primary_metric_validity"]["sample_observations"], 10)
        self.assertIsNone(aggregate["control_diagnostics"]["generated_null"]["mean_score"])

    def test_other_primary_metrics_still_work_without_optional_ocr(self):
        records = pairs()
        for record in records:
            record.update(ocr={"available": False}, ocr_attempts=[])
        aggregate = summarize_results(records, 31)
        self.assertEqual(aggregate["evidence_ladder"], "above-control candidate")
        self.assertEqual(aggregate["primary_metric_validity"]["status"], "not_required")

    def test_one_measured_pair_remains_insufficient_and_sealed_counts_stay_hidden(self):
        self.assertEqual(self.summarize(ocr_records(1))["evidence_ladder"], "insufficient independent samples")
        records = ocr_records()
        unavailable(records[0])
        sealed = summarize_blinded_results(records, "ocr_symbol_score")
        self.assertEqual(sealed["primary_metric_validity"], {"version": METRIC_VALIDITY_VERSION, "status": "sealed"})
        self.assertNotIn("unscored_sample_observations", json.dumps(sealed))

    def test_missing_legacy_attempts_are_not_invented_from_an_available_summary(self):
        record = ocr_records()[0]
        record.pop("ocr_attempts")
        measurement = assess_metric_result(record, "ocr_symbol_score")
        self.assertEqual(measurement["status"], "unscored")
        self.assertIn("missing_attempts", measurement["reason_codes"])

    def test_real_adapter_attempt_states_control_eligibility(self):
        for adapter, status in ((UnavailableStubAdapter(), "unscored"),
                                (FailingStubAdapter(), "unscored"),
                                (DeterministicStubAdapter("null", OCRPayload(text=None)), "unscored"),
                                (DeterministicStubAdapter("empty", OCRPayload(text="")), "measured")):
            with self.subTest(adapter=adapter.engine_id):
                ensemble = run_ocr_ensemble([adapter], OCRRequest(object()))
                record = {"ocr_attempts": ensemble["attempts"], "ocr": {"available": True, "text": ""}}
                self.assertEqual(assess_metric_result(record, "ocr_symbol_score")["status"], status)


class MetricMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.experiment = self.root / "experiment"
        self.run_dir = self.experiment / "runs/saved"
        records = ocr_records()
        aggregate = summarize_results(records, 31, primary_metric="ocr_symbol_score")
        aggregate.pop("primary_metric_validity")
        for record in records:
            unavailable(record)
        self.run = {"run_id": "saved", "experiment_id": "exp-test", "created_at": "2026-01-01T00:00:00Z",
                    "blind_seed": 31, "profile": "baseline", "protocol": "ocr", "results": records,
                    "review_state": {"unblinded": True}, "review_session": {"complete": True},
                    "aggregate_statistics": aggregate, "analysis_configuration": {"detectors": ["ocr"]}}
        manifest = new_manifest()
        manifest["outputs"] = {"latest_run": "runs/saved", "review_state": "unblinded"}
        write_manifest(self.experiment, manifest)
        write_json(self.run_dir / "results.json", self.run)
        write_json(self.run_dir / "report.json", {"aggregate_statistics": aggregate, "pair_quality_report_version": 1})
        (self.run_dir / "report.html").write_text("original report")
        self.originals = {name: (self.run_dir / name).read_bytes() for name in ("results.json", "report.json", "report.html")}

    def assert_originals_preserved(self):
        for name, value in self.originals.items():
            self.assertEqual((self.run_dir / name).read_bytes(), value)

    def test_current_statistics_migrates_in_memory_and_preserves_the_original_object(self):
        before = copy.deepcopy(self.run)
        current = current_statistics(self.run)
        self.assertEqual(current["aggregate_statistics"]["evidence_ladder"], "not tested")
        self.assertIn("metric_validity_migration", current)
        self.assertNotIn("statistics_migration", current)
        self.assertEqual(self.run, before)
        self.assert_originals_preserved()

    def test_report_view_csv_and_html_label_unscored_values_without_rewriting_artifacts(self):
        report = app_api.load_latest_report(self.experiment)
        self.assertEqual(Path(report["local_paths"]["report_json"]).name, "report.metric-validity-v1.json")
        self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "not tested")
        self.assertIn("Unscored OCR", Path(report["local_paths"]["report_html"]).read_text())
        csv_path = app_api.export_candidates_csv(self.experiment, self.root / "candidates.csv")
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        self.assertTrue(all(row["primary_metric_score"] == "" and row["primary_metric_status"] == "unscored" for row in rows))
        self.assert_originals_preserved()

    def test_bundle_and_minimal_exchange_use_current_measurement_eligibility(self):
        output = export_review_bundle(self.experiment, self.root / "review.zip")
        with zipfile.ZipFile(output) as bundle:
            report = json.loads(bundle.read("report.json"))
            self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "not tested")
            self.assertIsNone(report["aggregate_statistics"]["permutation_p_value"])
        document = prepare_exchange(self.experiment)["document"]
        self.assertEqual(document["findings"]["evidence_level"], "not tested")
        self.assertEqual(document["primary_metric_validity"]["status"], "incomplete")
        self.assertIsNone(document["findings"]["permutation_p_value"])
        self.assertNotIn("PRIVATE", json.dumps(document))
        self.assert_originals_preserved()


class MetricPipelineTests(unittest.TestCase):
    def test_actual_pipeline_distinguishes_unavailable_and_successful_empty_recognition(self):
        from laserlab.pipeline import run_experiment, unblind_latest_run
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_synthetic_positive(root / "laser/sample.png")
            create_synthetic_negative(root / "control/sample.png")
            # Generated images exercise declared-capture plumbing, not empirical evidence.
            for state, adapter, expected in (("unavailable", UnavailableStubAdapter(), "primary_metric_unavailable"),
                                             ("empty", DeterministicStubAdapter("empty", OCRPayload(text="")),
                                              "insufficient_independent_samples")):
                with self.subTest(state=state):
                    experiment = root / state
                    for source, role in (("laser", "laser"), ("control", "matched_control")):
                        app_api.add_capture(experiment, root / source, "image-set", role,
                            capture_metadata={"independent_pair_id": "pair-one", "pair_exchangeability_acknowledged": True})
                    with patch("laserlab.detectors._TESSERACT_ADAPTER", adapter):
                        saved = run_experiment(experiment, profile_name="baseline", protocol="ocr", primary_metric="ocr_symbol_score",
                                               blind_seed=31, control_generation="none")
                    self.assertEqual(saved["aggregate_statistics"]["primary_metric_validity"]["status"], "sealed")
                    revealed = unblind_latest_run(experiment)
                    self.assertEqual(revealed["aggregate_statistics"]["inference"]["status"], expected)
                    self.assertEqual({item["primary_metric_measurement"]["status"] for item in revealed["results"]},
                                     {"unscored" if state == "unavailable" else "measured"})
                    if state == "unavailable":
                        self.assertTrue(all(item["inference_metric_score"] is None for item in revealed["results"]))
                    else:
                        self.assertTrue(all(item["inference_metric_score"] == 0 for item in revealed["results"]))


if __name__ == "__main__":
    unittest.main()
