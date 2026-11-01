"""Truthful, bounded setup diagnostics with no inferred acquisition facts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from laserlab.pair_quality import assess_experiment, inspect_pair


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class PairQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"outputs": {}, "sources": [], "captures": []}
        for role, seed in (("laser", 13), ("matched_control", 27)):
            capture_id = role
            source_id = "source-" + role
            # Generated pixels test diagnostic plumbing, not empirical research validity.
            image = np.random.default_rng(seed).integers(30, 220, (192, 256, 3), dtype=np.uint8)
            frames = []
            for index in range(3):
                path = self.root / "frames" / capture_id / f"frame-{index}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), image)
                frames.append({"path": str(path.relative_to(self.root)), "source_sha256": digest(role + str(index))})
            self.manifest["sources"].append({"source_id": source_id, "sha256": digest(role)})
            self.manifest["captures"].append({
                "capture_id": capture_id, "source_id": source_id, "label": role, "kind": "image-set", "frames": frames,
                "media_metadata": {"width": 256, "height": 192, "image_count": 3, "formats": ["png"]},
                "metadata": {"footage_class": "primary_wall_projection", "independent_pair_id": "pair-01",
                             "pair_exchangeability_acknowledged": True, "camera": "private camera model",
                             "exposure": "private exposure", "focus_mode": "fixed", "compression_history": "original",
                             "projection_surface_type": "matte_wall", "projection_distance_meters": 2,
                             "laser_to_target_geometry_notes": "private geometry", "intermediate_material_notes": "none present",
                             "room_lighting_notes": "private room", "camera_fixed": True, "beam_path_fixed": True,
                             "non_reflective_surface": True, "projected_region_not_saturated": True}})

    def inspect(self):
        return inspect_pair(self.root, self.manifest, "laser", "matched_control")

    def check(self, result, key):
        return next(check for check in result["checks"] if check["key"] == key)

    def test_consistent_details_are_not_validation_and_do_not_mutate(self):
        before = copy.deepcopy(self.manifest)
        result = self.inspect()
        self.assertEqual(result["laser_capture_id"], "laser")
        self.assertEqual(result["control_capture_id"], "matched_control")
        self.assertEqual(result["status"], "consistent")
        self.assertIn("does not validate", result["summary"])
        self.assertEqual(self.manifest, before)
        content = json.dumps(result)
        for private in ("private camera model", "private exposure", "private geometry", "private room", str(self.root), digest("laser")):
            self.assertNotIn(private, content)
        self.assertFalse(assess_experiment(self.root, self.manifest)["requires_exploratory"])

    def test_missing_information_is_unknown_and_difference_is_mismatch(self):
        self.manifest["captures"][0]["metadata"]["exposure"] = None
        self.manifest["captures"][1]["metadata"]["camera_fixed"] = None
        result = self.inspect()
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(self.check(result, "exposure")["status"], "unknown")
        self.assertEqual(self.check(result, "camera_fixed")["status"], "unknown")
        self.manifest["captures"][1]["media_metadata"]["width"] = 640
        self.manifest["captures"][1]["metadata"]["camera"] = "other model"
        result = self.inspect()
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(self.check(result, "resolution")["status"], "mismatch")
        self.assertEqual(self.check(result, "camera")["status"], "mismatch")
        self.assertTrue(assess_experiment(self.root, self.manifest)["requires_exploratory"])

    def test_matching_automatic_modes_do_not_verify_equal_capture_settings(self):
        for key in ("exposure", "focus_mode"):
            for capture in self.manifest["captures"]:
                capture["metadata"][key] = " Auto "
            self.assertEqual(self.check(self.inspect(), key)["status"], "unknown")
            for capture in self.manifest["captures"]:
                capture["metadata"][key] = "manual; auto off"
            self.assertEqual(self.check(self.inspect(), key)["status"], "matched")

    def test_false_reported_condition_is_not_unknown(self):
        self.manifest["captures"][0]["metadata"]["projected_region_not_saturated"] = False
        self.assertEqual(self.check(self.inspect(), "projected_region_not_saturated")["status"], "mismatch")

    def test_shared_source_and_frame_hashes_are_rejected(self):
        self.manifest["sources"][1]["sha256"] = self.manifest["sources"][0]["sha256"]
        result = self.inspect()
        self.assertEqual(self.check(result, "source_provenance")["status"], "mismatch")
        self.manifest["sources"][1]["sha256"] = digest("distinct")
        self.manifest["captures"][1]["frames"][0]["source_sha256"] = self.manifest["captures"][0]["frames"][0]["source_sha256"]
        self.assertEqual(self.check(self.inspect(), "shared_frames")["status"], "mismatch")

    def test_fixtures_generated_and_other_control_roles_never_become_empirical(self):
        control = self.manifest["captures"][1]
        for changes in ({"synthetic": True}, {"parent_capture_id": "parent"}, {"label": "synthetic_negative"},
                        {"label": "control"}, {"label": "sensor_noise"},
                        {"metadata": {**control["metadata"], "fixture_id": "public-demo"}},
                        {"metadata": {**control["metadata"], "footage_class": "demo_fixture"}}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(control)
                control.update(changes)
                self.assertEqual(self.check(self.inspect(), "source_type")["status"], "mismatch")
                control.clear()
                control.update(original)

    def test_sealed_and_invalid_ids_are_rejected_before_frame_reads(self):
        with patch("cv2.imread", side_effect=AssertionError("must not read images")):
            for ids in ((None, "matched_control"), ("laser", "laser"), ("missing", "matched_control")):
                with self.assertRaises(ValueError):
                    inspect_pair(self.root, self.manifest, *ids)
            self.manifest["outputs"]["review_state"] = "blinded"
            with self.assertRaisesRegex(ValueError, "sealed"):
                self.inspect()
            with self.assertRaisesRegex(ValueError, "sealed"):
                assess_experiment(self.root, self.manifest)

    def test_frame_inspection_bound_and_source_videos_never_opened(self):
        for capture in self.manifest["captures"]:
            capture["frames"] = capture["frames"] * 1000
            capture["kind"] = "video"
            capture["media_metadata"].update(fps=30, frame_count=3000, duration_ms=100000, codec="H264")
        original_read = cv2.imread
        with patch("cv2.imread", wraps=original_read) as read, patch("cv2.VideoCapture", side_effect=AssertionError("source video opened")):
            result = self.inspect()
        self.assertEqual(read.call_count, 6)
        for side in ("laser", "control"):
            self.assertEqual(result["observations"][side]["sampled_frame_count"], 3)
            self.assertLessEqual(result["observations"][side]["max_dimension"], 256)

    def test_outside_and_non_imported_paths_are_not_read(self):
        outside = self.root.parent / "not-allowed.png"
        frames = self.manifest["captures"][0]["frames"]
        for frame, path in zip(frames, (str(outside), "../not-allowed.png", "original.png")):
            frame["path"] = path
        original_read = cv2.imread
        with patch("cv2.imread", wraps=original_read) as read:
            result = self.inspect()
        self.assertEqual(read.call_count, 3)
        self.assertEqual(result["observations"]["laser"]["sampled_frame_count"], 0)
        self.assertEqual(self.check(result, "sample_readability")["status"], "unknown")

    def test_missing_and_unreadable_frames_stay_unknown(self):
        capture = self.manifest["captures"][0]
        for frame in capture["frames"]:
            (self.root / frame["path"]).write_text("not an image")
        result = self.inspect()
        self.assertIsNone(result["observations"]["laser"]["clipped_channel_fraction"])
        self.assertEqual(self.check(result, "motion")["status"], "unknown")

    def test_approximate_clipping_and_reliable_motion_are_flagged(self):
        capture = self.manifest["captures"][0]
        base = cv2.imread(str(self.root / capture["frames"][0]["path"]))
        for index, frame in enumerate(capture["frames"]):
            moved = np.roll(base, index * 8, axis=1)
            moved[40:100, 40:100, 2] = 255
            cv2.imwrite(str(self.root / frame["path"]), moved)
        result = self.inspect()
        self.assertEqual(self.check(result, "clipping")["status"], "mismatch")
        self.assertTrue(self.check(result, "clipping")["approximate"])
        self.assertEqual(self.check(result, "motion")["status"], "mismatch")

    def test_flat_or_sparse_frames_do_not_claim_stationarity(self):
        for capture in self.manifest["captures"]:
            capture["frames"] = capture["frames"][:1]
            cv2.imwrite(str(self.root / capture["frames"][0]["path"]), np.full((50, 50, 3), 80, np.uint8))
        result = self.inspect()
        self.assertEqual(self.check(result, "motion")["status"], "unknown")
        self.assertEqual(result["status"], "unknown")

    def test_three_stationary_frames_are_not_rewindowed_between_comparisons(self):
        original = cv2.phaseCorrelate
        inputs = []

        def record(reference, moving, window):
            inputs.append((reference.copy(), moving.copy()))
            return original(reference, moving, window)

        with patch("cv2.phaseCorrelate", side_effect=record):
            result = self.inspect()
        self.assertEqual(len(inputs), 4)  # Two adjacent comparisons for each capture.
        for index, side in enumerate(("laser", "control")):
            self.assertTrue(np.array_equal(inputs[index * 2][1], inputs[index * 2 + 1][0]))
            observed = result["observations"][side]["motion"]
            self.assertEqual(observed["reliable_comparisons"], 2)
            self.assertEqual(observed["status"], "no_large_shift_detected")
            self.assertLess(observed["maximum_shift_fraction"], .001)

    def test_three_known_shift_frames_recover_both_adjacent_shifts(self):
        capture = self.manifest["captures"][0]
        base = cv2.imread(str(self.root / capture["frames"][0]["path"]))
        for index, frame in enumerate(capture["frames"]):
            cv2.imwrite(str(self.root / frame["path"]), np.roll(base, index * 6, axis=1))
        motion = self.inspect()["observations"]["laser"]["motion"]
        self.assertEqual(motion["reliable_comparisons"], 2)
        self.assertEqual(motion["status"], "motion_warning")
        self.assertAlmostEqual(motion["maximum_shift_fraction"], 6 / 192, delta=.005)

    def test_descriptive_brightness_difference_does_not_imply_mismatch(self):
        control = self.manifest["captures"][1]
        for frame in control["frames"]:
            path = self.root / frame["path"]
            cv2.imwrite(str(path), cv2.imread(str(path)) // 2)
        result = self.inspect()
        self.assertNotEqual(result["observations"]["laser"]["brightness_histogram"], result["observations"]["control"]["brightness_histogram"])
        self.assertEqual(self.check(result, "brightness")["status"], "unknown")
        self.assertEqual(result["status"], "consistent")

    def test_unequal_duration_and_frame_counts_are_descriptive_not_a_gate(self):
        for capture in self.manifest["captures"]:
            capture["kind"] = "video"
            capture["media_metadata"].update(fps=30, codec="H264", frame_count=300, duration_ms=10000)
        self.manifest["captures"][1]["media_metadata"].update(frame_count=600, duration_ms=20000)
        result = self.inspect()
        self.assertEqual(result["status"], "consistent")
        self.assertEqual(self.check(result, "frame_count")["status"], "mismatch")
        self.assertTrue(self.check(result, "frame_count")["descriptive"])
        self.assertTrue(self.check(result, "duration_ms")["descriptive"])
        self.assertFalse(assess_experiment(self.root, self.manifest)["requires_exploratory"])
        self.manifest["captures"][1]["media_metadata"]["duration_ms"] = None
        result = self.inspect()
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(self.check(result, "duration_ms")["status"], "unknown")

    def test_single_channel_clipping_is_measured_before_preview_resize(self):
        # A fine checkerboard loses its clipped red pixels under AREA downsampling.
        image = np.full((1024, 1024, 3), 100, np.uint8)
        image[::2, ::2, 2] = 255
        for frame in self.manifest["captures"][0]["frames"]:
            cv2.imwrite(str(self.root / frame["path"]), image)
        result = self.inspect()
        self.assertEqual(result["observations"]["laser"]["clipped_channel_fraction"], .25)
        self.assertEqual(self.check(result, "clipping")["status"], "mismatch")

    def test_no_ids_one_pair_is_descriptive_multiple_unassigned_are_not_invented(self):
        for capture in self.manifest["captures"]:
            capture["metadata"].pop("independent_pair_id")
        result = assess_experiment(self.root, self.manifest)
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(self.check(result["pairs"][0], "independent_design")["status"], "unknown")
        self.manifest["captures"].append(copy.deepcopy(self.manifest["captures"][0]))
        result = assess_experiment(self.root, self.manifest)
        self.assertEqual(result["pairs"], [])
        self.assertTrue(result["requires_exploratory"])
        self.assertIn("unassigned_captures", {item["key"] for item in result["checks"]})

    def test_incomplete_or_ambiguous_declared_groups_fail_closed(self):
        self.manifest["captures"][1]["metadata"]["independent_pair_id"] = "other-pair"
        result = assess_experiment(self.root, self.manifest)
        self.assertEqual(result["pairs"], [])
        self.assertTrue(result["requires_exploratory"])
        self.assertTrue(all(item["status"] == "unknown" for item in result["checks"]))

    def test_copy_across_declared_pairs_is_detected(self):
        captures = copy.deepcopy(self.manifest["captures"])
        for capture in captures:
            capture["capture_id"] += "-copy"
            capture["metadata"]["independent_pair_id"] = "pair-02"
        self.manifest["captures"].extend(captures)
        result = assess_experiment(self.root, self.manifest)
        self.assertEqual(len(result["pairs"]), 2)
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("shared_experiment_sources", {item["key"] for item in result["checks"]})


if __name__ == "__main__":
    unittest.main()
