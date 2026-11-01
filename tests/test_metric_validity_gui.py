"""Offscreen widget checks; not native visual or researcher acceptance."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from gui.lab_dashboard import LabDashboardWindow


class MetricValidityGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = LabDashboardWindow(preferences={"schema_version": 1,
            "recent_experiments": [], "last_source_directory": None})

    def tearDown(self):
        self.window.close()
        self.application.processEvents()

    def test_unscored_ocr_is_labeled_in_both_review_tables_before_and_after_unblind(self):
        candidate = {"blind_id": "sample-a", "primary_metric_score": None,
                     "primary_metric_measurement": {"status": "unscored"}}
        for unblinded in (False, True):
            with self.subTest(unblinded=unblinded):
                report = {"top_candidates": [candidate]}
                self.window._populate_candidate_table(report, unblinded)
                self.window._populate_filmstrip(report, unblinded)
                self.assertEqual(self.window.candidate_table.item(0, 2 if unblinded else 1).text(), "Unscored OCR")
                self.assertEqual(self.window.filmstrip_table.item(0, 1).text(), "Unscored OCR")

    def test_measured_empty_ocr_remains_a_numeric_zero(self):
        report = {"top_candidates": [{"blind_id": "sample-a", "primary_metric_score": 0,
                  "primary_metric_measurement": {"status": "measured"}}]}
        self.window._populate_candidate_table(report, False)
        self.window._populate_filmstrip(report, False)
        self.assertEqual(self.window.candidate_table.item(0, 1).text(), "0")
        self.assertEqual(self.window.filmstrip_table.item(0, 1).text(), "0")


if __name__ == "__main__":
    unittest.main()
