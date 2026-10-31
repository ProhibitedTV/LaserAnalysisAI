from __future__ import annotations

import json
import platform
import tempfile
import unittest
import zipfile
from pathlib import Path

from laserlab.artifacts import sha256_json
from scripts.build_release import default_target, executable_name

try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401

    HAS_IMAGE_STACK = True
except ImportError:
    HAS_IMAGE_STACK = False

try:
    import PyQt5  # noqa: F401

    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False


class HashingTests(unittest.TestCase):
    def test_release_target_and_executable_names(self) -> None:
        self.assertRegex(default_target(), r"^(windows|macos|linux)-(?:x86_64|arm64)$")
        expected = "LaserLab.exe" if platform.system() == "Windows" else "LaserLab"
        self.assertEqual(executable_name("LaserLab"), expected)

    def test_sha256_json_is_stable(self) -> None:
        left = {"b": 2, "a": [3, 1]}
        right = {"a": [3, 1], "b": 2}
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_fixture_catalog_separates_redistributable_sources(self) -> None:
        from laserlab.fixtures import list_fixtures, validate_fixture_catalog

        redistributable = list_fixtures()
        full_catalog = list_fixtures(include_restricted=True)
        self.assertGreaterEqual(len(redistributable), 3)
        self.assertGreater(len(full_catalog), len(redistributable))
        self.assertTrue(all(item["redistributable"] for item in redistributable))
        media_dir = Path(__file__).resolve().parents[1] / "sample_media"
        self.assertEqual(validate_fixture_catalog(media_dir, require_bundled_files=True), [])
        manifest = json.loads((media_dir / "fixture_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["id"] for item in manifest["fixtures"]},
            {item["id"] for item in redistributable},
        )


class ProtocolPresetTests(unittest.TestCase):
    def test_protocol_presets_are_listable_and_describable(self) -> None:
        from laserlab.protocols import describe_protocol, list_protocol_presets

        presets = list_protocol_presets()
        ids = {item["id"] for item in presets}

        self.assertEqual(ids, {"diffraction", "speckle", "ocr", "anomaly"})
        self.assertIn("2D FFT", describe_protocol("diffraction"))
        self.assertIn("speckle", describe_protocol("speckle").lower())


class CaptureProtocolTests(unittest.TestCase):
    def test_wall_projection_metadata_and_subjective_context_validation(self) -> None:
        from laserlab.capture_protocol import (
            capture_protocol_warnings,
            normalize_capture_metadata,
            normalize_study_context,
        )

        metadata = normalize_capture_metadata(
            {
                "footage_class": "primary_wall_projection",
                "laser_pattern_type": "cross",
                "wavelength_nm": 650,
                "projection_surface_type": "matte_wall",
                "camera_fixed": True,
                "beam_path_fixed": True,
                "non_reflective_surface": True,
                "projected_region_not_saturated": True,
                "cross_center_visible": True,
                "entire_cross_visible": True,
                "laser_class_label": "reported class",
                "safety_acknowledged": True,
            }
        )
        self.assertEqual(metadata["color_label"], "red")
        self.assertEqual(capture_protocol_warnings(metadata), [])
        with self.assertRaises(ValueError):
            normalize_study_context({"mode": "retrospective_report", "privacy_acknowledged": False})
        context = normalize_study_context(
            {
                "mode": "retrospective_report",
                "privacy_acknowledged": True,
                "pseudonymous_session_id": "session-7",
            }
        )
        self.assertTrue(context["subjective_report_attached"])


@unittest.skipUnless(HAS_IMAGE_STACK, "OpenCV and NumPy are required for sampling tests")
class SamplingAndProvenanceTests(unittest.TestCase):
    def test_sampling_profiles_and_duplicate_suppression_are_deterministic(self) -> None:
        import shutil
        import cv2

        from laserlab.ingest import init_experiment
        from laserlab.sampling import SAMPLING_PROFILES, resolve_sampling_plan, scene_change_score
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        self.assertEqual(set(SAMPLING_PROFILES), {"quick", "baseline", "wide", "exhaustive"})
        self.assertEqual(resolve_sampling_plan("exhaustive")["mode"], "all_frames")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "images"
            first = create_synthetic_positive(source / "first.png", text="KNOWN")
            shutil.copy2(first, source / "duplicate.png")
            create_synthetic_negative(source / "different.png")

            manifests = []
            for name in ("experiment-a", "experiment-b"):
                manifests.append(
                    init_experiment(
                        source,
                        "image-set",
                        "laser",
                        root / name,
                        sampling_profile="exhaustive",
                        deduplicate=True,
                    )
                )

            left = manifests[0]["captures"][0]
            right = manifests[1]["captures"][0]
            self.assertEqual(len(left["frames"]), 2)
            self.assertEqual(left["sampling"]["duplicate_frames_skipped"], 1)
            self.assertEqual(
                [(item["frame_index"], item["frame_signature"], item["output_sha256"]) for item in left["frames"]],
                [(item["frame_index"], item["frame_signature"], item["output_sha256"]) for item in right["frames"]],
            )
            self.assertEqual(left["frames"][0]["extraction_settings"]["profile"], "exhaustive")
            self.assertEqual(left["frames"][0]["input_source_sha256"], manifests[0]["sources"][0]["sha256"])
            self.assertGreater(scene_change_score(None, cv2.imread(str(first))), 0.9)

    def test_provenance_warnings_and_extended_control_role(self) -> None:
        from laserlab.ingest import init_experiment
        from laserlab.pipeline import run_experiment, unblind_latest_run
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            laser = root / "laser"
            control = root / "control"
            experiment = root / "experiment"
            create_synthetic_positive(laser / "laser.png")
            create_synthetic_negative(control / "control.png")
            manifest = init_experiment(laser, "image-set", "laser", experiment, max_frames=1)
            manifest = init_experiment(control, "image-set", "matched_control", experiment, max_frames=1)

            capture = manifest["captures"][0]
            self.assertGreater(capture["media_metadata"]["width"], 0)
            self.assertGreater(len(capture["provenance_warnings"]), 0)
            self.assertGreater(len(manifest["validation_warnings"]), 0)

            run_experiment(experiment, profile_name="baseline", blind_seed=41, control_generation="none")
            revealed = unblind_latest_run(experiment)
            self.assertEqual(revealed["aggregate_statistics"]["control_count"], 1)


@unittest.skipUnless(HAS_IMAGE_STACK, "OpenCV and NumPy are required for image pipeline tests")
class LaserLabPipelineTests(unittest.TestCase):
    def test_candidate_ranking_uses_structure_only_as_a_primary_metric_tiebreaker(self) -> None:
        from laserlab.report import top_candidates

        base = {
            "sample_id": "sample-1",
            "blind_id": "B000001",
            "blinded_label": "B000001",
            "primary_metric": "ocr_symbol_score",
            "primary_metric_score": 0.0,
            "persistence_score": 0.0,
            "ocr": {"text": "", "confidence": 0.0},
            "candidate_rois": [],
            "processed_path": "runs/test/processed.png",
            "review_image_path": "runs/test/original.png",
            "detector_family_scores": {},
            "cross_pattern": {},
        }
        low = {**base, "structure_score": 0.1, "preprocessing_variant": "grayscale"}
        high = {**base, "structure_score": 0.8, "preprocessing_variant": "adaptive"}

        ranked = top_candidates([low, high], score_key="primary_metric_score", unblinded=False)

        self.assertEqual(ranked[0]["preprocessing_variant"], "adaptive")
        self.assertEqual(ranked[0]["primary_metric_score"], 0.0)

    def test_scientific_metrics_detect_synthetic_fixtures(self) -> None:
        import cv2

        from laserlab.scientific import (
            benjamini_hochberg_q_values,
            cross_pattern_metrics,
            fft_spectrum_metrics,
            glcm_texture_metrics,
            phase_registration_metrics,
            speckle_contrast_metrics,
        )
        from laserlab.synthetic import (
            create_shifted_copy,
            create_synthetic_cross,
            create_synthetic_grating,
            create_synthetic_positive,
            create_synthetic_speckle,
        )

        golden = json.loads(
            (Path(__file__).parent / "golden" / "scientific_summary.json").read_text(encoding="utf-8")
        )["scientific_metrics"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            grating = cv2.imread(str(create_synthetic_grating(root / "grating.png")), cv2.IMREAD_COLOR)
            speckle = cv2.imread(str(create_synthetic_speckle(root / "speckle.png")), cv2.IMREAD_COLOR)
            positive = create_synthetic_positive(root / "positive.png")
            shifted = create_shifted_copy(positive, root / "shifted.png", shift_x=7, shift_y=4)
            cross_path = create_synthetic_cross(root / "cross.png", rotation_degrees=7)
            cross_image = cv2.imread(str(cross_path), cv2.IMREAD_COLOR)

            fft = fft_spectrum_metrics(grating)
            speckle_metrics = speckle_contrast_metrics(speckle)
            texture = glcm_texture_metrics(speckle)
            registration = phase_registration_metrics(
                cv2.imread(str(positive), cv2.IMREAD_COLOR),
                cv2.imread(str(shifted), cv2.IMREAD_COLOR),
            )
            cross = cross_pattern_metrics(cross_image)
            from laserlab.detectors import DetectorContext, extract_cross_rois

            cross_rois = extract_cross_rois(
                cross_image,
                DetectorContext(root, root / "run", "B000001", "grayscale", cross_image),
                cross,
            )

        self.assertGreater(fft["peak_prominence"], golden["fft_peak_prominence_min"])
        self.assertGreater(fft["ring_energy_ratio"], 0.0)
        self.assertGreater(speckle_metrics["spatial_contrast_mean"], golden["speckle_contrast_min"])
        self.assertLess(speckle_metrics["spatial_contrast_mean"], golden["speckle_contrast_max"])
        self.assertIn("entropy", texture)
        tolerance = golden["phase_shift_tolerance_px"]
        self.assertAlmostEqual(registration["shift_x"], 7.0, delta=tolerance)
        self.assertAlmostEqual(registration["shift_y"], 4.0, delta=tolerance)
        self.assertGreater(registration["response"], golden["phase_registration_response_min"])
        self.assertTrue(cross["detected"])
        self.assertGreater(cross["confidence"], 0.5)
        self.assertEqual(
            {item["region_type"] for item in cross_rois},
            {"cross_center", "horizontal_arm", "vertical_arm"},
        )
        self.assertEqual(benjamini_hochberg_q_values([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04])

    def test_image_set_ingest_run_and_report(self) -> None:
        from laserlab import app_api
        from laserlab.ingest import init_experiment
        from laserlab.manifest import load_manifest
        from laserlab.pipeline import run_experiment
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_laser = root / "laser"
            source_control = root / "control"
            experiment = root / "experiment"

            create_synthetic_positive(source_laser / "laser_001.png", text="SIGNAL 314")
            create_synthetic_negative(source_control / "control_001.png")

            init_experiment(source_laser, "image-set", "laser", experiment)
            init_experiment(source_control, "image-set", "control", experiment)

            manifest = load_manifest(experiment)
            self.assertEqual(len(manifest["captures"]), 2)
            self.assertEqual(manifest["captures"][0]["frames"][0]["frame_index"], 0)
            self.assertTrue((experiment / manifest["captures"][0]["frames"][0]["path"]).exists())

            run = run_experiment(experiment, profile_name="baseline", blind_seed=123)
            run_dir = experiment / "runs" / run["run_id"]

            self.assertTrue((run_dir / "results.json").exists())
            self.assertTrue((run_dir / "report.json").exists())
            self.assertTrue((run_dir / "report.html").exists())
            self.assertGreater(len(run["results"]), 0)
            for result in run["results"]:
                self.assertTrue(result["candidate_rois"])
                self.assertTrue((experiment / result["roi_overlay_path"]).exists())
                self.assertGreaterEqual(len(result["ocr_attempts"]), 1)
                self.assertEqual(result["ocr_ensemble"]["agreement_scope"], "per_roi")
                for attempt in result["ocr_attempts"]:
                    reference = attempt.get("roi_reference") or {}
                    self.assertTrue(reference.get("id"))
                for roi in result["candidate_rois"]:
                    self.assertTrue((experiment / roi["crop_path"]).exists())
                    self.assertTrue((experiment / roi["processed_crop_path"]).exists())
                    self.assertTrue((experiment / roi["mask_path"]).exists())
            self.assertIn("permutation_p_value", run["aggregate_statistics"])
            self.assertIn("evidence_ladder", run["aggregate_statistics"])
            self.assertEqual(run["aggregate_statistics"]["evidence_ladder"], "blinded review")
            self.assertFalse(run["review_state"]["unblinded"])

            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["run_id"], run["run_id"])
            self.assertIn("top_candidates", report)
            self.assertNotIn("source_path", report["top_candidates"][0])
            self.assertNotIn("unblinded_label", report["top_candidates"][0])
            self.assertIn("primary_metric_score", report["top_candidates"][0])
            self.assertIn("ocr_attempts", report["top_candidates"][0])
            self.assertIn("ocr_ensemble", report["top_candidates"][0])
            self.assertIn("roi_overlay_path", report["top_candidates"][0])
            self.assertIn("review blinded", report["badges"])
            sealed_manifest = load_manifest(experiment)
            self.assertTrue(all(source.get("sealed") for source in sealed_manifest["sources"]))
            self.assertTrue(all("path" not in source and "label" not in source for source in sealed_manifest["sources"]))

            latest = app_api.load_latest_report(experiment)
            self.assertEqual(latest["run_id"], run["run_id"])
            csv_path = app_api.export_candidates_csv(experiment, root / "candidates.csv")
            self.assertTrue(csv_path.exists())
            header = csv_path.read_text(encoding="utf-8").splitlines()[0]
            self.assertNotIn("source_path", header)
            self.assertNotIn("unblinded_label", header)
            self.assertIn("primary_metric_score", header)

            blind_id = latest["top_candidates"][0]["blind_id"]
            app_api.save_review_annotation(
                experiment,
                blind_id=blind_id,
                note="Repeated edge structure; inspect independently.",
                flags=["interesting", "persistent"],
            )
            app_api.complete_review(experiment)
            latest = app_api.load_latest_report(experiment)
            self.assertTrue(latest["review_session"]["complete"])
            self.assertEqual(latest["review_annotations"][blind_id]["flags"], ["interesting", "persistent"])
            self.assertNotIn("source_path", latest["top_candidates"][0])

            bundle_path = app_api.export_review_bundle(experiment, root / "review_bundle.zip")
            self.assertTrue(bundle_path.exists())
            with zipfile.ZipFile(bundle_path) as bundle:
                names = set(bundle.namelist())
                bundled_manifest = json.loads(bundle.read("manifest.json"))
                bundled_results = bundle.read("results.json").decode("utf-8")
            self.assertIn("manifest.json", names)
            self.assertIn("report.json", names)
            self.assertIn("results.json", names)
            self.assertIn("environment.json", names)
            self.assertIn("README.txt", names)
            self.assertTrue(any(name.startswith("top_originals/") for name in names))
            self.assertTrue(any(name.startswith("top_overlays/") for name in names))
            self.assertTrue(any(name.startswith("top_processed_crops/") for name in names))
            self.assertTrue(any(name.startswith("top_roi_masks/") for name in names))
            self.assertEqual(bundled_manifest["sources"], [])
            self.assertNotIn("unblinded_label", bundled_results)
            self.assertNotIn(str(source_laser), bundled_results)
            self.assertIn("Repeated edge structure", bundled_results)
            with self.assertRaises(ValueError):
                app_api.export_review_bundle(experiment, root / "forbidden.zip", include_media=True)

            revealed = app_api.unblind_latest_run(experiment)
            self.assertTrue(revealed["review_state"]["unblinded"])
            self.assertIn("source_path", revealed["top_candidates"][0])
            self.assertIn("unblinded_label", revealed["top_candidates"][0])
            self.assertIn("multiple comparisons corrected", revealed["badges"])
            self.assertEqual(
                revealed["review_annotations"][blind_id]["note"],
                "Repeated edge structure; inspect independently.",
            )
            self.assertFalse((run_dir / ".laserlab_unblind.json").exists())
            restored_manifest = load_manifest(experiment)
            self.assertTrue(all("path" in source and "label" in source for source in restored_manifest["sources"]))

    def test_tesseract_is_optional(self) -> None:
        from laserlab.detectors import run_ocr
        from laserlab.synthetic import create_synthetic_positive
        import cv2

        with tempfile.TemporaryDirectory() as temp:
            image_path = create_synthetic_positive(Path(temp) / "positive.png")
            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            result = run_ocr(image)
            self.assertIn("available", result)
            self.assertIn("text", result)

    def test_matched_null_fixture_cannot_promote_above_control(self) -> None:
        from laserlab.ingest import init_experiment
        from laserlab.pipeline import run_experiment, unblind_latest_run
        from laserlab.synthetic import create_synthetic_negative

        golden = json.loads(
            (Path(__file__).parent / "golden" / "scientific_summary.json").read_text(encoding="utf-8")
        )["null_run"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            laser = root / "laser"
            control = root / "control"
            experiment = root / "experiment"
            create_synthetic_negative(laser / "null.png")
            create_synthetic_negative(control / "null.png")
            init_experiment(laser, "image-set", "laser", experiment, max_frames=1)
            init_experiment(control, "image-set", "control", experiment, max_frames=1)
            run = run_experiment(experiment, profile_name="baseline", blind_seed=314)
            run = unblind_latest_run(experiment)

        ladder = run["aggregate_statistics"]["evidence_ladder"]
        self.assertIn(ladder, golden["allowed_evidence_levels"])
        self.assertNotIn(ladder, golden["forbidden_evidence_levels"])

    def test_wide_profile_has_parameter_sweep_variants(self) -> None:
        from laserlab.manifest import WIDE_PROFILE
        from laserlab.preprocessing import apply_profile_variants
        from laserlab.synthetic import create_synthetic_positive
        import cv2

        with tempfile.TemporaryDirectory() as temp:
            image_path = create_synthetic_positive(Path(temp) / "positive.png")
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            processed = apply_profile_variants(image, WIDE_PROFILE)

        variant_names = {item.variant_name for item in processed}
        self.assertGreaterEqual(len(processed), 15)
        self.assertIn("threshold_128", variant_names)
        self.assertIn("adaptive_51", variant_names)
        self.assertIn("resize_2x_otsu", variant_names)

    def test_app_api_fixture_style_flow(self) -> None:
        from laserlab import app_api
        from laserlab.synthetic import create_synthetic_negative, create_synthetic_positive

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            laser = root / "laser"
            control = root / "control"
            experiment = root / "experiment"
            create_synthetic_positive(laser / "laser.png")
            create_synthetic_negative(control / "control.png")

            manifest = app_api.create_experiment(experiment)
            self.assertIn("experiment_id", manifest)
            app_api.update_study_context(
                experiment,
                {
                    "mode": "retrospective_report",
                    "pseudonymous_session_id": "session-test",
                    "perception_notes": "Context only.",
                    "confidence": 0.5,
                    "privacy_acknowledged": True,
                },
            )
            trials_path = root / "trials.json"
            trials_path.write_text(
                json.dumps(
                    [
                        {"trial_id": "s1", "stimulus_truth": True, "response": "yes", "confidence": 0.8},
                        {"trial_id": "s2", "stimulus_truth": True, "response": "no", "confidence": 0.6},
                        {"trial_id": "n1", "stimulus_truth": False, "response": "yes", "confidence": 0.5},
                        {"trial_id": "n2", "stimulus_truth": False, "response": "no", "confidence": 0.9},
                    ]
                ),
                encoding="utf-8",
            )
            app_api.import_psychophysics_trials(experiment, trials_path)
            reference_path = root / "community-reference.json"
            reference_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "reference-secret",
                                "laser_wavelength": 532,
                                "pattern": "cross",
                                "observed_code": "context-secret",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            app_api.import_external_dataset_reference(experiment, reference_path)
            symbols_path = root / "symbol-transcriptions.json"
            symbols_path.write_text(
                json.dumps(
                    [
                        {
                            "pseudonymous_id": "observer-secret",
                            "coordinate_x": 12,
                            "coordinate_y": 8,
                            "coordinate_space": "pixels",
                            "timestamp_seconds": 2.5,
                            "wavelength_nm": 532,
                            "laser_pattern_type": "cross",
                            "transcription": "K-7-secret",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            app_api.import_symbol_transcriptions(experiment, symbols_path)
            app_api.add_capture(
                experiment,
                laser,
                "image-set",
                "laser",
                max_frames=1,
                capture_metadata={
                    "fixture_id": "synthetic-test-positive",
                    "fixture_title": "Synthetic test positive",
                    "limitations": "Unit-test fixture only",
                },
            )
            app_api.add_capture(experiment, control, "image-set", "control", max_frames=1)
            run = app_api.run_analysis(experiment, profile="baseline", blind_seed=99)
            report = app_api.load_latest_report(experiment)

            self.assertEqual(report["run_id"], run["run_id"])
            self.assertIn("local_paths", report)
            self.assertFalse(report["review_state"]["unblinded"])
            self.assertTrue(report["study_context"].get("sealed"))
            self.assertEqual(report["subjective_reports"], [])
            self.assertTrue(report["psychophysics_analysis"].get("sealed"))
            self.assertTrue(report["falsification_matrix"].get("sealed"))
            self.assertEqual(report["external_dataset_references"], [])
            self.assertEqual(report["symbol_transcription_summary"]["record_count"], 0)
            self.assertEqual(report["source_provenance"], [])
            public_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    experiment / "manifest.json",
                    Path(report["local_paths"]["results_json"]),
                    Path(report["local_paths"]["report_json"]),
                )
            )
            for secret in ("s1", "reference-secret", "context-secret", "observer-secret", "K-7-secret"):
                self.assertNotIn(secret, public_text)
            bundle_path = app_api.export_review_bundle(experiment, root / "sealed-research-bundle.zip")
            with zipfile.ZipFile(bundle_path) as bundle:
                bundled_public_text = "\n".join(
                    bundle.read(name).decode("utf-8")
                    for name in ("manifest.json", "results.json", "report.json")
                )
            for secret in ("s1", "reference-secret", "context-secret", "observer-secret", "K-7-secret"):
                self.assertNotIn(secret, bundled_public_text)
            seal_path = Path(report["local_paths"]["run_dir"]) / ".laserlab_unblind.json"
            sealed_payload = seal_path.read_bytes()
            seal_path.write_bytes(sealed_payload + b" ")
            with self.assertRaises(ValueError):
                app_api.unblind_latest_run(experiment)
            seal_path.write_bytes(sealed_payload)
            report = app_api.unblind_latest_run(experiment)
            self.assertEqual(report["study_context"]["mode"], "retrospective_report")
            self.assertEqual(report["subjective_reports"][0]["evidence_role"], "context_only")
            self.assertEqual(report["psychophysics_analysis"]["analysis_status"], "tested")
            matrix = {row["id"]: row for row in report["falsification_matrix"]["rows"]}
            self.assertEqual(matrix["participant_discrimination"]["status"], "tested")
            self.assertEqual(matrix["wall_coordinate_stability"]["status"], "not_tested")
            self.assertEqual(len(report["external_dataset_references"]), 1)
            self.assertEqual(report["symbol_transcription_summary"]["record_count"], 1)
            self.assertIn("external metadata context only", report["badges"])
            self.assertIn("symbol transcriptions context only", report["badges"])
            self.assertEqual(report["source_provenance"][0]["fixture_id"], "synthetic-test-positive")
            with self.assertRaises(ValueError):
                app_api.export_review_bundle(experiment, root / "unreviewed-context.zip")
            reviewed_bundle = app_api.export_review_bundle(
                experiment,
                root / "reviewed-context.zip",
                privacy_acknowledged=True,
            )
            self.assertTrue(reviewed_bundle.exists())
            self.assertIn(
                "Unit-test fixture only",
                Path(report["local_paths"]["report_html"]).read_text(encoding="utf-8"),
            )

            manifest = app_api.update_analysis_plan(
                experiment,
                protocol="diffraction",
                primary_metric="fft_peak_prominence",
                preprocessing_intensity="wide",
                control_generation="strict",
                frame_sampling_mode="capped_all_frames",
                roi={"x": 0, "y": 0, "width": 120, "height": 80},
            )
            self.assertEqual(manifest["analysis_plan"]["frame_sampling_mode"], "capped_all_frames")
            estimate = app_api.estimate_run(experiment, profile="wide", protocol="diffraction", control_generation="strict")
            self.assertEqual(estimate["control_generation"], "strict")
            self.assertGreater(estimate["detector_records"], 0)


@unittest.skipUnless(HAS_PYQT, "PyQt5 is required for dashboard smoke tests")
class LaserLabGuiTests(unittest.TestCase):
    def test_dashboard_instantiates_core_tabs(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gui.lab_dashboard import LabDashboardWindow

        app = QApplication.instance() or QApplication([])
        window = LabDashboardWindow()
        try:
            self.assertEqual(window.tabs.count(), 5)
            self.assertEqual([window.tabs.tabText(index) for index in range(5)], ["Setup", "Run", "Review", "Compare", "Export"])
            self.assertGreaterEqual(window.fixture_table.rowCount(), 4)
            self.assertEqual(window.home_demo_button.text(), "Run bundled demo")
            self.assertGreater(window.protocol_combo.count(), 3)
            self.assertEqual(window.candidate_table.columnCount(), 7)
            self.assertEqual(window.unblind_button.text(), "Unblind and compare")
            self.assertEqual(
                [window.setup_steps.tabText(index) for index in range(window.setup_steps.count())],
                ["1  Experiment", "2  Add Capture", "3  Analysis Plan", "Demo"],
            )
            self.assertFalse(window.capture_advanced.isVisible())
            self.assertFalse(window.protocol_advanced.isVisible())
            self.assertFalse(window.community_tools.isVisible())
            self.assertEqual(window.show_processed_overlay.text(), "ROI boxes")
            self.assertEqual(window.show_crop_overlay.text(), "Candidate crop")
            self.assertEqual(window.psychophysics_status.text(), "Not attached")
            self.assertEqual(window.footage_class_combo.currentData(), "primary_wall_projection")
            self.assertEqual(window.sampling_profile.count(), 4)
            self.assertEqual(
                set(window.review_flag_checks),
                {"interesting", "artifact", "ocr_hit", "persistent", "exclude"},
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
