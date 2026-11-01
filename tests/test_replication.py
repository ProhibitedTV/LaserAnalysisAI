"""Synthetic plumbing scenarios for conservative local session comparison."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from laserlab import app_api
from laserlab.artifacts import write_json, sha256_file, sha256_json, directory_fingerprint
from laserlab.manifest import new_manifest, write_manifest, load_manifest, DEFAULT_DETECTORS
from laserlab.replication import compare_sessions, export_comparison, record_replication_plan, comparison_html
from laserlab.stats import summarize_results
from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

try:
    from test_capture_inference import pairs, digest
except ModuleNotFoundError:
    from tests.test_capture_inference import pairs, digest


def synthetic_run(number: int, *, null: bool = False) -> dict:
    """Scores model declared-recording plumbing, not actual empirical research."""
    records = pairs(null=null)
    for record in records:
        record["sample_id"] += f"-PRIVATE-{number}"
        record["capture_id"] += f"-PRIVATE-{number}"
        record["capture_source_sha256"] = digest(f"original-{number}-" + record["capture_id"])
        record["source_sha256"] = digest(f"frame-{number}-" + record["sample_id"])
        record["capture_metadata"].update(
            acquisition_source_sha256=record["capture_source_sha256"], camera="PRIVATE camera description",
            exposure="PRIVATE exposure settings", focus_mode="manual", compression_history="original",
            projection_surface_type="matte_wall", projection_distance_meters=2,
            laser_to_target_geometry_notes="PRIVATE geometry", intermediate_material_notes="none",
            room_lighting_notes="PRIVATE room", camera_fixed=True, beam_path_fixed=True,
            projected_region_not_saturated=True, wavelength_nm=650, laser_pattern_type="cross", diffraction_optic_type="same optic")
        record["media_metadata"] = {"source_kind": "video", "width": 640, "height": 480, "fps": 30, "codec": "H264"}
    return {"experiment_id": f"PRIVATE-experiment-{number}", "run_id": f"PRIVATE-run-{number}",
            "created_at": "2026-01-02T00:00:00Z", "blind_seed": 31, "profile": "baseline", "protocol": "anomaly",
            "review_state": {"unblinded": True}, "results": records,
            "aggregate_statistics": summarize_results(records, 31),
            "pre_run_quality": {"status": "consistent", "requires_exploratory": False},
            "analysis_configuration": {"version": "analysis-config-v1", "detectors": DEFAULT_DETECTORS,
                                       "preprocessing_profile_sha256": digest("same-profile"), "roi": None,
                                       "preprocessing_intensity": "standard", "control_generation": "standard",
                                       "frame_sampling_mode": "interval", "ocr_engines": []},
            "replication_plan": {"version": "session-comparison-v1", "criterion": "same_primary_metric_above_control",
                                 "hypothesis_sha256": digest("PRIVATE-hypothesis"), "protocol": "anomaly", "primary_metric": "structure_score",
                                 "independent_original_acquisition_declared": True, "recorded_at": "2026-01-01T00:00:00Z"}}


class ReplicationComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runs = [synthetic_run(1), synthetic_run(2)]
        self.directories = [self.root / "PRIVATE-session-one", self.root / "PRIVATE-session-two"]
        self.save()

    def save(self):
        for directory, run in zip(self.directories, self.runs):
            manifest = new_manifest()
            manifest["outputs"] = {"latest_run": "runs/selected", "review_state": "unblinded"}
            write_manifest(directory, manifest)
            write_json(directory / "runs/selected/results.json", run)

    def test_positive_compatible_declarations_are_only_a_bounded_candidate(self):
        result = compare_sessions(self.directories)
        self.assertEqual(result["status"], "declared_replication_candidate")
        self.assertEqual(result["positive_session_count"], 2)
        self.assertEqual(result["sessions"][0]["independent_pair_count"], 5)
        self.assertEqual(result["sessions"][0]["within_session_p_value"], 1 / 32)
        self.assertNotIn("combined_p_value", result)
        self.assertNotIn("combined_score", result)
        self.assertIn("not verified independence", result["message"])
        self.assertTrue(all(value["status"] == "matched" for value in result["compatibility"]))

    def test_null_and_mixed_outcomes_are_not_positive_replication(self):
        self.runs = [synthetic_run(1, null=True), synthetic_run(2, null=True)]
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["status"], "no_positive_replication")
        self.assertEqual(result["null_session_count"], 2)
        self.runs[0] = synthetic_run(1)
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["positive_session_count"], 1)
        self.assertEqual(result["null_session_count"], 1)
        self.assertEqual(result["status"], "no_positive_replication")

    def test_copied_experiment_or_source_bytes_cannot_replicate(self):
        self.runs[1] = copy.deepcopy(self.runs[0])
        self.save()
        self.assertEqual(compare_sessions(self.directories)["status"], "shared_source_not_replication")
        self.runs[1] = synthetic_run(2)
        self.runs[1]["results"][0]["capture_source_sha256"] = self.runs[0]["results"][0]["capture_source_sha256"]
        self.save()
        self.assertEqual(compare_sessions(self.directories)["status"], "shared_source_not_replication")

    def test_nonoverlapping_derived_clips_with_shared_original_lineage_are_not_independent(self):
        # Different frame/container bytes still refer to the same original acquisition.
        for run in self.runs:
            run["results"][0]["capture_metadata"]["acquisition_source_sha256"] = digest("same-original-video")
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["status"], "shared_source_not_replication")
        self.assertTrue(any("lineage" in warning for warning in result["warnings"]))

    def test_shared_raw_frames_are_detected_across_different_source_hashes(self):
        self.runs[1]["results"][0]["source_sha256"] = self.runs[0]["results"][0]["source_sha256"]
        self.save()
        self.assertEqual(compare_sessions(self.directories)["status"], "shared_source_not_replication")

    def test_unknown_lineage_or_posthoc_hypothesis_remains_exploratory(self):
        for run in self.runs:
            for record in run["results"]:
                record["capture_metadata"].pop("acquisition_source_sha256")
        self.save()
        self.assertEqual(compare_sessions(self.directories)["status"], "exploratory_comparison")
        self.runs = [synthetic_run(1), synthetic_run(2)]
        self.runs[1]["replication_plan"]["recorded_at"] = "2026-02-01T00:00:00Z"
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["status"], "exploratory_comparison")
        self.assertTrue(any("cherry-picking" in warning for warning in result["warnings"]))

    def test_missing_or_incompatible_protocol_settings_and_geometry_are_visible(self):
        for change in (lambda r: r.update(protocol="speckle"),
                       lambda r: r["analysis_configuration"].update(roi={"x": 5}),
                       lambda r: r["results"][0]["capture_metadata"].update(camera=None),
                       lambda r: r["results"][0]["media_metadata"].update(width=1280),
                       lambda r: r["analysis_configuration"].pop("ocr_engines"),
                       lambda r: r.pop("analysis_configuration")):
            self.runs = [synthetic_run(1), synthetic_run(2)]
            change(self.runs[1])
            self.save()
            result = compare_sessions(self.directories)
            self.assertEqual(result["status"], "exploratory_comparison")
            self.assertTrue(result["warnings"])
        self.assertNotIn("combined_score", result)

    def test_persistence_does_not_promote_unverified_or_missing_control_results(self):
        for run in self.runs:
            run["aggregate_statistics"].update(evidence_ladder="not tested", laser_mean_persistence=1)
            run["aggregate_statistics"]["inference"]["status"] = "not_tested"
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["positive_session_count"], 0)
        self.assertEqual(result["null_session_count"], 0)
        self.assertEqual(result["status"], "exploratory_comparison")
        self.assertIn("not independent", result["replication_terms"]["repeat_within_capture"])

    def test_incomplete_or_invalid_saved_significance_is_not_a_tested_outcome(self):
        for value in (None, float("nan"), True, -1, 2):
            self.runs = [synthetic_run(1), synthetic_run(2)]
            self.runs[1]["aggregate_statistics"]["permutation_p_value"] = value
            self.save()
            result = compare_sessions(self.directories)
            self.assertEqual(result["status"], "exploratory_comparison")
            self.assertEqual(result["tested_session_count"], 1)
            self.assertIsNone(result["sessions"][1]["within_session_p_value"])

    def test_truncated_captures_cannot_inherit_saved_significance(self):
        self.runs[1]["results"].pop()
        self.save()
        result = compare_sessions(self.directories)
        self.assertEqual(result["status"], "exploratory_comparison")
        self.assertEqual(result["tested_session_count"], 1)
        self.assertIsNone(result["sessions"][1]["within_session_p_value"])

    def test_sealed_selection_and_duplicate_paths_fail_without_opening_private_maps(self):
        for state in ({"unblinded": False}, None, {}):
            self.runs[1]["review_state"] = state
            self.save()
            with self.assertRaisesRegex(ValueError, "unblinded"):
                compare_sessions(self.directories)
        with self.assertRaises(ValueError):
            compare_sessions([self.directories[0], self.directories[0]])
        with self.assertRaises(ValueError):
            compare_sessions(self.directories[:1])

    def test_export_is_pseudonymized_private_reviewed_read_only_and_snapshot_bound(self):
        before = {path: sha256_file(path) for directory in self.directories for path in directory.rglob("*.json")}
        result = compare_sessions(self.directories)
        content = json.dumps(result) + comparison_html(result)
        self.assertNotIn("PRIVATE", content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn(self.runs[0]["results"][0]["source_sha256"], content)
        self.assertEqual(result["sessions"][0]["session"], "S01")
        output = self.root / "summary.json"
        with self.assertRaises(ValueError):
            export_comparison(self.directories, output)
        export_comparison(self.directories, output, privacy_acknowledged=True, expected_snapshot=result["_snapshot_sha256"])
        self.assertNotIn("_snapshot", output.read_text())
        with self.assertRaises(FileExistsError):
            export_comparison(self.directories, output, privacy_acknowledged=True)
        self.assertEqual({path: sha256_file(path) for path in before}, before)
        self.runs[0]["created_at"] = "2026-01-03T00:00:00Z"
        self.save()
        with self.assertRaisesRegex(ValueError, "changed"):
            export_comparison(self.directories, self.root / "stale.json", privacy_acknowledged=True,
                              expected_snapshot=result["_snapshot_sha256"])


class ReplicationPipelineTests(unittest.TestCase):
    def test_pre_run_plan_cannot_be_retrofitted_and_stays_sealed_until_unblinding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            experiment = root / "experiment"
            app_api.create_experiment(experiment)
            declaration = record_replication_plan(experiment, "non-identifying-hypothesis", True)
            self.assertNotIn("non-identifying-hypothesis", json.dumps(declaration))
            with self.assertRaises(ValueError):
                record_replication_plan(experiment, "different", True)
            for role, generator in (("laser", create_synthetic_positive), ("matched_control", create_synthetic_negative)):
                source = root / role
                generator(source / "frame.png")
                original_hash = directory_fingerprint([source / "frame.png"])
                app_api.add_capture(experiment, source, "image-set", role,
                                    capture_metadata={"fixture_type": "synthetic", "footage_class": "regression_fixture",
                                                      "acquisition_source_sha256": original_hash})
            run = app_api.run_analysis(experiment, profile="baseline", control_generation="none")
            run_dir = experiment / load_manifest(experiment)["outputs"]["latest_run"]
            for filename in ("results.json", "report.json", "report.html"):
                self.assertNotIn(declaration["hypothesis_sha256"], (run_dir / filename).read_text())
            self.assertEqual(load_manifest(experiment)["replication_plan"], {"sealed": True})
            with self.assertRaises(ValueError):
                record_replication_plan(experiment, "retrofit", True)
            bundle = app_api.export_review_bundle(experiment, root / "sealed.zip")
            with zipfile.ZipFile(bundle) as archive:
                self.assertNotIn(declaration["hypothesis_sha256"].encode(), archive.read("results.json"))
            app_api.complete_review(experiment)
            report = app_api.unblind_latest_run(experiment)
            results = json.loads((run_dir / "results.json").read_text())
            self.assertEqual(results["replication_plan"], declaration)
            self.assertEqual(results["analysis_configuration"]["version"], "analysis-config-v1")
            with self.assertRaises(ValueError):
                app_api.export_review_bundle(experiment, root / "unreviewed.zip")
            app_api.export_review_bundle(experiment, root / "reviewed.zip", privacy_acknowledged=True)
            self.assertEqual(report["aggregate_statistics"]["evidence_ladder"], "not tested")
            other = root / "second-experiment"
            app_api.create_experiment(other)
            app_api.add_capture(other, root / "laser", "image-set", "laser",
                                capture_metadata={"fixture_type": "synthetic", "footage_class": "regression_fixture"})
            app_api.run_analysis(other, profile="baseline", control_generation="none")
            app_api.complete_review(other)
            app_api.unblind_latest_run(other)
            summary = compare_sessions([experiment, other])
            self.assertEqual(summary["status"], "exploratory_comparison")
            self.assertEqual(summary["tested_session_count"], 0)
            self.assertEqual(summary["sessions"][0]["empirical_capture_count"], 0)
            self.assertGreater(summary["sessions"][0]["source_class_frame_counts"]["synthetic_fixture"], 0)

    def test_invalid_lineage_hash_and_hypothesis_values_are_not_fabricated(self):
        from laserlab.capture_protocol import normalize_capture_metadata
        self.assertIsNone(normalize_capture_metadata({})["acquisition_source_sha256"])
        self.assertEqual(normalize_capture_metadata({"acquisition_source_sha256": "A" * 64})["acquisition_source_sha256"], "a" * 64)
        for value in ("invalid", "g" * 64, True):
            with self.assertRaises(ValueError):
                normalize_capture_metadata({"acquisition_source_sha256": value})
        with tempfile.TemporaryDirectory() as temporary:
            experiment = Path(temporary)
            app_api.create_experiment(experiment)
            with self.assertRaises(ValueError):
                record_replication_plan(experiment, "person@example.com", True)
            plan = record_replication_plan(experiment, "scope", "true")
            self.assertFalse(plan["independent_original_acquisition_declared"])


if __name__ == "__main__":
    unittest.main()
