from __future__ import annotations

import json
import unittest

import cv2
import numpy as np

from laserlab.roi_detection import crop_rois, detect_code_rois, draw_roi_overlay, non_max_suppression


class RoiDetectionTests(unittest.TestCase):
    def test_synthetic_text_produces_ranked_code_roi(self) -> None:
        image = np.full((180, 360), 18, dtype=np.uint8)
        cv2.putText(image, "A7 GRID", (58, 108), cv2.FONT_HERSHEY_SIMPLEX, 1.55, 235, 3, cv2.LINE_AA)

        rois = detect_code_rois(image, max_rois=4, parent_variant={"name": "clahe", "level": 2})

        self.assertFalse(rois[0]["fallback"])
        self.assertIn("repeated_glyph_contours", rois[0]["detector_reasons"])
        self.assertGreater(rois[0]["score"], 0.52)
        self.assertEqual(rois[0]["parent_variant"]["name"], "clahe")
        self.assertEqual(rois[0]["parent_variant"]["width"], 360)
        json.dumps(rois)

    def test_synthetic_grid_reports_grid_reason(self) -> None:
        image = np.full((220, 300), 16, dtype=np.uint8)
        for x in range(45, 256, 42):
            cv2.line(image, (x, 38), (x, 182), 225, 2)
        for y in range(38, 183, 36):
            cv2.line(image, (45, y), (255, y), 225, 2)

        rois = detect_code_rois(image, max_rois=3)

        self.assertTrue(any("grid_like_arrangement" in roi["detector_reasons"] for roi in rois))
        grid = next(roi for roi in rois if "grid_like_arrangement" in roi["detector_reasons"])
        self.assertFalse(grid["fallback"])
        self.assertGreaterEqual(grid["component_scores"]["structure_density"], 0.4)

    def test_smooth_and_noise_negatives_use_full_frame_fallback(self) -> None:
        smooth = np.tile(np.linspace(65, 120, 320, dtype=np.uint8), (180, 1))
        noise = np.random.default_rng(90210).integers(0, 256, size=(180, 320), dtype=np.uint8)

        for image in (smooth, noise):
            with self.subTest(kind="smooth" if image is smooth else "noise"):
                rois = detect_code_rois(image)
                self.assertEqual(len(rois), 1)
                self.assertTrue(rois[0]["fallback"])
                self.assertEqual(rois[0]["bbox"], {"x": 0, "y": 0, "width": 320, "height": 180})
                self.assertEqual(rois[0]["detector_reasons"], ["full_frame_fallback"])

    def test_ordering_is_deterministic_and_persistence_is_scored(self) -> None:
        image = np.full((220, 420), 12, dtype=np.uint8)
        cv2.putText(image, "LEFT", (18, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.25, 230, 3, cv2.LINE_AA)
        cv2.putText(image, "RIGHT", (230, 178), cv2.FONT_HERSHEY_SIMPLEX, 1.25, 230, 3, cv2.LINE_AA)
        persistence = np.zeros(image.shape, dtype=np.float32)
        persistence[110:210, 210:410] = 0.9

        first = detect_code_rois(image, max_rois=4, persistence=persistence)
        second = detect_code_rois(image, max_rois=4, persistence=persistence)

        self.assertEqual(first, second)
        self.assertGreater(first[0]["component_scores"]["persistence"], 0.0)
        self.assertEqual([roi["score"] for roi in first], sorted((roi["score"] for roi in first), reverse=True))

    def test_non_max_suppression_is_stable(self) -> None:
        candidates = [
            {"bbox": {"x": 10, "y": 10, "width": 80, "height": 50}, "score": 0.91, "name": "keep"},
            {"bbox": {"x": 14, "y": 12, "width": 78, "height": 50}, "score": 0.90, "name": "suppress"},
            {"bbox": {"x": 160, "y": 30, "width": 60, "height": 45}, "score": 0.72, "name": "separate"},
        ]

        kept = non_max_suppression(candidates, iou_threshold=0.35, max_rois=8)

        self.assertEqual([item["name"] for item in kept], ["keep", "separate"])

    def test_overlay_and_crop_helpers_preserve_expected_dimensions(self) -> None:
        image = np.full((120, 180), 25, dtype=np.uint8)
        rois = [
            {
                "bbox": {"x": 20, "y": 30, "width": 70, "height": 45},
                "score": 0.8,
                "detector_reasons": ["test"],
            }
        ]

        overlay = draw_roi_overlay(image, rois)
        crops = crop_rois(image, rois)

        self.assertEqual(overlay.shape, (120, 180, 3))
        self.assertEqual(crops[0].shape, (45, 70))
        self.assertFalse(np.shares_memory(crops[0], image))

    def test_blank_frame_fallback_is_explicit_and_json_safe(self) -> None:
        image = np.zeros((64, 96, 3), dtype=np.uint8)

        rois = detect_code_rois(image, max_rois=2, parent_variant="raw")

        self.assertEqual(rois[0]["id"], "roi-000-full-frame")
        self.assertTrue(rois[0]["fallback"])
        self.assertEqual(rois[0]["score"], 0.0)
        self.assertEqual(rois[0]["parent_variant"], {"name": "raw", "width": 96, "height": 64})
        json.dumps(rois)


if __name__ == "__main__":
    unittest.main()
